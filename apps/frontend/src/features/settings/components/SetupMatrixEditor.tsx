/**
 * SetupMatrixEditor — N×N setup time matrix for tools on a machine.
 */

import { useState } from 'react';
import type { ETool } from '@/domain/types/scheduling';
import './SetupMatrixEditor.css';

interface SetupMatrixEditorProps {
  tools: ETool[];
}

function setupColor(min: number): string {
  if (min <= 0) return 'var(--bg-raised)';
  if (min < 30) return 'var(--accent)';
  if (min <= 60) return 'var(--semantic-amber)';
  return 'var(--semantic-red)';
}

function defaultMatrix(tools: ETool[]): number[][] {
  return tools.map((from) =>
    tools.map((to) => {
      if (from.id === to.id) return 0;
      return Math.round(Math.max(from.sH, to.sH) * 60);
    }),
  );
}

export function SetupMatrixEditor({ tools }: SetupMatrixEditorProps) {
  const [matrix, setMatrix] = useState(() => defaultMatrix(tools));
  const [editing, setEditing] = useState<{ r: number; c: number } | null>(null);
  const [editVal, setEditVal] = useState('');

  if (tools.length === 0) {
    return (
      <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
        Sem ferramentas para esta máquina
      </div>
    );
  }

  const startEdit = (r: number, c: number) => {
    if (r === c) return;
    setEditing({ r, c });
    setEditVal(String(matrix[r][c]));
  };

  const commitEdit = () => {
    if (!editing) return;
    const val = Math.max(0, Math.round(Number(editVal) || 0));
    setMatrix((prev) => {
      const next = prev.map((row) => [...row]);
      next[editing.r][editing.c] = val;
      return next;
    });
    setEditing(null);
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
        <span style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 500 }}>Dados ISOP</span>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table className="setup-matrix">
          <thead>
            <tr>
              <th className="setup-matrix__corner">De \ Para</th>
              {tools.map((t) => (
                <th key={t.id} className="setup-matrix__header" title={t.nm}>
                  {t.id.length > 8 ? `${t.id.slice(0, 8)}…` : t.id}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tools.map((from, ri) => (
              <tr key={from.id}>
                <td className="setup-matrix__row-label" title={from.nm}>
                  {from.id.length > 8 ? `${from.id.slice(0, 8)}…` : from.id}
                </td>
                {tools.map((_, ci) => {
                  const isDiag = ri === ci;
                  const val = matrix[ri][ci];
                  const isEditing = editing?.r === ri && editing?.c === ci;
                  return (
                    <td
                      key={ci}
                      className={
                        isDiag
                          ? 'setup-matrix__cell setup-matrix__cell--diagonal'
                          : 'setup-matrix__cell'
                      }
                      style={{
                        color: isDiag ? 'var(--text-muted)' : setupColor(val),
                        cursor: isDiag ? 'default' : 'pointer',
                      }}
                      onClick={() => startEdit(ri, ci)}
                    >
                      {isEditing ? (
                        <input
                          className="setup-matrix__input"
                          type="number"
                          value={editVal}
                          onChange={(e) => setEditVal(e.target.value)}
                          onBlur={commitEdit}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') commitEdit();
                            if (e.key === 'Escape') setEditing(null);
                          }}
                          style={{
                            width: 40,
                            textAlign: 'center',
                            fontSize: 12,
                            fontFamily: 'var(--font-mono)',
                          }}
                        />
                      ) : (
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{val}</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div
        style={{
          marginTop: 12,
          display: 'flex',
          gap: 16,
          fontSize: 12,
          color: 'var(--text-muted)',
        }}
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
