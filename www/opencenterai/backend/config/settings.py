"""
OpenCenterAI Trading — Settings (Pydantic)
============================================
Chargé depuis variables d'environnement et/ou fichier .env
ZERO fichier JSON. Secrets uniquement dans .env.
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AppSettings:
    """Configuration application — chargée depuis l'environnement."""

    # ── IG Broker ──────────────────────────────────────────────
    ig_mode: str = "DEMO"
    ig_username: str = ""
    ig_password: str = ""
    ig_api_key: str = ""
    ig_acc_number: str = ""

    # ── Claude AI ──────────────────────────────────────────────
    claude_api_key: str = ""
    claude_model_primary: str = "claude-haiku-4-5-20251001"
    claude_model_critical: str = "claude-sonnet-4-20250514"

    # ── MongoDB ────────────────────────────────────────────────
    mongo_uri: str = "mongodb://127.0.0.1:27017"
    mongo_db: str = "opencenterai"

    # ── Flask/FastAPI ──────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 5002
    debug: bool = False

    # ── Auth ───────────────────────────────────────────────────
    auth_login: str = "admin"
    auth_password: str = ""
    secret_key: str = "opencenterai-secret-change-me"
    ip_whitelist: list = field(default_factory=lambda: ["127.0.0.1", "::1"])

    # ── Logging ────────────────────────────────────────────────
    log_level: str = "INFO"
    log_file: str = "logs/trading.log"

    @classmethod
    def from_env(cls) -> "AppSettings":
        """Charge la config depuis les variables d'environnement (préfixe OC_)."""
        prefix = "OC_"
        kwargs = {}

        # Mapping champ → variable d'environnement
        env_map = {
            "ig_mode": "IG_MODE",
            "ig_username": "IG_USERNAME",
            "ig_password": "IG_PASSWORD",
            "ig_api_key": "IG_API_KEY",
            "ig_acc_number": "IG_ACC_NUMBER",
            "claude_api_key": "CLAUDE_API_KEY",
            "claude_model_primary": "CLAUDE_MODEL_PRIMARY",
            "claude_model_critical": "CLAUDE_MODEL_CRITICAL",
            "mongo_uri": "MONGO_URI",
            "mongo_db": "MONGO_DB",
            "host": "HOST",
            "port": "PORT",
            "debug": "DEBUG",
            "auth_login": "AUTH_LOGIN",
            "auth_password": "AUTH_PASSWORD",
            "secret_key": "SECRET_KEY",
            "log_level": "LOG_LEVEL",
            "log_file": "LOG_FILE",
        }

        for field_name, env_suffix in env_map.items():
            # Essayer OC_XXX puis XXX directement
            val = os.environ.get(f"{prefix}{env_suffix}") or os.environ.get(env_suffix)
            if val is not None:
                # Conversion de type
                field_type = cls.__dataclass_fields__[field_name].type
                if field_type == "int":
                    val = int(val)
                elif field_type == "bool":
                    val = val.lower() in ("true", "1", "yes")
                kwargs[field_name] = val

        # IP whitelist depuis variable d'environnement (séparées par virgule)
        ip_wl = os.environ.get(f"{prefix}IP_WHITELIST") or os.environ.get("IP_WHITELIST")
        if ip_wl:
            kwargs["ip_whitelist"] = [ip.strip() for ip in ip_wl.split(",")]

        return cls(**kwargs)


