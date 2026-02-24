'use client';

import { useTradingStore } from '@/stores/tradingStore';

export function StatusBar() {
  const { engineStatus, wsConnected, ticker } = useTradingStore();

  const isRunning = engineStatus?.running ?? false;
  const igConnected = engineStatus?.ig_connected ?? false;
  const mode = engineStatus?.mode ?? '—';
  const session = engineStatus?.current_session ?? '—';
  const price = ticker?.bid ? ticker.bid.toFixed(2) : '—';
  const changePct = ticker?.change_pct ?? 0;

  return (
    <div className="flex items-center justify-between px-4 py-2 bg-bg-surface border-b border-border text-xs">
      {/* Left: Brand + Status */}
      <div className="flex items-center gap-4">
        <span className="font-bold text-sm text-accent-blue">OpenCenterAI</span>
        <span className="text-text-muted">v2.0</span>

        {/* Engine status */}
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full ${isRunning ? 'bg-accent-green live-dot' : 'bg-accent-red'}`} />
          <span className={isRunning ? 'text-accent-green' : 'text-accent-red'}>
            {isRunning ? 'RUNNING' : 'STOPPED'}
          </span>
        </div>

        {/* IG connection */}
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full ${igConnected ? 'bg-accent-green' : 'bg-accent-yellow'}`} />
          <span className="text-text-muted">
            IG {igConnected ? 'OK' : 'DISC'}
          </span>
        </div>

        {/* WebSocket */}
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-accent-blue' : 'bg-accent-red'}`} />
          <span className="text-text-muted">
            WS {wsConnected ? 'OK' : 'OFF'}
          </span>
        </div>
      </div>

      {/* Center: Price */}
      <div className="flex items-center gap-3">
        <span className="text-text-muted">ETH/USD</span>
        <span className="font-mono font-bold text-sm">${price}</span>
        <span className={`font-mono ${changePct >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>
          {changePct >= 0 ? '+' : ''}{changePct.toFixed(2)}%
        </span>
      </div>

      {/* Right: Mode + Session */}
      <div className="flex items-center gap-4">
        <span className="px-2 py-0.5 rounded bg-bg-surface2 border border-border text-accent-purple font-medium">
          {mode}
        </span>
        <span className="text-text-muted">{session}</span>
        <span className="text-text-faint">
          {new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}
        </span>
      </div>
    </div>
  );
}
