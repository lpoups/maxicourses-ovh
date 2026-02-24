'use client';

import { useTradingStore } from '@/stores/tradingStore';

export function SignalPanel() {
  const signal = useTradingStore((s) => s.latestSignal);

  if (!signal) {
    return (
      <div className="bg-bg-surface rounded-lg border border-border p-3">
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
          Signal IA
        </h3>
        <p className="text-xs text-text-faint text-center py-4">
          En attente d&apos;analyse...
        </p>
      </div>
    );
  }

  const actionColor = {
    LONG: 'text-accent-green bg-accent-green/15',
    SHORT: 'text-accent-red bg-accent-red/15',
    WAIT: 'text-accent-yellow bg-accent-yellow/15',
    HOLD: 'text-accent-blue bg-accent-blue/15',
    EXIT_LONG: 'text-accent-orange bg-accent-orange/15',
    EXIT_SHORT: 'text-accent-orange bg-accent-orange/15',
    QUITTER: 'text-accent-red bg-accent-red/15',
  }[signal.action] || 'text-text-muted bg-bg-surface2';

  const confColor =
    signal.confidence >= 80
      ? 'text-accent-green'
      : signal.confidence >= 65
        ? 'text-accent-yellow'
        : 'text-accent-red';

  return (
    <div className="bg-bg-surface rounded-lg border border-border p-3">
      <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
        Signal IA
      </h3>

      {/* Action + Confidence */}
      <div className="flex items-center justify-between mb-3">
        <span className={`px-3 py-1 rounded-lg font-bold text-sm ${actionColor}`}>
          {signal.action}
        </span>
        <div className="text-right">
          <span className={`text-2xl font-bold font-mono ${confColor}`}>
            {signal.confidence}
          </span>
          <span className="text-xs text-text-muted ml-1">%</span>
        </div>
      </div>

      {/* Regime + Direction */}
      <div className="grid grid-cols-2 gap-2 mb-3 text-xs">
        <div className="bg-bg rounded p-2">
          <span className="text-text-faint">Regime</span>
          <p className="font-medium text-accent-blue">{signal.regime || '—'}</p>
        </div>
        <div className="bg-bg rounded p-2">
          <span className="text-text-faint">Direction</span>
          <p className="font-medium">{signal.direction || '—'}</p>
        </div>
      </div>

      {/* Score bars */}
      <div className="space-y-1.5 mb-3">
        <div className="flex items-center gap-2 text-xs">
          <span className="w-12 text-text-faint">Long</span>
          <div className="flex-1 h-2 bg-bg rounded-full overflow-hidden">
            <div
              className="h-full bg-accent-green rounded-full transition-all"
              style={{ width: `${Math.min(100, (signal.score_long || 0) * 10)}%` }}
            />
          </div>
          <span className="w-6 text-right font-mono">{signal.score_long || 0}</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="w-12 text-text-faint">Short</span>
          <div className="flex-1 h-2 bg-bg rounded-full overflow-hidden">
            <div
              className="h-full bg-accent-red rounded-full transition-all"
              style={{ width: `${Math.min(100, (signal.score_short || 0) * 10)}%` }}
            />
          </div>
          <span className="w-6 text-right font-mono">{signal.score_short || 0}</span>
        </div>
      </div>

      {/* Horizons */}
      {signal.horizons && (
        <div className="grid grid-cols-4 gap-1 mb-3">
          {(['15m', '30m', '1h', '4h'] as const).map((tf) => (
            <div key={tf} className="bg-bg rounded p-1.5 text-center">
              <span className="text-2xs text-text-faint">{tf}</span>
              <p className="text-xs font-medium mt-0.5">
                {signal.horizons[tf] || '—'}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Reason */}
      {signal.reason && (
        <p className="text-xs text-text-muted leading-relaxed border-t border-border pt-2">
          {signal.reason}
        </p>
      )}

      {/* Wait reason */}
      {signal.wait_reason_code && (
        <p className="text-xs text-accent-yellow mt-1">
          Wait: {signal.wait_reason_code}
        </p>
      )}
    </div>
  );
}
