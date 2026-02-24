'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { useTradingStore } from '@/stores/tradingStore';
import { marketApi } from '@/lib/api';

// IG API rate limits: 30 non-trading req/min/account
const TIMEFRAMES = [
  { label: '1m', value: '1m', initCount: 500, refreshCount: 10, round: 60 },
  { label: '5m', value: '5m', initCount: 500, refreshCount: 5, round: 300 },
  { label: '15m', value: '15m', initCount: 400, refreshCount: 3, round: 900 },
  { label: '1h', value: '1h', initCount: 168, refreshCount: 2, round: 3600 },
  { label: '4h', value: '4h', initCount: 42, refreshCount: 1, round: 14400 },
];

// ═══════════════════════════════════════════════════════════════
// INDICATOR CALCULATIONS (frontend — no extra API call needed)
// ═══════════════════════════════════════════════════════════════

function computeRSI(closes: number[], period = 14): (number | null)[] {
  const len = closes.length;
  if (len < period + 1) return closes.map(() => null);

  const result: (number | null)[] = new Array(period).fill(null);
  let avgGain = 0;
  let avgLoss = 0;

  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d > 0) avgGain += d;
    else avgLoss -= d;
  }
  avgGain /= period;
  avgLoss /= period;
  result.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss));

  for (let i = period + 1; i < len; i++) {
    const d = closes[i] - closes[i - 1];
    avgGain = (avgGain * (period - 1) + (d > 0 ? d : 0)) / period;
    avgLoss = (avgLoss * (period - 1) + (d < 0 ? -d : 0)) / period;
    result.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss));
  }
  return result;
}

function computeStochastic(
  highs: number[], lows: number[], closes: number[],
  kPeriod = 14, kSmooth = 3, dSmooth = 3,
): { k: (number | null)[]; d: (number | null)[] } {
  const len = closes.length;
  if (len < kPeriod) return { k: closes.map(() => null), d: closes.map(() => null) };

  // Raw %K
  const rawK: number[] = [];
  for (let i = 0; i < len; i++) {
    if (i < kPeriod - 1) { rawK.push(NaN); continue; }
    let hh = -Infinity, ll = Infinity;
    for (let j = i - kPeriod + 1; j <= i; j++) {
      if (highs[j] > hh) hh = highs[j];
      if (lows[j] < ll) ll = lows[j];
    }
    rawK.push(hh === ll ? 50 : ((closes[i] - ll) / (hh - ll)) * 100);
  }

  const smoothK = sma(rawK, kSmooth);
  const signalD = sma(smoothK, dSmooth);

  return {
    k: smoothK.map((v) => (isNaN(v) ? null : v)),
    d: signalD.map((v) => (isNaN(v) ? null : v)),
  };
}

function sma(values: number[], period: number): number[] {
  const out: number[] = [];
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1 || isNaN(values[i])) { out.push(NaN); continue; }
    let sum = 0, cnt = 0;
    for (let j = i - period + 1; j <= i; j++) {
      if (!isNaN(values[j])) { sum += values[j]; cnt++; }
    }
    out.push(cnt === period ? sum / cnt : NaN);
  }
  return out;
}

function computeEMA(values: number[], period: number): (number | null)[] {
  if (values.length < period) return values.map(() => null);
  const k = 2 / (period + 1);
  const result: (number | null)[] = new Array(period - 1).fill(null);
  // Seed with SMA
  let sum = 0;
  for (let i = 0; i < period; i++) sum += values[i];
  let ema = sum / period;
  result.push(ema);
  for (let i = period; i < values.length; i++) {
    ema = values[i] * k + ema * (1 - k);
    result.push(ema);
  }
  return result;
}

function computeSMA(values: number[], period: number): (number | null)[] {
  const raw = sma(values, period);
  return raw.map((v) => (isNaN(v) ? null : v));
}

