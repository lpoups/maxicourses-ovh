"""
OpenCenterAI — Trading Endpoints (FastAPI)
============================================
Positions, trade history, engine start/stop, manual close.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from api.middleware import verify_auth
from api.websocket import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter()


# ═════════════════════════════════════════════════════════════════
# PYDANTIC RESPONSE / REQUEST MODELS
# ═════════════════════════════════════════════════════════════════
class PositionOut(BaseModel):
    deal_id: str
    direction: str
    size: float
    entry_price: float
    current_price: float = 0.0
    pnl: float = 0.0
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    created_at: Optional[str] = None


class PositionListResponse(BaseModel):
    positions: List[PositionOut]
    count: int


class TradeOut(BaseModel):
    trade_id: str
    deal_id: str
    direction: str
    size: float
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    pnl_eur: Optional[float] = None
    peak_pnl: Optional[float] = None
    status: str
    exit_reason: Optional[str] = None
    duration_sec: Optional[float] = None
    open_timestamp: Optional[str] = None
    close_timestamp: Optional[str] = None


class TradeHistoryResponse(BaseModel):
    trades: List[TradeOut]
    total: int
    skip: int
    limit: int


class EngineActionResponse(BaseModel):
    success: bool
    message: str
    engine_running: bool = False


class ClosePositionResponse(BaseModel):
    success: bool
    message: str
    deal_id: str


class ManualOrderRequest(BaseModel):
    direction: str = Field(..., pattern="^(BUY|SELL)$", description="BUY for long, SELL for short")
    size: float = Field(default=0.0, ge=0.0, le=10.0, description="Position size in ETH (0 = use config default)")
    sl_pts: Optional[float] = Field(default=None, ge=0, le=250, description="Stop-loss distance in points")
    tp_pts: Optional[float] = Field(default=None, ge=0, le=500, description="Take-profit distance in points")


class ManualOrderResponse(BaseModel):
    success: bool
    message: str
    deal_id: str = ""
    direction: str = ""
    size: float = 0.0


# ═════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════
def _serialize_trade(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Convert MongoDB trade doc to API-safe dict."""
    doc.pop("_id", None)
    for ts_field in ("open_timestamp", "close_timestamp", "created_at"):
        val = doc.get(ts_field)
        if isinstance(val, datetime):
            doc[ts_field] = val.isoformat()
    # Extract peak_pnl from exit_context if available
    exit_ctx = doc.get("exit_context") or {}
    if isinstance(exit_ctx, dict) and "peak_pnl" in exit_ctx:
        doc["peak_pnl"] = exit_ctx["peak_pnl"]
    return doc


# ═════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═════════════════════════════════════════════════════════════════

@router.get("/positions", response_model=PositionListResponse)
async def get_positions(user: str = Depends(verify_auth)):
    """
    Open positions with live PnL.
    Merges broker positions with local trade tracking data.
    """
    from db.trade_repo import get_open_trades

    try:
        open_trades = get_open_trades()
        positions = []
        for t in open_trades:
            t = _serialize_trade(t)
            positions.append(
                PositionOut(
                    deal_id=t.get("deal_id", ""),
                    direction=t.get("direction", ""),
                    size=t.get("size", 0.0),
                    entry_price=t.get("entry_price", 0.0),
                    current_price=t.get("current_price", 0.0),
                    pnl=t.get("pnl_eur", 0.0) or 0.0,
                    sl_price=t.get("sl_price"),
                    tp_price=t.get("tp_price"),
                    created_at=t.get("open_timestamp"),
                )
            )
        return PositionListResponse(positions=positions, count=len(positions))

    except Exception as e:
        logger.exception("Error fetching positions")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history", response_model=TradeHistoryResponse)
async def get_trade_history(
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    direction: Optional[str] = Query(None),
    user: str = Depends(verify_auth),
):
    """
    Trade history — paginated and filterable.
    Params: limit, skip, status (WIN|LOSS|OPEN), direction (BUY|SELL).
    """
    from db.trade_repo import get_trade_history, count_trades

    try:
        trades_raw = get_trade_history(
            limit=limit,
            skip=skip,
            status=status_filter,
            direction=direction,
        )
        trades = [_serialize_trade(t) for t in trades_raw]
        total = count_trades(status=status_filter)

        return TradeHistoryResponse(
            trades=[TradeOut(**{k: t.get(k) for k in TradeOut.model_fields}) for t in trades],
            total=total,
            skip=skip,
            limit=limit,
        )

    except Exception as e:
        logger.exception("Error fetching trade history")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/start", response_model=EngineActionResponse)
