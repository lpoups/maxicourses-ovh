'use client';

import { useEffect, useState } from 'react';
import { analyticsApi } from '@/lib/api';

interface AIAnalysis {
  timestamp: string | null;
  action: string;
  confidence: number;
  direction: string | null;
  regime: string | null;
  thinking: string | null;
  reason: string | null;
  score_long: number | null;
  score_short: number | null;
  horizons: Record<string, string> | null;
  wait_reason_code: string | null;
  model_used: string | null;
  tokens_in: number;
  tokens_out: number;
}

const ACTION_COLORS: Record<string, string> = {
  LONG: 'bg-accent-green/20 text-accent-green',
  SHORT: 'bg-accent-red/20 text-accent-red',
  WAIT: 'bg-accent-yellow/20 text-accent-yellow',
  HOLD: 'bg-accent-blue/20 text-accent-blue',
  EXIT_LONG: 'bg-accent-orange/20 text-accent-orange',
  EXIT_SHORT: 'bg-accent-orange/20 text-accent-orange',
  QUITTER: 'bg-accent-red/20 text-accent-red',
};

export function AIAnalysisPanel() {
  const [analyses, setAnalyses] = useState<AIAnalysis[]>([]);
  const [totalInDb, setTotalInDb] = useState(0);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadAnalyses();
    const interval = setInterval(loadAnalyses, 60000);
    return () => clearInterval(interval);
  }, []);

  async function loadAnalyses() {
    try {
      const res = await analyticsApi.getAiAnalyses(20);
      if (res.success && res.data) {
        const data = res.data as any;
        setAnalyses(data.analyses || []);
        setTotalInDb(data.total_in_db || 0);
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }

  function formatTime(ts: string | null): string {
    if (!ts) return '—';
    try {
      const d = new Date(ts);
      return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return ts;
    }
  }

  function formatDate(ts: string | null): string {
    if (!ts) return '';
    try {
      const d = new Date(ts);
      return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' });
    } catch {
      return '';
    }
  }

  if (loading) {
    return (
      <div className="bg-bg-surface rounded-lg border border-border p-3">
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
          Analyses IA
        </h3>
        <p className="text-xs text-text-faint text-center py-4">Chargement...</p>
      </div>
    );
  }

  // Stats summary
  const totalTokensIn = analyses.reduce((s, a) => s + a.tokens_in, 0);
  const totalTokensOut = analyses.reduce((s, a) => s + a.tokens_out, 0);
  const avgConfidence = analyses.length > 0
    ? Math.round(analyses.reduce((s, a) => s + a.confidence, 0) / analyses.length)
    : 0;
  const actionCounts: Record<string, number> = {};
  analyses.forEach((a) => { actionCounts[a.action] = (actionCounts[a.action] || 0) + 1; });

  return (
    <div className="bg-bg-surface rounded-lg border border-border p-3">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-accent-purple live-dot" />
          <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider">
            Analyses IA
          </h3>
        </div>
        <span className="text-2xs text-text-faint">{totalInDb} total</span>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-1.5 mb-3">
        <div className="bg-bg rounded p-1.5 text-center">
          <p className="text-xs font-bold font-mono text-accent-purple">{avgConfidence}%</p>
          <p className="text-2xs text-text-faint">Conf. moy</p>
        </div>
        <div className="bg-bg rounded p-1.5 text-center">
          <p className="text-xs font-bold font-mono text-accent-blue">{analyses.length}</p>
          <p className="text-2xs text-text-faint">Recentes</p>
        </div>
        <div className="bg-bg rounded p-1.5 text-center">
          <p className="text-xs font-bold font-mono text-text">{(totalTokensIn / 1000).toFixed(1)}k</p>
          <p className="text-2xs text-text-faint">Tokens In</p>
        </div>
        <div className="bg-bg rounded p-1.5 text-center">
          <p className="text-xs font-bold font-mono text-text">{(totalTokensOut / 1000).toFixed(1)}k</p>
          <p className="text-2xs text-text-faint">Tokens Out</p>
        </div>
      </div>

      {/* Action distribution */}
      <div className="flex gap-1 mb-3 flex-wrap">
        {Object.entries(actionCounts).map(([action, count]) => (
          <span
            key={action}
            className={`px-1.5 py-0.5 rounded text-2xs font-mono font-medium ${ACTION_COLORS[action] || 'bg-bg text-text-muted'}`}
          >
            {action} ({count})
          </span>
        ))}
      </div>

      {/* Skills loaded indicator */}
      <div className="flex items-center gap-2 mb-3 px-2 py-1.5 bg-bg rounded border border-border/50">
        <span className="w-1.5 h-1.5 rounded-full bg-accent-green" />
        <span className="text-2xs text-text-muted">SKILL.md + Chartisme chargés</span>
      </div>

      {/* Analysis list */}
      <div className="space-y-1 max-h-80 overflow-y-auto">
        {analyses.length === 0 ? (
          <p className="text-xs text-text-faint text-center py-4">Aucune analyse</p>
        ) : (
          analyses.map((a, i) => (
            <div key={i} className="bg-bg rounded border border-border/30">
              {/* Row header - clickable */}
              <button
                onClick={() => setExpanded(expanded === i ? null : i)}
                className="w-full flex items-center justify-between px-2 py-1.5 hover:bg-bg-hover transition-colors"
              >
                <div className="flex items-center gap-2">
                  <span className={`px-1.5 py-0.5 rounded text-2xs font-mono font-bold ${ACTION_COLORS[a.action] || 'bg-bg text-text-muted'}`}>
                    {a.action}
                  </span>
                  <span className="text-2xs font-mono text-text-muted">
                    {a.confidence}%
                  </span>
                  {a.regime && (
                    <span className="text-2xs text-accent-blue">{a.regime}</span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-2xs text-text-faint font-mono">
                    {formatDate(a.timestamp)} {formatTime(a.timestamp)}
                  </span>
                  <span className="text-2xs text-text-faint">{expanded === i ? '▲' : '▼'}</span>
                </div>
              </button>

              {/* Expanded details */}
              {expanded === i && (
                <div className="px-2 pb-2 space-y-2 border-t border-border/30">
                  {/* Model + Tokens */}
                  <div className="flex items-center gap-3 pt-1.5">
                    <span className="text-2xs text-text-faint">
                      Model: <span className="text-accent-purple font-mono">{a.model_used || '—'}</span>
                    </span>
                    <span className="text-2xs text-text-faint">
                      Tokens: <span className="font-mono">{a.tokens_in}→{a.tokens_out}</span>
                    </span>
                  </div>

                  {/* Scores */}
                  {(a.score_long !== null || a.score_short !== null) && (
                    <div className="flex gap-3">
                      <div className="flex items-center gap-1">
                        <span className="text-2xs text-text-faint">Long:</span>
                        <div className="w-16 h-1.5 bg-bg-surface2 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-accent-green rounded-full"
                            style={{ width: `${Math.min(100, (a.score_long || 0) * 10)}%` }}
                          />
                        </div>
                        <span className="text-2xs font-mono">{a.score_long ?? 0}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <span className="text-2xs text-text-faint">Short:</span>
                        <div className="w-16 h-1.5 bg-bg-surface2 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-accent-red rounded-full"
                            style={{ width: `${Math.min(100, (a.score_short || 0) * 10)}%` }}
                          />
                        </div>
                        <span className="text-2xs font-mono">{a.score_short ?? 0}</span>
                      </div>
                    </div>
                  )}

                  {/* Horizons */}
                  {a.horizons && (
                    <div className="flex gap-1">
                      {Object.entries(a.horizons).map(([tf, dir]) => (
                        <span key={tf} className="px-1.5 py-0.5 bg-bg-surface2 rounded text-2xs">
                          <span className="text-text-faint">{tf}:</span>{' '}
                          <span className="font-medium">{dir}</span>
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Reason */}
                  {a.reason && (
                    <div>
                      <span className="text-2xs text-text-faint">Raison:</span>
                      <p className="text-xs text-text-muted leading-relaxed mt-0.5">
                        {a.reason}
                      </p>
                    </div>
                  )}

                  {/* Thinking */}
                  {a.thinking && (
                    <div>
                      <span className="text-2xs text-text-faint">Raisonnement:</span>
                      <p className="text-2xs text-text-faint leading-relaxed mt-0.5 max-h-24 overflow-y-auto whitespace-pre-wrap">
                        {a.thinking}
                      </p>
                    </div>
                  )}

                  {/* Wait reason */}
                  {a.wait_reason_code && (
                    <p className="text-2xs text-accent-yellow">
                      Code attente: {a.wait_reason_code}
                    </p>
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
