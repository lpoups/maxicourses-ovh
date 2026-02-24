'use client';

import { useState } from 'react';
import { useTradingStore } from '@/stores/tradingStore';
import { tradingApi } from '@/lib/api';

export function ManualTradePanel() {
  const ticker = useTradingStore((s) => s.ticker);
  const config = useTradingStore((s) => s.config);
  const [loading, setLoading] = useState<'BUY' | 'SELL' | null>(null);
  const [feedback, setFeedback] = useState<{ type: 'ok' | 'err'; msg: string } | null>(null);

  const bid = ticker?.bid ?? 0;
  const offer = ticker?.offer ?? 0;
  const spread = ticker?.spread ?? 0;
  const size = config?.position_size_eth ?? 2;

  async function handleOrder(direction: 'BUY' | 'SELL') {
    setLoading(direction);
    setFeedback(null);
    try {
      const res = await tradingApi.manualOrder(direction, size);
      if (res.success && (res.data as any)?.success) {
        const data = res.data as any;
        setFeedback({
          type: 'ok',
          msg: `${direction} ${data.size} ETH — ${data.deal_id?.slice(0, 12)}`,
        });
      } else {
        const data = res.data as any;
        setFeedback({
          type: 'err',
          msg: data?.message || res.error || 'Erreur inconnue',
        });
      }
    } catch (e) {
      setFeedback({ type: 'err', msg: String(e) });
    } finally {
      setLoading(null);
      // Clear feedback after 5s
      setTimeout(() => setFeedback(null), 5000);
    }
  }

  return (
    <div className="bg-bg-surface rounded-lg border border-border p-3">
      <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
        Trade Manuel
      </h3>

      {/* Price info */}
      <div className="flex items-center justify-between mb-3 text-xs font-mono">
        <div>
          <span className="text-text-faint">Bid </span>
          <span className="text-accent-green font-bold">{bid.toFixed(2)}</span>
        </div>
        <div className="text-text-faint">
          Spread {spread.toFixed(1)}
        </div>
        <div>
          <span className="text-text-faint">Ask </span>
          <span className="text-accent-red font-bold">{offer.toFixed(2)}</span>
        </div>
      </div>

      {/* Size info */}
      <div className="text-center text-xs text-text-muted mb-3">
        Taille: <span className="font-mono font-bold text-text">{size} ETH</span>
        <span className="text-text-faint ml-1">(≈ ${(size * bid).toFixed(0)})</span>
      </div>

      {/* BUY / SELL buttons */}
      <div className="grid grid-cols-2 gap-2">
        <button
          onClick={() => handleOrder('BUY')}
          disabled={loading !== null || bid === 0}
          className={`py-3 rounded-lg font-bold text-sm transition-all
            ${loading === 'BUY'
              ? 'bg-accent-green/30 text-accent-green animate-pulse'
              : 'bg-accent-green/20 text-accent-green border border-accent-green/30 hover:bg-accent-green/40 active:bg-accent-green/50'
            }
            ${loading !== null && loading !== 'BUY' ? 'opacity-40 cursor-not-allowed' : ''}
            ${bid === 0 ? 'opacity-30 cursor-not-allowed' : ''}
          `}
        >
          {loading === 'BUY' ? (
            <span className="flex items-center justify-center gap-1">
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
              ACHAT...
            </span>
          ) : (
            <>
              BUY LONG
              <span className="block text-[10px] font-normal opacity-70 mt-0.5">
                @ {offer.toFixed(2)}
              </span>
            </>
          )}
        </button>

        <button
          onClick={() => handleOrder('SELL')}
          disabled={loading !== null || bid === 0}
          className={`py-3 rounded-lg font-bold text-sm transition-all
            ${loading === 'SELL'
              ? 'bg-accent-red/30 text-accent-red animate-pulse'
              : 'bg-accent-red/20 text-accent-red border border-accent-red/30 hover:bg-accent-red/40 active:bg-accent-red/50'
            }
            ${loading !== null && loading !== 'SELL' ? 'opacity-40 cursor-not-allowed' : ''}
            ${bid === 0 ? 'opacity-30 cursor-not-allowed' : ''}
          `}
        >
          {loading === 'SELL' ? (
            <span className="flex items-center justify-center gap-1">
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
              VENTE...
            </span>
          ) : (
            <>
              SELL SHORT
              <span className="block text-[10px] font-normal opacity-70 mt-0.5">
                @ {bid.toFixed(2)}
              </span>
            </>
          )}
        </button>
      </div>

      {/* Feedback */}
      {feedback && (
        <div className={`mt-2 text-xs text-center py-1.5 rounded ${
          feedback.type === 'ok'
            ? 'bg-accent-green/10 text-accent-green'
            : 'bg-accent-red/10 text-accent-red'
        }`}>
          {feedback.msg}
        </div>
      )}
    </div>
  );
}
