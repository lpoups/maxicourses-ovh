"""
OpenCenterAI — Analytics Endpoints (FastAPI)
==============================================
Performance summaries, daily breakdown, knowledge base,
exit-reason PnL, AI analysis statistics.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.middleware import verify_auth

logger = logging.getLogger(__name__)
router = APIRouter()


# ═════════════════════════════════════════════════════════════════
# PYDANTIC RESPONSE MODELS
# ═════════════════════════════════════════════════════════════════
class PerformanceSummary(BaseModel):
    period_days: int
    total_trades: int
    wins: int = 0
    losses: int = 0
    win_rate_pct: float = 0.0
    total_pnl_eur: float = 0.0
    gross_profit_eur: float = 0.0
    gross_loss_eur: float = 0.0
    profit_factor: float = 0.0
    best_trade_eur: float = 0.0
    worst_trade_eur: float = 0.0
    avg_duration_min: float = 0.0


class DailyBreakdown(BaseModel):
    date: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate_pct: float = 0.0
    total_pnl_eur: float = 0.0
    gross_profit_eur: float = 0.0
    gross_loss_eur: float = 0.0
    profit_factor: float = 0.0
    max_win_eur: float = 0.0
    max_loss_eur: float = 0.0
    avg_pnl_eur: float = 0.0
    avg_duration_sec: float = 0.0


class KnowledgeInsight(BaseModel):
    type: Optional[str] = None
    content: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeResponse(BaseModel):
    aggregates: Optional[Dict[str, Any]] = None
    insights: List[KnowledgeInsight]
    patterns_count: int = 0
    best_hours: List[int] = Field(default_factory=list)
    avoid_hours: List[int] = Field(default_factory=list)


class ExitReasonStat(BaseModel):
    exit_reason: Optional[str] = None
    count: int = 0
    total_pnl_eur: float = 0.0
    win_rate_pct: float = 0.0


class ExitReasonsResponse(BaseModel):
    period_days: int
    reasons: List[ExitReasonStat]


class AIActionStat(BaseModel):
    count: int = 0
    avg_confidence: float = 0.0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    avg_latency_ms: float = 0.0


class AIStatsResponse(BaseModel):
    period_hours: int
    total_analyses: int = 0
    by_action: Dict[str, AIActionStat]


# ═════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═════════════════════════════════════════════════════════════════

@router.get("/summary", response_model=PerformanceSummary)
async def get_performance_summary(
    days: int = Query(7, ge=1, le=365, description="Lookback period in days"),
    user: str = Depends(verify_auth),
):
    """Performance summary over N days: win rate, PnL, profit factor, etc."""
    from db.perf_repo import get_performance_summary as repo_summary

    try:
        data = repo_summary(days=days)
        return PerformanceSummary(**data)

    except Exception as e:
        logger.exception("Error computing performance summary")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/daily", response_model=DailyBreakdown)
async def get_daily_breakdown(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    user: str = Depends(verify_auth),
):
    """Detailed performance breakdown for a single day."""
    from db.perf_repo import compute_daily_perf

    # Basic date format validation
    try:
        from datetime import datetime as dt
        dt.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    try:
        data = compute_daily_perf(date=date)
        return DailyBreakdown(**data)

    except Exception as e:
        logger.exception("Error computing daily breakdown for %s", date)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge", response_model=KnowledgeResponse)
async def get_knowledge(user: str = Depends(verify_auth)):
    """
    Knowledge base insights: aggregated patterns, best/worst hours,
    regime stats, top lessons learned.
    """
    from db.knowledge_repo import (
        get_aggregates,
        get_insights,
        get_patterns,
        get_best_hours,
        get_avoid_hours,
    )

    try:
        aggregates = get_aggregates()
        raw_insights = get_insights()
        patterns = get_patterns()
        best = get_best_hours()
        avoid = get_avoid_hours()

        insights = [
            KnowledgeInsight(type=i.get("type"), content=i)
            for i in raw_insights
        ]

        return KnowledgeResponse(
            aggregates=aggregates,
            insights=insights,
            patterns_count=len(patterns),
            best_hours=best,
            avoid_hours=avoid,
        )

    except Exception as e:
        logger.exception("Error fetching knowledge base")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/exit-reasons", response_model=ExitReasonsResponse)
async def get_exit_reasons(
    days: int = Query(30, ge=1, le=365, description="Lookback period in days"),
    user: str = Depends(verify_auth),
):
    """PnL breakdown by exit reason over N days."""
    from db.perf_repo import get_pnl_by_exit_reason

    try:
        reasons_data = get_pnl_by_exit_reason(days=days)
        reasons = [ExitReasonStat(**r) for r in reasons_data]

        return ExitReasonsResponse(period_days=days, reasons=reasons)

    except Exception as e:
        logger.exception("Error fetching exit reasons")
        raise HTTPException(status_code=500, detail=str(e))


class AIAnalysisEntry(BaseModel):
    timestamp: Optional[str] = None
    action: str = "WAIT"
    confidence: int = 0
    direction: Optional[str] = None
    regime: Optional[str] = None
    thinking: Optional[str] = None
    reason: Optional[str] = None
    score_long: Optional[int] = None
    score_short: Optional[int] = None
    horizons: Optional[Dict[str, Any]] = None
    wait_reason_code: Optional[str] = None
    model_used: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0


class AIAnalysesResponse(BaseModel):
    analyses: List[AIAnalysisEntry]
    count: int
    total_in_db: int = 0


@router.get("/ai-analyses", response_model=AIAnalysesResponse)
async def get_ai_analyses(
    limit: int = Query(20, ge=1, le=100, description="Number of recent analyses"),
    user: str = Depends(verify_auth),
):
    """Recent AI analyses with full details: thinking, reason, scores, model, tokens."""
    from db.mongo import get_db
    from db.collections import AI_ANALYSES

    try:
        db = get_db()
        total = db[AI_ANALYSES].count_documents({})
        cursor = db[AI_ANALYSES].find().sort("timestamp", -1).limit(limit)

        analyses = []
        for doc in cursor:
            doc.pop("_id", None)
            ts = doc.get("timestamp") or doc.get("created_at")
            analyses.append(AIAnalysisEntry(
                timestamp=ts.isoformat() if hasattr(ts, "isoformat") else str(ts) if ts else None,
                action=doc.get("action", "WAIT"),
                confidence=doc.get("confidence", 0),
                direction=doc.get("direction"),
                regime=doc.get("regime"),
                thinking=doc.get("thinking"),
                reason=doc.get("reason"),
                score_long=doc.get("score_long"),
                score_short=doc.get("score_short"),
                horizons=doc.get("horizons"),
                wait_reason_code=doc.get("wait_reason_code"),
                model_used=doc.get("model_used"),
                tokens_in=doc.get("tokens_in", 0),
                tokens_out=doc.get("tokens_out", 0),
            ))

        return AIAnalysesResponse(
            analyses=analyses,
            count=len(analyses),
            total_in_db=total,
        )

    except Exception as e:
        logger.exception("Error fetching AI analyses")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-stats", response_model=AIStatsResponse)
async def get_ai_stats(
    hours: int = Query(24, ge=1, le=720, description="Lookback period in hours"),
    user: str = Depends(verify_auth),
):
    """AI analysis statistics: call counts, confidence, tokens, latency."""
    from db.analysis_repo import get_analysis_stats

    try:
        data = get_analysis_stats(hours=hours)

        by_action = {}
        for action, stats in data.get("by_action", {}).items():
            by_action[action] = AIActionStat(
                count=stats.get("count", 0),
                avg_confidence=round(stats.get("avg_confidence", 0), 1),
                total_tokens_in=stats.get("total_tokens_in", 0),
                total_tokens_out=stats.get("total_tokens_out", 0),
                avg_latency_ms=round(stats.get("avg_latency_ms", 0), 1),
            )

        return AIStatsResponse(
            period_hours=hours,
            total_analyses=data.get("total_analyses", 0),
            by_action=by_action,
        )

    except Exception as e:
        logger.exception("Error fetching AI stats")
        raise HTTPException(status_code=500, detail=str(e))