function computeBollinger(
  closes: number[], period = 20, mult = 2,
): { upper: (number | null)[]; mid: (number | null)[]; lower: (number | null)[] } {
  const len = closes.length;
  const upper: (number | null)[] = [];
  const mid: (number | null)[] = [];
  const lower: (number | null)[] = [];
  for (let i = 0; i < len; i++) {
    if (i < period - 1) { upper.push(null); mid.push(null); lower.push(null); continue; }
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += closes[j];
    const mean = sum / period;
    let sqSum = 0;
    for (let j = i - period + 1; j <= i; j++) sqSum += (closes[j] - mean) ** 2;
    const std = Math.sqrt(sqSum / period);
    mid.push(mean);
    upper.push(mean + mult * std);
    lower.push(mean - mult * std);
  }
  return { upper, mid, lower };
}

// ═══════════════════════════════════════════════════════════════
// CHART COMPONENT
// ═══════════════════════════════════════════════════════════════

export function Chart() {
  // Main chart
  const mainRef = useRef<HTMLDivElement>(null);
  const mainChartRef = useRef<any>(null);
  const candleSeriesRef = useRef<any>(null);
  const volumeSeriesRef = useRef<any>(null);

  // RSI pane
  const rsiRef = useRef<HTMLDivElement>(null);
  const rsiChartRef = useRef<any>(null);
  const rsiSeriesRef = useRef<any>(null);

  // Stochastic pane
  const stochRef = useRef<HTMLDivElement>(null);
  const stochChartRef = useRef<any>(null);
  const stochKRef = useRef<any>(null);
  const stochDRef = useRef<any>(null);

  // Overlay series (EMA, SMA, Bollinger) on main chart
  const ema9Ref = useRef<any>(null);
  const ema21Ref = useRef<any>(null);
  const ema50Ref = useRef<any>(null);
  const sma200Ref = useRef<any>(null);
  const bbUpperRef = useRef<any>(null);
  const bbMidRef = useRef<any>(null);
  const bbLowerRef = useRef<any>(null);

  // Data tracking
  const dataLoadedRef = useRef(false);
  const candleDataRef = useRef<{ time: number; open: number; high: number; low: number; close: number }[]>([]);
  const liveCandleRef = useRef<{ time: number; open: number; high: number; low: number; close: number } | null>(null);
  const isSyncing = useRef(false);

  const ticker = useTradingStore((s) => s.ticker);
  const [activeTf, setActiveTf] = useState('1m');
  const activeTfRef = useRef('1m');

  // ── Build & set indicator data from candle array ────────────
  const setIndicatorData = useCallback((
    candles: { time: number; open: number; high: number; low: number; close: number }[],
  ) => {
    if (candles.length < 16) return;

    const closes = candles.map((c) => c.close);
    const highs = candles.map((c) => c.high);
    const lows = candles.map((c) => c.low);
    const times = candles.map((c) => c.time);

    // Helper to build line data
    const toLine = (vals: (number | null)[]) =>
      times.reduce<{ time: number; value: number }[]>((acc, t, i) => {
        const v = vals[i];
        if (v !== null) acc.push({ time: t, value: v });
        return acc;
      }, []);

    // RSI
    const rsiVals = computeRSI(closes);
    if (rsiSeriesRef.current) rsiSeriesRef.current.setData(toLine(rsiVals));

    // Stochastic
    const { k, d } = computeStochastic(highs, lows, closes);
    if (stochKRef.current) stochKRef.current.setData(toLine(k));
    if (stochDRef.current) stochDRef.current.setData(toLine(d));

    // EMA overlays
    if (ema9Ref.current) ema9Ref.current.setData(toLine(computeEMA(closes, 9)));
    if (ema21Ref.current) ema21Ref.current.setData(toLine(computeEMA(closes, 21)));
    if (ema50Ref.current) ema50Ref.current.setData(toLine(computeEMA(closes, 50)));

    // SMA 200
    if (sma200Ref.current) sma200Ref.current.setData(toLine(computeSMA(closes, 200)));

    // Bollinger Bands (20, 2σ)
    const bb = computeBollinger(closes, 20, 2);
    if (bbUpperRef.current) bbUpperRef.current.setData(toLine(bb.upper));
    if (bbMidRef.current) bbMidRef.current.setData(toLine(bb.mid));
    if (bbLowerRef.current) bbLowerRef.current.setData(toLine(bb.lower));
  }, []);

  // ── Initialize all three charts ─────────────────────────────
  useEffect(() => {
    if (!mainRef.current || !rsiRef.current || !stochRef.current) return;

    let cancelled = false;
    let charts: any[] = [];
    let refreshInterval: NodeJS.Timeout | null = null;
    let resizeTimer: NodeJS.Timeout | null = null;

    async function init() {
      try {
        const lc = await import('lightweight-charts');
        if (cancelled) return;

        const base = (extra: any = {}) => ({
          layout: {
            background: { type: lc.ColorType.Solid, color: '#0d1117' },
            textColor: '#8b949e',
            fontFamily: "'Inter', system-ui, sans-serif",
            fontSize: 11,
          },
          grid: {
            vertLines: { color: '#1c2128' },
            horzLines: { color: '#1c2128' },
          },
          crosshair: {
            vertLine: { color: '#30363d', width: 1, style: 2, labelBackgroundColor: '#161b22' },
            horzLine: { color: '#30363d', width: 1, style: 2, labelBackgroundColor: '#161b22' },
          },
          handleScroll: { vertTouchDrag: false },
          autoSize: true,
          ...extra,
        });

        // ── Main Chart ──────────────────────────────────
        // Time scale hidden on main — shown only on bottom (Stoch) for perfect alignment
        // FIXED_SCALE_W: all 3 charts use the same price scale width → perfect alignment
        const FIXED_SCALE_W = 200;

        const mainChart = lc.createChart(mainRef.current!, base({
          rightPriceScale: { borderColor: '#30363d', scaleMargins: { top: 0.05, bottom: 0.05 }, minimumWidth: FIXED_SCALE_W },
          timeScale: { borderColor: '#30363d', visible: false },
        }));

        const candleSeries = mainChart.addCandlestickSeries({
          upColor: '#3fb950', downColor: '#f85149',
          borderUpColor: '#3fb950', borderDownColor: '#f85149',
          wickUpColor: '#3fb950', wickDownColor: '#f85149',
        });

        // NOTE: IG CFD ne fournit PAS de vrais volumes (uniquement tick count = ~12/min constant)
        // Les barres de volume sont désactivées car trompeuses. Volume réel à ajouter via exchange API.
        volumeSeriesRef.current = null;

        // ── Overlay indicators on main chart ──────────
        const ema9 = mainChart.addLineSeries({
          color: '#e5a00d', lineWidth: 1, title: 'EMA 9',
          lastValueVisible: false, priceLineVisible: false,
        });
        const ema21 = mainChart.addLineSeries({
          color: '#58a6ff', lineWidth: 1, title: 'EMA 21',
          lastValueVisible: false, priceLineVisible: false,
        });
        const ema50 = mainChart.addLineSeries({
          color: '#bc8cff', lineWidth: 1, title: 'EMA 50',
          lastValueVisible: false, priceLineVisible: false,
        });
        const sma200s = mainChart.addLineSeries({
          color: '#8b949e', lineWidth: 1, title: 'SMA 200',
          lastValueVisible: false, priceLineVisible: false, lineStyle: 2,
        });
        // Bollinger Bands (20, 2σ)
        const bbUpper = mainChart.addLineSeries({
          color: 'rgba(248,81,73,0.4)', lineWidth: 1,
          lastValueVisible: false, priceLineVisible: false, lineStyle: 2,
        });
        const bbMid = mainChart.addLineSeries({
          color: 'rgba(139,148,158,0.4)', lineWidth: 1,
          lastValueVisible: false, priceLineVisible: false, lineStyle: 2,
        });
        const bbLower = mainChart.addLineSeries({
          color: 'rgba(63,185,80,0.4)', lineWidth: 1,
          lastValueVisible: false, priceLineVisible: false, lineStyle: 2,
        });

        ema9Ref.current = ema9;
        ema21Ref.current = ema21;
        ema50Ref.current = ema50;
        sma200Ref.current = sma200s;
        bbUpperRef.current = bbUpper;
        bbMidRef.current = bbMid;
        bbLowerRef.current = bbLower;

        // ── RSI Chart ───────────────────────────────────
        const rsiChart = lc.createChart(rsiRef.current!, base({
          rightPriceScale: { borderColor: '#30363d', scaleMargins: { top: 0.08, bottom: 0.08 }, minimumWidth: FIXED_SCALE_W },
          timeScale: { borderColor: '#30363d', visible: false },
        }));

        const rsiSeries = rsiChart.addLineSeries({
          color: '#e5a00d', lineWidth: 2,
          priceFormat: { type: 'custom', formatter: (v: number) => v.toFixed(0) },
          lastValueVisible: true, priceLineVisible: false,
        });
        rsiSeries.createPriceLine({ price: 70, color: '#f8514955', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '' });
        rsiSeries.createPriceLine({ price: 30, color: '#3fb95055', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '' });
        rsiSeries.createPriceLine({ price: 50, color: '#30363d44', lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: '' });

        // ── Stochastic Chart ────────────────────────────
        // Bottom chart: shows the shared time scale for all 3 charts
        const stochChart = lc.createChart(stochRef.current!, base({
          rightPriceScale: { borderColor: '#30363d', scaleMargins: { top: 0.08, bottom: 0.08 }, minimumWidth: FIXED_SCALE_W },
          timeScale: { borderColor: '#30363d', timeVisible: true, secondsVisible: false },
        }));

        const stochK = stochChart.addLineSeries({
          color: '#58a6ff', lineWidth: 2,
          priceFormat: { type: 'custom', formatter: (v: number) => v.toFixed(0) },
          lastValueVisible: true, priceLineVisible: false,
        });
        const stochD = stochChart.addLineSeries({
          color: '#f78166', lineWidth: 1, lineStyle: 2,
          priceFormat: { type: 'custom', formatter: (v: number) => v.toFixed(0) },
          lastValueVisible: true, priceLineVisible: false,
        });
        stochK.createPriceLine({ price: 80, color: '#f8514955', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '' });
        stochK.createPriceLine({ price: 20, color: '#3fb95055', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '' });

        // Store refs
        mainChartRef.current = mainChart;
        candleSeriesRef.current = candleSeries;
        rsiChartRef.current = rsiChart;
        rsiSeriesRef.current = rsiSeries;
        stochChartRef.current = stochChart;
        stochKRef.current = stochK;
        stochDRef.current = stochD;
        charts = [mainChart, rsiChart, stochChart];

        // ── Time Scale Sync ─────────────────────────────
        charts.forEach((chart, i) => {
          chart.timeScale().subscribeVisibleLogicalRangeChange((range: any) => {
            if (isSyncing.current || !range) return;
            isSyncing.current = true;
            charts.forEach((other, j) => {
              if (i !== j) other.timeScale().setVisibleLogicalRange(range);
            });
            isSyncing.current = false;
          });
        });

        // ── Crosshair Sync ──────────────────────────────
        const seriesMap = [candleSeries, rsiSeries, stochK];
        charts.forEach((chart, i) => {
          chart.subscribeCrosshairMove((param: any) => {
            if (isSyncing.current) return;
            isSyncing.current = true;
            charts.forEach((other, j) => {
              if (i !== j) {
                if (param.time) {
                  other.setCrosshairPosition(NaN, param.time, seriesMap[j]);
                } else {
                  other.clearCrosshairPosition();
                }
              }
            });
            isSyncing.current = false;
          });
        });

        // ── Sync price scale widths across all 3 charts ──
        // After data renders, measure widest scale and enforce on all
        const syncScaleWidths = () => {
          try {
            const widths = [mainChart, rsiChart, stochChart].map(
              (c) => c.priceScale('right').width()
            );
            const maxW = Math.max(...widths);
            if (maxW > 0) {
              [mainChart, rsiChart, stochChart].forEach((c) => {
                c.applyOptions({ rightPriceScale: { minimumWidth: maxW } });
              });
            }
          } catch {}
        };

        // ── Load initial data ───────────────────────────
        await loadCandles('1m', TIMEFRAMES[0].initCount);

        // Sync scale widths after render
        requestAnimationFrame(() => requestAnimationFrame(syncScaleWidths));

        // ── Periodic refresh (every 60s) + sync ─────────
        refreshInterval = setInterval(() => {
          const tf = TIMEFRAMES.find((t) => t.value === activeTfRef.current);
          if (tf) refreshLastCandles(tf.value, tf.refreshCount);
          syncScaleWidths();
        }, 60000);

        // Also sync on any resize
        resizeTimer = setInterval(syncScaleWidths, 3000);

      } catch (err) {
        console.error('[Chart] Init error:', err);
      }
    }

    init();

    return () => {
      cancelled = true;
      if (refreshInterval) clearInterval(refreshInterval);
      if (resizeTimer) clearInterval(resizeTimer);
      charts.forEach((c) => { try { c.remove(); } catch {} });
      mainChartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      rsiChartRef.current = null;
      rsiSeriesRef.current = null;
      stochChartRef.current = null;
      stochKRef.current = null;
      stochDRef.current = null;
      ema9Ref.current = null;
      ema21Ref.current = null;
      ema50Ref.current = null;
      sma200Ref.current = null;
      bbUpperRef.current = null;
      bbMidRef.current = null;
      bbLowerRef.current = null;
      dataLoadedRef.current = false;
      candleDataRef.current = [];
    };
  }, []);

  // ── Real-time ticker update ─────────────────────────────────
  useEffect(() => {
    if (!ticker || !candleSeriesRef.current || !dataLoadedRef.current) return;

    try {
      const tf = TIMEFRAMES.find((t) => t.value === activeTfRef.current);
      const roundSec = tf?.round || 60;
      const now = Math.floor(Date.now() / 1000);
      const candleTime = now - (now % roundSec);
      const bid = ticker.bid;

      let live = liveCandleRef.current;
      if (!live || live.time !== candleTime) {
        live = { time: candleTime, open: bid, high: bid, low: bid, close: bid };
      } else {
        live = { ...live, high: Math.max(live.high, bid), low: Math.min(live.low, bid), close: bid };
      }
      liveCandleRef.current = live;
      candleSeriesRef.current.update(live);

      // Update indicators with live candle
      const data = candleDataRef.current;
      if (data.length < 16) return;

      // Build arrays with live candle
      const closes = data.map((c) => c.close);
      const highs = data.map((c) => c.high);
      const lows = data.map((c) => c.low);

      if (data.length > 0 && data[data.length - 1].time === live.time) {
        closes[closes.length - 1] = live.close;
        highs[highs.length - 1] = live.high;
        lows[lows.length - 1] = live.low;
      } else {
        closes.push(live.close);
        highs.push(live.high);
        lows.push(live.low);
      }

      // Helper for live update
      const liveUpdate = (ref: any, vals: (number | null)[]) => {
        const v = vals[vals.length - 1];
        if (v !== null && ref.current) ref.current.update({ time: live.time, value: v });
      };

      // RSI live update
      liveUpdate(rsiSeriesRef, computeRSI(closes));

      // Stochastic live update
      const { k, d } = computeStochastic(highs, lows, closes);
      liveUpdate(stochKRef, k);
      liveUpdate(stochDRef, d);

      // EMA overlays live update
      liveUpdate(ema9Ref, computeEMA(closes, 9));
      liveUpdate(ema21Ref, computeEMA(closes, 21));
      liveUpdate(ema50Ref, computeEMA(closes, 50));

      // SMA 200
      liveUpdate(sma200Ref, computeSMA(closes, 200));

      // Bollinger Bands live update
      const bb = computeBollinger(closes, 20, 2);
      liveUpdate(bbUpperRef, bb.upper);
      liveUpdate(bbMidRef, bb.mid);
      liveUpdate(bbLowerRef, bb.lower);
    } catch {
      // Ignore update errors
    }
  }, [ticker]);

  // ── Timeframe switch ────────────────────────────────────────
  function switchTimeframe(tfValue: string) {
    setActiveTf(tfValue);
    activeTfRef.current = tfValue;
    dataLoadedRef.current = false;
    liveCandleRef.current = null;
    candleDataRef.current = [];
    const tf = TIMEFRAMES.find((t) => t.value === tfValue);
    if (tf) loadCandles(tf.value, tf.initCount);
  }

  // ── Full load (initial + timeframe switch) ──────────────────
  const loadCandles = useCallback(async (resolution: string, count: number) => {
    try {
      const res = await marketApi.getCandles(resolution, count);
      if (res.success && res.data && candleSeriesRef.current) {
        const candles = (res.data as any).candles || res.data;
        if (Array.isArray(candles) && candles.length > 0) {
          const candleData = candles.map((c: any) => ({
            time: Math.floor(Number(c.time || c.timestamp)),
            open: Number(c.open),
            high: Number(c.high),
            low: Number(c.low),
            close: Number(c.close),
          }));

          candleSeriesRef.current.setData(candleData);
          candleDataRef.current = candleData;

          // Volume data
          if (volumeSeriesRef.current) {
            const volumeData = candles.map((c: any) => ({
              time: Math.floor(Number(c.time || c.timestamp)),
              value: Math.max(Number(c.volume) || 0, 1),
              color: Number(c.close) >= Number(c.open) ? 'rgba(63,185,80,0.5)' : 'rgba(248,81,73,0.5)',
            }));
            volumeSeriesRef.current.setData(volumeData);
          }

          // Compute & set indicators
          setIndicatorData(candleData);

          dataLoadedRef.current = true;
        }
      }
    } catch (err) {
      console.error('[Chart] loadCandles error:', err);
    }
  }, [setIndicatorData]);

  // ── Refresh last N candles (saves IG quota) ─────────────────
  const refreshLastCandles = useCallback(async (resolution: string, count: number) => {
    try {
      const res = await marketApi.getCandles(resolution, count);
      if (res.success && res.data && candleSeriesRef.current) {
        const candles = (res.data as any).candles || res.data;
        if (Array.isArray(candles)) {
          const stored = candleDataRef.current;

          for (const c of candles) {
            try {
              const pt = {
                time: Math.floor(Number(c.time || c.timestamp)),
                open: Number(c.open),
                high: Number(c.high),
                low: Number(c.low),
                close: Number(c.close),
              };
              candleSeriesRef.current.update(pt);

              // Update stored array
              const idx = stored.findIndex((s) => s.time === pt.time);
              if (idx >= 0) stored[idx] = pt;
              else stored.push(pt);
            } catch {
              // Ignore individual update errors
            }
          }

          // Recompute indicators after refresh
          if (stored.length > 16) setIndicatorData(stored);
        }
      }
    } catch {
      // Ignore refresh errors
    }
  }, [setIndicatorData]);

  // ── Render ──────────────────────────────────────────────────
  return (
    <div className="relative w-full h-full flex flex-col">
      {/* Timeframe selector */}
      <div className="absolute top-2 left-2 z-10 flex gap-1">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf.value}
            onClick={() => switchTimeframe(tf.value)}
            className={`px-2 py-0.5 rounded text-[10px] font-mono font-medium transition-colors ${
              activeTf === tf.value
                ? 'bg-accent-blue/20 text-accent-blue border border-accent-blue/30'
                : 'bg-bg/80 text-text-muted border border-border/50 hover:text-text'
            }`}
          >
            {tf.label}
          </button>
        ))}
      </div>

      {/* Indicator legend */}
      <div className="absolute top-2 right-2 z-10 flex gap-2 text-[9px] font-mono opacity-70">
        <span className="text-[#e5a00d]">EMA9</span>
        <span className="text-[#58a6ff]">EMA21</span>
        <span className="text-[#bc8cff]">EMA50</span>
        <span className="text-[#8b949e]">SMA200</span>
        <span className="text-[#f85149]/60">BB</span>
      </div>

      {/* Main candlestick chart */}
      <div ref={mainRef} className="flex-1 min-h-0" />

      {/* RSI(14) pane */}
      <div className="relative border-t border-border/30" style={{ height: 90 }}>
        <span className="absolute top-0.5 left-2 z-10 text-[9px] font-mono text-[#e5a00d]/70 pointer-events-none">
          RSI(14)
        </span>
        <div ref={rsiRef} className="w-full h-full" />
      </div>

      {/* Stochastic(14,3,3) pane — includes shared time scale */}
      <div className="relative border-t border-border/30" style={{ height: 115 }}>
        <span className="absolute top-0.5 left-2 z-10 text-[9px] font-mono pointer-events-none">
          <span className="text-[#58a6ff]/70">Stoch</span>
          <span className="text-text-faint/50">(14,3,3)</span>
          {' '}
          <span className="text-[#58a6ff]">%K</span>
          {' '}
          <span className="text-[#f78166]">%D</span>
        </span>
        <div ref={stochRef} className="w-full h-full" />
      </div>
    </div>
  );
}
