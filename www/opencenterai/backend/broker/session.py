"""
OpenCenterAI Trading -- IG Session Manager
============================================
Handles:
  - IPv4 enforcement (IG blocks IPv6)
  - OAuth session lifecycle (create, refresh, persist to MongoDB)
  - Reconnection with exponential backoff
  - Circuit-breaker patterns (server outage, auth storm)
  - Session state extraction and recovery
  - Thread-safe API lock
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from trading_ig import IGService
from trading_ig.rest import IGException

from config.settings import AppSettings
from db.mongo import get_db

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# IPv4 ENFORCEMENT
# IG API blocks unrecognised IPv6 connections.
# Monkey-patch socket.getaddrinfo once at module load.
# ═══════════════════════════════════════════════════════════════
_original_getaddrinfo = socket.getaddrinfo


def _ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """Force IPv4 (AF_INET) for all DNS resolution."""
    return _original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = _ipv4_only_getaddrinfo

# ═══════════════════════════════════════════════════════════════
# MONGODB COLLECTION FOR SESSION STATE
# ═══════════════════════════════════════════════════════════════
_SESSION_COLLECTION = "ig_sessions"
_SESSION_DOC_ID = "current"


class IGSessionManager:
    """
    Manages IG API session lifecycle: login, refresh, persist, recover.

    All public methods that touch the IG session acquire ``api_lock``
    internally, so callers never need to manage locking themselves.
    """

    def __init__(self, settings: AppSettings):
        self.settings = settings

        # ── Core state ──────────────────────────────────────────
        self.ig_service: Optional[IGService] = None
        self.connected: bool = False
        self.account_id: Optional[str] = None
        self.last_error: Optional[str] = None
        self.last_success: float = 0.0

        # ── Login backoff ───────────────────────────────────────
        self.last_login_attempt: float = 0.0
        self.backoff_count: int = 0
        self._last_login_failed: bool = False
        self.LOGIN_COOLDOWN: float = 30.0
        self.LOGIN_COOLDOWN_DEMO: float = 10.0
        self.LOGIN_COOLDOWN_DEMO_MAX: float = 60.0

        # ── Session probe / degraded ────────────────────────────
        self._session_check_degraded_until: float = 0.0
        self._session_check_fail_count: int = 0
        self._last_session_degraded_log: float = 0.0
        self.SESSION_OK_GRACE_SEC: float = 90.0
        self.SESSION_PROBE_MIN_INTERVAL_SEC: float = 18.0
        self._last_session_probe_ts: float = 0.0

        # ── Auth repair guard ───────────────────────────────────
        self.AUTH_REPAIR_MIN_INTERVAL_SEC: float = 8.0
        self._last_auth_repair_attempt_ts: float = 0.0

        # ── Auth-storm circuit breaker ──────────────────────────
        self.AUTH_STORM_WINDOW_SEC: float = 35.0
        self.AUTH_STORM_THRESHOLD: int = 3
        self.AUTH_STORM_COOLDOWN_SEC: float = 20.0
        self._auth_storm_count: int = 0
        self._auth_storm_last_ts: float = 0.0
        self._auth_storm_until: float = 0.0
        self._last_auth_storm_log: float = 0.0

        # ── Server-outage circuit breaker ───────────────────────
        self._server_issue_count: int = 0
        self._server_issue_until: float = 0.0
        self._last_server_issue_log: float = 0.0
        self.SERVER_ISSUE_THRESHOLD: int = 3
        self.SERVER_ISSUE_BASE_COOLDOWN_SEC: float = 10.0
        self.SERVER_ISSUE_MAX_COOLDOWN_SEC: float = 120.0

        # ── Login version skip memory ──────────────────────────
        self._login_version_skip_until: Dict[str, float] = {}

        # ── Thread safety ──────────────────────────────────────
        self.api_lock = threading.RLock()

        logger.info("IGSessionManager initialised (id=%s)", hex(id(self)))

    # ─────────────────────────────────────────────────────────────
    # PROPERTIES / HELPERS
    # ─────────────────────────────────────────────────────────────

    @property
    def is_demo(self) -> bool:
        return str(self.settings.ig_mode).upper() == "DEMO"

    # ─────────────────────────────────────────────────────────────
    # CIRCUIT BREAKERS
    # ─────────────────────────────────────────────────────────────

    def register_server_issue(self, context: str, detail: str = "") -> None:
        """Increment outage counter; open a temporary cooldown window."""
        now = time.time()
        self._server_issue_count = min(10, self._server_issue_count + 1)
        if self._server_issue_count >= self.SERVER_ISSUE_THRESHOLD:
            level = self._server_issue_count - self.SERVER_ISSUE_THRESHOLD
            cooldown = min(
                self.SERVER_ISSUE_MAX_COOLDOWN_SEC,
                self.SERVER_ISSUE_BASE_COOLDOWN_SEC * (2 ** min(level, 4)),
            )
            self._server_issue_until = now + cooldown
            if (now - self._last_server_issue_log) > 8.0:
                logger.warning(
                    "IG circuit-breaker active (%s): pause %ds after %d server errors",
                    context, int(cooldown), self._server_issue_count,
                )
                self._last_server_issue_log = now

    def clear_server_issue(self) -> None:
        self._server_issue_count = 0
        self._server_issue_until = 0.0

    def server_issue_cooldown_active(self) -> bool:
        return time.time() < self._server_issue_until

    def register_auth_storm(self, context: str) -> None:
        now = time.time()
        if (now - self._auth_storm_last_ts) <= self.AUTH_STORM_WINDOW_SEC:
            self._auth_storm_count = min(20, self._auth_storm_count + 1)
        else:
            self._auth_storm_count = 1
        self._auth_storm_last_ts = now

        if self._auth_storm_count >= self.AUTH_STORM_THRESHOLD:
            self._auth_storm_until = max(
                self._auth_storm_until, now + self.AUTH_STORM_COOLDOWN_SEC,
            )
            if (now - self._last_auth_storm_log) > 6.0:
                logger.warning(
                    "IG auth-storm guard active (%s): pause info calls %ds (failures=%d)",
                    context, int(self.AUTH_STORM_COOLDOWN_SEC), self._auth_storm_count,
                )
                self._last_auth_storm_log = now

    def clear_auth_storm(self) -> None:
        self._auth_storm_count = 0
        self._auth_storm_last_ts = 0.0
        self._auth_storm_until = 0.0

    def auth_storm_cooldown_active(self) -> bool:
        return time.time() < self._auth_storm_until

    # ─────────────────────────────────────────────────────────────
    # LOGIN VERSION SKIP
    # ─────────────────────────────────────────────────────────────

    def is_login_version_skipped(self, version: str) -> bool:
        until = self._login_version_skip_until.get(str(version), 0.0)
        return time.time() < until

    def skip_login_version_for(self, version: str, seconds: float, reason: str) -> None:
        ver = str(version).strip()
        if ver not in {"1", "2", "3"}:
            return
        until = time.time() + max(30.0, float(seconds))
        if until > self._login_version_skip_until.get(ver, 0.0):
            self._login_version_skip_until[ver] = until
            logger.warning(
                "Login v%s temporarily skipped for %ds (%s)", ver, int(seconds), reason,
            )

    # ─────────────────────────────────────────────────────────────
    # SESSION STATE EXTRACTION / INJECTION
    # ─────────────────────────────────────────────────────────────

    def extract_session_state(self) -> Dict[str, Any]:
        """Collect current authentication tokens + account info."""
        if not self.ig_service:
            return {}

        try:
            session = getattr(self.ig_service, "session", None)
            headers = dict(getattr(session, "headers", {}) or {})
        except Exception:
            headers = {}

        def _pick(*keys: str) -> Optional[str]:
            for key in keys:
                raw = headers.get(key)
                if raw is not None:
                    val = str(raw).strip()
                    if val:
                        return val
            return None

        cst = _pick("CST", "cst")
        x_security_token = _pick("X-SECURITY-TOKEN", "x-security-token")
        authorization = _pick("Authorization", "authorization")
        refresh_token = str(
            getattr(self.ig_service, "_refresh_token", "") or ""
        ).strip() or None

        valid_until_ts: Optional[float] = None
        valid_until = getattr(self.ig_service, "_valid_until", None)
        if isinstance(valid_until, datetime):
            try:
                valid_until_ts = float(valid_until.timestamp())
            except Exception:
                pass

        account_id = str(
            self.account_id
            or getattr(self.ig_service, "accountId", "")
            or headers.get("IG-ACCOUNT-ID", "")
            or self.settings.ig_acc_number
            or ""
        ).strip() or None

        return {
            "cst": cst,
            "x_security_token": x_security_token,
            "authorization": authorization,
            "refresh_token": refresh_token,
            "oauth_valid_until_ts": valid_until_ts,
            "account_id": account_id,
            "timestamp": time.time(),
        }

    def apply_session_state(self, cache: Dict[str, Any]) -> None:
        """Inject a persisted session state into the current IGService instance."""
        if not self.ig_service:
            return

        cst = str(cache.get("cst") or "").strip()
        x_security_token = str(cache.get("x_security_token") or "").strip()
        authorization = str(cache.get("authorization") or "").strip()
        refresh_token = str(cache.get("refresh_token") or "").strip()
        account_id = str(
            cache.get("account_id") or self.settings.ig_acc_number or ""
        ).strip()

        headers_to_apply: Dict[str, str] = {}
        if cst:
            headers_to_apply["CST"] = cst
        if x_security_token:
            headers_to_apply["X-SECURITY-TOKEN"] = x_security_token
        if authorization:
            headers_to_apply["Authorization"] = authorization
        if account_id:
            headers_to_apply["IG-ACCOUNT-ID"] = account_id

        if headers_to_apply:
            try:
                self.ig_service.session.headers.update(headers_to_apply)
            except Exception:
                pass
            try:
                crud_session = getattr(
                    getattr(self.ig_service, "crud_session", None), "session", None,
                )
                if crud_session is not None and crud_session is not self.ig_service.session:
                    crud_session.headers.update(headers_to_apply)
            except Exception:
                pass

        if refresh_token:
            setattr(self.ig_service, "_refresh_token", refresh_token)

        # Preserve OAuth expiry for automatic refresh.
        try:
            if authorization:
                valid_until_ts = cache.get("oauth_valid_until_ts")
                if valid_until_ts:
                    setattr(
                        self.ig_service,
                        "_valid_until",
                        datetime.fromtimestamp(float(valid_until_ts)),
                    )
                else:
                    # Force an early refresh on next request.
                    setattr(
                        self.ig_service,
                        "_valid_until",
                        datetime.now() - timedelta(seconds=1),
                    )
        except Exception:
            pass

        if account_id:
            self.account_id = account_id
            setattr(self.ig_service, "accountId", account_id)
            setattr(self.ig_service, "ACC_NUMBER", account_id)

    # ─────────────────────────────────────────────────────────────
    # MONGODB PERSISTENCE (replaces ig_session.json)
    # ─────────────────────────────────────────────────────────────

    def persist_session(self) -> bool:
        """Save current session tokens to MongoDB for HA recovery."""
        try:
            state = self.extract_session_state()
            has_auth = bool(
                state.get("cst")
                or state.get("authorization")
                or state.get("x_security_token")
            )
            if not has_auth:
                logger.warning("Persist skipped: no auth material in session state")
                return False

            db = get_db()
            state["_id"] = _SESSION_DOC_ID
            db[_SESSION_COLLECTION].replace_one(
                {"_id": _SESSION_DOC_ID}, state, upsert=True,
            )
            logger.info("Session persisted to MongoDB")
            return True
        except Exception as exc:
            logger.warning("Session persist failed: %s", exc)
            return False

    def load_persisted_session(self) -> Optional[Dict[str, Any]]:
        """Load the most recent session state from MongoDB."""
        try:
            db = get_db()
            doc = db[_SESSION_COLLECTION].find_one({"_id": _SESSION_DOC_ID})
            if doc:
                doc.pop("_id", None)
                return doc
        except Exception as exc:
            logger.warning("Session load from MongoDB failed: %s", exc)
        return None

    def clear_persisted_session(self) -> None:
        """Remove persisted session from MongoDB."""
        try:
            db = get_db()
            db[_SESSION_COLLECTION].delete_one({"_id": _SESSION_DOC_ID})
            logger.info("Persisted session cleared from MongoDB")
        except Exception as exc:
            logger.warning("Clear persisted session failed: %s", exc)

    # ─────────────────────────────────────────────────────────────
    # REFRESH / REPAIR
    # ─────────────────────────────────────────────────────────────

    def try_refresh_repair(self) -> bool:
        """Attempt a fast session repair via refresh-token (no full re-login)."""
        if not self.ig_service:
            return False

        now = time.time()
        if (now - self._last_auth_repair_attempt_ts) < self.AUTH_REPAIR_MIN_INTERVAL_SEC:
            return False

        refresh_token = str(
            getattr(self.ig_service, "_refresh_token", "") or ""
        ).strip()
        if not refresh_token:
            return False

        self._last_auth_repair_attempt_ts = now
        try:
            with self.api_lock:
                status = self.ig_service.refresh_session(version="1")
                if int(status or 0) != 200:
                    raise IGException(f"refresh_session status={status}")

                runtime_account = str(
                    self.account_id or self.settings.ig_acc_number or ""
                ).strip()
                if runtime_account:
                    self.ig_service.session.headers["IG-ACCOUNT-ID"] = runtime_account
                    setattr(self.ig_service, "accountId", runtime_account)
                    setattr(self.ig_service, "ACC_NUMBER", runtime_account)
                    self.account_id = runtime_account

                self.ig_service.fetch_accounts()

            self.connected = True
            self.last_success = time.time()
            self._last_login_failed = False
            self.backoff_count = 0
            self._session_check_fail_count = 0
            self._session_check_degraded_until = 0.0
            self.clear_server_issue()
            self.clear_auth_storm()
            self.persist_session()
            logger.info("Session repaired via refresh-token on %s", self.account_id or "N/A")
            return True
        except Exception as exc:
            logger.warning("Session refresh repair failed: %s", exc)
            return False

    # ─────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────

    def _create_ig_service(self) -> IGService:
        """Instantiate a bare IGService with credentials from settings."""
        return IGService(
            username=self.settings.ig_username,
            password=self.settings.ig_password,
            api_key=self.settings.ig_api_key,
            acc_type=self.settings.ig_mode,
            acc_number=self.settings.ig_acc_number,
        )

    def mark_success(self) -> None:
        """Called after any successful IG API call."""
        self.last_success = time.time()
        self.clear_server_issue()
        self.clear_auth_storm()

    def reset_on_login_success(self) -> None:
        """Reset all backoff / degraded counters after a successful login."""
        self.backoff_count = 0
        self._last_login_failed = False
        self._session_check_fail_count = 0
        self._session_check_degraded_until = 0.0
        self.connected = True
        self.last_success = time.time()
        self.clear_server_issue()
        self.clear_auth_storm()
