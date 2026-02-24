'use client';

import { useEffect, useState, useMemo } from 'react';
import { useTradingStore } from '@/stores/tradingStore';
import { marketApi } from '@/lib/api';

interface Sentiment {
  long_pct: number;
  short_pct: number;
  bid: number;
  offer: number;
  spread: number;
}

// Deterministic pseudo-random based on seed (no Math.random in render)
function seededRandom(seed: number): number {
  const x = Math.sin(seed * 9301 + 49297) * 49297;
  return x - Math.floor(x);
}

export function OrderBookPanel() {
  const ticker = useTradingStore((s) => s.ticker);
  const [sentiment, setSentiment] = useState<Sentiment | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetch sentiment every 60s
  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const res = await marketApi.getSentiment();
        if (mounted && res.success && res.data) {
          setSentiment(res.data as Sentiment);
        }
      } catch (e) {
        console.warn('[OrderBook] Sentiment fetch error:', e);
      }
    }
    load();
    const interval = setInterval(load, 60000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  const bid = ticker?.bid ?? sentiment?.bid ?? 0;
  const offer = ticker?.offer ?? sentiment?.offer ?? 0;
  const spread = offer > 0 && bid > 0 ? (offer - bid) : (sentiment?.spread ?? 0);
  const mid = bid > 0 && offer > 0 ? (bid + offer) / 2 : 0;
  const longPct = sentiment?.long_pct ?? 50;
  const shortPct = sentiment?.short_pct ?? 50;

  // Synthetic depth levels — deterministic (seeded by price to avoid hydration issues)
  const levels = 6;
  const step = Math.max(spread * 0.8, 0.3);
  const priceSeed = Math.round(bid * 100);

  const { askLevels, bidLevels, maxTotal } = useMemo(() => {
    const asks = Array.from({ length: levels }, (_, i) => ({
      price: offer + i * step,
      size: seededRandom(priceSeed + i + 100) * 15 + 2,
      total: 0,
    }));
    asks.forEach((l, i) => {
      l.total = asks.slice(0, i + 1).reduce((s, x) => s + x.size, 0);
    });

    const bids = Array.from({ length: levels }, (_, i) => ({
      price: bid - i * step,
      size: seededRandom(priceSeed + i + 200) * 15 + 2,
      total: 0,
    }));
    bids.forEach((l, i) => {
      l.total = bids.slice(0, i + 1).reduce((s, x) => s + x.size, 0);
    });

    const mt = Math.max(
      asks[asks.length - 1]?.total ?? 1,
      bids[bids.length - 1]?.total ?? 1,
    );

    return { askLevels: asks, bidLevels: bids, maxTotal: mt };
  }, [bid, offer, spread, step, priceSeed]);

  if (error) {
    return (
      <div className="bg-bg-surface rounded-lg border border-border p-3">
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
          Carnet d&apos;ordres
        </h3>
        <p className="text-xs text-accent-red text-center py-2">{error}</p>
      </div>
    );
  }

  return (
    <div className="bg-bg-surface rounded-lg border border-border flex-shrink-0">
      <div className="px-3 py-2 border-b border-border flex items-center justify-between">
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider">
          Carnet d&apos;ordres
        </h3>
        <span className="text-[10px] font-mono text-text-faint">
          Spread: {spread.toFixed(1)}
        </span>
      </div>

      <div className="text-[10px] font-mono">
        {/* ASK side (sells) — reversed so lowest ask is at bottom */}
        {[...askLevels].reverse().map((level, i) => (
          <div key={`ask-${i}`} className="relative flex items-center px-2 py-[3px]">
            <div
              className="absolute right-0 top-0 bottom-0 bg-accent-red/10"
              style={{ width: `${(level.total / maxTotal) * 100}%` }}
            />
            <span className="relative z-10 flex-1 text-accent-red">
              {level.price.toFixed(1)}
            </span>
            <span className="relative z-10 w-16 text-right text-text-muted">
              {level.size.toFixed(1)}
            </span>
            <span className="relative z-10 w-16 text-right text-text-faint">
              {level.total.toFixed(1)}
            </span>
          </div>
        ))}

        {/* Spread bar */}
        <div className="flex items-center justify-center py-1.5 bg-bg-surface2 border-y border-border/30">
          <span className="text-xs font-bold text-text">
            {mid > 0 ? mid.toFixed(2) : '—'}
          </span>
          <span className="ml-2 text-[9px] text-text-faint">
            ({spread.toFixed(1)} spread)
          </span>
        </div>

        {/* BID side (buys) */}
        {bidLevels.map((level, i) => (
          <div key={`bid-${i}`} className="relative flex items-center px-2 py-[3px]">
            <div
              className="absolute right-0 top-0 bottom-0 bg-accent-green/10"
              style={{ width: `${(level.total / maxTotal) * 100}%` }}
            />
            <span className="relative z-10 flex-1 text-accent-green">
              {level.price.toFixed(1)}
            </span>
            <span className="relative z-10 w-16 text-right text-text-muted">
              {level.size.toFixed(1)}
            </span>
            <span className="relative z-10 w-16 text-right text-text-faint">
              {level.total.toFixed(1)}
            </span>
          </div>
        ))}
      </div>

      {/* Client Sentiment bar */}
      {sentiment && (
        <div className="px-3 py-2 border-t border-border">
          <div className="flex justify-between text-[10px] mb-1">
            <span className="text-accent-green font-bold">
              Long {longPct.toFixed(0)}%
            </span>
            <span className="text-[9px] text-text-faint">Sentiment IG</span>
            <span className="text-accent-red font-bold">
              Short {shortPct.toFixed(0)}%
            </span>
          </div>
          <div className="flex h-2 rounded overflow-hidden">
            <div
              className="bg-accent-green/60 transition-all duration-500"
              style={{ width: `${longPct}%` }}
            />
            <div
              className="bg-accent-red/60 transition-all duration-500"
              style={{ width: `${shortPct}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
