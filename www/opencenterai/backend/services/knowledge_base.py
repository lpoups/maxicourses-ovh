"""
OpenCenterAI — Knowledge Base Service
========================================
Moteur d'apprentissage continu.
Analyse les trades passés pour extraire des patterns et insights.
Persistance via MongoDB (zéro JSON).
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from db import trade_repo, knowledge_repo
from config.settings import TradingParams

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """Service d'apprentissage à partir des trades passés."""

    def __init__(self, params: TradingParams):
        self.params = params
        self._lock = threading.Lock()
        self._last_recompute: Optional[datetime] = None
        self._recompute_interval = params.kb_recompute_interval_sec

    def maybe_recompute(self) -> bool:
        """Recompute si le délai est écoulé."""
        if self._last_recompute:
            elapsed = (datetime.now(timezone.utc) - self._last_recompute).total_seconds()
            if elapsed < self._recompute_interval:
                return False

        return self.recompute_aggregates()

    def recompute_aggregates(self) -> bool:
        """Recalcule tous les agrégats depuis les trades MongoDB."""
        with self._lock:
            try:
                trades = trade_repo.get_trade_history(limit=500, status=None)
                closed = [t for t in trades if t.get("status") in ("WIN", "LOSS")]

                if not closed:
                    return False

                aggregates = self._compute_aggregates(closed)
                knowledge_repo.save_aggregates(aggregates)
                self._last_recompute = datetime.now(timezone.utc)

                logger.info(
                    "Knowledge base recomputed: %d trades, WR=%.1f%%",
                    len(closed),
                    aggregates.get("overall_win_rate", 0),
                )
                return True

            except Exception as e:
                logger.error("Erreur recompute KB: %s", e)
                return False

    def record_trade(self, trade: Dict, peak_pnl: float = 0.0):
        """Enregistre un nouveau trade et déclenche un recompute si nécessaire."""
        # Le trade est déjà enregistré dans MongoDB via trade_repo
        # On déclenche juste un recompute
        self.maybe_recompute()

    def get_insights_for_prompt(self) -> str:
        """Génère un résumé textuel pour le prompt Claude."""
        aggregates = knowledge_repo.get_aggregates()
        if not aggregates:
            return "Pas encore assez de données pour l'apprentissage."

        lines = []
        total = aggregates.get("total_trades", 0)
        wr = aggregates.get("overall_win_rate", 0)
        pnl = aggregates.get("overall_pnl", 0)

        lines.append(f"[KB] {total} trades, WR={wr:.1f}%, PnL={pnl:+.2f} EUR")

        # Best/worst hours
        best = aggregates.get("best_hours", [])
        worst = aggregates.get("worst_hours", [])
        avoid = aggregates.get("avoid_hours", [])

        if best:
            lines.append(f"  Best hours: {best}")
        if worst:
            lines.append(f"  Worst hours: {worst}")
        if avoid:
            lines.append(f"  AVOID hours: {avoid}")

        # By direction
        by_dir = aggregates.get("by_direction", {})
        for direction, stats in by_dir.items():
            dir_trades = stats.get("trades", 0)
            dir_wr = stats.get("win_rate", 0)
            if dir_trades >= 3:
                lines.append(f"  {direction}: {dir_trades} trades, WR={dir_wr:.1f}%")

        # By regime
        by_regime = aggregates.get("by_regime", {})
        for regime, stats in by_regime.items():
            reg_trades = stats.get("trades", 0)
            reg_wr = stats.get("win_rate", 0)
            if reg_trades >= 3:
                lines.append(f"  {regime}: {reg_trades} trades, WR={reg_wr:.1f}%")

        return "\n".join(lines)

    def _compute_aggregates(self, trades: List[Dict]) -> Dict:
        """Calcule les agrégats depuis une liste de trades."""
        total = len(trades)
        wins = sum(1 for t in trades if t.get("status") == "WIN")
        total_pnl = sum(t.get("pnl_eur", 0) or 0 for t in trades)

        # Par heure
        by_hour: Dict[str, Dict] = {}
        for t in trades:
            ts = t.get("open_timestamp")
            if ts:
                hour = str(ts.hour if hasattr(ts, "hour") else 0)
                if hour not in by_hour:
                    by_hour[hour] = {"trades": 0, "wins": 0, "pnl": 0.0}
                by_hour[hour]["trades"] += 1
                if t.get("status") == "WIN":
                    by_hour[hour]["wins"] += 1
                by_hour[hour]["pnl"] += t.get("pnl_eur", 0) or 0

        # Win rate par heure
        for h, stats in by_hour.items():
            stats["win_rate"] = (
                round(stats["wins"] / stats["trades"] * 100, 1)
                if stats["trades"] > 0
                else 0
            )

        # Par direction
        by_direction: Dict[str, Dict] = {}
        for t in trades:
            d = t.get("direction", "UNKNOWN")
            if d not in by_direction:
                by_direction[d] = {"trades": 0, "wins": 0, "pnl": 0.0}
            by_direction[d]["trades"] += 1
            if t.get("status") == "WIN":
                by_direction[d]["wins"] += 1
            by_direction[d]["pnl"] += t.get("pnl_eur", 0) or 0

        for d, stats in by_direction.items():
            stats["win_rate"] = (
                round(stats["wins"] / stats["trades"] * 100, 1)
                if stats["trades"] > 0
                else 0
            )

        # Par régime
        by_regime: Dict[str, Dict] = {}
        for t in trades:
            regime = (t.get("ai_entry") or {}).get("regime", "UNKNOWN")
            if regime not in by_regime:
                by_regime[regime] = {"trades": 0, "wins": 0, "pnl": 0.0}
            by_regime[regime]["trades"] += 1
            if t.get("status") == "WIN":
                by_regime[regime]["wins"] += 1
            by_regime[regime]["pnl"] += t.get("pnl_eur", 0) or 0

        for r, stats in by_regime.items():
            stats["win_rate"] = (
                round(stats["wins"] / stats["trades"] * 100, 1)
                if stats["trades"] > 0
                else 0
            )

        # Par exit reason
        by_exit_reason: Dict[str, Dict] = {}
        for t in trades:
            reason = t.get("exit_reason", "UNKNOWN")
            if reason not in by_exit_reason:
                by_exit_reason[reason] = {"trades": 0, "wins": 0, "pnl": 0.0}
            by_exit_reason[reason]["trades"] += 1
            if t.get("status") == "WIN":
                by_exit_reason[reason]["wins"] += 1
            by_exit_reason[reason]["pnl"] += t.get("pnl_eur", 0) or 0

        # Best/worst/avoid hours
        min_trades = self.params.kb_min_trades_per_bucket
        best_hours = sorted(
            [int(h) for h, s in by_hour.items() if s["trades"] >= min_trades and s["win_rate"] > 60],
            key=lambda h: by_hour[str(h)]["win_rate"],
            reverse=True,
        )[:5]

        worst_hours = sorted(
            [int(h) for h, s in by_hour.items() if s["trades"] >= min_trades and s["win_rate"] < 35],
            key=lambda h: by_hour[str(h)]["win_rate"],
        )[:5]

        avoid_hours = [
            int(h) for h, s in by_hour.items()
            if s["trades"] >= self.params.kb_avoid_hour_min_trades
            and s["win_rate"] <= self.params.kb_avoid_hour_max_wr
        ]

        return {
            "total_trades": total,
            "overall_win_rate": round(wins / total * 100, 1) if total > 0 else 0,
            "overall_pnl": round(total_pnl, 2),
            "by_hour": by_hour,
            "by_direction": by_direction,
            "by_regime": by_regime,
            "by_exit_reason": by_exit_reason,
            "best_hours": best_hours,
            "worst_hours": worst_hours,
            "avoid_hours": avoid_hours,
        }