@dataclass
class TradingParams:
    """
    Paramètres de trading — Persistés dans MongoDB collection 'config'.
    C'est la SOURCE UNIQUE DE VÉRITÉ pour tous les paramètres de trading.
    Modifiable via le dashboard → PUT /api/config.
    """

    # ── Exécution ──────────────────────────────────────────────
    enabled: bool = False
    mode: str = "AGRESSIF"                      # AGRESSIF | PRUDENT
    frequency_mode: str = "AUTO"                # AUTO | MANUAL | OFF
    position_size_eth: float = 2.0
    max_open_positions: int = 2
    max_total_exposure_eth: float = 4.0
    min_confidence: int = 65
    loop_interval_sec: int = 5
    min_trade_interval_sec: int = 180
    entry_attempt_cooldown_sec: int = 15

    # ── Risk Management ────────────────────────────────────────
    sl_pct: float = 0.01                        # 1% du prix
    tp_pct: float = 0.02                        # 2% du prix (RR 1:2)
    stop_distance_pts: float = 40.0
    limit_distance_pts: float = 60.0
    hard_loss_cap_pct: float = 0.02             # 2% du montant position
    hard_loss_cap_eur: float = 80.0
    daily_loss_limit_eur: float = 50.0
    loss_cooldown_min: int = 5
    early_stop_ratio: float = 0.62

    # ── AI Exit ────────────────────────────────────────────────
    ai_exit_only_mode: bool = True

    # ── AI Blind Exit (protection quand IA indisponible) ──────
    ai_blind_exit_enabled: bool = True
    ai_blind_exit_loss_eur: float = 80.0
    ai_blind_exit_min_blind_sec: int = 180
    ai_blind_profit_exit_pts: float = 2.0

    # ── Profit Retrace ─────────────────────────────────────────
    profit_retrace_enabled: bool = True
    profit_retrace_arm_ratio: float = 0.45
    profit_retrace_keep_ratio: float = 0.55
    profit_retrace_min_peak_eur: float = 10.0
    profit_retrace_min_drop_eur: float = 3.0
    profit_retrace_force_drop_ratio: float = 0.45
    profit_retrace_min_adverse_markers: int = 2

    # ── Partial Exit ───────────────────────────────────────────
    partial_exit_enabled: bool = True
    partial_exit_min_profit_eur: float = 8.0
    partial_exit_size_step: float = 1.0
    partial_exit_min_close_eth: float = 1.0
    partial_exit_min_remaining_eth: float = 1.0
    partial_exit_cooldown_sec: int = 35
    partial_exit_min_progress_eur: float = 5.0

    # ── Trailing / Preserve Gains ──────────────────────────────
    preserve_gains_enabled: bool = True
    preserve_gain_trigger_ratio: float = 0.25
    preserve_gain_lock_ratio: float = 0.75
    dynamic_mode: bool = True
    dynamic_manage_open_risk: bool = True
    dynamic_risk_min_update_sec: int = 20
    prevent_sl_widening: bool = True

    # ── AI Autonomous Risk ─────────────────────────────────────
    ai_autonomous_risk_enabled: bool = True
    ai_autonomous_sl_atr_mult: float = 1.25
    ai_autonomous_tp_rr_trend: float = 2.20
    ai_autonomous_tp_rr_range: float = 2.50
    ai_autonomous_tp_rr_transition: float = 1.80
    ai_autonomous_tp_rr_turbo: float = 1.35
    ai_autonomous_min_rr: float = 1.50
    ai_autonomous_max_rr: float = 2.40

    # ── Timing / Fréquence IA ──────────────────────────────────
    analysis_interval_idle_min: int = 10
    analysis_interval_active_min: int = 2
    check_interval_sec: int = 60
    max_data_age_sec: int = 600

    # ── Scalping Mode ──────────────────────────────────────────
    scalping_mode_enabled: bool = False
    scalping_interval_with_position_sec: int = 15
    scalping_interval_without_position_sec: int = 60

    # ── Schedule ───────────────────────────────────────────────
    entry_block_hours_enabled: bool = False
    entry_block_hours_paris: list = field(default_factory=list)
    ig_connect_retry_base_sec: int = 20
    ig_connect_retry_max_sec: int = 180
    ig_weekly_preclose_buffer_min: int = 15

    # ── Knowledge Base ─────────────────────────────────────────
    kb_recompute_interval_sec: int = 300
    kb_min_trades_per_bucket: int = 3
    kb_avoid_hour_min_trades: int = 5
    kb_avoid_hour_max_wr: float = 15.0
    kb_worst_hour_max_wr: float = 25.0

    # ── Next Trade Secure ──────────────────────────────────────
    next_trade_secure_after_loss_enabled: bool = True
    next_trade_secure_loss_trigger_eur: float = 21.0
    next_trade_secure_gain_trigger_ratio: float = 0.30
    next_trade_secure_gain_lock_ratio: float = 0.70

    # ── Hybrid / Prediction ────────────────────────────────────
    hybrid_analysis_mode: str = "SERVER"
    hybrid_prediction_max_age_sec: int = 180

    # ── Market ─────────────────────────────────────────────────
    reversal_risk_threshold: int = 60
    chase_atr_threshold: float = 0.8
    range_breakout_strength_min: int = 65

    def to_dict(self) -> dict:
        """Sérialise en dict pour MongoDB."""
        from dataclasses import asdict
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TradingParams":
        """Désérialise depuis un dict MongoDB."""
        import dataclasses
        valid_fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    # Champs modifiables via le dashboard (les autres sont en lecture seule)
    RUNTIME_FIELDS = {
        "enabled", "mode", "frequency_mode",
        "position_size_eth", "stop_distance_pts", "limit_distance_pts",
        "min_confidence", "max_open_positions",
        "hybrid_analysis_mode", "scalping_mode_enabled",
        "daily_loss_limit_eur",
    }
