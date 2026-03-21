/**
 * WorkflowTable — Editable governance table for L5 workflows & approvals.
 */

import './WorkflowTable.css';

export type GovernanceLevel = 0 | 1 | 2 | 3 | 4 | 5;

export interface WorkflowRow {
  id: string;
  action: string;
  level: GovernanceLevel;
  approval: boolean;
  contrafactual: boolean;
  ledger: boolean;
  approver: string;
}

const LEVEL_LABELS: Record<GovernanceLevel, string> = {
  0: 'L0 — Logging',
  1: 'L1 — Validacao',
  2: 'L2 — Preview',
  3: 'L3 — Contrafactual',
  4: 'L4 — Aprovacao',
  5: 'L5 — Multi-aprovacao',
};

function levelClass(level: GovernanceLevel): string {
  if (level <= 1) return 'workflow-table__level workflow-table__level--low';
  if (level <= 3) return 'workflow-table__level workflow-table__level--mid';
  return 'workflow-table__level workflow-table__level--high';
}

interface WorkflowTableProps {
  rows: WorkflowRow[];
  onChange: (rows: WorkflowRow[]) => void;
}

export function WorkflowTable({ rows, onChange }: WorkflowTableProps) {
  const updateRow = (id: string, patch: Partial<WorkflowRow>) => {
    onChange(rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  };

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="workflow-table">
        <thead>
          <tr>
            <th>Accao</th>
            <th>Governance</th>
            <th>Aprovacao</th>
            <th>Contrafactual</th>
            <th>Ledger</th>
            <th>Aprovador</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td style={{ fontWeight: 500 }}>{row.action}</td>
              <td>
                <select
                  className="constraint-toggles__param-select"
                  value={row.level}
                  onChange={(e) =>
                    updateRow(row.id, { level: Number(e.target.value) as GovernanceLevel })
                  }
                  style={{ fontSize: 12 }}
                >
                  {([0, 1, 2, 3, 4, 5] as GovernanceLevel[]).map((lv) => (
                    <option key={lv} value={lv}>
                      {LEVEL_LABELS[lv]}
                    </option>
                  ))}
                </select>
                <span className={levelClass(row.level)} style={{ marginLeft: 8 }}>
                  L{row.level}
                </span>
              </td>
              <td>
                <label className="constraint-toggles__switch">
                  <input
                    type="checkbox"
                    checked={row.approval}
                    onChange={(e) => updateRow(row.id, { approval: e.target.checked })}
                  />
                  <span className="constraint-toggles__slider" />
                </label>
              </td>
              <td>
                <label className="constraint-toggles__switch">
                  <input
                    type="checkbox"
                    checked={row.contrafactual}
                    onChange={(e) => updateRow(row.id, { contrafactual: e.target.checked })}
                  />
                  <span className="constraint-toggles__slider" />
                </label>
              </td>
              <td>
                <label className="constraint-toggles__switch">
                  <input
                    type="checkbox"
                    checked={row.ledger}
                    onChange={(e) => updateRow(row.id, { ledger: e.target.checked })}
                  />
                  <span className="constraint-toggles__slider" />
                </label>
              </td>
              <td>
                <input
                  type="text"
                  value={row.approver}
                  onChange={(e) => updateRow(row.id, { approver: e.target.value })}
                  placeholder="—"
                  style={{
                    background: 'var(--bg-raised)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 4,
                    color: 'var(--text-primary)',
                    padding: '4px 8px',
                    fontSize: 12,
                    width: '100%',
                    minWidth: 100,
                  }}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
