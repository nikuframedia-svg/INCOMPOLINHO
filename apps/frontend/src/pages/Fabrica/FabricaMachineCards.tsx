import { C } from '../../lib/engine';

/** Aggregate daily values into weekly averages (5 working days per week) */
function aggregateWeekly(vals: number[]): number[] {
  const weeks: number[] = [];
  for (let i = 0; i < vals.length; i += 5) {
    const chunk = vals.slice(i, i + 5).filter((v) => v > 0);
    weeks.push(chunk.length > 0 ? chunk.reduce((a, b) => a + b, 0) / chunk.length : 0);
  }
  return weeks;
}

interface MachineStatProps {
  id: string;
  area: string;
  totalPcs: number;
  totalOps: number;
  totalSetupMin: number;
  setupCount: number;
  totalBlk: number;
  utils: number[];
  setupUtils: number[];
  avgUtil: number;
  toolCount: number;
}

interface FabricaMachineCardsProps {
  machineStats: MachineStatProps[];
  focusMachine: string | undefined;
  onMachineClick: (machineId: string) => void;
}

export function FabricaMachineCards({
  machineStats,
  focusMachine,
  onMachineClick,
}: FabricaMachineCardsProps) {
  return (
    <div className="fab__machines">
      {machineStats.map((m) => {
        const borderColor = m.avgUtil > 1.0 ? C.rd : m.avgUtil > 0.85 ? C.yl : C.ac;
        const isFocused = focusMachine === m.id;
        return (
          <div
            key={m.id}
            className={`fab__mcard fab__mcard--clickable${isFocused ? ' fab__mcard--focused' : ''}`}
            style={{ borderLeft: `3px solid ${borderColor}` }}
            onClick={() => onMachineClick(m.id)}
            data-testid={`fab-mcard-${m.id}`}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: 6,
              }}
            >
              <span
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  fontFamily: "'JetBrains Mono',monospace",
                  color: C.t1,
                }}
              >
                {m.id}
              </span>
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  padding: '1px 5px',
                  borderRadius: 3,
                  background: m.area === 'PG1' ? C.acS : C.blS,
                  color: m.area === 'PG1' ? C.ac : C.bl,
                }}
              >
                {m.area}
              </span>
            </div>
            {/* Dual sparkline — prod (green) + setup (purple) */}
            <div style={{ display: 'flex', gap: 2, marginBottom: 6, height: 24 }}>
              {(m.utils.length > 20 ? aggregateWeekly(m.utils) : m.utils).map((u, i) => {
                const su =
                  m.utils.length > 20
                    ? (aggregateWeekly(m.setupUtils)[i] ?? 0)
                    : (m.setupUtils[i] ?? 0);
                const prodU = Math.max(u - su, 0);
                return (
                  <div
                    key={i}
                    style={{
                      flex: 1,
                      display: 'flex',
                      flexDirection: 'column',
                      justifyContent: 'flex-end',
                    }}
                  >
                    {su > 0 && (
                      <div
                        style={{
                          height: `${Math.max(su * 100, 1)}%`,
                          background: C.pp + '88',
                          borderRadius: '1px 1px 0 0',
                          minHeight: 1,
                        }}
                      />
                    )}
                    <div
                      style={{
                        height: `${Math.max(prodU * 100, 2)}%`,
                        background: u > 0.85 ? C.yl : u > 0 ? C.ac : C.s2,
                        borderRadius: su > 0 ? '0 0 1px 1px' : 1,
                        minHeight: 2,
                      }}
                    />
                  </div>
                );
              })}
            </div>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                fontSize: 12,
                color: C.t2,
              }}
            >
              <span>
                Util.{' '}
                <span style={{ fontWeight: 600, color: m.avgUtil > 0.85 ? C.yl : C.t1 }}>
                  {(m.avgUtil * 100).toFixed(0)}%
                </span>
              </span>
              <span>{m.totalPcs.toLocaleString()} pcs</span>
            </div>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                fontSize: 12,
                color: C.t3,
                marginTop: 1,
              }}
            >
              <span>
                {m.totalOps} ops · {m.toolCount} tools
              </span>
              <span style={{ color: C.pp }}>
                {m.setupCount} setups · {Math.round(m.totalSetupMin)}m
              </span>
            </div>
            {m.totalBlk > 0 && (
              <div style={{ fontSize: 12, fontWeight: 600, color: C.rd, marginTop: 2 }}>
                {m.totalBlk} bloqueada(s)
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
