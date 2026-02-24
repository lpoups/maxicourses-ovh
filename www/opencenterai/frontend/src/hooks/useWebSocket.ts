// ═══════════════════════════════════════════════════════════════
// OpenCenterAI — WebSocket Hook
// ═══════════════════════════════════════════════════════════════

'use client';

import { useEffect, useRef } from 'react';
import { wsClient } from '@/lib/ws';
import { useTradingStore } from '@/stores/tradingStore';

export function useWebSocket() {
  const initialized = useRef(false);
  const {
    updateTicker,
    updatePositions,
    updateSignal,
    setAiThinking,
    updateEngineStatus,
    addTrade,
    setWsConnected,
  } = useTradingStore();

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    // Subscribe to events
    const unsubs = [
      wsClient.on('price_update', (data) => {
        updateTicker(data);
      }),

      wsClient.on('position_update', (data) => {
        updatePositions(data.positions || []);
      }),

      wsClient.on('signal_update', (data) => {
        updateSignal(data);
      }),

      wsClient.on('ai_thinking', (data) => {
        setAiThinking(data.thinking || null);
      }),

      wsClient.on('engine_status', (data) => {
        updateEngineStatus(data);
      }),

      wsClient.on('trade_event', (data) => {
        addTrade(data);
      }),
    ];

    // Connect
    wsClient.connect();

    // Check connection state periodically
    const interval = setInterval(() => {
      setWsConnected(wsClient.isConnected);
    }, 2000);

    return () => {
      unsubs.forEach((unsub) => unsub());
      clearInterval(interval);
      wsClient.disconnect();
    };
  }, []);
}
