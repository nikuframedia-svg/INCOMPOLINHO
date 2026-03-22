/**
 * Risk Map — Unified risk grid page.
 * 3 dimensions: capacity (machines), stock (MRP), constraints (violations).
 * Rows = entities, Columns = planning days. Cells colored by risk level.
 * Clicking a cell opens ContextPanel with entity detail.
 */

import { useCallback, useMemo, useState } from 'react';
import type { RiskLevel, RiskRow } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { EmptyState } from '../../components/Common/EmptyState';
import { SkeletonTable } from '../../components/Common/SkeletonLoader';
import { useScheduleData } from '../../hooks/useScheduleData';
import { useUIStore } from '../../stores/useUIStore';
import { gridDensityVars } from '../../utils/gridDensity';
import './Risk.css';

type FilterKey = 'capacity' | 'stock' | 'constraints';

const RISK_BG: Record<RiskLevel, string> = {
  critical: C.rdM,
  high: C.ylS,
  medium: C.blS,
  ok: 'transparent',
};

export function Risk() {
  const { engine, loading, error } = useScheduleData();
  const openContextPanel = useUIStore((s) => s.actions.openContextPanel);
  const setFocus = useUIStore((s) => s.actions.setFocus);
  const panelOpen = useUIStore((s) => s.contextPanelOpen);

  const [filters, setFilters] = useState<Record<FilterKey, boolean>>({
    capacity: true,
    stock: true,
    constraints: true,
  });

  const toggleFilter = useCallback((key: FilterKey) => {
    setFilters((f) => ({ ...f, [key]: !f[key] }));
  }, []);

  const { riskGrid: backendRiskGrid } = useScheduleData();
  const grid = useMemo(() => {
    if (!engine || !backendRiskGrid) return null;
    return backendRiskGrid as {
      rows: RiskRow[];
      dates: string[];
      dnames: string[];
      summary: { criticalCount: number; highCount: number; mediumCount: number };
    };
  }, [engine, backendRiskGrid]);

  const filteredRows = useMemo(() => {
    if (!grid)
      return { capacity: [] as RiskRow[], stock: [] as RiskRow[], constraints: [] as RiskRow[] };
    return {
      capacity: filters.capacity ? grid.rows.filter((r) => r.entityType === 'machine') : [],
      stock: filters.stock ? grid.rows.filter((r) => r.entityType === 'tool') : [],
      constraints: filters.constraints
        ? grid.rows.filter((r) => r.entityType === 'constraint')
        : [],
    };
  }, [grid, filters]);

  const handleCellClick = useCallback(
    (row: RiskRow, dayIdx: number) => {
      if (!engine) return;
      if (row.entityType === 'machine' || row.entityType === 'constraint') {
        const machineId = row.entityType === 'constraint' ? row.label : row.id;
        openContextPanel({ type: 'machine', id: machineId });
        setFocus({ machine: machineId, day: engine.dates[dayIdx], dayIdx });
      } else if (row.entityType === 'tool') {
        openContextPanel({ type: 'tool', id: row.id });
        setFocus({ toolId: row.id, day: engine.dates[dayIdx], dayIdx });
      }
    },
    [engine, openContextPanel, setFocus],
  );

  if (loading)
    return (
      <div className="risk" data-testid="risk-page">
        <div className="risk__header">
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>Mapa de Risco</h1>
          <p className="page-desc">
            Grelha unificada: capacidade, stock e restrições por máquina e dia.
          </p>
        </div>
        <SkeletonTable rows={8} cols={9} />
      </div>
    );

  if (error || !engine || !grid)
    return (
      <div className="risk" data-testid="risk-page">
        <div className="risk__header">
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>Mapa de Risco</h1>
          <p className="page-desc">
            Grelha unificada: capacidade, stock e restrições por máquina e dia.
          </p>
        </div>
        <EmptyState
          icon="error"
          title="Sem dados de planeamento"
          description={error || 'Importe um ficheiro ISOP para visualizar o mapa de risco.'}
        />
      </div>
    );

  const totalVisible =
    filteredRows.capacity.length + filteredRows.stock.length + filteredRows.constraints.length;

  return (
    <div className={`risk${panelOpen ? ' risk--panel-open' : ''}`} data-testid="risk-page">
      <div className="risk__header">
        <div>
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>Mapa de Risco</h1>
          <p className="page-desc">
            Grelha unificada: capacidade, stock e restrições por máquina e dia.
          </p>
        </div>
        <div className="risk__summary">
          {grid.summary.criticalCount > 0 && (
            <span className="risk__badge risk__badge--critical">
              {grid.summary.criticalCount} críticos
            </span>
          )}
          {grid.summary.highCount > 0 && (
            <span className="risk__badge risk__badge--high">{grid.summary.highCount} altos</span>
          )}
          {grid.summary.mediumCount > 0 && (
            <span className="risk__badge risk__badge--medium">
              {grid.summary.mediumCount} médios
            </span>
          )}
          {grid.summary.criticalCount === 0 &&
            grid.summary.highCount === 0 &&
            grid.summary.mediumCount === 0 && (
              <span className="risk__badge risk__badge--ok">Sem riscos</span>
            )}
        </div>
      </div>

      {/* Filters */}
      <div className="risk__filters">
        <button
          className={`risk__pill${filters.capacity ? ' risk__pill--active' : ''}`}
          onClick={() => toggleFilter('capacity')}
          data-testid="risk-filter-capacity"
        >
          Capacidade ({grid.rows.filter((r) => r.entityType === 'machine').length})
        </button>
        <button
          className={`risk__pill${filters.stock ? ' risk__pill--active' : ''}`}
          onClick={() => toggleFilter('stock')}
          data-testid="risk-filter-stock"
        >
          Stock ({grid.rows.filter((r) => r.entityType === 'tool').length})
        </button>
        <button
          className={`risk__pill${filters.constraints ? ' risk__pill--active' : ''}`}
          onClick={() => toggleFilter('constraints')}
          data-testid="risk-filter-constraints"
        >
          Restrições ({grid.rows.filter((r) => r.entityType === 'constraint').length})
        </button>
      </div>

      {totalVisible === 0 ? (
        <div style={{ padding: 24, fontSize: 12, color: C.t3, textAlign: 'center' }}>
          Nenhuma dimensão seleccionada. Active pelo menos um filtro.
        </div>
      ) : (
        <div
          className="risk__grid"
          style={
            { '--n-days': engine.nDays, ...gridDensityVars(engine.nDays) } as React.CSSProperties
          }
        >
          {/* Day headers */}
          <div className="risk__grid-header">
            <div className="risk__label-col" />
            {grid.dnames.map((dn, i) => (
              <div key={i} className="risk__day-header" title={grid.dates[i]}>
                {dn}
                <br />
                <span style={{ color: C.t3 }}>
                  {engine.nDays > 30 ? grid.dates[i]?.slice(0, 2) : grid.dates[i]}
                </span>
              </div>
            ))}
          </div>

          {/* Capacity group */}
          {filteredRows.capacity.length > 0 && (
            <RiskGroup
              label="MÁQUINAS"
              rows={filteredRows.capacity}
              nDays={engine.nDays}
              onCellClick={handleCellClick}
            />
          )}

          {/* Stock group */}
          {filteredRows.stock.length > 0 && (
            <RiskGroup
              label="STOCK"
              rows={filteredRows.stock}
              nDays={engine.nDays}
              onCellClick={handleCellClick}
            />
          )}

          {/* Constraints group */}
          {filteredRows.constraints.length > 0 && (
            <RiskGroup
              label="RESTRIÇÕES"
              rows={filteredRows.constraints}
              nDays={engine.nDays}
              onCellClick={handleCellClick}
            />
          )}
        </div>
      )}

      {/* Legend */}
      <div className="risk__legend">
        <span className="risk__legend-item">
          <span className="risk__legend-dot" style={{ background: C.rdM }} />
          Crítico
        </span>
        <span className="risk__legend-item">
          <span className="risk__legend-dot" style={{ background: C.ylS }} />
          Alto
        </span>
        <span className="risk__legend-item">
          <span className="risk__legend-dot" style={{ background: C.blS }} />
          Médio
        </span>
        <span className="risk__legend-item">
          <span className="risk__legend-dot" style={{ background: 'var(--bg-raised)' }} />
          OK
        </span>
      </div>
    </div>
  );
}

