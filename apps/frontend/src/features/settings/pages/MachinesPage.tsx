/**
 * MachinesPage — Machine configuration with persistent overrides.
 * Route: /settings/machines
 *
 * Reads machines from engine data. Edits persist via useMasterDataStore.
 */

import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState } from '@/components/Common/EmptyState';
import { SkeletonTable } from '@/components/Common/SkeletonLoader';
import { useScheduleData } from '@/hooks/useScheduleData';
import { useMasterDataStore } from '@/stores/useMasterDataStore';

export function MachinesPage() {
  const { engine, loading, error } = useScheduleData();
  const machineOverrides = useMasterDataStore((s) => s.machineOverrides);
  const setMachineOverride = useMasterDataStore((s) => s.setMachineOverride);
  const clearOverride = useMasterDataStore((s) => s.clearOverride);

  const machines = useMemo(() => {
    if (!engine) return [];
    return engine.machines.map((m) => {
      const ov = machineOverrides[m.id];
      const toolCount = engine.tools.filter((t) => t.m === m.id).length;
      return {
        id: m.id,
        area: ov?.area ?? m.area,
        status: ov?.status ?? 'running',
        toolCount,
        isOverridden: ov !== undefined,
        overriddenFields: {
          area: ov?.area !== undefined,
          status: ov?.status !== undefined,
        },
      };
    });
  }, [engine, machineOverrides]);

  if (loading)
    return (
      <div style={{ padding: 32 }}>
        <SkeletonTable rows={5} cols={5} />
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

  const overrideCount = machines.filter((m) => m.isOverridden).length;

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
        Máquinas
      </h2>

      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
        {machines.length} máquinas · {engine.tools.length} ferramentas
        {overrideCount > 0 && (
          <span style={{ marginLeft: 8, color: 'var(--accent)', fontWeight: 600 }}>
            · {overrideCount} editada{overrideCount > 1 ? 's' : ''}
          </span>
        )}
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table className="setup-matrix">
          <thead>
            <tr>
              <th className="setup-matrix__corner">Máquina</th>
              <th className="setup-matrix__header">Área</th>
              <th className="setup-matrix__header">Estado</th>
              <th className="setup-matrix__header">Ferramentas</th>
              <th className="setup-matrix__header">Fonte</th>
              <th className="setup-matrix__header" style={{ width: 60 }} />
            </tr>
          </thead>
          <tbody>
            {machines.map((m) => (
              <tr key={m.id}>
                <td className="setup-matrix__row-label">
                  <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{m.id}</span>
                </td>
                <td className="setup-matrix__cell" style={{ fontSize: 12 }}>
                  <select
                    value={m.area}
                    onChange={(e) => setMachineOverride(m.id, { area: e.target.value })}
                    style={{
                      fontSize: 12,
                      fontFamily: 'var(--font-mono)',
                      background: 'var(--bg-card)',
                      color: m.area === 'PG1' ? 'var(--accent)' : 'var(--semantic-amber)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 3,
                      padding: '2px 4px',
                      borderLeft: m.overriddenFields.area
                        ? '2px solid var(--accent)'
                        : undefined,
                    }}
                  >
                    <option value="PG1">PG1</option>
                    <option value="PG2">PG2</option>
                  </select>
                </td>
                <td className="setup-matrix__cell" style={{ fontSize: 12 }}>
                  <select
                    value={m.status}
                    onChange={(e) =>
                      setMachineOverride(m.id, {
                        status: e.target.value as 'running' | 'down',
                      })
                    }
                    style={{
                      fontSize: 12,
                      background: 'var(--bg-card)',
                      color:
                        m.status === 'running' ? 'var(--accent)' : 'var(--semantic-red)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 3,
                      padding: '2px 4px',
                      borderLeft: m.overriddenFields.status
                        ? '2px solid var(--accent)'
                        : undefined,
                    }}
                  >
                    <option value="running">Running</option>
                    <option value="down">Down</option>
                  </select>
                </td>
                <td
                  className="setup-matrix__cell"
                  style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}
                >
                  {m.toolCount}
                </td>
                <td className="setup-matrix__cell" style={{ fontSize: 12 }}>
                  {m.isOverridden ? (
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
                  {m.isOverridden && (
                    <button
                      onClick={() => clearOverride('machine', m.id)}
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
    </div>
  );
}
