import { Collapsible } from '../../components/Common/Collapsible';
import { Term } from '../../components/Common/Tooltip';
import { C, TC } from '../../lib/engine';

interface OpDayEntry {
  pg1: number;
  pg2: number;
  total: number;
}

interface BacklogOp {
  id: string;
  t: string;
  sku: string;
  nm: string;
  m: string;
  atr: number;
}

interface EngineRef {
  dnames: string[];
  dates: string[];
  tools: Array<{ id: string }>;
  mo?: { PG1: number[]; PG2: number[] };
}

interface DashboardBottomRowProps {
  wdi: number[];
  opsByDay: OpDayEntry[];
  backlogOps: BacklogOp[];
  engine: EngineRef;
  metrics: {
    overflows: number;
    setupCount: number;
    setupMin: number;
    capVar: number;
    setupByShift?: Record<string, number>;
  };
}

export function DashboardBottomRow({
  wdi,
  opsByDay,
  backlogOps,
  engine,
  metrics,
}: DashboardBottomRowProps) {
  return (
    <>
      <div className="dash__bottom-row">
        <div className="dash__ops-card">
          <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 6 }}>
            Operadores por Dia
          </div>
          {wdi.map((i) => {
            const od = opsByDay[i];
            if (!od) return null;
            const capPG1 = engine.mo?.PG1[i] ?? 4;
            const capPG2 = engine.mo?.PG2[i] ?? 4;
            const totalCap = capPG1 + capPG2;
            const overCap = od.total > totalCap;
            return (
              <div
                key={i}
                style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}
              >
                <span
                  style={{
                    width: 28,
                    fontSize: 12,
                    fontFamily: "'JetBrains Mono',monospace",
                    color: C.t3,
                    textAlign: 'right',
                  }}
                >
                  {engine.dnames[i]}
                </span>
                <div
                  style={{
                    flex: 1,
                    height: 14,
                    background: C.s1,
                    borderRadius: 3,
                    display: 'flex',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      width: `${Math.min((od.pg1 / Math.max(totalCap, 1)) * 100, 100)}%`,
                      background: C.ac,
                      opacity: 0.6,
                    }}
                  />
                  <div
                    style={{
                      width: `${Math.min((od.pg2 / Math.max(totalCap, 1)) * 100, 100)}%`,
                      background: C.bl,
                      opacity: 0.6,
                    }}
                  />
                </div>
                <span
                  style={{
                    width: 40,
                    fontSize: 12,
                    fontFamily: "'JetBrains Mono',monospace",
                    color: overCap ? C.rd : C.t2,
                    textAlign: 'right',
                  }}
                >
                  {od.total}/{totalCap}
                </span>
              </div>
            );
          })}
          <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
            <span style={{ fontSize: 12, color: C.ac }}>
              ■ <Term code="PG1" label="PG1" />
            </span>
            <span style={{ fontSize: 12, color: C.bl }}>
              ■ <Term code="PG2" label="PG2" />
            </span>
          </div>
        </div>

        <div className="dash__backlogs-card">
          <Collapsible
            title="Top Atrasos (Backlog)"
            defaultOpen={backlogOps.length > 0}
            badge={backlogOps.length > 0 ? `${backlogOps.length}` : undefined}
          >
            {backlogOps.length === 0 ? (
              <div style={{ fontSize: 12, color: C.ac, padding: 8 }}>
                Sem atrasos pendentes — todas as encomendas dentro do prazo.
              </div>
            ) : (
              <table className="dash__table">
                <thead>
                  <tr>
                    <th>Ferramenta</th>
                    <th>SKU</th>
                    <th>Nome</th>
                    <th style={{ textAlign: 'right' }}>
                      <Term code="Backlog" label="Backlog" />
                    </th>
                    <th>Máquina</th>
                  </tr>
                </thead>
                <tbody>
                  {backlogOps.map((op) => {
                    const ti = engine.tools.findIndex((t) => t.id === op.t);
                    return (
                      <tr key={op.id}>
                        <td>
                          <span
                            style={{
                              color: TC[ti >= 0 ? ti % TC.length : 0],
                              fontFamily: "'JetBrains Mono',monospace",
                            }}
                          >
                            {op.t}
                          </span>
                        </td>
                        <td style={{ fontFamily: "'JetBrains Mono',monospace" }}>{op.sku}</td>
                        <td
                          style={{
                            maxWidth: 120,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {op.nm}
                        </td>
                        <td style={{ textAlign: 'right', fontWeight: 600, color: C.yl }}>
                          {op.atr.toLocaleString()}
                        </td>
                        <td style={{ fontFamily: "'JetBrains Mono',monospace" }}>{op.m}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </Collapsible>
        </div>
      </div>

      {/* Overflow & Capacity summary */}
      {(metrics.overflows > 0 || metrics.setupCount > 0) && (
        <div className="dash__bottom-row" style={{ marginTop: 16 }}>
          <div className="dash__ops-card">
            <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
              Setup & Capacidade
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div>
                <div
                  style={{
                    fontSize: 12,
                    color: C.t3,
                    textTransform: 'uppercase',
                    letterSpacing: '.04em',
                    marginBottom: 2,
                  }}
                >
                  Total Setups
                </div>
                <div
                  style={{
                    fontSize: 20,
                    fontWeight: 600,
                    color: C.t1,
                    fontFamily: "'JetBrains Mono',monospace",
                  }}
                >
                  {metrics.setupCount}
                </div>
                <div style={{ fontSize: 12, color: C.t3 }}>
                  {Math.round(metrics.setupMin)} min total
                </div>
              </div>
              <div>
                <div
                  style={{
                    fontSize: 12,
                    color: C.t3,
                    textTransform: 'uppercase',
                    letterSpacing: '.04em',
                    marginBottom: 2,
                  }}
                >
                  Overflows
                </div>
                <div
                  style={{
                    fontSize: 20,
                    fontWeight: 600,
                    color: metrics.overflows > 0 ? C.yl : C.t1,
                    fontFamily: "'JetBrains Mono',monospace",
                  }}
                >
                  {metrics.overflows}
                </div>
                <div style={{ fontSize: 12, color: C.t3 }}>
                  Cap. var: {(metrics.capVar * 100).toFixed(0)}%
                </div>
              </div>
            </div>
          </div>
          <div className="dash__ops-card">
            <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
              Setups por Turno
            </div>
            <div style={{ display: 'flex', gap: 16 }}>
              {(['X', 'Y', 'Z'] as const).map((sh) => {
                const val = metrics.setupByShift?.[sh] ?? 0;
                if (sh === 'Z' && val === 0) return null;
                return (
                  <div key={sh}>
                    <div
                      style={{
                        fontSize: 12,
                        color: C.t3,
                        textTransform: 'uppercase',
                        marginBottom: 2,
                      }}
                    >
                      Turno {sh}
                    </div>
                    <div
                      style={{
                        fontSize: 18,
                        fontWeight: 600,
                        color: C.t1,
                        fontFamily: "'JetBrains Mono',monospace",
                      }}
                    >
                      {val}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
