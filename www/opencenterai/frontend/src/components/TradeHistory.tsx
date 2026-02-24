'use client';

import { useMemo } from 'react';
import { useTradingStore } from '@/stores/tradingStore';

function formatDate(ts: string | null | undefined): string {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}`;
  } catch {
    return '—';
  }
}

function formatTime(ts: string | null | undefined): string {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  } catch {
    return '—';
  }
}

export function TradeHistory() {
  const trades = useTradingStore((s) => s.recentTrades);

  // Filter closed trades, sort by open_timestamp descending (most recent first)
  const closedTrades = useMemo(() => {
    return [...trades]
      .filter((t) => t.status !== 'OPEN')
      .sort((a, b) => {
        const ta = a.open_timestamp ? new Date(a.open_timestamp).getTime() : 0;
        const tb = b.open_timestamp ? new Date(b.open_timestamp).getTime() : 0;
        return tb - ta;
      });
  }, [trades]);

  // Total PnL
  const totalPnl = useMemo(() => {
    return closedTrades.reduce((sum, t) => sum + (t.pnl_eur ?? 0), 0);
  }, [closedTrades]);

  const totalWins = closedTrades.filter((t) => t.status === 'WIN').length;
  const totalLosses = closedTrades.filter((t) => t.status === 'LOSS').length;
  const winRate = closedTrades.length > 0 ? (totalWins / closedTrades.length) * 100 : 0;

  return (
    <div className="bg-bg-surface rounded-lg border border-border h-full flex flex-col overflow-hidden">
      {/* Header with summary */}
      <div className="px-3 py-2 border-b border-border flex-shrink-0 flex items-center justify-between">
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider">
          Historique ({closedTrades.length})
        </h3>
        <div className="flex items-center gap-3 text-[10px] font-mono">
          <span className="text-accent-green">{totalWins}W</span>
          <span className="text-text-faint">/</span>
          <span className="text-accent-red">{totalLosses}L</span>
          <span className="text-text-faint">({winRate.toFixed(0)}%)</span>
          <span
            className={`font-bold ${totalPnl >= 0 ? 'text-accent-green' : 'text-accent-red'}`}
          >
            Total: {totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(2)}€
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <table className="w-full text-[10px]">
          <thead className="sticky top-0 bg-bg-surface2 z-10">
            <tr className="text-text-faint">
              <th className="text-left px-2 py-1.5 font-medium">Date</th>
              <th className="text-left px-2 py-1.5 font-medium">Open</th>
              <th className="text-left px-2 py-1.5 font-medium">Close</th>
              <th className="text-center px-2 py-1.5 font-medium">Dir</th>
              <th className="text-right px-2 py-1.5 font-medium">Size</th>
              <th className="text-right px-2 py-1.5 font-medium">Entry</th>
              <th className="text-right px-2 py-1.5 font-medium">Exit</th>
              <th className="text-right px-2 py-1.5 font-medium">PnL</th>
              <th className="text-right px-2 py-1.5 font-medium">Manqué</th>
              <th className="text-left px-2 py-1.5 font-medium">Raison</th>
            </tr>
          </thead>
          <tbody>
            {closedTrades.map((trade) => {
              const isWin = trade.status === 'WIN';
              const isLong = trade.direction === 'BUY';
              const pnl = trade.pnl_eur ?? 0;
              const peakPnl = trade.peak_pnl ?? null;
              // Manqué = peak_pnl - actual_pnl (what we left on the table)
              const missed = peakPnl !== null && peakPnl > pnl ? peakPnl - pnl : null;

              return (
                <tr
                  key={trade.trade_id || trade.deal_id}
                  className="border-b border-border/30 hover:bg-bg-hover transition-colors"
                >
                  <td className="px-2 py-1 text-text-muted font-mono">
                    {formatDate(trade.open_timestamp)}
                  </td>
                  <td className="px-2 py-1 text-text-muted font-mono">
                    {formatTime(trade.open_timestamp)}
                  </td>
                  <td className="px-2 py-1 text-text-muted font-mono">
                    {formatTime(trade.close_timestamp)}
                  </td>
                  <td className="px-2 py-1 text-center">
                    <span
                      className={`px-1 py-0.5 rounded text-[9px] font-bold ${
                        isLong
                          ? 'bg-accent-green/15 text-accent-green'
                          : 'bg-accent-red/15 text-accent-red'
                      }`}
                    >
                      {isLong ? 'L' : 'S'}
                    </span>
                  </td>
                  <td className="px-2 py-1 text-right font-mono">{trade.size}</td>
                  <td className="px-2 py-1 text-right font-mono">
                    {(trade.entry_price ?? 0).toFixed(1)}
                  </td>
                  <td className="px-2 py-1 text-right font-mono">
                    {trade.exit_price != null ? trade.exit_price.toFixed(1) : '—'}
                  </td>
                  <td
                    className={`px-2 py-1 text-right font-mono font-bold ${
                      isWin ? 'text-accent-green' : 'text-accent-red'
                    }`}
                  >
                    {pnl >= 0 ? '+' : ''}
                    {pnl.toFixed(2)}
                  </td>
                  <td className="px-2 py-1 text-right font-mono text-accent-yellow/70">
                    {missed !== null ? `+${missed.toFixed(2)}` : '—'}
                  </td>
                  <td className="px-2 py-1 text-text-faint truncate max-w-[80px]">
                    {trade.exit_reason || '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {closedTrades.length === 0 && (
          <p className="text-xs text-text-faint text-center py-6">
            Aucun trade enregistré
          </p>
        )}
      </div>
    </div>
  );
}
