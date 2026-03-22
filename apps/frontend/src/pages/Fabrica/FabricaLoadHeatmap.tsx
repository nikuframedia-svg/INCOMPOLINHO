import React from 'react';
import type { DayLoad } from '@/domain/types/scheduling';
import { DAY_CAP } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { HeatmapLegend } from '../../components/Common/HeatmapLegend';
import { gridDensityVars, showDetailedCells } from '../../utils/gridDensity';
import { utilColor } from '../../utils/utilColor';

interface Machine {
  id: string;
  area: string;
}

interface FabricaLoadHeatmapProps {
  machines: Machine[];
  cap: Record<string, DayLoad[]>;
  wdi: number[];
  dnames: string[];
  dates: string[];
  dailyTotals: number[];
  factoryCap: number;
  onMachineClick: (machineId: string) => void;
  onCellClick: (machineId: string, dayIdx: number) => void;
}

export function FabricaLoadHeatmap({
  machines,
  cap,
  wdi,
  dnames,
  dates,
  dailyTotals,
  factoryCap,
  onMachineClick,
  onCellClick,
}: FabricaLoadHeatmapProps) {
  return (
    <div className="fab__section-card">
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
        Mapa de Cargas
      </div>
      <HeatmapLegend />
      <div
        className="fab__heatmap-full"
        style={
          {
            gridTemplateColumns: `72px repeat(${wdi.length}, 1fr)`,
            '--n-days': wdi.length,
            ...gridDensityVars(wdi.length),
          } as React.CSSProperties
        }
      >
        <div className="fab__hf-corner" />
        {wdi.map((i, pos) => {
          const isWeekBorder = pos > 0 && dnames[i]?.toLowerCase() === 'seg';
          return (
            <div
              key={i}
              className={`fab__hf-header${isWeekBorder ? ' fab__hf-header--week-start' : ''}`}
            >
              <span style={{ fontWeight: 600 }}>{dnames[i]}</span>
              <span style={{ color: C.t3 }}>
                {wdi.length > 30 ? dates[i]?.slice(0, 2) : dates[i]}
              </span>
            </div>
          );
        })}
        {machines.map((m) => {
          const mc = cap[m.id] || [];
          const detailed = showDetailedCells(wdi.length);
          return (
            <React.Fragment key={m.id}>
              <div
                className="fab__hf-label fab__hf-label--clickable"
                onClick={() => onMachineClick(m.id)}
                data-testid={`fab-hm-label-${m.id}`}
              >
                <span
                  style={{
                    fontFamily: "'JetBrains Mono',monospace",
                    fontSize: 12,
                    fontWeight: 600,
                    color: C.t1,
                  }}
                >
                  {m.id}
                </span>
                <span style={{ fontSize: 12, color: C.t3 }}>{m.area}</span>
              </div>
              {wdi.map((i, pos) => {
                const d: DayLoad = mc[i] || { prod: 0, setup: 0, ops: 0, pcs: 0, blk: 0 };
                const total = d.prod + d.setup;
                const u = total / DAY_CAP;
                const isWeekBorder = pos > 0 && dnames[i]?.toLowerCase() === 'seg';
                return (
                  <div
                    key={i}
                    className={`fab__hf-cell fab__hf-cell--clickable${isWeekBorder ? ' fab__hf-cell--week-start' : ''}`}
                    style={{
                      background: utilColor(u),
                      ...(d.blk > 0 ? { borderLeft: '2px solid var(--semantic-red)' } : {}),
                    }}
                    onClick={() => onCellClick(m.id, i)}
                    title={`${m.id} ${dnames[i]} ${dates[i]}: ${Math.round(total)}min (${(u * 100).toFixed(0)}%) — ${d.pcs} pcs${d.blk > 0 ? `, ${d.blk} bloqueada(s)` : ''}`}
                    data-testid={`fab-hm-cell-${m.id}-${i}`}
                  >
                    <span className="fab__hf-val">
                      {detailed ? Math.round(total) : `${(u * 100).toFixed(0)}%`}
                    </span>
                    {detailed && (
                      <span className="fab__hf-sub">
                        {(u * 100).toFixed(0)}% · {d.pcs} pcs
                      </span>
                    )}
                    {detailed && d.setup > 0 && (
                      <span style={{ fontSize: 12, color: C.pp }}>{Math.round(d.setup)}m</span>
                    )}
                  </div>
                );
              })}
            </React.Fragment>
          );
        })}
        {/* Total row */}
        <div className="fab__hf-label" style={{ borderTop: `1px solid ${C.bd}` }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: C.t2 }}>TOTAL</span>
        </div>
        {dailyTotals.map((t, idx) => (
          <div key={idx} className="fab__hf-cell" style={{ borderTop: `1px solid ${C.bd}` }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: C.t1 }}>{Math.round(t)}</span>
            <span style={{ fontSize: 12, color: C.t3 }}>
              {((t / factoryCap) * 100).toFixed(0)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
