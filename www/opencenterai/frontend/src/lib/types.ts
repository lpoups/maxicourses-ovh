// ═══════════════════════════════════════════════════════════════
// OpenCenterAI — TypeScript Types & Interfaces
// ═══════════════════════════════════════════════════════════════

// ── Market Data ───────────────────────────────────────────────
export interface Ticker {
  bid: number;
  offer: number;
  spread: number;
  change_pct: number;
  high: number;
  low: number;
  timestamp: string;
}

export interface Candle {
  time: number; // Unix timestamp
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// ── Positions & Trades ────────────────────────────────────────
export interface Position {
  deal_id: string;
  direction: 'BUY' | 'SELL';
  size: number;
  entry_price: number;
  current_price: number;
  pnl_eur: number;
  pnl_pct: number;
  sl_price: number | null;
  tp_price: number | null;
  trailing_active: boolean;
  created_at: string;
}

export interface Trade {
  trade_id: string;
  deal_id: string;
  direction: 'BUY' | 'SELL';
  size: number;
  entry_price: number;
  exit_price: number | null;
  pnl_eur: number | null;
  peak_pnl: number | null;
  status: 'OPEN' | 'WIN' | 'LOSS' | 'BREAKEVEN';
  exit_reason: string | null;
  duration_sec: number | null;
  open_timestamp: string;
  close_timestamp: string | null;
  ai_entry?: AIDecision;
}

// ── AI Decision ───────────────────────────────────────────────
export interface AIDecision {
  action: 'LONG' | 'SHORT' | 'WAIT' | 'HOLD' | 'EXIT_LONG' | 'EXIT_SHORT' | 'QUITTER';
  confidence: number;
  direction: string;
  regime: string;
  entry_mode: string;
  thinking: string;
  reason: string;
  score_long: number;
  score_short: number;
  horizons: {
    '15m': string;
    '30m': string;
    '1h': string;
    '4h': string;
  };
  wait_reason_code: string | null;
  timestamp: string;
}

// ── Engine Status ─────────────────────────────────────────────
export interface EngineStatus {
  running: boolean;
  mode: string;
  ig_connected: boolean;
  ai_available: boolean;
  daily_pnl_eur: number;
  daily_trades: number;
  daily_wins: number;
  daily_losses: number;
  current_session: string;
  last_analysis_time: string | null;
  last_trade_time: string | null;
  uptime_sec: number;
}

// ── Trading Config ────────────────────────────────────────────
export interface TradingConfig {
  enabled: boolean;
  mode: string;
  frequency_mode: string;
  position_size_eth: number;
  max_open_positions: number;
  min_confidence: number;
  stop_distance_pts: number;
  limit_distance_pts: number;
  daily_loss_limit_eur: number;
  scalping_mode_enabled: boolean;
  hybrid_analysis_mode: string;
}

// ── Analytics ─────────────────────────────────────────────────
export interface PerformanceSummary {
  period_days: number;
  total_trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  total_pnl_eur: number;
  profit_factor: number;
  best_trade_eur: number;
  worst_trade_eur: number;
  avg_duration_min: number;
}

export interface DailyPerf {
  date: string;
  total_trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  total_pnl_eur: number;
  profit_factor: number;
}

export interface ExitReasonStat {
  exit_reason: string;
  count: number;
  total_pnl_eur: number;
  win_rate_pct: number;
}

// ── WebSocket Events ──────────────────────────────────────────
export type WSEventType =
  | 'price_update'
  | 'position_update'
  | 'signal_update'
  | 'trade_event'
  | 'engine_status'
  | 'ai_thinking';

export interface WSMessage {
  event: WSEventType;
  data: any;
  ts: number;
}

// ── Account ───────────────────────────────────────────────────
export interface AccountInfo {
  balance: number;
  available: number;
  profit_loss: number;
  deposit: number;
  currency: string;
}
