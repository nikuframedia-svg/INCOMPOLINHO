/**
 * OperatorsPage — Operator count per tool with persistent overrides.
 * Route: /settings/operators
 *
 * Operator count is per-tool (op field). Edits persist via useMasterDataStore.toolOverrides.
 * Also shows the skill matrix (OperatorSkillMatrix) below.
 */

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState } from '@/components/Common/EmptyState';
import { SkeletonTable } from '@/components/Common/SkeletonLoader';
import { useScheduleData } from '@/hooks/useScheduleData';
import { DEFAULT_WORKFORCE_CONFIG } from '@/lib/engine';
import { useMasterDataStore } from '@/stores/useMasterDataStore';
import type { OperatorEntry } from '../components/OperatorSkillMatrix';
import { OperatorSkillMatrix } from '../components/OperatorSkillMatrix';

export function OperatorsPage() {
  const { engine, loading, error } = useScheduleData();
  const toolOverrides = useMasterDataStore((s) => s.toolOverrides);
  const setToolOverride = useMasterDataStore((s) => s.setToolOverride);
  const clearFieldOverride = useMasterDataStore((s) => s.clearFieldOverride);
  const [machineFilter, setMachineFilter] = useState('');

  const machineIds = useMemo(() => (engine ? engine.machines.map((m) => m.id) : []), [engine]);

  const tools = useMemo(() => {
    if (!engine) return [];
    const filtered = machineFilter
      ? engine.tools.filter((t) => t.m === machineFilter)
      : engine.tools;
    return filtered.map((t) => ({
      id: t.id,
      nm: t.nm,
      m: t.m,
      op: t.op,
      isOverridden: toolOverrides[t.id]?.op !== undefined,
    }));
  }, [engine, machineFilter, toolOverrides]);

  const { operators } = useMemo(() => {
    if (!engine) return { operators: [] };
    const ops: OperatorEntry[] = [];
    let idx = 1;
    for (const [group, windows] of Object.entries(DEFAULT_WORKFORCE_CONFIG.laborGroups)) {
      const maxCap = Math.max(...windows.map((w) => w.capacity));
      for (let i = 0; i < maxCap; i++) {
        ops.push({ id: `op-${idx}`, name: `Operador ${idx}`, group });
        idx++;
      }
    }
    return { operators: ops };
  }, [engine]);

  const overrideCount = tools.filter((t) => t.isOverridden).length;

  if (loading)
    return (
      <div style={{ padding: 32 }}>
        <SkeletonTable rows={6} cols={5} />
      </div>
    );
  if (error || !engine) {
    return (
      <div style={{ padding: 32 }}>
        <Link
          to="/settings"
          style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}
        >
          ← Settings
        </Link>
        <EmptyState icon="error" title="Sem dados" description={error || 'Importe ISOP.'} />
      </div>
    );
  }

  return (
    <div style={{ padding: 32, display: 'flex', flexDirection: 'column', gap: 24 }}>
      <Link to="/settings" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>
        ← Settings
      </Link>
      <h2
        style={{
          color: 'var(--text-primary)',
          fontSize: 'var(--text-h3)',
          fontWeight: 600,
          margin: 0,
        }}
      >
        Operadores por Ferramenta
      </h2>

      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Filtrar por máquina:</label>
        <select
          className="constraint-toggles__param-select"
          value={machineFilter}
          onChange={(e) => setMachineFilter(e.target.value)}
          style={{ fontSize: 12 }}
        >
          <option value="">Todas ({engine.tools.length} ferramentas)</option>
          {machineIds.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        {overrideCount > 0 && (
          <span style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}>
            {overrideCount} editado{overrideCount > 1 ? 's' : ''}
          </span>
        )}
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table className="setup-matrix">
          <thead>
            <tr>
              <th className="setup-matrix__corner">Ferramenta</th>
              <th className="setup-matrix__header">Máquina</th>
              <th className="setup-matrix__header">Operadores</th>
              <th className="setup-matrix__header">Fonte</th>
              <th className="setup-matrix__header" style={{ width: 60 }} />
            </tr>
          </thead>
          <tbody>
            {tools.map((t) => (
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
                    borderLeft: t.isOverridden ? '2px solid var(--accent)' : undefined,
                  }}
                >
                  <select
                    value={t.op}
                    onChange={(e) => setToolOverride(t.id, { op: Number(e.target.value) })}
                    style={{
                      fontSize: 12,
                      fontFamily: 'var(--font-mono)',
                      background: 'var(--bg-card)',
                      color: 'var(--text-primary)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 3,
                      padding: '2px 4px',
                    }}
                  >
                    {[1, 2, 3].map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="setup-matrix__cell" style={{ fontSize: 12 }}>
                  {t.isOverridden ? (
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
                    <span style={{ color: 'var(--text-muted)' }}>ISOP</span>
                  )}
                </td>
                <td className="setup-matrix__cell" style={{ textAlign: 'center' }}>
                  {t.isOverridden && (
                    <button
                      onClick={() => clearFieldOverride('tool', t.id, 'op')}
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
            ))}
          </tbody>
        </table>
      </div>

      <h3
        style={{
          color: 'var(--text-primary)',
          fontSize: 'var(--text-body)',
          fontWeight: 600,
          margin: '16px 0 0',
        }}
      >
        Matriz de Competências
      </h3>
      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
        {operators.length} operadores · {machineIds.length} máquinas · Click para alterar nível
      </div>
      <OperatorSkillMatrix operators={operators} machines={machineIds} />
    </div>
  );
}
