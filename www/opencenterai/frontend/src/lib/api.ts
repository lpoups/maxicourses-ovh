// ═══════════════════════════════════════════════════════════════
// OpenCenterAI — API Client
// ═══════════════════════════════════════════════════════════════

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
}

async function fetchApi<T>(
  path: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  try {
    const url = `${API_BASE}${path}`;
    const res = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    });

    if (!res.ok) {
      const errorText = await res.text();
      return { success: false, error: `HTTP ${res.status}: ${errorText}` };
    }

    const data = await res.json();
    return { success: true, data };
  } catch (err) {
    return { success: false, error: String(err) };
  }
}

// ── Trading ───────────────────────────────────────────────────
export const tradingApi = {
  getPositions: () => fetchApi('/trading/positions'),
  getHistory: (limit = 50, skip = 0) =>
    fetchApi(`/trading/history?limit=${limit}&skip=${skip}`),
  startEngine: () => fetchApi('/trading/start', { method: 'POST' }),
  stopEngine: () => fetchApi('/trading/stop', { method: 'POST' }),
  closePosition: (dealId: string) =>
    fetchApi(`/trading/close/${dealId}`, { method: 'POST' }),
  manualOrder: (direction: 'BUY' | 'SELL', size?: number) =>
    fetchApi('/trading/manual-order', {
      method: 'POST',
      body: JSON.stringify({ direction, size: size || 0 }),
    }),
};

// ── Market ────────────────────────────────────────────────────
export const marketApi = {
  getTicker: () => fetchApi('/market/ticker'),
  getCandles: (resolution = '5m', count = 200) =>
    fetchApi(`/market/candles?resolution=${resolution}&count=${count}`),
  getIndicators: () => fetchApi('/market/indicators'),
  getSentiment: () => fetchApi('/market/sentiment'),
};

// ── Config ────────────────────────────────────────────────────
export const configApi = {
  getConfig: () => fetchApi('/config'),
  updateConfig: (updates: Record<string, any>) =>
    fetchApi('/config', {
      method: 'PUT',
      body: JSON.stringify({ updates }),
    }),
};

// ── Analytics ─────────────────────────────────────────────────
export const analyticsApi = {
  getSummary: (days = 7) => fetchApi(`/analytics/summary?days=${days}`),
  getDaily: (date?: string) =>
    fetchApi(`/analytics/daily${date ? `?date=${date}` : ''}`),
  getKnowledge: () => fetchApi('/analytics/knowledge'),
  getExitReasons: (days = 30) =>
    fetchApi(`/analytics/exit-reasons?days=${days}`),
  getAiStats: (hours = 24) => fetchApi(`/analytics/ai-stats?hours=${hours}`),
  getAiAnalyses: (limit = 20) =>
    fetchApi(`/analytics/ai-analyses?limit=${limit}`),
};

// ── Status ────────────────────────────────────────────────────
export const statusApi = {
  getStatus: () => fetchApi('/status'),
  getAccount: () => fetchApi('/account'),
};
