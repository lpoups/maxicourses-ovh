"""
OpenCenterAI — FastAPI Middleware
==================================
Auth, CORS, error handling, IP whitelist.
"""

import logging
import secrets
from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from config.settings import AppSettings

logger = logging.getLogger(__name__)
security = HTTPBasic()

# ── Singleton settings (loaded once at startup) ─────────────────
_settings: Optional[AppSettings] = None


def init_settings(settings: AppSettings) -> None:
    """Inject app settings at startup."""
    global _settings
    _settings = settings


def _get_settings() -> AppSettings:
    if _settings is None:
        raise RuntimeError("Settings not initialised — call init_settings() first")
    return _settings


# ═════════════════════════════════════════════════════════════════
# AUTH DEPENDENCY
# ═════════════════════════════════════════════════════════════════
def verify_auth(request: Request) -> str:
    """
    Auth dependency — accepts EITHER:
      1. Valid HTTP Basic credentials (Authorization header)
      2. Whitelisted IP (via X-Real-IP header from nginx, or direct client IP)
    Returns username or IP on success.
    """
    settings = _get_settings()

    # 1. Try HTTP Basic auth if Authorization header present
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("basic "):
        import base64
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
            login_ok = secrets.compare_digest(username, settings.auth_login)
            pwd_ok = secrets.compare_digest(password, settings.auth_password)
            if login_ok and pwd_ok:
                return username
        except Exception:
            pass

    # 2. Check IP whitelist (nginx sets X-Real-IP)
    client_ip = (
        request.headers.get("x-real-ip")
        or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "")
    )
    if client_ip and client_ip in settings.ip_whitelist:
        return f"ip:{client_ip}"

    # 3. Neither auth nor whitelisted IP → 401
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Basic"},
    )


# ═════════════════════════════════════════════════════════════════
# IP WHITELIST CHECK
# ═════════════════════════════════════════════════════════════════
async def check_ip_whitelist(request: Request) -> None:
    """Reject requests from non-whitelisted IPs (when list is non-empty)."""
    settings = _get_settings()
    whitelist = settings.ip_whitelist

    if not whitelist:
        return

    client_ip = request.client.host if request.client else "unknown"
    if client_ip not in whitelist:
        logger.warning("IP rejected: %s (whitelist=%s)", client_ip, whitelist)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="IP not allowed",
        )


# ═════════════════════════════════════════════════════════════════
# CORS
# ═════════════════════════════════════════════════════════════════
def setup_cors(app) -> None:
    """Attach CORS middleware to the FastAPI app."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # tightened in production via env
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ═════════════════════════════════════════════════════════════════
# GLOBAL ERROR HANDLER
# ═════════════════════════════════════════════════════════════════
def setup_error_handlers(app) -> None:
    """Register exception handlers returning consistent JSON."""

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.detail, "status": exc.status_code},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "status": 500},
        )
