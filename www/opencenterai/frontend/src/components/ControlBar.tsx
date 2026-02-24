'use client';

import { useState } from 'react';
import { useTradingStore } from '@/stores/tradingStore';
import { tradingApi, configApi, statusApi } from '@/lib/api';
import { SettingsDialog } from './SettingsDialog';
import type { EngineStatus } from '@/lib/types';

export function ControlBar() {
  const { engineStatus, config } = useTradingStore();
  const [loading, setLoading] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const isRunning = engineStatus?.running ?? false;
  const dailyPnl = engineStatus?.daily_pnl_eur ?? 0;
  const dailyTrades = engineStatus?.daily_trades ?? 0;
  const dailyWins = engineStatus?.daily_wins ?? 0;
  const dailyLosses = engineStatus?.daily_losses ?? 0;

  const updateEngineStatus = useTradingStore((s) => s.updateEngineStatus);

  async function toggleEngine() {
    setLoading(true);
    try {
      if (isRunning) {
        await tradingApi.stopEngine();
      } else {
        await tradingApi.startEngine();
      }
      // Optimistic update: flip immediately for instant UI feedback
      if (engineStatus) {
        updateEngineStatus({ ...engineStatus, running: !isRunning });
      }
      // Then confirm with real status from server (belt & suspenders)
      const res = await statusApi.getStatus();
      if (res.success && res.data) {
        updateEngineStatus(res.data as EngineStatus);
      }
    } finally {
      setLoading(false);
    }
  }

  async function updateMode(mode: string) {
    await configApi.updateConfig({ mode });
  }

  async function updateSize(size: number) {
    if (size >= 0.1 && size <= 4.0) {
      await configApi.updateConfig({ position_size_eth: size });
    }
  }

  return (
    <div className="flex items-center justify-between px-4 py-2 bg-bg-surface2 border-b border-border">
      {/* Left: Start/Stop + Mode */}
      <div className="flex items-center gap-3">
        <button
          onClick={toggleEngine}
          disabled={loading}
          className={`px-4 py-1.5 rounded-lg font-semibold text-sm transition-all ${
            isRunning
              ? 'bg-accent-red/20 text-accent-red border border-accent-red/30 hover:bg-accent-red/30'
              : 'bg-accent-green/20 text-accent-green border border-accent-green/30 hover:bg-accent-green/30'
          } ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
        >
          {loading ? '...' : isRunning ? 'STOP' : 'START'}
        </button>

        {/* Mode selector */}
        <div className="flex rounded-lg overflow-hidden border border-border">
          {['AGRESSIF', 'PRUDENT'].map((m) => (
            <button
              key={m}
              onClick={() => updateMode(m)}
              className={`px-3 py-1 text-xs font-medium transition-colors ${
                config?.mode === m
                  ? 'bg-accent-purple/20 text-accent-purple'
                  : 'text-text-muted hover:text-text hover:bg-bg-hover'
              }`}
            >
              {m}
            </button>
          ))}
        </div>

        {/* Size */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted">Size:</span>
          <div className="flex items-center rounded-lg border border-border overflow-hidden">
            <button
              onClick={() => updateSize((config?.position_size_eth ?? 2) - 0.5)}
              className="px-2 py-1 text-xs text-text-muted hover:bg-bg-hover"
            >
              -
            </button>
            <span className="px-2 py-1 text-xs font-mono font-medium bg-bg">
              {config?.position_size_eth ?? 2} ETH
            </span>
            <button
              onClick={() => updateSize((config?.position_size_eth ?? 2) + 0.5)}
              className="px-2 py-1 text-xs text-text-muted hover:bg-bg-hover"
            >
              +
            </button>
          </div>
        </div>
      </div>

      {/* Right: Daily stats + Settings */}
      <div className="flex items-center gap-4 text-xs">
        <div className="flex items-center gap-1.5">
          <span className="text-text-muted">PnL:</span>
          <span className={`font-mono font-bold ${dailyPnl >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>
            {dailyPnl >= 0 ? '+' : ''}{dailyPnl.toFixed(2)}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-text-muted">Trades:</span>
          <span className="font-mono">{dailyTrades}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-accent-green font-mono">{dailyWins}W</span>
          <span className="text-text-faint">/</span>
          <span className="text-accent-red font-mono">{dailyLosses}L</span>
        </div>
        {dailyTrades > 0 && (
          <span className="font-mono text-text-muted">
            {((dailyWins / dailyTrades) * 100).toFixed(0)}% WR
          </span>
        )}
        <button
          onClick={() => setSettingsOpen(true)}
          className="ml-2 px-3 py-1.5 rounded-lg text-text-muted hover:text-text hover:bg-bg-hover
                     border border-border transition-colors"
          title="Configuration"
        >
          Settings
        </button>
      </div>

      {/* Settings dialog */}
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
