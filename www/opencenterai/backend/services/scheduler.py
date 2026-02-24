"""
OpenCenterAI — Analysis Scheduler
====================================
Gère la fréquence des analyses Claude AI.
Mode AUTO : adapte la fréquence selon qu'on a une position ou non.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from config.settings import TradingParams

logger = logging.getLogger(__name__)


class AnalysisScheduler:
    """Planifie quand lancer la prochaine analyse Claude."""

    def __init__(self, params: TradingParams):
        self.params = params
        self._last_analysis: Optional[datetime] = None
        self._force_next: bool = False

    def should_analyze(self, has_position: bool) -> bool:
        """Détermine si on doit lancer une analyse maintenant."""

        # Force next analysis (triggered by trade events)
        if self._force_next:
            self._force_next = False
            return True

        # No previous analysis → analyze immediately
        if self._last_analysis is None:
            return True

        # Frequency mode OFF → never
        if self.params.frequency_mode == "OFF":
            return False

        # Frequency mode MANUAL → only when forced
        if self.params.frequency_mode == "MANUAL":
            return False

        # AUTO mode: adapt interval
        elapsed = (datetime.now(timezone.utc) - self._last_analysis).total_seconds()

        if self.params.scalping_mode_enabled:
            # Scalping: very frequent
            interval = (
                self.params.scalping_interval_with_position_sec
                if has_position
                else self.params.scalping_interval_without_position_sec
            )
        else:
            # Normal: idle vs active
            interval = (
                self.params.analysis_interval_active_min * 60
                if has_position
                else self.params.analysis_interval_idle_min * 60
            )

        return elapsed >= interval

    def mark_analysis_done(self):
        """Marque qu'une analyse vient d'être effectuée."""
        self._last_analysis = datetime.now(timezone.utc)

    def force_next_analysis(self):
        """Force la prochaine analyse (après trade event, par ex.)."""
        self._force_next = True

    def get_next_analysis_in_sec(self, has_position: bool) -> float:
        """Retourne le temps restant avant la prochaine analyse."""
        if self._last_analysis is None:
            return 0.0

        elapsed = (datetime.now(timezone.utc) - self._last_analysis).total_seconds()

        if self.params.scalping_mode_enabled:
            interval = (
                self.params.scalping_interval_with_position_sec
                if has_position
                else self.params.scalping_interval_without_position_sec
            )
        else:
            interval = (
                self.params.analysis_interval_active_min * 60
                if has_position
                else self.params.analysis_interval_idle_min * 60
            )

        remaining = interval - elapsed
        return max(0.0, remaining)
