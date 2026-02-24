"""
OpenCenterAI — Config Endpoints (FastAPI)
==========================================
Read / update trading parameters and config change history.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.middleware import verify_auth
from config.settings import TradingParams

logger = logging.getLogger(__name__)
router = APIRouter()


# ═════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═════════════════════════════════════════════════════════════════
class ConfigResponse(BaseModel):
    params: Dict[str, Any]
    runtime_fields: List[str]
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


class ConfigUpdateRequest(BaseModel):
    """Only RUNTIME_FIELDS keys are accepted; others are silently rejected."""
    updates: Dict[str, Any]


class ConfigUpdateResponse(BaseModel):
    success: bool
    message: str
    applied: Dict[str, Any]
    rejected: List[str]


class ConfigHistoryEntry(BaseModel):
    timestamp: Optional[str] = None
    source: Optional[str] = None
    params: Dict[str, Any]


class ConfigHistoryResponse(BaseModel):
    entries: List[ConfigHistoryEntry]
    count: int


# ═════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═════════════════════════════════════════════════════════════════

@router.get("", response_model=ConfigResponse)
async def get_config(user: str = Depends(verify_auth)):
    """Current trading parameters (full snapshot)."""
    from db.config_repo import load_trading_params

    try:
        params = load_trading_params()
        return ConfigResponse(
            params=params.to_dict(),
            runtime_fields=sorted(TradingParams.RUNTIME_FIELDS),
        )

    except Exception as e:
        logger.exception("Error loading config")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("", response_model=ConfigUpdateResponse)
async def update_config(
    body: ConfigUpdateRequest,
    user: str = Depends(verify_auth),
):
    """
    Update RUNTIME fields only (validated).
    Read-only fields are rejected but do not cause a 400 error.
    """
    from db.config_repo import update_runtime_fields

    updates = body.updates
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    allowed = TradingParams.RUNTIME_FIELDS
    rejected = [k for k in updates if k not in allowed]
    applied_keys = {k: v for k, v in updates.items() if k in allowed}

    if not applied_keys:
        raise HTTPException(
            status_code=400,
            detail=f"No valid runtime fields. Allowed: {sorted(allowed)}",
        )

    try:
        params = update_runtime_fields(applied_keys, source=f"dashboard:{user}")
        if params is None:
            raise HTTPException(status_code=500, detail="Failed to update config")

        logger.info(
            "Config updated by %s: %s (rejected: %s)", user, applied_keys, rejected
        )

        return ConfigUpdateResponse(
            success=True,
            message="Config updated",
            applied=applied_keys,
            rejected=rejected,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating config")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history", response_model=ConfigHistoryResponse)
async def get_config_history(
    limit: int = Query(20, ge=1, le=100),
    user: str = Depends(verify_auth),
):
    """Config change history (most recent first)."""
    from db.mongo import get_db
    from db.collections import CONFIG_HISTORY

    try:
        db = get_db()
        cursor = (
            db[CONFIG_HISTORY]
            .find()
            .sort("timestamp", -1)
            .limit(limit)
        )

        entries = []
        for doc in cursor:
            doc.pop("_id", None)
            ts = doc.get("timestamp")
            entries.append(
                ConfigHistoryEntry(
                    timestamp=ts.isoformat() if isinstance(ts, datetime) else str(ts) if ts else None,
                    source=doc.get("source"),
                    params=doc.get("params", {}),
                )
            )

        return ConfigHistoryResponse(entries=entries, count=len(entries))

    except Exception as e:
        logger.exception("Error fetching config history")
        raise HTTPException(status_code=500, detail=str(e))
