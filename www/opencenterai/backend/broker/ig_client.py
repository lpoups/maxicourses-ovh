"""
OpenCenterAI Trading -- IG Client
===================================
Main broker client wrapping the trading-ig library.

Responsibilities:
  - connect / disconnect / ensure_connected
  - open_position / close_position / get_positions
  - get_ticker / get_candles / update_position_risk
  - Account info queries
  - Throttling (info 30 req/min, trading 100 req/min)
  - Error handling with transient-error detection

All session lifecycle concerns are delegated to ``IGSessionManager``
in broker.session.  This class only drives the high-level trading API.
"""

from __future__ import annotations

import json as _json
import logging
import math
import os
import time
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
from trading_ig.rest import ApiExceededException, IGException

from broker.models import Candle, OrderResult, Position, Ticker
from broker.session import IGSessionManager
from config.settings import AppSettings
from config.constants import ETH_EPIC
from db.collections import CANDLE_CACHE

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
            return float(default)
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return float(default)
        return out
    except Exception:
        return float(default)


def _safe_optional_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return None
        return out
    except Exception:
        return None


def _is_transient_error(text: str) -> bool:
    """Check whether an error string suggests a transient server problem."""
    txt = str(text or "").lower()
    markers = (
        "status code: 500", "internal server error", "service unavailable",
        "gateway timeout", "bad gateway", "tempor", "connection reset",
        "connection aborted", "read timed out", "connection timed out",
        "remote end closed connection", "502", "503", "504",
    )
    return any(m in txt for m in markers)


_AUTH_MARKERS = (
    "oauth-token-invalid", "client-token-missing", "token-missing",
    "invalid token", "token invalid", "unauthorized", "session expired",
    "authentication", "error.security",
)

_VALIDATION_MARKERS = (
    "validation.", "null-not-allowed", "invalid.input",
    "invalid.request", "constraint",
)


