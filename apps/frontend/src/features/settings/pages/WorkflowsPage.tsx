/**
 * WorkflowsPage — L5: Governance workflows & approvals.
 * Route: /settings/workflows
 */

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState } from '@/components/Common/EmptyState';
import { SkeletonTable } from '@/components/Common/SkeletonLoader';
import { useScheduleData } from '@/hooks/useScheduleData';
import type { GovernanceLevel, WorkflowRow } from '../components/WorkflowTable';
import { WorkflowTable } from '../components/WorkflowTable';

const DEFAULT_WORKFLOWS: WorkflowRow[] = [
  {
    id: 'w1',
    action: 'Alterar plano frozen',
    level: 4,
    approval: true,
    contrafactual: true,
    ledger: true,
    approver: 'Chefe Produção',
  },
  {
    id: 'w2',
    action: 'Activar turno noite',
    level: 4,
    approval: true,
    contrafactual: true,
    ledger: true,
    approver: 'Director Industrial',
  },
  {
    id: 'w3',
    action: 'Override prioridade',
    level: 3,
    approval: true,
    contrafactual: true,
    ledger: true,
    approver: 'Dir. Comercial',
  },
  {
    id: 'w4',
    action: 'Mover op zona slushy',
    level: 3,
    approval: false,
    contrafactual: true,
    ledger: true,
    approver: '',
  },
  {
    id: 'w5',
    action: 'Mover op zona liquid',
    level: 2,
    approval: false,
    contrafactual: false,
    ledger: true,
    approver: '',
  },
  {
    id: 'w6',
    action: 'Ver dados',
    level: 0,
    approval: false,
    contrafactual: false,
    ledger: false,
    approver: '',
  },
];

/** 6 decision categories (inline, not imported from scheduling) */
const DECISION_ACTIONS = [
  'Alterar plano frozen',
  'Activar turno noite',
  'Override prioridade',
  'Mover op zona slushy',
  'Mover op zona liquid',
  'Split lote',
  'Trocar máquina',
  'Adiar encomenda',
  'Antecipar encomenda',
  'Resequenciar fila',
];

function countApprovalActions(rows: WorkflowRow[]): number {
  return rows.filter((r) => r.approval).length;
}

function countByLevel(rows: WorkflowRow[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const r of rows) {
    const key = `L${r.level}`;
    counts[key] = (counts[key] ?? 0) + 1;
  }
  return counts;
}

export function WorkflowsPage() {
  const { engine, loading, error } = useScheduleData();
  const [rows, setRows] = useState<WorkflowRow[]>(DEFAULT_WORKFLOWS);
  const [showAddRow, setShowAddRow] = useState(false);
  const [newAction, setNewAction] = useState('');

  const approvalCount = useMemo(() => countApprovalActions(rows), [rows]);
  const levelBreakdown = useMemo(() => countByLevel(rows), [rows]);

  const addRow = () => {
    if (!newAction.trim()) return;
    const id = `w_${Date.now()}`;
    const row: WorkflowRow = {
      id,
      action: newAction.trim(),
      level: 2 as GovernanceLevel,
      approval: false,
      contrafactual: false,
      ledger: true,
      approver: '',
    };
    setRows((prev) => [...prev, row]);
    setNewAction('');
    setShowAddRow(false);
  };

  if (loading)
    return (
      <div style={{ padding: 32 }}>
        <SkeletonTable rows={6} cols={6} />
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
        Workflows & Aprovacoes (L5)
      </h2>
      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
        {rows.length} accoes configuradas · {approvalCount} requerem aprovacao ·{' '}
        {Object.entries(levelBreakdown)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([k, v]) => `${k}: ${v}`)
          .join(', ')}
      </div>

      <WorkflowTable rows={rows} onChange={setRows} />

      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        {showAddRow ? (
          <>
            <select
              className="constraint-toggles__param-select"
              value={newAction}
              onChange={(e) => setNewAction(e.target.value)}
              style={{ fontSize: 12, flex: 1, maxWidth: 300 }}
            >
              <option value="">Seleccionar accao...</option>
              {DECISION_ACTIONS.filter((a) => !rows.some((r) => r.action === a)).map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
            <button
              className="schedule-comparison__btn schedule-comparison__btn--primary"
              onClick={addRow}
              disabled={!newAction.trim()}
              style={{ fontSize: 12 }}
            >
              Adicionar
            </button>
            <button
              className="schedule-comparison__btn"
              onClick={() => {
                setShowAddRow(false);
                setNewAction('');
              }}
              style={{ fontSize: 12 }}
            >
              Cancelar
            </button>
          </>
        ) : (
          <button
            className="schedule-comparison__btn schedule-comparison__btn--primary"
            onClick={() => setShowAddRow(true)}
            style={{ fontSize: 12 }}
          >
            + Nova Accao
          </button>
        )}
      </div>

      <div
        style={{
          padding: 'var(--space-8) var(--space-12)',
          background: 'var(--accent-bg)',
          border: '1px solid var(--accent-border)',
          borderRadius: 'var(--radius-xs)',
          fontSize: 'var(--text-sm)',
          color: 'var(--accent-light)',
        }}
      >
        Com estas regras, <strong>{approvalCount}</strong> tipos de accao requerem aprovacao
        explícita antes de execucao.
      </div>
    </div>
  );
}
