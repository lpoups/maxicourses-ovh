// ═══════════════════════════════════════════════════════════════
// OpenCenterAI — API Hook for initial data loading
// ═══════════════════════════════════════════════════════════════

'use client';

import { useEffect } from 'react';
import { useTradingStore } from '@/stores/tradingStore';
import { tradingApi, statusApi, analyticsApi, configApi, marketApi } from '@/lib/api';
import type { Trade, EngineStatus, TradingConfig, PerformanceSummary, Ticker, AIDecision, Position } from '@/lib/types';

export function useInitialData() {
  const {
    setRecentTrades,
    updateEngineStatus,
    setConfig,
    setPerformance,
    updateTicker,
    updatePositions,
    updateSignal,
    setAiThinking,
  } = useTradingStore();

  useEffect(() => {
    loadInitialData();
    // Refresh every 30s as fallback (WebSocket is primary)
    const interval = setInterval(loadInitialData, 30000);
    return () => clearInterval(interval);
  }, []);

  async function loadInitialData() {
    const [statusRes, tradesRes, configRes, perfRes, tickerRes, posRes, aiRes] = await Promise.allSettled([
      statusApi.getStatus(),
      tradingApi.getHistory(200),
      configApi.getConfig(),
      analyticsApi.getSummary(7),
      marketApi.getTicker(),
      tradingApi.getPositions(),
      analyticsApi.getAiAnalyses(1),
    ]);

    if (statusRes.status === 'fulfilled' && statusRes.value.success) {
      updateEngineStatus(statusRes.value.data as EngineStatus);
    }

    if (tradesRes.status === 'fulfilled' && tradesRes.value.success) {
      const data = tradesRes.value.data as any;
      setRecentTrades((data.trades || data) as Trade[]);
    }

    if (configRes.status === 'fulfilled' && configRes.value.success) {
      const configData = configRes.value.data as any;
      setConfig((configData?.params || configData) as TradingConfig);
    }

    if (perfRes.status === 'fulfilled' && perfRes.value.success) {
      setPerformance(perfRes.value.data as PerformanceSummary);
    }

    if (tickerRes.status === 'fulfilled' && tickerRes.value.success) {
      updateTicker(tickerRes.value.data as Ticker);
    }

    // Load positions from REST (WebSocket also pushes them)
    if (posRes.status === 'fulfilled' && posRes.value.success) {
      const posData = posRes.value.data as any;
      updatePositions((posData.positions || posData || []) as Position[]);
    }

    // Load latest AI signal from REST -> populates SignalPanel + AIThinking
    if (aiRes.status === 'fulfilled' && aiRes.value.success) {
      const aiData = aiRes.value.data as any;
      const analyses = aiData.analyses || [];
      if (analyses.length > 0) {
        const latest = analyses[0];
        updateSignal({
          action: latest.action || 'WAIT',
          confidence: latest.confidence || 0,
          direction: latest.direction || '',
          regime: latest.regime || '',
          entry_mode: '',
          thinking: latest.thinking || '',
          reason: latest.reason || '',
          score_long: latest.score_long || 0,
          score_short: latest.score_short || 0,
          horizons: latest.horizons || {},
          wait_reason_code: latest.wait_reason_code || null,
          timestamp: latest.timestamp || '',
        } as AIDecision);
        if (latest.thinking) {
          setAiThinking(latest.thinking);
        }
      }
    }
  }
}
