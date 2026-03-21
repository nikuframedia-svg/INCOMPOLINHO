/**
 * CapacityImpactPanel — Per-machine capacity heatmap for affected/down machines.
 */
import type { Block, DayLoad, EngineData } from '../../../../lib/engine';
import { C, DAY_CAP } from '../../../../lib/engine';
import { gridDensityVars } from '../../../../utils/gridDensity';
import { Card, dot, Tag } from '../atoms';

export interface CapacityImpactPanelProps {
  data: EngineData;
  blocks: Block[];
  cap: Record<string, DayLoad[]>;
  mSt: Record<string, string>;
  moves: import('../../../../lib/engine').MoveAction[];
}

export function CapacityImpactPanel({ data, blocks, cap, mSt, moves }: CapacityImpactPanelProps) {
  const { machines, dates, dnames } = data;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t1 }}>Impacto Capacidade</div>
      {machines
        .filter((m) => {
          const d = mSt[m.id] === 'down';
          const h = blocks.some(
            (b) => (b.moved && b.machineId === m.id) || (b.moved && b.origM === m.id),
          );
          return d || h;
        })
        .slice(0, 6)
        .map((mc) => {
          const isD = mSt[mc.id] === 'down';
          const mc_c = cap[mc.id];
          return (
            <Card key={mc.id} style={{ padding: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 6 }}>
                <span style={dot(isD ? C.rd : C.ac, isD)} />
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 600,
                    color: isD ? C.rd : C.t1,
                    fontFamily: 'monospace',
                  }}
                >
                  {mc.id}
                </span>
                <Tag color={isD ? C.rd : C.ac}>{isD ? 'OFF' : 'ON'}</Tag>
              </div>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: `repeat(${data.nDays},1fr)`,
                  gap: 2,
                  ...gridDensityVars(data.nDays),
                }}
              >
                {dates.map((_, di) => {
                  const dc = mc_c?.[di] || { prod: 0, setup: 0 };
                  const tot = dc.prod + dc.setup;
                  const u = tot / DAY_CAP;
                  return (
                    <div key={di} style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: 12, color: C.t4 }}>{dnames[di]}</div>
                      <div
                        style={{
                          height: 32,
                          display: 'flex',
                          flexDirection: 'column',
                          justifyContent: 'flex-end',
                          background: C.bg,
                          borderRadius: 3,
                          overflow: 'hidden',
                        }}
                      >
                        {dc.setup > 0 && (
                          <div
                            style={{
                              height: `${Math.min((dc.setup / DAY_CAP) * 100, 30)}%`,
                              background: C.pp + '66',
                              minHeight: 1,
                            }}
                          />
                        )}
                        {dc.prod > 0 && (
                          <div
                            style={{
                              height: `${Math.min((dc.prod / DAY_CAP) * 100, 100)}%`,
                              background: isD ? C.rd + '44' : u > 1 ? C.rd + '66' : C.ac + '66',
                              minHeight: 1,
                            }}
                          />
                        )}
                      </div>
                      {tot > 0 && (
                        <div style={{ fontSize: 12, color: u > 1 ? C.rd : C.ac, fontWeight: 600 }}>
                          {(u * 100).toFixed(0)}%
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </Card>
          );
        })}
      {Object.values(mSt).every((s) => s !== 'down') && moves.length === 0 && (
        <Card style={{ padding: 24, textAlign: 'center' }}>
          <div style={{ fontSize: 12, color: C.t4 }}>Marca DOWN para ver impacto</div>
        </Card>
      )}
    </div>
  );
}
