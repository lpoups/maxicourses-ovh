"""
OpenCenterAI Trading - Prophet Engine (Claude AI Core)
======================================================
Extracted from prophet_engine.py (5400 lines) -- clean, focused version.
Uses the Anthropic Python SDK (not raw requests).

Responsibilities:
- ProphetEngine singleton: manages Claude API lifecycle
- analyze(): Single analysis cycle -- build prompt, call Claude, sanitize, log
- get_latest_prediction(): Returns cached prediction
- Scheduling: interval-based analysis loop with backoff

Models:
- claude_model_primary (Haiku) -- routine surveillance cycles
- claude_model_critical (Sonnet) -- critical decisions (entry/exit with open position)

IMPORTANT: Uses `anthropic` library (not openai, not raw requests).
IMPORTANT: Supports cache_control for system prompts (ephemeral caching).
IMPORTANT: Logs every analysis to MongoDB via db.analysis_repo.
NO Gemini code, NO OpenAI code -- Claude ONLY.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

import anthropic
import pytz

from ai.prompt_builder import (
    build_ai_prompt_v2,
    build_claude_system_prompt,
    get_trading_decision_tool,
)
from ai.decision import sanitize_ai_decision
from config.settings import AppSettings

logger = logging.getLogger("prophet")


# ===================================================================
# CONSTANTS
# ===================================================================

AI_COOLDOWN_BASE = 60       # Initial backoff duration (seconds)
AI_COOLDOWN_MAX = 300       # Max backoff (5 min)
AI_COOLDOWN_MULTIPLIER = 2  # Exponential multiplier
MAX_OUTPUT_TOKENS = 2500


class ProphetEngine:
    """
    Singleton AI engine that calls Claude for market analysis.
    Uses Anthropic Python SDK with tool_use structured outputs.
    """

    _instance: Optional["ProphetEngine"] = None

    def __new__(cls, settings: Optional[AppSettings] = None) -> "ProphetEngine":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        if self._initialized:
            return

        self.settings = settings
        self.running = False
        self.paris_tz = pytz.timezone("Europe/Paris")
        self.newyork_tz = pytz.timezone("America/New_York")

        # --- Anthropic client ---
        api_key = settings.claude_api_key if settings else ""
        self.client: Optional[anthropic.Anthropic] = None
        if api_key:
            self.client = anthropic.Anthropic(api_key=api_key)

        # --- Model config ---
        self.model_primary = settings.claude_model_primary if settings else "claude-haiku-4-5-20251001"
        self.model_critical = settings.claude_model_critical if settings else "claude-sonnet-4-6"

        # --- Latest prediction (cached) ---
        self.latest_prediction: Dict[str, Any] = {
            "timestamp": None,
            "timestamp_str": None,
            "signal": "WAIT",
            "action": "INITIALISATION...",
            "direction": "NEUTRAL",
            "probability": 0,
            "reason": "Starting...",
            "trend_4h": "NEUTRAL",
            "indicators": {},
            "ai_metadata": {
                "model_used": "N/A",
                "next_analysis": "N/A",
                "schedule_zone": "N/A",
            },
        }

        # --- Anti-flip-flop tracking ---
        self._prev_ai_action = ""
        self._prev_ai_action_ts = 0.0

        # --- Signal history for self-awareness ---
        self._signal_history: list = []
        self._max_signal_history = 8

        # --- Timing & status ---
        self.status = "IDLE"
        self.last_analysis_start = 0.0
        self.last_analysis_end = 0.0
        self.next_scheduled_run = 0.0
        self.ai_cooldown_until = 0.0
        self._ai_cooldown_consecutive = 0
        self._analysis_lock = threading.Lock()

        if self.client:
            logger.info(
                "Claude API active -- Primary: %s, Critical: %s",
                self.model_primary,
                self.model_critical,
            )
        else:
            logger.warning("No Claude API key -- deterministic mode only")

        self._initialized = True
        logger.info("ProphetEngine initialized")

    # ---------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.next_scheduled_run = 0  # Force immediate analysis
        threading.Thread(target=self._run_loop, daemon=True).start()
        logger.info("ProphetEngine started (immediate analysis scheduled)")

    def stop(self) -> None:
        self.running = False

    def get_latest_prediction(self) -> Dict[str, Any]:
        return self.latest_prediction

    def get_mode(self) -> Dict[str, Any]:
        now = datetime.now(self.paris_tz)
        model, interval, zone = self.get_schedule_params(now)
        return {
            "status": self.status,
            "zone": zone,
            "interval_sec": interval,
            "model": model,
            "next_run_ts": self.next_scheduled_run,
        }

    # ---------------------------------------------------------------
    # Scheduling
    # ---------------------------------------------------------------

    def get_schedule_params(
        self,
        dt: datetime,
        has_position: bool = False,
        scalping_enabled: bool = False,
    ) -> tuple:
        """
        Returns (model_name, interval_seconds, zone_name).
        Haiku for all cycles. Interval depends on position state.
        """
        model = self.model_primary

        if scalping_enabled:
            if has_position:
                interval_sec = 15
                zone = f"Haiku {interval_sec}s (SCALPING -- position open)"
            else:
                interval_sec = 60
                zone = f"Haiku {interval_sec}s (SCALPING -- surveillance)"
        else:
            if has_position:
                interval_sec = 60
                zone = f"Haiku {interval_sec}s (position open)"
            else:
                interval_sec = 180
                zone = f"Haiku {interval_sec}s (surveillance 3min)"

        return model, interval_sec, zone

    # ---------------------------------------------------------------
    # Core Analysis
    # ---------------------------------------------------------------

    def analyze(
        self,
        snapshot: Dict[str, Any],
        has_position: bool = False,
        position_direction: str = "",
        market_risk_score: int = 50,
        risk_label: str = "MODERE",
        partial_profit_eur: float = 8.0,
        full_profit_eur: float = 15.0,
        chart_image_base64: str = "",
        model_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Single analysis cycle:
        1. Build system prompt (cached) + user prompt (variable data)
        2. Call Claude via Anthropic SDK with tool_use
        3. Sanitize the response
        4. Log to MongoDB
        5. Update latest_prediction

        Returns the sanitized decision dict.
        """
        if not self.client:
            logger.warning("No Claude client -- cannot analyze")
            return {"action": "WAIT", "confidence": 0, "reason": "No AI client"}

        # Check cooldown
        now_ts = time.time()
        if now_ts < self.ai_cooldown_until:
            logger.info("Claude in cooldown -- skipping analysis")
            return {"action": "WAIT", "confidence": 0, "reason": "AI cooldown"}

        model = model_override or self.model_primary

        # 1. Build prompts
        system_prompt = build_claude_system_prompt(
            has_position=has_position,
            position_direction=position_direction,
            market_risk_score=market_risk_score,
            risk_label=risk_label,
            partial_profit_eur=partial_profit_eur,
            full_profit_eur=full_profit_eur,
        )
        user_prompt = build_ai_prompt_v2(snapshot)

        # 2. Call Claude
        claude_result = self._query_claude(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            chart_image_base64=chart_image_base64,
        )

        if not claude_result or claude_result.get("status", 0) != 200:
            status = claude_result.get("status", -1) if claude_result else -1
            if status in (429, 529):
                self._ai_cooldown_consecutive += 1
                backoff = min(
                    AI_COOLDOWN_MAX,
                    AI_COOLDOWN_BASE * (AI_COOLDOWN_MULTIPLIER ** (self._ai_cooldown_consecutive - 1)),
                )
                self.ai_cooldown_until = time.time() + backoff
                logger.warning(
                    "Claude %d (x%d). Backoff %ds",
                    status,
                    self._ai_cooldown_consecutive,
                    int(backoff),
                )
            return {"action": "WAIT", "confidence": 0, "reason": f"Claude error {status}"}

        # Reset consecutive failures on success
        if self._ai_cooldown_consecutive > 0:
            logger.info("Claude back online after %d consecutive failures", self._ai_cooldown_consecutive)
            self._ai_cooldown_consecutive = 0

        tool_input = claude_result.get("tool_input")
        if not tool_input:
            logger.warning("Claude returned no tool_use output")
            return {"action": "WAIT", "confidence": 0, "reason": "No tool_use output"}

        # 3. Sanitize
        decision = sanitize_ai_decision(
            ai_data=tool_input,
            snapshot=snapshot,
            position_direction=position_direction,
            prev_action=self._prev_ai_action,
            prev_action_ts=self._prev_ai_action_ts,
        )

        # Update anti-flip-flop tracking
        action = decision.get("action", "WAIT")
        if action in ("LONG", "SHORT"):
            self._prev_ai_action = action
            self._prev_ai_action_ts = time.time()

        # 4. Log to MongoDB
        self._log_analysis(decision, claude_result, model, snapshot, has_position, position_direction, market_risk_score, risk_label)

        # 5. Update latest prediction
        self._update_prediction(decision, model, snapshot)

        # 6. Update signal history
        self._record_signal(decision, snapshot)

        logger.info(
            "AI (%s): %s (%d%%) T=%.2f/S=%.2f",
            model,
            action,
            decision.get("confidence", 0),
            decision.get("target", 0),
            decision.get("stop", 0),
        )

        return decision

    # ---------------------------------------------------------------
    # Claude API Call (Anthropic SDK)
    # ---------------------------------------------------------------

    def _query_claude(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        chart_image_base64: str = "",
    ) -> Dict[str, Any]:
        """
        Call Claude Messages API with tool_use (structured outputs).
        Uses the Anthropic Python SDK.

        Returns: {"text": ..., "tool_input": ..., "usage": ..., "status": ...}
        tool_input = Python dict (no JSON parsing needed).

        Supports:
        - cache_control for system prompts (ephemeral)
        - Image input (chart snapshots as base64)
        - Beta features: prompt-caching, skills, code-execution
        """
        if model is None:
            model = self.model_primary

        try:
            # System prompt with cache_control for 90% cost savings
            system_block = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

            # User content: text + optional image
            user_content = []
            if chart_image_base64:
                # Parse data URL format: "data:image/jpeg;base64,XXXX"
                if "," in chart_image_base64:
                    media_type_part, b64_data = chart_image_base64.split(",", 1)
                    media_type = "image/jpeg"
                    if "png" in media_type_part:
                        media_type = "image/png"
                    elif "webp" in media_type_part:
                        media_type = "image/webp"
                else:
                    b64_data = chart_image_base64
                    media_type = "image/jpeg"

                user_content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64_data,
                    },
                })

            user_content.append({"type": "text", "text": user_prompt})

            # Tools: trading_decision + code_execution
            tools = [get_trading_decision_tool()]

            # Beta headers for prompt caching
            extra_headers = {
                "anthropic-beta": "prompt-caching-2024-07-31",
            }

            # Call Claude via SDK
            response = self.client.messages.create(
                model=model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=system_block,
                messages=[{"role": "user", "content": user_content}],
                tools=tools,
                tool_choice={"type": "tool", "name": "trading_decision"},
                extra_headers=extra_headers,
            )

            # Extract text, thinking, and tool_input from response
            text = ""
            thinking_text = ""
            tool_input = None

            for block in response.content:
                if block.type == "text":
                    text += block.text
                elif block.type == "tool_use":
                    tool_input = block.input

            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
            # Cache tokens if available
            if hasattr(response.usage, "cache_read_input_tokens"):
                usage["cache_read_input_tokens"] = response.usage.cache_read_input_tokens
            if hasattr(response.usage, "cache_creation_input_tokens"):
                usage["cache_creation_input_tokens"] = response.usage.cache_creation_input_tokens

            stop_reason = response.stop_reason or "unknown"

            result = {
                "text": text.strip(),
                "tool_input": tool_input,
                "usage": usage,
                "status": 200,
                "stop_reason": stop_reason,
            }
            if thinking_text:
                result["thinking"] = thinking_text

            # Log cost + mode
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)
            cache_create = usage.get("cache_creation_input_tokens", 0)
            mode = "tool_use" if tool_input is not None else "text"
            logger.info(
                "Claude [%s] tokens: in=%d (cache_read=%d, cache_create=%d), out=%d | mode=%s stop=%s",
                model,
                input_tokens,
                cache_read,
                cache_create,
                output_tokens,
                mode,
                stop_reason,
            )
            return result

        except anthropic.RateLimitError:
            logger.warning("Claude 429 rate limit")
            return {"text": "ERROR_429", "tool_input": None, "usage": {}, "status": 429}

        except anthropic.APIStatusError as e:
            if e.status_code == 529:
                logger.warning("Claude 529 overloaded")
                return {"text": "", "tool_input": None, "usage": {}, "status": 529}
            logger.warning("Claude API Error %d: %s", e.status_code, str(e)[:300])
            return {"text": "", "tool_input": None, "usage": {}, "status": e.status_code}

        except Exception as e:
            logger.error("Claude request exception: %s", e)
            return {"text": "", "tool_input": None, "usage": {}, "status": -1}

    # ---------------------------------------------------------------
    # MongoDB Logging
    # ---------------------------------------------------------------

    def _log_analysis(
        self,
        decision: Dict[str, Any],
        claude_result: Dict[str, Any],
        model: str,
        snapshot: Dict[str, Any],
        has_position: bool,
        position_direction: str,
        market_risk_score: int,
        risk_label: str,
    ) -> None:
        """Log AI analysis to MongoDB via db.analysis_repo."""
        try:
            from db.analysis_repo import log_analysis

            usage = claude_result.get("usage", {})
            horizon_forecast = decision.get("horizon_forecast", {})
            log_analysis(
                action=decision.get("action", "WAIT"),
                confidence=decision.get("confidence", 0),
                direction=decision.get("direction"),
                regime=decision.get("regime"),
                entry_mode=decision.get("entry_mode"),
                thinking=(decision.get("thinking") or "")[:300],
                reason=(decision.get("reason") or "")[:200],
                score_long=decision.get("score_long"),
                score_short=decision.get("score_short"),
                horizon_15m=horizon_forecast.get("15m"),
                horizon_30m=horizon_forecast.get("30m"),
                horizon_1h=horizon_forecast.get("1h"),
                horizon_4h=horizon_forecast.get("4h"),
                wait_reason_code=decision.get("wait_reason_code"),
                model_used=model,
                tokens_in=usage.get("input_tokens", 0),
                tokens_out=usage.get("output_tokens", 0),
                raw_response={
                    "has_position": has_position,
                    "position_direction": position_direction,
                    "market_price": snapshot.get("current_price"),
                    "market_risk_score": market_risk_score,
                    "risk_label": risk_label,
                    "target": decision.get("target"),
                    "stop": decision.get("stop"),
                    "size": decision.get("size"),
                    "invalidation_level": decision.get("invalidation_level"),
                    "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
                    "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0),
                },
            )
        except Exception as e:
            logger.debug("MongoDB log skip: %s", e)

    # ---------------------------------------------------------------
    # Prediction Update
    # ---------------------------------------------------------------

    def _update_prediction(
        self,
        decision: Dict[str, Any],
        model: str,
        snapshot: Dict[str, Any],
    ) -> None:
        """Update the cached latest_prediction dict."""
        now = datetime.now(self.paris_tz)
        action = decision.get("action", "WAIT")
        confidence = decision.get("confidence", 0)

        self.latest_prediction = {
            "timestamp": time.time(),
            "timestamp_str": now.strftime("%Y-%m-%d %H:%M:%S"),
            "signal": action,
            "action": action,
            "direction": decision.get("direction", "NEUTRAL"),
            "probability": confidence,
            "confidence": confidence,
            "reason": decision.get("reason", ""),
            "thinking": decision.get("thinking", ""),
            "regime": decision.get("regime", "TRANSITION"),
            "trend_strength": decision.get("trend_strength", 0),
            "score_long": decision.get("score_long", 0),
            "score_short": decision.get("score_short", 0),
            "entry_mode": decision.get("entry_mode", "NONE"),
            "position_advice": decision.get("position_advice", "KEEP"),
            "wait_reason_code": decision.get("wait_reason_code", "NONE"),
            "horizon_forecast": decision.get("horizon_forecast", {}),
            "trigger_snapshot": decision.get("trigger_snapshot", ""),
            "size": decision.get("size", 1.0),
            "target": decision.get("target", 0.0),
            "stop": decision.get("stop", 0.0),
            "invalidation_level": decision.get("invalidation_level", 0.0),
            # Pass current_price through so engine can resolve it
            "current_price": snapshot.get("current_price", 0),
            "trend_4h": snapshot.get("trend_4h_bias", "NEUTRAL"),
            "indicators": {},
            "ai_metadata": {
                "model_used": model,
                "next_analysis": "N/A",
                "schedule_zone": "N/A",
            },
        }

    # ---------------------------------------------------------------
    # Signal History (self-awareness)
    # ---------------------------------------------------------------

    def _record_signal(self, decision: Dict[str, Any], snapshot: Dict[str, Any]) -> None:
        """Record signal in history for AI self-awareness."""
        entry = {
            "ts": time.time(),
            "action": decision.get("action", "WAIT"),
            "confidence": decision.get("confidence", 0),
            "price": snapshot.get("current_price"),
            "direction": decision.get("direction", "NEUTRAL"),
            "thinking": (decision.get("thinking") or "")[:150],
        }
        self._signal_history.append(entry)
        if len(self._signal_history) > self._max_signal_history:
            self._signal_history = self._signal_history[-self._max_signal_history:]

    # ---------------------------------------------------------------
    # Scheduler Loop
    # ---------------------------------------------------------------

    def run_analysis_now(self) -> bool:
        """Force an immediate analysis cycle. Returns True if analysis ran."""
        if not self._analysis_lock.acquire(blocking=False):
            return False
        try:
            self.status = "ANALYZING"
            # Subclasses or callers should provide snapshot + context
            # This is a placeholder for the integration layer
            logger.info("run_analysis_now called -- integration layer should provide snapshot")
            return True
        finally:
            self.status = "IDLE"
            self._analysis_lock.release()

    def _run_loop(self) -> None:
        """Main scheduler loop."""
        logger.info("Prophet scheduler loop started")
        while self.running:
            try:
                now = time.time()
                if self.next_scheduled_run <= now:
                    ran = self.run_analysis_now()
                    if not ran:
                        self.status = "WAITING"
                else:
                    self.status = "WAITING"
                time.sleep(5)  # Poll every 5s
            except Exception as e:
                logger.error("Loop error: %s", e)
                time.sleep(10)

    def force_analysis(self) -> bool:
        """Public method to force immediate analysis."""
        self.next_scheduled_run = 0
        return self.run_analysis_now()


# ===================================================================
# MODULE-LEVEL SINGLETON ACCESSOR
# ===================================================================

_prophet_instance: Optional[ProphetEngine] = None


def get_prophet(settings: Optional[AppSettings] = None) -> ProphetEngine:
    """Return the singleton ProphetEngine instance."""
    global _prophet_instance
    if _prophet_instance is None:
        _prophet_instance = ProphetEngine(settings)
    return _prophet_instance
