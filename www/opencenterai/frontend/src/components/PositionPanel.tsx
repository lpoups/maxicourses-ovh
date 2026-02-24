'use client';

import { useTradingStore } from '@/stores/tradingStore';
import { tradingApi } from '@/lib/api';

export function PositionPanel() {
  const positions = useTradingStore((s) => s.positions);

  if (positions.length === 0) {
    return (
      <div className="bg-bg-surface rounded-lg border border-border p-3">
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
          Positions
        </h3>
        <p className="text-xs text-text-faint text-center py-4">
          Aucune position ouverte
        </p>
      </div>
    );
  }

  return (
    <div className="bg-bg-surface rounded-lg border border-border p-3">
      <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
        Positions ({positions.length})
      </h3>
      <div className="space-y-2">
        {positions.map((pos) => {
          const isLong = pos.direction === 'BUY';
          const pnlColor = pos.pnl_eur >= 0 ? 'text-accent-green' : 'text-accent-red';

          return (
            <div
              key={pos.deal_id}
              className="bg-bg rounded-lg border border-border p-3 space-y-2"
            >
              {/* Header: Direction + Size + PnL */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-bold ${
                      isLong
                        ? 'bg-accent-green/15 text-accent-green'
                        : 'bg-accent-red/15 text-accent-red'
                    }`}
                  >
                    {isLong ? 'LONG' : 'SHORT'}
                  </span>
                  <span className="text-xs font-mono">{pos.size} ETH</span>
                </div>
                <span className={`font-mono font-bold text-sm ${pnlColor}`}>
                  {pos.pnl_eur >= 0 ? '+' : ''}
                  {pos.pnl_eur.toFixed(2)}
                </span>
              </div>

              {/* Details */}
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div>
                  <span className="text-text-faint">Entry</span>
                  <p className="font-mono">{pos.entry_price.toFixed(2)}</p>
                </div>
                <div>
                  <span className="text-text-faint">Current</span>
                  <p className="font-mono">{pos.current_price.toFixed(2)}</p>
                </div>
                <div>
                  <span className="text-text-faint">PnL%</span>
                  <p className={`font-mono ${pnlColor}`}>
                    {pos.pnl_pct >= 0 ? '+' : ''}{pos.pnl_pct.toFixed(2)}%
                  </p>
                </div>
              </div>

              {/* SL/TP + Trailing */}
              <div className="flex items-center justify-between text-xs">
                <div className="flex gap-3">
                  {pos.sl_price && (
                    <span className="text-accent-red">
                      SL: {pos.sl_price.toFixed(2)}
                    </span>
                  )}
                  {pos.tp_price && (
                    <span className="text-accent-green">
                      TP: {pos.tp_price.toFixed(2)}
                    </span>
                  )}
                </div>
                {pos.trailing_active && (
                  <span className="text-accent-yellow text-2xs">TRAILING</span>
                )}
              </div>

              {/* Close button */}
              <button
                onClick={() => tradingApi.closePosition(pos.deal_id)}
                className="w-full py-1 rounded text-xs font-medium text-accent-red border border-accent-red/30
                           hover:bg-accent-red/10 transition-colors"
              >
                Fermer manuellement
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
