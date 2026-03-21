/**
 * SetupTable — Editable table of setup times and production rates per tool.
 * Extracted from SetupMatrixPage to comply with 300-line component limit.
 */

import { useState } from 'react';

export interface SetupTableProps {
  tools: Array<{ id: string; nm: string; m: string; sH: number; pH: number }>;
  toolOverrides: Record<string, { s?: number; pH?: number }>;
  onSetOverride: (id: string, minutes: number) => void;
  onSetRateOverride: (id: string, pH: number) => void;
  onClearOverride: (id: string) => void;
  onClearRateOverride: (id: string) => void;
}

function setupColor(min: number): string {
  if (min <= 0) return 'var(--bg-raised)';
  if (min < 30) return 'var(--accent)';
  if (min <= 60) return 'var(--semantic-amber)';
  return 'var(--semantic-red)';
}

export function SetupTable({
  tools,
  toolOverrides,
  onSetOverride,
  onSetRateOverride,
  onClearOverride,
  onClearRateOverride,
}: SetupTableProps) {
  const [editing, setEditing] = useState<string | null>(null);
  const [editVal, setEditVal] = useState('');
  const [editingRate, setEditingRate] = useState<string | null>(null);
  const [editRateVal, setEditRateVal] = useState('');

  if (tools.length === 0) {
    return (
      <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
        Sem ferramentas para esta máquina
      </div>
    );
  }

  const startEdit = (toolId: string, currentMinutes: number) => {
    setEditing(toolId);
    setEditVal(String(currentMinutes));
  };

  const commitEdit = (toolId: string) => {
    const val = Math.max(0, Math.round(Number(editVal) || 0));
    onSetOverride(toolId, val);
    setEditing(null);
  };

  const startRateEdit = (toolId: string, currentPH: number) => {
    setEditingRate(toolId);
    setEditRateVal(String(currentPH));
  };

  const commitRateEdit = (toolId: string) => {
    const val = Math.max(0, Math.round(Number(editRateVal) || 0));
    onSetRateOverride(toolId, val);
    setEditingRate(null);
  };

  const stats = {
    count: tools.length,
    avgSetup:
      tools.length > 0 ? Math.round(tools.reduce((s, t) => s + t.sH * 60, 0) / tools.length) : 0,
    minSetup: tools.length > 0 ? Math.round(Math.min(...tools.map((t) => t.sH * 60))) : 0,
    maxSetup: tools.length > 0 ? Math.round(Math.max(...tools.map((t) => t.sH * 60))) : 0,
  };

  return (
    <div>
      <div
        style={{
          display: 'flex',
          gap: 16,
          fontSize: 12,
          color: 'var(--text-secondary)',
          marginBottom: 12,
        }}
      >
        <span>{stats.count} ferramentas</span>
        <span>
          Média:{' '}
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
            {stats.avgSetup}m
          </span>
        </span>
        <span>
          Min: <span style={{ fontFamily: 'var(--font-mono)' }}>{stats.minSetup}m</span>
        </span>
        <span>
          Max: <span style={{ fontFamily: 'var(--font-mono)' }}>{stats.maxSetup}m</span>
        </span>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table className="setup-matrix">
          <thead>
            <tr>
              <th className="setup-matrix__corner">Ferramenta</th>
              <th className="setup-matrix__header">Máquina</th>
              <th className="setup-matrix__header">Setup (min)</th>
              <th className="setup-matrix__header">Peças/h</th>
              <th className="setup-matrix__header">Fonte</th>
              <th className="setup-matrix__header" style={{ width: 60 }} />
            </tr>
          </thead>
          <tbody>
            {tools.map((t) => {
              const ov = toolOverrides[t.id];
              const isSetupOverridden = ov?.s !== undefined;
              const isRateOverridden = ov?.pH !== undefined;
              const isOverridden = isSetupOverridden || isRateOverridden;
              const displayMinutes = Math.round(t.sH * 60);
              const isEditing = editing === t.id;
              const isEditingPH = editingRate === t.id;

              return (
                <tr key={t.id}>
                  <td className="setup-matrix__row-label" title={t.nm}>
                    {t.id}
                  </td>
                  <td className="setup-matrix__cell" style={{ fontSize: 12 }}>
                    {t.m}
                  </td>
                  <td
                    className="setup-matrix__cell"
                    style={{
                      cursor: 'pointer',
                      color: setupColor(displayMinutes),
                      borderLeft: isSetupOverridden ? '2px solid var(--accent)' : undefined,
                    }}
                    tabIndex={0}
                    role="gridcell"
                    onClick={() => startEdit(t.id, displayMinutes)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); startEdit(t.id, displayMinutes); } }}
                  >
                    {isEditing ? (
                      <input
                        className="setup-matrix__input"
                        type="number"
                        value={editVal}
                        onChange={(e) => setEditVal(e.target.value)}
                        onBlur={() => commitEdit(t.id)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') commitEdit(t.id);
                          if (e.key === 'Escape') setEditing(null);
                        }}
                        autoFocus
                        style={{
                          width: 50,
                          textAlign: 'center',
                          fontSize: 12,
                          fontFamily: 'var(--font-mono)',
                        }}
                      />
                    ) : (
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                        {displayMinutes}
                      </span>
                    )}
                  </td>
                  <td
                    className="setup-matrix__cell"
                    style={{
                      cursor: 'pointer',
                      borderLeft: isRateOverridden ? '2px solid var(--accent)' : undefined,
                    }}
                    tabIndex={0}
                    role="gridcell"
                    onClick={() => startRateEdit(t.id, t.pH)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); startRateEdit(t.id, t.pH); } }}
                  >
                    {isEditingPH ? (
                      <input
                        className="setup-matrix__input"
                        type="number"
                        value={editRateVal}
                        onChange={(e) => setEditRateVal(e.target.value)}
                        onBlur={() => commitRateEdit(t.id)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') commitRateEdit(t.id);
                          if (e.key === 'Escape') setEditingRate(null);
                        }}
                        autoFocus
                        style={{
                          width: 60,
                          textAlign: 'center',
                          fontSize: 12,
                          fontFamily: 'var(--font-mono)',
                        }}
                      />
                    ) : (
                      <span
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: 12,
                          color: t.pH > 0 ? 'var(--text-primary)' : 'var(--semantic-red)',
                        }}
                      >
                        {t.pH > 0 ? t.pH : '—'}
                      </span>
                    )}
                  </td>
                  <td className="setup-matrix__cell" style={{ fontSize: 12 }}>
                    {isOverridden ? (
                      <span
                        style={{
                          color: 'var(--accent)',
                          fontWeight: 600,
                          padding: '1px 4px',
                          borderRadius: 3,
                          background: 'rgba(34,197,94,0.1)',
                        }}
                      >
                        Editado
                      </span>
                    ) : (
                      <span style={{ color: 'var(--text-muted)' }}>
                        {t.sH > 0 ? 'ISOP' : 'Default'}
                      </span>
                    )}
                  </td>
                  <td className="setup-matrix__cell" style={{ textAlign: 'center' }}>
                    {isOverridden && (
                      <button
                        onClick={() => {
                          if (isSetupOverridden) onClearOverride(t.id);
                          if (isRateOverridden) onClearRateOverride(t.id);
                        }}
                        style={{
                          fontSize: 12,
                          color: 'var(--text-muted)',
                          background: 'none',
                          border: '1px solid var(--border-subtle)',
                          borderRadius: 3,
                          padding: '1px 6px',
                          cursor: 'pointer',
                        }}
                        title="Reset para valor ISOP"
                      >
                        Reset
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div
        style={{ marginTop: 12, display: 'flex', gap: 16, fontSize: 12, color: 'var(--text-muted)' }}
      >
        <span>
          <span
            style={{
              display: 'inline-block',
              width: 8,
              height: 8,
              borderRadius: 2,
              background: 'var(--accent)',
              marginRight: 4,
            }}
          />
          &lt;30 min
        </span>
        <span>
          <span
            style={{
              display: 'inline-block',
              width: 8,
              height: 8,
              borderRadius: 2,
              background: 'var(--semantic-amber)',
              marginRight: 4,
            }}
          />
          30-60 min
        </span>
        <span>
          <span
            style={{
              display: 'inline-block',
              width: 8,
              height: 8,
              borderRadius: 2,
              background: 'var(--semantic-red)',
              marginRight: 4,
            }}
          />
          &gt;60 min
        </span>
      </div>
    </div>
  );
}
