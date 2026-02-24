'use client';

import { useTradingStore } from '@/stores/tradingStore';

export function AIThinking() {
  const aiThinking = useTradingStore((s) => s.aiThinking);
  const signal = useTradingStore((s) => s.latestSignal);

  const thinking = aiThinking || signal?.thinking;

  if (!thinking) {
    return null;
  }

  return (
    <div className="bg-bg-surface rounded-lg border border-border p-3">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-2 h-2 rounded-full bg-accent-purple live-dot" />
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider">
          Claude AI
        </h3>
      </div>
      <div className="bg-bg rounded-lg p-2.5 max-h-32 overflow-y-auto">
        <p className="text-xs text-text-muted leading-relaxed whitespace-pre-wrap">
          {thinking}
        </p>
      </div>
    </div>
  );
}
