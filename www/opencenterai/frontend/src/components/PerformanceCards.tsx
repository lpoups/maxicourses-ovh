'use client';

import { useTradingStore } from '@/stores/tradingStore';

export function PerformanceCards() {
  const perf = useTradingStore((s) => s.performance);

  if (!perf) {
    return (
      <div className="bg-bg-surface rounded-lg border border-border p-3">
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
          Performance
        </h3>
        <p className="text-xs text-text-faint text-center py-2">Chargement...</p>
      </div>
    );
  }

  const cards = [
    {
      label: 'Win Rate',
      value: `${perf.win_rate_pct.toFixed(1)}%`,
      color: perf.win_rate_pct >= 50 ? 'text-accent-green' : 'text-accent-red',
    },
    {
      label: 'PnL Total',
      value: `${perf.total_pnl_eur >= 0 ? '+' : ''}${perf.total_pnl_eur.toFixed(2)}`,
      color: perf.total_pnl_eur >= 0 ? 'text-accent-green' : 'text-accent-red',
    },
    {
      label: 'Profit Factor',
      value: perf.profit_factor.toFixed(2),
      color: perf.profit_factor >= 1.5 ? 'text-accent-green' : perf.profit_factor >= 1 ? 'text-accent-yellow' : 'text-accent-red',
    },
    {
      label: 'Trades',
      value: `${perf.total_trades}`,
      color: 'text-accent-blue',
    },
    {
      label: 'Best',
      value: `+${perf.best_trade_eur.toFixed(2)}`,
      color: 'text-accent-green',
    },
    {
      label: 'Worst',
      value: `${perf.worst_trade_eur.toFixed(2)}`,
      color: 'text-accent-red',
    },
  ];

  return (
    <div className="bg-bg-surface rounded-lg border border-border p-3">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider">
          Performance
        </h3>
        <span className="text-2xs text-text-faint">{perf.period_days}j</span>
      </div>

      <div className="grid grid-cols-3 gap-2">
        {cards.map((card) => (
          <div key={card.label} className="bg-bg rounded-lg p-2 text-center">
            <p className={`text-sm font-bold font-mono ${card.color}`}>
              {card.value}
            </p>
            <p className="text-2xs text-text-faint mt-0.5">{card.label}</p>
          </div>
        ))}
      </div>

      {/* W/L bar */}
      {perf.total_trades > 0 && (
        <div className="mt-3">
          <div className="flex rounded-full overflow-hidden h-1.5">
            <div
              className="bg-accent-green"
              style={{ width: `${perf.win_rate_pct}%` }}
            />
            <div
              className="bg-accent-red"
              style={{ width: `${100 - perf.win_rate_pct}%` }}
            />
          </div>
          <div className="flex justify-between mt-1 text-2xs text-text-faint">
            <span>{perf.wins}W</span>
            <span>{perf.losses}L</span>
          </div>
        </div>
      )}
    </div>
  );
}
