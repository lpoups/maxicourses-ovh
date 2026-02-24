// ═══════════════════════════════════════════════════════════════
// OpenCenterAI — Zustand Trading Store
// ═══════════════════════════════════════════════════════════════

import { create } from 'zustand';
import type {
  Ticker,
  Position,
  Trade,
  AIDecision,
  EngineStatus,
  TradingConfig,
  PerformanceSummary,
} from '@/lib/types';

interface TradingState {
  // Market
  ticker: Ticker | null;

  // Positions & Trades
  positions: Position[];
  recentTrades: Trade[];

  // AI
  latestSignal: AIDecision | null;
  aiThinking: string | null;

  // Engine
  engineStatus: EngineStatus | null;
  config: TradingConfig | null;

  // Analytics
  performance: PerformanceSummary | null;

  // Connection
  wsConnected: boolean;

  // Actions
  updateTicker: (ticker: Ticker) => void;
  updatePositions: (positions: Position[]) => void;
  addTrade: (trade: Trade) => void;
  updateSignal: (signal: AIDecision) => void;
  setAiThinking: (thinking: string | null) => void;
  updateEngineStatus: (status: EngineStatus) => void;
  setConfig: (config: TradingConfig) => void;
  setPerformance: (perf: PerformanceSummary) => void;
  setRecentTrades: (trades: Trade[]) => void;
  setWsConnected: (connected: boolean) => void;
}

export const useTradingStore = create<TradingState>((set) => ({
  // Initial state
  ticker: null,
  positions: [],
  recentTrades: [],
  latestSignal: null,
  aiThinking: null,
  engineStatus: null,
  config: null,
  performance: null,
  wsConnected: false,

  // Actions
  updateTicker: (ticker) => set({ ticker }),

  updatePositions: (positions) => set({ positions }),

  addTrade: (trade) =>
    set((state) => ({
      recentTrades: [trade, ...state.recentTrades].slice(0, 50),
    })),

  updateSignal: (signal) => set({ latestSignal: signal }),

  setAiThinking: (thinking) => set({ aiThinking: thinking }),

  updateEngineStatus: (status) => set({ engineStatus: status }),

  setConfig: (config) => set({ config }),

  setPerformance: (performance) => set({ performance }),

  setRecentTrades: (trades) => set({ recentTrades: trades }),

  setWsConnected: (connected) => set({ wsConnected: connected }),
}));
