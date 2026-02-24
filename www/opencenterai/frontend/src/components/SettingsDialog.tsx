'use client';

import { useState } from 'react';
import { useTradingStore } from '@/stores/tradingStore';
import { configApi } from '@/lib/api';
import type { TradingConfig } from '@/lib/types';

interface SettingsDialogProps {
  open: boolean;
  onClose: () => void;
}

export function SettingsDialog({ open, onClose }: SettingsDialogProps) {
  const config = useTradingStore((s) => s.config);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<Partial<TradingConfig>>(config || {});

  if (!open || !config) return null;

  async function handleSave() {
    setSaving(true);
    try {
      await configApi.updateConfig(form);
      onClose();
    } finally {
      setSaving(false);
    }
  }

  function updateField(key: keyof TradingConfig, value: any) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  const sections = [
    {
      title: 'Execution',
      fields: [
        { key: 'position_size_eth', label: 'Position Size (ETH)', type: 'number', step: 0.5, min: 0.1, max: 4 },
        { key: 'max_open_positions', label: 'Max Positions', type: 'number', min: 1, max: 4 },
        { key: 'min_confidence', label: 'Min Confidence (%)', type: 'number', min: 50, max: 95 },
      ],
    },
    {
      title: 'Risk',
      fields: [
        { key: 'stop_distance_pts', label: 'Stop Loss (pts)', type: 'number', min: 10, max: 200 },
        { key: 'limit_distance_pts', label: 'Take Profit (pts)', type: 'number', min: 20, max: 400 },
        { key: 'daily_loss_limit_eur', label: 'Daily Loss Limit (EUR)', type: 'number', min: 10, max: 500 },
      ],
    },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-bg-surface border border-border rounded-xl w-full max-w-md max-h-[80vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h2 className="text-sm font-semibold">Configuration</h2>
          <button
            onClick={onClose}
            className="text-text-muted hover:text-text text-lg"
          >
            &times;
          </button>
        </div>

        {/* Body */}
        <div className="p-4 space-y-4">
          {sections.map((section) => (
            <div key={section.title}>
              <h3 className="text-xs font-semibold text-accent-blue uppercase tracking-wider mb-2">
                {section.title}
              </h3>
              <div className="space-y-2">
                {section.fields.map((field) => (
                  <div key={field.key} className="flex items-center justify-between">
                    <label className="text-xs text-text-muted">{field.label}</label>
                    <input
                      type={field.type}
                      value={(form as any)[field.key] ?? (config as any)[field.key] ?? ''}
                      onChange={(e) =>
                        updateField(
                          field.key as keyof TradingConfig,
                          field.type === 'number' ? Number(e.target.value) : e.target.value
                        )
                      }
                      min={field.min}
                      max={field.max}
                      step={field.step}
                      className="w-24 px-2 py-1 bg-bg border border-border rounded text-xs font-mono text-right
                                 focus:outline-none focus:border-accent-blue"
                    />
                  </div>
                ))}
              </div>
            </div>
          ))}

          {/* Toggles */}
          <div>
            <h3 className="text-xs font-semibold text-accent-blue uppercase tracking-wider mb-2">
              Mode
            </h3>
            <div className="flex gap-2">
              {['AGRESSIF', 'PRUDENT'].map((m) => (
                <button
                  key={m}
                  onClick={() => updateField('mode', m)}
                  className={`flex-1 py-1.5 rounded text-xs font-medium transition-colors ${
                    form.mode === m || (!form.mode && config.mode === m)
                      ? 'bg-accent-purple/20 text-accent-purple border border-accent-purple/30'
                      : 'bg-bg border border-border text-text-muted hover:text-text'
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-xs text-text-muted">Scalping Mode</span>
            <button
              onClick={() => updateField('scalping_mode_enabled', !form.scalping_mode_enabled)}
              className={`w-10 h-5 rounded-full transition-colors relative ${
                form.scalping_mode_enabled ? 'bg-accent-green' : 'bg-border'
              }`}
            >
              <div
                className={`w-4 h-4 rounded-full bg-white absolute top-0.5 transition-transform ${
                  form.scalping_mode_enabled ? 'translate-x-5' : 'translate-x-0.5'
                }`}
              />
            </button>
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 p-4 border-t border-border">
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-xs text-text-muted hover:text-text rounded border border-border"
          >
            Annuler
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-1.5 text-xs font-medium text-white bg-accent-blue rounded hover:bg-accent-blue/80
                       disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Sauvegarder'}
          </button>
        </div>
      </div>
    </div>
  );
}