class IGClient:
    """
    High-level IG broker client.

    Usage::

        settings = AppSettings.from_env()
        client = IGClient(settings)
        client.connect()
        positions = client.get_positions()
    """

    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.session_mgr = IGSessionManager(settings)

        # ── Rate limiting timestamps ────────────────────────────
        self._last_info_call: float = 0.0
        self._last_trade_call: float = 0.0

        # ── Trade priority window ───────────────────────────────
        self._trade_priority_until: float = 0.0

        # ── Caches ──────────────────────────────────────────────
        self._account_cache: Dict[str, Any] = {}
        self._account_cache_ts: float = 0.0
        self._ticker_cache: Dict[str, Dict[str, Any]] = {}
        self._ticker_cache_ts: Dict[str, float] = {}
        self._positions_cache: Optional[tuple] = None  # (ts, data)
        self._candle_cache: Dict[str, tuple] = {}

        # ── Quota backoff ─────────────────────────────────────────
        self._quota_exceeded_until: float = 0.0  # Per-minute rate limit backoff

        # ── Anti-duplicate close ────────────────────────────────
        self._recent_close_success: Dict[str, float] = {}

        # ── Anti-loop SL/TP update ──────────────────────────────
        self._risk_update_failures: Dict[str, int] = {}
        self._risk_update_block_until: Dict[str, float] = {}
        self._risk_update_last_error_log: Dict[str, float] = {}

        # ── Watchdog ────────────────────────────────────────────
        self._watchdog_running = False
        self._watchdog_thread: Optional[threading.Thread] = None

        logger.info("IGClient initialised (id=%s)", hex(id(self)))

    # ─── Convenience properties ────────────────────────────────

    @property
    def connected(self) -> bool:
        return self.session_mgr.connected

    @property
    def ig_service(self):
        return self.session_mgr.ig_service

    @property
    def account_id(self) -> Optional[str]:
        return self.session_mgr.account_id

    # ═══════════════════════════════════════════════════════════
    # THROTTLE
    # ═══════════════════════════════════════════════════════════

    def _throttle(self, is_trading: bool = False) -> None:
        """
        Rate limiter conforming to IG Labs limits:
          - Information: 30 req/min  (1 every 2.0s)
          - Trading:    100 req/min  (1 every 0.6s)
        """
        now = time.time()
        if is_trading:
            wait = max(0.0, 0.6 - (now - self._last_trade_call))
            if wait > 0:
                time.sleep(wait)
            self._last_trade_call = time.time()
        else:
            wait = max(0.0, 2.1 - (now - self._last_info_call))
            if wait > 0:
                time.sleep(wait)
            self._last_info_call = time.time()

    # ═══════════════════════════════════════════════════════════
    # TRADE PRIORITY
    # ═══════════════════════════════════════════════════════════

    def _enter_trade_priority(self, seconds: float = 8.0) -> None:
        until = time.time() + max(2.0, float(seconds))
        if until > self._trade_priority_until:
            self._trade_priority_until = until

    def _is_trade_priority_active(self) -> bool:
        return time.time() < self._trade_priority_until

    # ═══════════════════════════════════════════════════════════
    # CANONICAL DEAL ID
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _canonical_id(rid: str) -> str:
        if not rid:
            return ""
        rid = str(rid).upper().strip()
        for prefix in ("DIAAAA", "DIAAAB", "W", "V"):
            if rid.startswith(prefix):
                rid = rid[len(prefix):]
                break
        return rid

    # ═══════════════════════════════════════════════════════════
    # WATCHDOG
    # ═══════════════════════════════════════════════════════════

    def start_watchdog(self) -> None:
        if self._watchdog_running:
            return
        self._watchdog_running = True
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True, name="IGWatchdogThread",
        )
        self._watchdog_thread.start()
        logger.info("IG watchdog started")

    def _watchdog_loop(self) -> None:
        while self._watchdog_running:
            try:
                self.ensure_connected()
            except Exception as exc:
                logger.error("Watchdog error: %s", exc)
            time.sleep(30)

    # ═══════════════════════════════════════════════════════════
    # CONNECT / DISCONNECT
    # ═══════════════════════════════════════════════════════════

    def connect(self, force: bool = False) -> bool:
        """Establish connection with IG API (login + optional account switch)."""
        mgr = self.session_mgr
        with mgr.api_lock:
            now = time.time()

            # Idempotent: another thread may have connected while waiting.
            if mgr.connected and mgr.ig_service:
                mgr.last_success = now
                return True

            # ── Backoff ─────────────────────────────────────────
            is_reconnect_after_expiry = (
                not mgr.connected and not mgr._last_login_failed
            )
            base_cd = mgr.LOGIN_COOLDOWN_DEMO if mgr.is_demo else mgr.LOGIN_COOLDOWN
            max_level = 3 if mgr.is_demo else 7
            current_cd = base_cd * (2 ** min(mgr.backoff_count, max_level))
            if mgr.is_demo:
                current_cd = min(mgr.LOGIN_COOLDOWN_DEMO_MAX, current_cd)

            if (
                not force
                and not is_reconnect_after_expiry
                and (now - mgr.last_login_attempt) < current_cd
                and not mgr.connected
            ):
                remaining = max(0, int(current_cd - (now - mgr.last_login_attempt)))
                mgr.last_error = f"HA cooldown active ({remaining}s)"
                return False

            mgr.last_login_attempt = now
            self._throttle(is_trading=False)

            # ── Attempt session recovery from MongoDB ───────────
            try:
                cache = mgr.load_persisted_session()
                if cache and (now - cache.get("timestamp", 0)) < 12 * 3600:
                    has_cst = bool(str(cache.get("cst") or "").strip())
                    has_xst = bool(str(cache.get("x_security_token") or "").strip())
                    has_auth = bool(str(cache.get("authorization") or "").strip())
                    oauth_only = has_auth and not has_cst and not has_xst
                    skip_oauth_only = str(
                        os.environ.get("IG_SKIP_OAUTH_ONLY_CACHE", "1")
                    ).strip() != "0"

                    if oauth_only and skip_oauth_only:
                        logger.info("OAuth-only session cache ignored (prefer fresh login)")
                        raise RuntimeError("SKIP_OAUTH_ONLY_CACHE")

                    logger.info("Attempting session recovery from MongoDB ...")
                    mgr.ig_service = mgr._create_ig_service()
                    mgr.apply_session_state(cache)

                    try:
                        self._throttle(is_trading=False)
                        mgr.ig_service.fetch_accounts()
                        mgr.account_id = str(
                            cache.get("account_id")
                            or mgr.account_id
                            or self.settings.ig_acc_number
                            or ""
                        ).strip()
                        mgr.reset_on_login_success()
                        mgr.persist_session()
                        logger.info("Session recovered on %s", mgr.account_id)
                        return True
                    except Exception as exc:
                        logger.warning("Persisted session invalid: %s", exc)
                        if mgr.try_refresh_repair():
                            mgr.account_id = str(
                                cache.get("account_id")
                                or mgr.account_id
                                or self.settings.ig_acc_number
                                or ""
                            ).strip()
                            logger.info("Session refreshed on %s", mgr.account_id)
                            return True
                        mgr.connected = False
            except Exception as exc:
                logger.warning("Session recovery failed: %s -- fresh login required", exc)

            # ── Fresh login ─────────────────────────────────────
            try:
                target_account = self.settings.ig_acc_number
                acc_type = self.settings.ig_mode
                mgr._last_login_failed = True

                mgr.ig_service = mgr._create_ig_service()

                # Login version order
                default_versions = "3,2" if mgr.is_demo else "2,3,1"
                raw_versions = os.environ.get("IG_LOGIN_VERSIONS", default_versions)
                login_versions: List[str] = []
                for tok in str(raw_versions).split(","):
                    v = tok.strip()
                    if v in {"1", "2", "3"} and v not in login_versions:
                        login_versions.append(v)
                login_versions = [
                    v for v in login_versions if not mgr.is_login_version_skipped(v)
                ]
                if not login_versions:
                    fallback = ["3", "2"] if mgr.is_demo else ["2", "3", "1"]
                    login_versions = [
                        v for v in fallback if not mgr.is_login_version_skipped(v)
                    ]
                if not login_versions:
                    mgr.last_error = "No IG login version currently eligible"
                    return False

                logger.info("IG login versions order: %s", ",".join(login_versions))

                login_errors: List[str] = []
                login_ok = False
                rate_limit_hit = False

                for ver in login_versions:
                    encryption_attempts = [False, True] if ver in {"1", "2"} else [False]
                    for enc in encryption_attempts:
                        try:
                            self._throttle(is_trading=False)
                            res = mgr.ig_service.create_session(version=ver, encryption=enc)
                            login_acc = self._extract_login_account(res)
                            self._finalize_account(login_acc, target_account)
                            logger.info(
                                "Login OK via v%s%s on %s",
                                ver, " (enc)" if enc else "", target_account,
                            )
                            mgr._last_login_failed = False
                            login_ok = True
                            break
                        except Exception as exc:
                            detail = self._format_login_error(exc)
                            login_errors.append(f"v{ver}{'+enc' if enc else ''}: {detail}")
                            logger.warning("Login v%s%s failed: %s", ver, " (enc)" if enc else "", detail)
                            err_l = str(detail).lower()
                            if any(m in err_l for m in (
                                "apiexceededexception", "exceeded-api-key-allowance",
                            )) or ("status code: 403" in err_l and "session" in err_l):
                                rate_limit_hit = True
                                break
                            if "stockbroking-not-supported" in err_l:
                                mgr.skip_login_version_for(ver, 6 * 3600, "stockbroking-not-supported")
                                break
                            if not enc and ver in {"1", "2"} and "encryption.required" in err_l:
                                continue
                    if login_ok or rate_limit_hit:
                        break

                if not login_ok:
                    if rate_limit_hit:
                        mgr.backoff_count = max(3, mgr.backoff_count + 1)
                    else:
                        mgr.backoff_count += 1
                    mgr._last_login_failed = True
                    condensed = " | ".join(login_errors[-4:]) if login_errors else "UNKNOWN"
                    mgr.last_error = f"Login Failed: {condensed}"
                    logger.error("Login failed: %s", condensed)

                    # Clear persisted session on hard failures
                    transient_only = all(
                        _is_transient_error(e) or "stockbroking-not-supported" in e.lower()
                        for e in login_errors
                    ) if login_errors else False
                    if not (mgr.is_demo and transient_only):
                        mgr.clear_persisted_session()
                    return False

                mgr.reset_on_login_success()
                mgr.persist_session()
                logger.info("Connection established on %s", mgr.account_id)
                return True

            except Exception as exc:
                mgr.last_error = f"Connection error: {exc}"
                mgr.backoff_count += 1
                logger.error("Critical connection error: %s", exc)
                return False

    def disconnect(self) -> None:
        """Cleanly close the IG session."""
        mgr = self.session_mgr
        if mgr.ig_service:
            try:
                mgr.ig_service.logout()
            except Exception:
                pass
        mgr.connected = False
        mgr.ig_service = None
        logger.info("Disconnected from IG")

    def ensure_connected(self, force: bool = False) -> bool:
        """Verify session validity; reconnect if needed."""
        mgr = self.session_mgr
        now = time.time()

        # Fast paths: skip deep probe when unnecessary.
        if self._is_trade_priority_active() and mgr.connected and mgr.ig_service:
            return True
        if mgr.connected and mgr.ig_service and not force and mgr.server_issue_cooldown_active():
            return True
        if mgr.connected and mgr.ig_service and (now - mgr.last_success) < mgr.SESSION_OK_GRACE_SEC:
            return True
        if (
            mgr.connected and mgr.ig_service and not force
            and (now - mgr._last_session_probe_ts) < mgr.SESSION_PROBE_MIN_INTERVAL_SEC
        ):
            return True
        if (
            mgr.connected and mgr.ig_service and not force
            and now < mgr._session_check_degraded_until
        ):
            return True

        if not mgr.connected or not mgr.ig_service:
            return self.connect(force=force)

        # Deep session probe
        try:
            mgr._last_session_probe_ts = now
            with mgr.api_lock:
                self._throttle(is_trading=False)
                mgr.ig_service.fetch_accounts()
            mgr.mark_success()
            mgr._session_check_fail_count = 0
            mgr._session_check_degraded_until = 0.0
            return True
        except Exception as exc:
            err_str = str(exc).lower()
            self._handle_api_error(exc, "Session check")

            has_auth_marker = any(m in err_str for m in _AUTH_MARKERS)
            has_401 = "401" in err_str
            has_403 = "403" in err_str
            has_validation = any(m in err_str for m in _VALIDATION_MARKERS)

            if (has_401 or (has_403 and has_auth_marker) or has_auth_marker) and not has_validation:
                logger.warning("Session invalid (%s) -- repairing ...", err_str[:120])
                mgr.connected = False
                mgr._last_login_failed = False
                mgr._session_check_fail_count = 0
                mgr._session_check_degraded_until = 0.0
                if mgr.try_refresh_repair():
                    return True
                return self.connect(force=True)

            # Non-auth issue: back off session checks.
            mgr._session_check_fail_count = min(8, mgr._session_check_fail_count + 1)
            degraded_for = min(120, 10 * (2 ** min(mgr._session_check_fail_count - 1, 4)))
            mgr._session_check_degraded_until = now + degraded_for
            mgr._last_session_probe_ts = now
            if (now - mgr._last_session_degraded_log) > 15:
                logger.warning(
                    "Session check non-auth issue (%s) -- next deep check in %ds",
                    err_str[:120], int(degraded_for),
                )
                mgr._last_session_degraded_log = now
            return mgr.connected

    # ═══════════════════════════════════════════════════════════
    # POSITIONS
    # ═══════════════════════════════════════════════════════════

    def get_positions(self) -> List[Position]:
        """Fetch all open positions (with short cache)."""
        now = time.time()
        CACHE_TTL = 6.0

        if self._positions_cache:
            ts, data = self._positions_cache
            if (now - ts) < CACHE_TTL:
                return data
        if mgr_guard := self._cache_guard_positions(now, 120, 60, 300):
            return mgr_guard

        if not self.ensure_connected():
            if self._positions_cache:
                ts, data = self._positions_cache
                if (now - ts) < 60:
                    return data
            return []

        try:
            with self.session_mgr.api_lock:
                self._throttle(is_trading=False)
                df = self.ig_service.fetch_open_positions()

            self.session_mgr.mark_success()
            positions: List[Position] = []

            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    current_level = _safe_float(row.get("level", 0))
                    bid = _safe_float(row.get("bid", current_level), current_level)
                    offer = _safe_float(row.get("offer", current_level), current_level)
                    size = _safe_float(row.get("size", 0))
                    direction = row.get("direction", "")
                    open_level = _safe_float(row.get("level", 0))

                    pnl_api = row.get("profitAndLoss")
                    if pnl_api is not None and not pd.isna(pnl_api):
                        pnl = _safe_float(pnl_api)
                    else:
                        pnl = (
                            (bid - open_level) * size
                            if direction == "BUY"
                            else (open_level - offer) * size
                        )
                    if math.isnan(pnl) or math.isinf(pnl):
                        pnl = 0.0

                    positions.append(Position(
                        deal_id=str(row.get("dealId", "")),
                        epic=str(row.get("market_epic", row.get("epic", ""))),
                        direction=direction,
                        size=size,
                        entry_price=open_level,
                        current_price=round(bid if direction == "BUY" else offer, 2),
                        sl_price=_safe_optional_float(row.get("stopLevel")),
                        tp_price=_safe_optional_float(row.get("limitLevel")),
                        pnl=round(pnl, 2),
                        currency=str(row.get("currency", "USD")),
                        expiry=str(row.get("expiry", "-") or "-"),
                        created_at=str(row.get("createdDate", "")),
                        bid=bid,
                        offer=offer,
                    ))

            self._positions_cache = (now, positions)
            return positions

        except Exception as exc:
            self._handle_api_error(exc, "Positions")
            if self._positions_cache:
                return self._positions_cache[1]
            return []

    # ═══════════════════════════════════════════════════════════
    # TICKER / MARKET INFO
    # ═══════════════════════════════════════════════════════════

    def get_ticker(self, epic: str = "") -> Optional[Ticker]:
        """Real-time market snapshot."""
        epic = epic or ETH_EPIC
        now = time.time()

        # Cache check
        if epic in self._ticker_cache:
            ts = self._ticker_cache_ts.get(epic, 0)
            if (now - ts) < 15:
                return self._ticker_from_dict(self._ticker_cache[epic])
        if self._storm_guard_ticker(epic, now, 120, 120, 300):
            return self._ticker_from_dict(self._ticker_cache[epic])

        if not self.ensure_connected():
            if epic in self._ticker_cache:
                return self._ticker_from_dict(self._ticker_cache[epic])
            return None

        try:
            with self.session_mgr.api_lock:
                self._throttle(is_trading=False)
                markets = self.ig_service.fetch_market_by_epic(epic)

            if not markets:
                return self._stale_ticker(epic, now)

            snapshot = self._safe_attr(markets, "snapshot")
            instrument = self._safe_attr(markets, "instrument")
            rules = self._safe_attr(markets, "dealingRules")

            if not snapshot:
                return self._stale_ticker(epic, now)

            self.session_mgr.mark_success()

            bid = float(snapshot.get("bid", 0))
            offer = float(snapshot.get("offer", 0))
            high = float(snapshot.get("high", 0))
            low = float(snapshot.get("low", 0))

            # Price scaling fix
            scale = 1.0
            if bid > 100_000:
                scale = 0.01
                bid /= 100
                offer /= 100
                high /= 100
                low /= 100

            min_stop = None
            min_limit = None
            if rules:
                try:
                    min_stop = (rules.get("minStopDistance") or {}).get("value")
                    min_limit = (rules.get("minLimitDistance") or {}).get("value")
                    if scale != 1.0:
                        if min_stop is not None:
                            min_stop = float(min_stop) * scale
                        if min_limit is not None:
                            min_limit = float(min_limit) * scale
                except Exception:
                    pass

            min_size = 0.1
            if rules:
                try:
                    md = rules.get("minDealSize") or {}
                    min_size = float(md.get("value", 0.1) if hasattr(md, "get") else 0.1) or 0.1
                except Exception:
                    pass

            result_dict = {
                "epic": epic,
                "name": str(
                    (instrument.get("name") if instrument and hasattr(instrument, "get") else None)
                    or "ETH/USD"
                ),
                "bid": bid,
                "offer": offer,
                "high": high,
                "low": low,
                "change": float(snapshot.get("percentageChange", 0) or 0),
                "market_status": str(snapshot.get("marketStatus", "CLOSED") or "CLOSED"),
                "min_size": min_size,
                "min_stop_distance": float(min_stop) if min_stop is not None else None,
                "min_limit_distance": float(min_limit) if min_limit is not None else None,
            }

            self._ticker_cache[epic] = result_dict
            self._ticker_cache_ts[epic] = time.time()
            return self._ticker_from_dict(result_dict)

        except Exception as exc:
            self._handle_api_error(exc, f"Market Info ({epic})")
            if epic in self._ticker_cache:
                return self._ticker_from_dict(self._ticker_cache[epic])
            return None

    # ═══════════════════════════════════════════════════════════
    # CANDLES
    # ═══════════════════════════════════════════════════════════

    def get_candles(self, epic: str = "", resolution: str = "5min", count: int = 100) -> List[Candle]:
        """Fetch historical OHLCV candles with MongoDB persistent cache."""
        epic = epic or ETH_EPIC

        resolution_map = {
            "1min": "1Min", "5min": "5Min", "15min": "15Min", "30min": "30Min",
            "1h": "1H", "4h": "4H", "1D": "1D",
        }
        res_ig = resolution_map.get(resolution, "5Min")

        cache_ttl_map = {
            "1Min": 120, "5Min": 600, "15Min": 1200, "30Min": 2400,
            "1H": 3600, "4H": 7200, "1D": 14400,
        }
        cache_ttl = cache_ttl_map.get(res_ig, 300)

        cache_key = f"{epic}_{resolution}_{count}"
        now = time.time()

        # 1. Check in-memory cache
        cached = self._candle_cache.get(cache_key)
        if cached:
            data, ts = cached
            if (now - ts) < cache_ttl:
                return data

        # Check superset in-memory caches
        prefix = f"{epic}_{resolution}_"
        best_super = None
        for key, val in self._candle_cache.items():
            if not key.startswith(prefix):
                continue
            try:
                pts = int(key[len(prefix):])
            except Exception:
                continue
            d, ts = val
            if (now - ts) >= cache_ttl:
                continue
            if pts >= count and (best_super is None or pts < best_super[0]):
                best_super = (pts, d)
        if best_super is not None:
            return best_super[1][-count:]

        # 2. During rate limit backoff, serve from MongoDB cache
        if time.time() < self._quota_exceeded_until:
            mongo_candles = self._load_candles_from_mongo(epic, res_ig, count)
            if mongo_candles:
                self._candle_cache[cache_key] = (mongo_candles, now)
                return mongo_candles
            # In-memory fallback
            for key, val in self._candle_cache.items():
                if key.startswith(prefix):
                    d, ts = val
                    if d:
                        return d[-count:] if len(d) >= count else d
            return []

        # 3. Fetch from IG API
        if not self.ensure_connected():
            mongo_candles = self._load_candles_from_mongo(epic, res_ig, count)
            return mongo_candles if mongo_candles else []

        try:
            result = None
            try:
                if not self.ensure_connected():
                    raise ConnectionError("IG not connected")
                with self.session_mgr.api_lock:
                    self._throttle(is_trading=False)
                    result = self.ig_service.fetch_historical_prices_by_epic(
                        epic=epic, resolution=res_ig, numpoints=min(count, 4000),
                    )
                self.session_mgr.mark_success()
            except Exception as exc:
                err_detail = str(exc)
                if hasattr(exc, "response") and exc.response is not None:
                    try:
                        err_detail = f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
                    except Exception:
                        pass
                logger.error("Candles %s/%s: %s", epic, res_ig, err_detail)
                self._handle_api_error(exc, "History fetch")

            prices_df = result.get("prices") if isinstance(result, dict) else result
            if prices_df is None or len(prices_df) == 0:
                # Fallback to MongoDB cache
                mongo_candles = self._load_candles_from_mongo(epic, res_ig, count)
                if mongo_candles:
                    self._candle_cache[cache_key] = (mongo_candles, now)
                    return mongo_candles
                if cached:
                    return cached[0]
                return []

            candles = self._parse_candles(prices_df)
            if candles:
                self._candle_cache[cache_key] = (candles, now)
                # Persist to MongoDB (async-ish, fire and forget)
                self._save_candles_to_mongo(epic, res_ig, candles)
            return candles

        except Exception as exc:
            logger.error("Historical prices error: %s", exc)
            mongo_candles = self._load_candles_from_mongo(epic, res_ig, count)
            if mongo_candles:
                return mongo_candles
            if cached:
                return cached[0]
            return []

    def _save_candles_to_mongo(self, epic: str, resolution: str, candles: List[Candle]) -> None:
        """Persist candles to MongoDB for cross-restart cache."""
        try:
            from db.mongo import get_db
            db = get_db()
            coll = db[CANDLE_CACHE]
            ops = []
            from pymongo import UpdateOne
            for c in candles:
                ops.append(UpdateOne(
                    {"epic": epic, "resolution": resolution, "timestamp": c.timestamp},
                    {
                        "$set": {
                            "open": c.open, "high": c.high, "low": c.low,
                            "close": c.close,
                        },
                        # Use $max for volume so IG's 0 never overwrites tick counts
                        "$max": {"volume": c.volume},
                    },
                    upsert=True,
                ))
            if ops:
                coll.bulk_write(ops, ordered=False)
                logger.debug("Saved %d candles to MongoDB (%s/%s)", len(ops), epic, resolution)
        except Exception as exc:
            logger.warning("MongoDB candle save failed: %s", exc)

    def _load_candles_from_mongo(self, epic: str, resolution: str, count: int) -> List[Candle]:
        """Load candles from MongoDB persistent cache."""
        try:
            from db.mongo import get_db
            db = get_db()
            coll = db[CANDLE_CACHE]
            docs = list(coll.find(
                {"epic": epic, "resolution": resolution},
                {"_id": 0, "timestamp": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            ).sort("timestamp", -1).limit(count))
            if not docs:
                return []
            docs.reverse()
            candles = [
                Candle(
                    timestamp=d["timestamp"], open=d["open"], high=d["high"],
                    low=d["low"], close=d["close"], volume=d.get("volume", 0),
                )
                for d in docs
            ]
            logger.info("Loaded %d candles from MongoDB cache (%s/%s)", len(candles), epic, resolution)
            return candles
        except Exception as exc:
            logger.warning("MongoDB candle load failed: %s", exc)
            return []

    # ═══════════════════════════════════════════════════════════
    # OPEN POSITION
    # ═══════════════════════════════════════════════════════════

    def open_position(
        self,
        direction: str,
        size: float,
        epic: str = "",
        sl_pts: Optional[float] = None,
        tp_pts: Optional[float] = None,
    ) -> OrderResult:
        """Open a new CFD position."""
        self._enter_trade_priority(10.0)
        epic = epic or ETH_EPIC

        if not self.ensure_connected(force=True):
            return OrderResult(success=False, error="Session invalid")

        try:
            # Clamp distances
            MAX_STOP_PTS = 250.0
            MAX_LIMIT_PTS = 500.0
            base_stop = min(float(sl_pts), MAX_STOP_PTS) if sl_pts is not None else None
            base_limit = min(float(tp_pts), MAX_LIMIT_PTS) if tp_pts is not None else None

            def _submit(stop_d=None, limit_d=None):
                with self.session_mgr.api_lock:
                    self._throttle(is_trading=True)
                    return self.ig_service.create_open_position(
                        currency_code="USD",
                        direction=direction,
                        epic=epic,
                        expiry="-",
                        force_open=True,
                        guaranteed_stop=False,
                        level=None,
                        limit_level=None,
                        limit_distance=limit_d,
                        stop_level=None,
                        stop_distance=stop_d,
                        order_type="MARKET",
                        quote_id=None,
                        size=size,
                        trailing_stop=False,
                        trailing_stop_increment=None,
                    )

            def _accepted(resp):
                return bool(resp and str(resp.get("dealStatus", "")).upper() == "ACCEPTED")

            # Primary attempt
            response = _submit(base_stop, base_limit)
            if _accepted(response):
                self._positions_cache = None
                return OrderResult(
                    success=True,
                    deal_id=response.get("dealId", ""),
                    deal_reference=response.get("dealReference", ""),
                    direction=direction,
                    size=size,
                )

            reason = str(response.get("reason", "Unknown") if response else "No response")

            # Retry with wider distances on ATTACHED_ORDER_LEVEL_ERROR
            if "ATTACHED_ORDER_LEVEL_ERROR" in reason.upper() and (base_stop or base_limit):
                ticker = self.get_ticker(epic)
                safe_floor = 1.0
                if ticker:
                    safe_floor = max(
                        safe_floor,
                        ticker.min_stop_distance or 0,
                        ticker.min_limit_distance or 0,
                    )

                for mult in (1.0, 1.5):
                    retry_stop = max(float(base_stop or safe_floor), safe_floor * mult) if base_stop is not None else None
                    retry_limit = max(float(base_limit or safe_floor), safe_floor * mult) if base_limit is not None else None
                    resp_retry = _submit(retry_stop, retry_limit)
                    if _accepted(resp_retry):
                        self._positions_cache = None
                        return OrderResult(
                            success=True,
                            deal_id=resp_retry.get("dealId", ""),
                            deal_reference=resp_retry.get("dealReference", ""),
                            direction=direction,
                            size=size,
                        )
                    reason = str(resp_retry.get("reason", "Unknown") if resp_retry else "No response")
                    if "ATTACHED_ORDER_LEVEL_ERROR" not in reason.upper():
                        break

                # Fallback: open without levels, then apply risk separately
                if "ATTACHED_ORDER_LEVEL_ERROR" in reason.upper():
                    resp_plain = _submit(None, None)
                    if _accepted(resp_plain):
                        deal_id = resp_plain.get("dealId", "")
                        self._positions_cache = None
                        risk_ok = self._try_apply_post_open_risk(
                            deal_id, direction, epic, base_stop, base_limit, safe_floor,
                        )
                        if not risk_ok:
                            # Emergency close
                            close_res = self.close_position(deal_id, direction, size)
                            return OrderResult(
                                success=False,
                                deal_id=deal_id,
                                deal_reference=resp_plain.get("dealReference", ""),
                                error="OPEN_ABORTED_NO_RISK",
                                direction=direction,
                                size=size,
                                risk_attached=False,
                            )
                        return OrderResult(
                            success=True,
                            deal_id=deal_id,
                            deal_reference=resp_plain.get("dealReference", ""),
                            direction=direction,
                            size=size,
                            opened_without_attached_orders=True,
                            risk_attached=True,
                        )
                    reason = str(resp_plain.get("reason", "Unknown") if resp_plain else "No response")

            return OrderResult(success=False, error=reason)

        except Exception as exc:
            self._handle_api_error(exc, "Open Position")
            return OrderResult(success=False, error=str(exc))

    # ═══════════════════════════════════════════════════════════
    # CLOSE POSITION
    # ═══════════════════════════════════════════════════════════

    def close_position(
        self,
        deal_id: str,
        direction: str = "",
        size: float = 0.0,
        epic: str = "",
    ) -> OrderResult:
        """Close an existing position."""
        self._enter_trade_priority(12.0)
        deal_key = str(deal_id or "").upper().strip()
        deal_canon = self._canonical_id(deal_key)

        # Anti-duplicate guard
        now_ts = time.time()
        last_ok = self._recent_close_success.get(deal_key, 0)
        if last_ok and (now_ts - last_ok) <= 30:
            return OrderResult(
                success=True, deal_id=deal_id,
                reason="Already closed recently",
                duplicate_recent_success=True,
            )

        if not self.ensure_connected(force=True):
            return OrderResult(success=False, error="Reconnection failed")

        # Retrieve position info if not supplied
        pos_epic = epic or ETH_EPIC
        pos_expiry = "-"
        if not size or not direction:
            for pos in self.get_positions():
                pid = str(pos.deal_id).upper().strip()
                if pid == deal_key or self._canonical_id(pid) == deal_canon:
                    size = size or pos.size
                    direction = direction or pos.direction
                    pos_epic = pos.epic or pos_epic
                    pos_expiry = pos.expiry or pos_expiry
                    break

        if not size or not direction:
            return OrderResult(success=False, deal_id=deal_id, error=f"Position {deal_id} not found")

        close_direction = "SELL" if str(direction).upper() == "BUY" else "BUY"

        profiles = [
            {"name": "v1_dealid_eae", "version": "1", "id_mode": "dealId", "tif": "EXECUTE_AND_ELIMINATE"},
            {"name": "v1_dealid_fok", "version": "1", "id_mode": "dealId", "tif": "FILL_OR_KILL"},
        ]
        if pos_epic:
            profiles.append({"name": "v1_epic_eae", "version": "1", "id_mode": "epic", "tif": "EXECUTE_AND_ELIMINATE"})

        max_attempts = 3
        last_error = "Close failed"

        for attempt in range(1, max_attempts + 1):
            self._enter_trade_priority(12.0)
            if not self.ensure_connected(force=True):
                last_error = "Reconnection failed"
                time.sleep(0.35)
                continue

            allow_epic_fb = False
            dealid_unusable = False

            for profile in profiles:
                pname = profile["name"]
                id_mode = profile["id_mode"].lower()
                if id_mode == "epic" and not allow_epic_fb:
                    continue
                if id_mode == "dealid" and dealid_unusable:
                    continue

                try:
                    with self.session_mgr.api_lock:
                        self._throttle(is_trading=True)

                        payload: Dict[str, Any] = {
                            "direction": close_direction,
                            "orderType": "MARKET",
                            "size": size,
                            "timeInForce": profile["tif"],
                        }
                        if id_mode == "epic":
                            payload["epic"] = pos_epic
                            payload["expiry"] = pos_expiry
                        else:
                            payload["dealId"] = deal_id

                        ig_session = self.ig_service.crud_session.session
                        base_url = self.ig_service.crud_session.BASE_URL
                        url = f"{base_url}/positions/otc"
                        old_headers = dict(ig_session.headers)
                        try:
                            ig_session.headers.update({
                                "VERSION": profile["version"],
                                "_method": "DELETE",
                                "X-HTTP-Method-Override": "DELETE",
                                "Content-Type": "application/json; charset=UTF-8",
                            })
                            resp = ig_session.post(url, data=_json.dumps(payload))
                        finally:
                            ig_session.headers.clear()
                            ig_session.headers.update(old_headers)

                    status_code = int(getattr(resp, "status_code", 0) or 0)
                    resp_text = str(getattr(resp, "text", "") or "")
                    try:
                        resp_json = _json.loads(resp_text) if resp_text else {}
                    except Exception:
                        resp_json = {}

                    if status_code == 200:
                        deal_ref = str(resp_json.get("dealReference", "")).strip()
                        if deal_ref:
                            confirm = self.ig_service.fetch_deal_by_deal_reference(deal_ref)
                            if confirm and str(confirm.get("dealStatus", "")).upper() == "ACCEPTED":
                                self._recent_close_success[deal_key] = time.time()
                                self._positions_cache = None
                                return OrderResult(
                                    success=True, deal_id=deal_id,
                                    deal_reference=deal_ref,
                                    reason="Position closed",
                                    profile=pname,
                                )

                        # Verify by re-reading positions
                        if self._confirm_closed(deal_key, deal_canon):
                            self._recent_close_success[deal_key] = time.time()
                            self._positions_cache = None
                            return OrderResult(
                                success=True, deal_id=deal_id,
                                reason="Confirmed by positions read",
                                profile=pname,
                            )
                        last_error = self._extract_reason(resp_json, resp_text) or last_error
                        continue

                    reason_txt = self._extract_reason(resp_json, resp_text) or f"HTTP {status_code}"
                    last_error = reason_txt

                    if self._is_not_found(reason_txt, status_code):
                        if self._confirm_closed(deal_key, deal_canon):
                            self._recent_close_success[deal_key] = time.time()
                            self._positions_cache = None
                            return OrderResult(
                                success=True, deal_id=deal_id,
                                reason="Already closed", profile=pname,
                            )
                        if id_mode == "dealid" and pos_epic:
                            allow_epic_fb = True
                            dealid_unusable = True
                        continue

                    if self._is_auth_issue(reason_txt, status_code):
                        self.session_mgr.connected = False
                        self.ensure_connected(force=True)
                    continue

                except Exception as exc:
                    self._handle_api_error(exc, f"Close {deal_id} [{pname}]")
                    last_error = str(exc)

            # After all profiles: re-check closure
            if self._confirm_closed(deal_key, deal_canon):
                self._recent_close_success[deal_key] = time.time()
                self._positions_cache = None
                return OrderResult(
                    success=True, deal_id=deal_id, reason="Confirmed after retry loop",
                )

            time.sleep(0.45 * attempt)

        return OrderResult(success=False, deal_id=deal_id, error=last_error)

    # ═══════════════════════════════════════════════════════════
    # UPDATE POSITION RISK
    # ═══════════════════════════════════════════════════════════

    def update_position_risk(
        self,
        deal_id: str,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
    ) -> OrderResult:
        """Update SL/TP levels (absolute prices) on an open position."""
        self._enter_trade_priority(10.0)
        deal_key = str(deal_id or "").upper().strip()

        if not deal_key:
            return OrderResult(success=False, error="deal_id missing")
        if sl_price is None and tp_price is None:
            return OrderResult(success=False, error="No levels to update")

        now_ts = time.time()
        block_until = self._risk_update_block_until.get(deal_key, 0)
        if block_until > now_ts:
            return OrderResult(success=False, error="RISK_UPDATE_COOLDOWN")

        if not self.ensure_connected(force=True):
            return OrderResult(success=False, error="Reconnection failed")

        try:
            stop_lvl = round(_safe_float(sl_price), 2) if sl_price is not None else None
            limit_lvl = round(_safe_float(tp_price), 2) if tp_price is not None else None

            with self.session_mgr.api_lock:
                self._throttle(is_trading=True)
                result = self.ig_service.update_open_position(
                    limit_level=limit_lvl,
                    stop_level=stop_lvl,
                    deal_id=deal_id,
                    guaranteed_stop=False,
                    trailing_stop=False,
                    trailing_stop_distance=None,
                    trailing_stop_increment=None,
                    version="2",
                )

            success, reason, deal_ref = self._parse_update_result(result)
            if success:
                self._positions_cache = None
                self._risk_update_failures.pop(deal_key, None)
                self._risk_update_block_until.pop(deal_key, None)
                logger.info(
                    "Position risk updated %s: stop=%s limit=%s",
                    deal_id,
                    stop_lvl if stop_lvl is not None else "-",
                    limit_lvl if limit_lvl is not None else "-",
                )
                return OrderResult(
                    success=True, deal_id=deal_id, deal_reference=deal_ref or "",
                )

            # Track failures for anti-loop cooldown
            fail_count = self._risk_update_failures.get(deal_key, 0) + 1
            self._risk_update_failures[deal_key] = fail_count
            if fail_count >= 3:
                cooldown = min(45, 6 * (2 ** min(fail_count - 3, 3)))
                self._risk_update_block_until[deal_key] = now_ts + cooldown

            return OrderResult(success=False, deal_id=deal_id, error=reason)

        except Exception as exc:
            self._handle_api_error(exc, f"Update Position {deal_id}")
            return OrderResult(success=False, deal_id=deal_id, error=str(exc))

    # ═══════════════════════════════════════════════════════════
    # ACCOUNT INFO
    # ═══════════════════════════════════════════════════════════

    def get_sentiment(self, market_id: str = "ETHUSD") -> Optional[Dict[str, Any]]:
        """Fetch client sentiment (% long vs short) for an instrument."""
        now = time.time()

        # Cache: refresh every 60s max
        cache_key = f"_sentiment_{market_id}"
        cached = getattr(self, cache_key, None)
        cached_ts = getattr(self, f"{cache_key}_ts", 0)
        if cached and (now - cached_ts) < 60:
            return cached

        if not self.ensure_connected():
            return cached or None

        try:
            with self.session_mgr.api_lock:
                self._throttle(is_trading=False)
                sentiment = self.ig_service.fetch_client_sentiment_by_instrument(market_id)

            if not sentiment:
                return cached or None

            data = {
                "market_id": str(getattr(sentiment, "marketId", market_id)),
                "long_pct": float(getattr(sentiment, "longPositionPercentage", 50)),
                "short_pct": float(getattr(sentiment, "shortPositionPercentage", 50)),
            }
            setattr(self, cache_key, data)
            setattr(self, f"{cache_key}_ts", now)
            self.session_mgr.mark_success()
            return data

        except Exception as exc:
            self._handle_api_error(exc, "Sentiment")
            return cached or None

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        """Fetch account balance and info."""
        now = time.time()
        if self._account_cache and (now - self._account_cache_ts) < 20:
            return self._account_cache
        if (self.session_mgr.auth_storm_cooldown_active() or self.session_mgr.server_issue_cooldown_active()):
            if self._account_cache and (now - self._account_cache_ts) < 300:
                return self._account_cache

        if not self.ensure_connected():
            return self._account_cache or None

        try:
            with self.session_mgr.api_lock:
                self._throttle(is_trading=False)
                accounts = self.ig_service.fetch_accounts()

            if accounts is None or accounts.empty:
                return None

            target = str(self.account_id or "").strip()
            acc = accounts[accounts["accountId"].astype(str).str.strip() == target]
            account = acc.iloc[0] if not acc.empty else accounts.iloc[0]

            info = {
                "account_id": str(account.get("accountId", "")),
                "balance": float(account.get("balance", 0)),
                "deposit": float(account.get("deposit", 0)),
                "profit_loss": float(account.get("profitLoss", 0)),
                "available": float(account.get("available", 0)),
                "currency": str(account.get("currency", "EUR")),
            }
            self._account_cache = info
            self._account_cache_ts = time.time()
            self.session_mgr.mark_success()
            return info

        except Exception as exc:
            self._handle_api_error(exc, "Account balance")
            return self._account_cache or None

    # ═══════════════════════════════════════════════════════════
    # ERROR HANDLING
    # ═══════════════════════════════════════════════════════════

    def _handle_api_error(self, exc: Exception, context: str) -> None:
        """Centralised IG API error handler."""
        err_str = str(exc).lower()
        now = time.time()
        mgr = self.session_mgr

        status_code = 0
        response_error_code = ""
        body = ""
        if hasattr(exc, "response") and exc.response is not None:
            try:
                status_code = int(getattr(exc.response, "status_code", 0) or 0)
            except Exception:
                pass
            try:
                body = str(exc.response.text or "")
            except Exception:
                pass
            try:
                payload = exc.response.json()
                if isinstance(payload, dict):
                    response_error_code = str(
                        payload.get("errorCode") or payload.get("error") or ""
                    ).strip()
            except Exception:
                pass

        full_err = " | ".join(filter(None, [
            err_str,
            f"http={status_code}" if status_code else "",
            f"code={response_error_code}" if response_error_code else "",
        ]))

        # Historical data allowance exceeded (account-level quota, not per-minute)
        if "exceeded-account-historical-data-allowance" in full_err:
            self._quota_exceeded_until = time.time() + 3600  # 1h backoff, serve from MongoDB cache
            logger.warning("IG historical data allowance exceeded (%s) — using MongoDB cache for 1h", context)
            mgr.last_error = "IG historical data allowance exceeded — using cached data"
            return
        # Per-minute API key rate limit
        if "exceeded-api-key-allowance" in full_err or "allowance" in full_err:
            self._quota_exceeded_until = time.time() + 65  # Wait ~1 minute for rate limit reset
            logger.warning("IG rate limit hit (%s) — pausing 65s", context)
            mgr.last_error = "IG rate limit (per-minute) — retry in 65s"
            return

        # Auth errors
        full_l = full_err.lower()
        has_auth = any(m in full_l for m in _AUTH_MARKERS)
        has_validation = any(m in full_l for m in _VALIDATION_MARKERS)
        is_auth = (
            status_code == 401
            or has_auth
            or (status_code == 403 and not has_validation and not _is_transient_error(full_l))
        )

        if is_auth and not has_validation:
            mgr.connected = False
            mgr._last_login_failed = False
            mgr.register_auth_storm(context)
            hard_markers = ("invalid credentials", "api key invalid", "apikey disabled")
            if any(m in full_l for m in hard_markers):
                mgr.clear_persisted_session()

        # Transient server error
        if _is_transient_error(full_l):
            mgr.register_server_issue(context, full_l)

        logger.error("IG API error (%s): %s", context, full_err[:300])

    # ═══════════════════════════════════════════════════════════
    # PRIVATE HELPERS
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _format_login_error(exc: Exception) -> str:
        detail = str(exc or "").strip()
        if hasattr(exc, "response") and exc.response is not None:
            try:
                rj = exc.response.json()
                code = str(rj.get("errorCode", "")).strip()
                msg = str(rj.get("error", exc.response.text) or "").strip()
                if code:
                    return f"{code} | {msg}"
                return msg or detail
            except Exception:
                try:
                    return f"HTTP {exc.response.status_code} | {exc.response.text}"
                except Exception:
                    return detail
        return detail or type(exc).__name__

    @staticmethod
    def _extract_login_account(response_data: Any) -> Optional[str]:
        if not isinstance(response_data, dict):
            return None
        acc = str(response_data.get("accountId") or response_data.get("currentAccountId") or "").strip()
        if acc:
            return acc
        try:
            accounts = response_data.get("accounts") or []
            if isinstance(accounts, list):
                for a in accounts:
                    if isinstance(a, dict) and bool(a.get("preferred")):
                        aid = str(a.get("accountId", "")).strip()
                        if aid:
                            return aid
                for a in accounts:
                    if isinstance(a, dict):
                        aid = str(a.get("accountId", "")).strip()
                        if aid:
                            return aid
        except Exception:
            pass
        return None

    def _finalize_account(self, login_acc: Optional[str], target: str) -> None:
        """Switch to target account after login if needed."""
        mgr = self.session_mgr
        runtime = str(login_acc or target).strip()

        if login_acc and str(login_acc).strip() != str(target).strip():
            try:
                self._throttle(is_trading=False)
                mgr.ig_service.switch_account(target, False)
                runtime = target
            except Exception as exc:
                msg = str(exc).lower()
                if "must-be-different" in msg:
                    runtime = target
                elif "status code: 500" in msg or "internal server error" in msg:
                    runtime = str(login_acc).strip()
                    logger.warning("IG switch transient failure; keeping account %s", runtime)
                else:
                    raise

        runtime = runtime or target
        mgr.account_id = runtime
        setattr(mgr.ig_service, "accountId", runtime)
        setattr(mgr.ig_service, "ACC_NUMBER", runtime)
        mgr.ig_service.session.headers["IG-ACCOUNT-ID"] = runtime

    def _cache_guard_positions(self, now: float, storm_ttl: float, trade_ttl: float, server_ttl: float):
        """Return cached positions if any circuit breaker is active."""
        mgr = self.session_mgr
        if not self._positions_cache:
            return None
        ts, data = self._positions_cache
        if mgr.auth_storm_cooldown_active() and (now - ts) < storm_ttl:
            return data
        if self._is_trade_priority_active() and (now - ts) < trade_ttl:
            return data
        if mgr.server_issue_cooldown_active() and (now - ts) < server_ttl:
            return data
        return None

    def _storm_guard_ticker(self, epic: str, now: float, storm: float, trade: float, server: float) -> bool:
        """Check if ticker should be served from cache due to active guards."""
        if epic not in self._ticker_cache:
            return False
        ts = self._ticker_cache_ts.get(epic, 0)
        mgr = self.session_mgr
        if mgr.auth_storm_cooldown_active() and (now - ts) < storm:
            return True
        if self._is_trade_priority_active() and (now - ts) < trade:
            return True
        if mgr.server_issue_cooldown_active() and (now - ts) < server:
            return True
        return False

    @staticmethod
    def _ticker_from_dict(d: Dict[str, Any]) -> Ticker:
        return Ticker(
            epic=d.get("epic", ""),
            name=d.get("name", ""),
            bid=d.get("bid", 0.0),
            offer=d.get("offer", 0.0),
            high=d.get("high", 0.0),
            low=d.get("low", 0.0),
            change_pct=d.get("change", 0.0),
            market_status=d.get("market_status", "CLOSED"),
            min_size=d.get("min_size", 0.1),
            min_stop_distance=d.get("min_stop_distance"),
            min_limit_distance=d.get("min_limit_distance"),
            timestamp=time.time(),
        )

    def _stale_ticker(self, epic: str, now: float) -> Optional[Ticker]:
        if epic in self._ticker_cache:
            ts = self._ticker_cache_ts.get(epic, 0)
            if (now - ts) < 3600:
                return self._ticker_from_dict(self._ticker_cache[epic])
        return None

    @staticmethod
    def _safe_attr(obj, name: str):
        try:
            return obj.get(name) if hasattr(obj, "get") else getattr(obj, name, None)
        except Exception:
            return None

    def _parse_candles(self, df) -> List[Candle]:
        """Parse IG historical prices DataFrame into Candle list."""
        candles: List[Candle] = []
        for idx, row in df.iterrows():
            try:
                if isinstance(idx, pd.Timestamp):
                    ts = int(idx.timestamp())
                else:
                    ts = int(pd.to_datetime(idx).timestamp())

                def mid(bid_key, ask_key):
                    b = _safe_float(row.get(("bid", bid_key), 0))
                    a = _safe_float(row.get(("ask", ask_key), 0))
                    return (b + a) / 2

                o = mid("Open", "Open")
                h = mid("High", "High")
                lo = mid("Low", "Low")
                c = mid("Close", "Close")

                vol = 0
                if ("last", "Volume") in row:
                    vol = int(_safe_float(row[("last", "Volume")]))
                elif ("tick", "Count") in row:
                    vol = int(_safe_float(row[("tick", "Count")]))

                if o == 0 and c == 0:
                    continue

                candles.append(Candle(timestamp=ts, open=o, high=h, low=lo, close=c, volume=vol))
            except Exception:
                continue

        candles.sort(key=lambda x: x.timestamp)
        return candles

    def _confirm_closed(self, deal_key: str, deal_canon: str) -> bool:
        """Check that a position is no longer in the open positions list."""
        for _ in range(3):
            time.sleep(0.35)
            self._positions_cache = None
            positions = self.get_positions()
            still_open = False
            for pos in positions:
                pid = str(pos.deal_id).upper().strip()
                if pid == deal_key or self._canonical_id(pid) == deal_canon:
                    still_open = True
                    break
            if not still_open:
                return True
        return False

    @staticmethod
    def _extract_reason(resp_json: Any, raw_text: str) -> str:
        if isinstance(resp_json, dict):
            for key in ("errorCode", "reason", "error", "message"):
                val = resp_json.get(key)
                if val:
                    return str(val)
        txt = str(raw_text or "").strip()
        return txt[:300] if txt else "Unknown"

    @staticmethod
    def _is_not_found(reason: str, status_code: int = 0) -> bool:
        if status_code == 404:
            return True
        r = str(reason or "").lower()
        markers = ("position not found", "deal not found", "not found", "invalid_deal")
        return any(m in r for m in markers)

    @staticmethod
    def _is_auth_issue(reason: str, status_code: int = 0) -> bool:
        if status_code == 401:
            return True
        r = str(reason or "").lower()
        return any(m in r for m in _AUTH_MARKERS)

    @staticmethod
    def _parse_update_result(raw: Any):
        success = False
        reason = ""
        deal_ref = None
        if isinstance(raw, dict):
            reason = str(raw.get("reason") or "").strip()
            deal_ref = raw.get("dealReference") or raw.get("dealId")
            status_up = str(raw.get("status", "")).upper()
            deal_status_up = str(raw.get("dealStatus", "")).upper()
            ok_markers = {"SUCCESS", "OK", "ACCEPTED", "OPEN"}
            if reason.upper() in ok_markers:
                success = True
            elif status_up in ok_markers or deal_status_up in ok_markers:
                success = True
            elif (not reason or reason.upper() in ("NONE", "NULL")) and deal_ref:
                success = True
        elif raw:
            success = True
        return success, reason, deal_ref

    def _try_apply_post_open_risk(
        self,
        deal_id: str,
        direction: str,
        epic: str,
        base_stop: Optional[float],
        base_limit: Optional[float],
        safe_floor: float,
    ) -> bool:
        """After opening without attached levels, try to apply SL/TP via update."""
        if base_stop is None and base_limit is None:
            return True

        # Find the entry price
        open_level = 0.0
        for attempt in range(5):
            self._positions_cache = None
            for pos in self.get_positions():
                if pos.deal_id == deal_id:
                    open_level = pos.entry_price
                    break
            if open_level > 0:
                break
            time.sleep(1.0)

        if open_level <= 0:
            return False

        # Compute absolute levels from distances
        attempts = [
            (base_stop, base_limit),
            (
                max(float(base_stop or safe_floor), safe_floor) if base_stop is not None else None,
                max(float(base_limit or safe_floor), safe_floor) if base_limit is not None else None,
            ),
            (
                max(float(base_stop or safe_floor * 1.5), safe_floor * 1.5) if base_stop is not None else None,
                max(float(base_limit or safe_floor * 1.5), safe_floor * 1.5) if base_limit is not None else None,
            ),
        ]

        for sd, ld in attempts:
            sl = None
            tp = None
            if direction == "BUY":
                if sd is not None:
                    sl = round(open_level - float(sd), 2)
                if ld is not None:
                    tp = round(open_level + float(ld), 2)
            else:
                if sd is not None:
                    sl = round(open_level + float(sd), 2)
                if ld is not None:
                    tp = round(open_level - float(ld), 2)

            res = self.update_position_risk(deal_id, sl_price=sl, tp_price=tp)
            if res.success:
                return True

        return False


# ═══════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════
_client: Optional[IGClient] = None
_client_lock = threading.Lock()


def get_ig_client(settings: Optional[AppSettings] = None) -> IGClient:
    """Return the singleton IGClient instance (thread-safe)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                if settings is None:
                    settings = AppSettings.from_env()
                _client = IGClient(settings)
                _client.start_watchdog()
    return _client