async def start_engine(request: Request, user: str = Depends(verify_auth)):
    """Start the trading engine."""
    from db.config_repo import update_runtime_fields

    try:
        params = update_runtime_fields({"enabled": True}, source=f"api:{user}")
        if params is None:
            raise HTTPException(status_code=400, detail="Failed to update config")

        # Actually start the engine thread
        engine = request.app.state.engine
        engine.start()

        await ws_manager.broadcast("engine_status", {"running": True, "started_by": user})
        logger.info("Engine started by %s", user)

        return EngineActionResponse(
            success=True,
            message="Trading engine started",
            engine_running=engine.state.running,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error starting engine")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop", response_model=EngineActionResponse)
async def stop_engine(request: Request, user: str = Depends(verify_auth)):
    """Stop the trading engine."""
    from db.config_repo import update_runtime_fields

    try:
        params = update_runtime_fields({"enabled": False}, source=f"api:{user}")
        if params is None:
            raise HTTPException(status_code=400, detail="Failed to update config")

        # Actually stop the engine thread
        engine = request.app.state.engine
        engine.stop()

        await ws_manager.broadcast("engine_status", {"running": False, "stopped_by": user})
        logger.info("Engine stopped by %s", user)

        return EngineActionResponse(
            success=True,
            message="Trading engine stopped",
            engine_running=engine.state.running,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error stopping engine")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/close/{deal_id}", response_model=ClosePositionResponse)
async def close_position(deal_id: str, user: str = Depends(verify_auth)):
    """
    Manually close a position by deal_id.
    Sends a close order to the broker and logs the result.
    """
    from db.trade_repo import get_open_trades

    try:
        # Verify position exists locally
        open_trades = get_open_trades()
        trade = next((t for t in open_trades if t.get("deal_id") == deal_id), None)

        if trade is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No open position with deal_id={deal_id}",
            )

        # NOTE: The actual broker close call is delegated to core.engine
        # which handles IG API interaction, PnL calculation, and trade logging.
        # This endpoint signals the engine to close the position.
        await ws_manager.broadcast(
            "trade_event",
            {"action": "manual_close_requested", "deal_id": deal_id, "by": user},
        )

        logger.info("Manual close requested for deal_id=%s by %s", deal_id, user)

        return ClosePositionResponse(
            success=True,
            message=f"Close request sent for {deal_id}",
            deal_id=deal_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error closing position %s", deal_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/manual-order", response_model=ManualOrderResponse)
async def manual_order(request: Request, body: ManualOrderRequest, user: str = Depends(verify_auth)):
    """
    Open a manual position directly via IG broker.
    Bypasses AI signals — the user is fully in control.
    """
    from db.config_repo import load_trading_params
    from db.trade_repo import log_trade_open

    try:
        ig_client = request.app.state.ig_client
        params = load_trading_params()

        # Use config default size if not specified
        size = body.size if body.size > 0 else params.position_size_eth

        # Use config default SL/TP if not specified
        sl_pts = body.sl_pts if body.sl_pts is not None else params.stop_distance_pts
        tp_pts = body.tp_pts if body.tp_pts is not None else params.limit_distance_pts

        # Ensure IG is connected
        if not ig_client.ensure_connected():
            raise HTTPException(status_code=503, detail="IG broker not connected")

        # Execute the order
        result = ig_client.open_position(
            direction=body.direction,
            size=size,
            sl_pts=sl_pts if sl_pts and sl_pts > 0 else None,
            tp_pts=tp_pts if tp_pts and tp_pts > 0 else None,
        )

        if not result.success:
            return ManualOrderResponse(
                success=False,
                message=f"Order rejected: {result.error or 'Unknown error'}",
                direction=body.direction,
                size=size,
            )

        # Log trade in MongoDB
        try:
            log_trade_open(
                trade_id=f"MANUAL-{result.deal_id}",
                deal_id=result.deal_id,
                direction=body.direction,
                size=size,
                entry_price=0.0,  # Will be updated by position manager
                sl_pts=sl_pts if sl_pts and sl_pts > 0 else None,
                tp_pts=tp_pts if tp_pts and tp_pts > 0 else None,
                ai_entry={"source": "manual", "user": user},
            )
        except Exception as e:
            logger.warning("Failed to log manual trade: %s", e)

        # Broadcast trade event
        await ws_manager.broadcast(
            "trade_event",
            {
                "action": "manual_open",
                "deal_id": result.deal_id,
                "direction": body.direction,
                "size": size,
                "by": user,
            },
        )

        logger.info(
            "Manual %s order opened: deal_id=%s, size=%.2f ETH by %s",
            body.direction, result.deal_id, size, user,
        )

        return ManualOrderResponse(
            success=True,
            message=f"Position {body.direction} opened successfully",
            deal_id=result.deal_id,
            direction=body.direction,
            size=size,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error opening manual order")
        raise HTTPException(status_code=500, detail=str(e))