// ── RiskGroup sub-component ─────────────────────────────────

function RiskGroup({
  label,
  rows,
  nDays,
  onCellClick,
}: {
  label: string;
  rows: RiskRow[];
  nDays: number;
  onCellClick: (row: RiskRow, dayIdx: number) => void;
}) {
  return (
    <>
      <div className="risk__group-header">{label}</div>
      {rows.map((row) => (
        <div key={row.id} className="risk__row">
          <div className="risk__row-label">
            <span
              style={{
                fontFamily: "'JetBrains Mono',monospace",
                fontSize: 12,
                fontWeight: 600,
                color: 'var(--text-primary)',
              }}
            >
              {row.label}
            </span>
            <span className={`risk__row-dot risk__row-dot--${row.worstLevel}`} />
          </div>
          {Array.from({ length: nDays }, (_, di) => {
            const cell = row.cells[di];
            if (!cell) return <div key={di} className="risk__cell" />;
            return (
              <div
                key={di}
                className={`risk__cell risk__cell--${cell.level}`}
                style={{ background: RISK_BG[cell.level] }}
                title={cell.tooltip}
                onClick={() => onCellClick(row, di)}
                data-testid={`risk-cell-${row.id}-${di}`}
              />
            );
          })}
        </div>
      ))}
    </>
  );
}
