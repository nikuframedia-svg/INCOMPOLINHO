/**
 * SetupMatrixPage — Setup time editor per tool, persisted via useMasterDataStore.
 * Route: /settings/setup-matrix
 *
 * Reads setup times from engine (ISOP+fixture merged).
 * Edits write to useMasterDataStore.toolOverrides → schedule recomputes.
 */

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState } from '@/components/Common/EmptyState';
import { SkeletonTable } from '@/components/Common/SkeletonLoader';
import { useScheduleData } from '@/hooks/useScheduleData';
import { useMasterDataStore } from '@/stores/useMasterDataStore';
import { SetupTable } from '../components/SetupTable';

export function SetupMatrixPage() {
  const { engine, loading, error } = useScheduleData();
  const [machineFilter, setMachineFilter] = useState('');
  const toolOverrides = useMasterDataStore((s) => s.toolOverrides);
  const setToolOverride = useMasterDataStore((s) => s.setToolOverride);
  const clearFieldOverride = useMasterDataStore((s) => s.clearFieldOverride);

  const machines = useMemo(() => (engine ? engine.machines.map((m) => m.id) : []), [engine]);
  const filteredTools = useMemo(() => {
    if (!engine) return [];
    if (!machineFilter) return engine.tools;
    return engine.tools.filter((t) => t.m === machineFilter);
  }, [engine, machineFilter]);

  const overrideCount = useMemo(
    () =>
      filteredTools.filter(
        (t) => toolOverrides[t.id]?.s !== undefined || toolOverrides[t.id]?.pH !== undefined,
      ).length,
    [filteredTools, toolOverrides],
  );

  if (loading)
    return (
      <div style={{ padding: 32 }}>
        <SkeletonTable rows={8} cols={4} />
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
        Tempos de Setup
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
          {machines.map((m) => (
            <option key={m} value={m}>
              {m} ({engine.tools.filter((t) => t.m === m).length} ferramentas)
            </option>
          ))}
        </select>
        {overrideCount > 0 && (
          <span style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}>
            {overrideCount} editado{overrideCount > 1 ? 's' : ''}
          </span>
        )}
      </div>

      <SetupTable
        tools={filteredTools}
        toolOverrides={toolOverrides}
        onSetOverride={(id, minutes) => setToolOverride(id, { s: minutes / 60 })}
        onSetRateOverride={(id, pH) => setToolOverride(id, { pH })}
        onClearOverride={(id) => clearFieldOverride('tool', id, 's')}
        onClearRateOverride={(id) => clearFieldOverride('tool', id, 'pH')}
      />
    </div>
  );
}
