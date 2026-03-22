import { C } from '@/theme/color-bridge';
import { Collapsible } from '../../components/Common/Collapsible';
import { Term } from '../../components/Common/Tooltip';

interface OpsByDayEntry {
  pg1: number;
  pg2: number;
  total: number;
}

interface ManningOverride {
  PG1: number[];
  PG2: number[];
}

interface FabricaOperatorTableProps {
  wdi: number[];
  dnames: string[];
  dates: string[];
  opsByDay: OpsByDayEntry[];
  mo: ManningOverride | undefined;
}

export function FabricaOperatorTable({
  wdi,
  dnames,
  dates,
  opsByDay,
  mo,
}: FabricaOperatorTableProps) {
  return (
    <div className="fab__section-card">
      <Collapsible title="Operadores por Dia" defaultOpen={true}>
        <table className="fab__op-table">
          <thead>
            <tr>
              <th>Dia</th>
              <th>Data</th>
              <th style={{ textAlign: 'right' }}>
                <Term code="PG1" />
              </th>
              <th style={{ textAlign: 'right' }}>
                Cap <Term code="PG1" />
              </th>
              <th style={{ textAlign: 'right' }}>
                <Term code="PG2" />
              </th>
              <th style={{ textAlign: 'right' }}>
                Cap <Term code="PG2" />
              </th>
              <th style={{ textAlign: 'right' }}>Total</th>
              <th style={{ textAlign: 'right' }}>Cap</th>
              <th style={{ textAlign: 'center' }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {wdi.map((di) => {
              const od = opsByDay[di];
              if (!od) return null;
              const cp1 = mo?.PG1[di] ?? 4;
              const cp2 = mo?.PG2[di] ?? 4;
              const totalCap = cp1 + cp2;
              const over = od.total > totalCap;
              return (
                <tr key={di} style={{ color: over ? C.rd : undefined }}>
                  <td style={{ fontWeight: 600 }}>{dnames[di]}</td>
                  <td>{dates[di]}</td>
                  <td style={{ textAlign: 'right' }}>{od.pg1}</td>
                  <td style={{ textAlign: 'right', color: C.t3 }}>{cp1.toFixed(1)}</td>
                  <td style={{ textAlign: 'right' }}>{od.pg2}</td>
                  <td style={{ textAlign: 'right', color: C.t3 }}>{cp2.toFixed(1)}</td>
                  <td style={{ textAlign: 'right', fontWeight: 600 }}>{od.total}</td>
                  <td style={{ textAlign: 'right', color: C.t3 }}>{totalCap.toFixed(1)}</td>
                  <td style={{ textAlign: 'center' }}>
                    {over ? (
                      <span
                        style={{
                          fontSize: 12,
                          fontWeight: 600,
                          color: C.rd,
                          background: C.rdS,
                          padding: '1px 4px',
                          borderRadius: 3,
                        }}
                      >
                        OVER
                      </span>
                    ) : (
                      <span style={{ fontSize: 12, color: C.ac }}>OK</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Collapsible>
    </div>
  );
}
