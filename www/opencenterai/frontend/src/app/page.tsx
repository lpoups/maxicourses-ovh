'use client';

import { useState, useEffect } from 'react';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useInitialData } from '@/hooks/useApi';
import { StatusBar } from '@/components/StatusBar';
import { ControlBar } from '@/components/ControlBar';
import { Chart } from '@/components/Chart';
import { PositionPanel } from '@/components/PositionPanel';
import { SignalPanel } from '@/components/SignalPanel';
import { TradeHistory } from '@/components/TradeHistory';
import { PerformanceCards } from '@/components/PerformanceCards';
import { AIThinking } from '@/components/AIThinking';
import { AIAnalysisPanel } from '@/components/AIAnalysisPanel';
import { OrderBookPanel } from '@/components/OrderBookPanel';
import { ManualTradePanel } from '@/components/ManualTradePanel';

export default function DashboardPage() {
  // Prevent SSR hydration mismatches (Math.random, Date, etc.)
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  // Initialize WebSocket and load initial data
  useWebSocket();
  useInitialData();

  if (!mounted) {
    return (
      <div className="flex items-center justify-center h-screen bg-bg text-text">
        <div className="text-center">
          <div className="text-2xl font-bold text-accent-blue mb-2">OpenCenterAI</div>
          <div className="text-sm text-text-muted">Chargement du dashboard...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {/* Top: Status bar */}
      <StatusBar />

      {/* Controls */}
      <ControlBar />

      {/* Main content */}
      <div className="flex-1 grid grid-cols-12 gap-2 p-2 overflow-hidden">
        {/* Left: Chart + Trade History (8 cols) */}
        <div className="col-span-8 flex flex-col gap-2">
          <div className="flex-1 bg-bg-surface rounded-lg border border-border overflow-hidden">
            <Chart />
          </div>
          <div className="h-56">
            <TradeHistory />
          </div>
        </div>

        {/* Right: Panels (4 cols) */}
        <div className="col-span-4 flex flex-col gap-2 overflow-y-auto">
          <ManualTradePanel />
          <PositionPanel />
          <SignalPanel />
          <OrderBookPanel />
          <AIThinking />
          <AIAnalysisPanel />
          <PerformanceCards />
        </div>
      </div>
    </div>
  );
}
