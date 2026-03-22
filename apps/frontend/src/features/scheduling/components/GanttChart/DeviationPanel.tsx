/**
 * DeviationPanel — Firewall comparison modal.
 *
 * Shows actual vs proposed metrics when a block is dragged,
 * collects incentive category + justification, and logs to Decision Ledger.
 */

import { useMemo, useState } from 'react';
import type { Block, OptResult } from '@/domain/types/scheduling';
import { assessDeviation } from '../../api/firewallApi';
import { createLedgerEntry } from '../../api/ledgerApi';
import type { ProposedMove } from '../../hooks/useGanttDragDrop';
import './DeviationPanel.css';

interface DeviationPanelProps {
  move: ProposedMove;
  blocks: Block[];
  currentMetrics: OptResult | null;
  onConfirm: () => void;
  onCancel: () => void;
}

const INCENTIVE_CATS = [
  { value: 'technical', label: 'Tecnico' },
  { value: 'commercial_pressure', label: 'Pressao comercial' },
  { value: 'operational_convenience', label: 'Conveniencia operacional' },
  { value: 'hierarchical_pressure', label: 'Pressao hierarquica' },
  { value: 'risk_deferral', label: 'Risco diferido' },
];

function governanceLevel(cost: number, isFrozen: boolean): string {
  if (isFrozen) return 'L4';
  if (cost > 200) return 'L5';
  if (cost > 100) return 'L4';
  if (cost > 50) return 'L3';
  if (cost > 20) return 'L2';
  if (cost > 0) return 'L1';
  return 'L0';
}

function deltaClass(actual: number, proposed: number, higherIsBetter: boolean): string {
  if (Math.abs(actual - proposed) < 0.01) return 'dev-panel__delta--neutral';
  const better = higherIsBetter ? proposed > actual : proposed < actual;
  return better ? 'dev-panel__delta--better' : 'dev-panel__delta--worse';
}

function fmtDelta(actual: number, proposed: number, suffix = ''): string {
  const d = proposed - actual;
  if (Math.abs(d) < 0.01) return `—`;
  const sign = d > 0 ? '+' : '';
  return `${sign}${d.toFixed(1)}${suffix}`;
}

export function DeviationPanel({
  move,
  blocks,
  currentMetrics,
  onConfirm,
  onCancel,
}: DeviationPanelProps) {
  const [category, setCategory] = useState('technical');
  const [justification, setJustification] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Proposed metrics: use currentMetrics as baseline (full scoring requires backend)
  // For the deviation panel, we show the same metrics and flag the move as a deviation.
  // True proposed metrics would require a backend call; for now, keep currentMetrics.
  const proposedMetrics = currentMetrics;

  const actOTD = currentMetrics?.otdDelivery ?? 0;
  const propOTD = proposedMetrics?.otdDelivery ?? actOTD;
  const actSetup = (currentMetrics?.setupMin ?? 0) / 60;
  const propSetup = (proposedMetrics?.setupMin ?? 0) / 60;
  const actTardy = currentMetrics?.tardinessDays ?? 0;
  const propTardy = proposedMetrics?.tardinessDays ?? 0;
  const actOver = currentMetrics?.overflows ?? 0;
  const propOver = proposedMetrics?.overflows ?? 0;

  // Cascade: blocks that changed position
  const cascadeCount = useMemo(() => {
    if (!proposedMetrics) return 0;
    const newBlocks = blocks.map((b) => {
      if (b.opId !== move.block.opId || b.dayIdx !== move.block.dayIdx) return b;
      return { ...b, machineId: move.toMachineId, startMin: move.toStartMin };
    });
    return newBlocks.filter((nb, i) => {
      const ob = blocks[i];
      return ob && (nb.machineId !== ob.machineId || Math.abs(nb.startMin - ob.startMin) > 1);
    }).length;
  }, [blocks, proposedMetrics, move]);

  // Deviation cost: simple heuristic based on OTD drop + setup increase
  const deviationCost = useMemo(() => {
    const otdDrop = Math.max(0, actOTD - propOTD);
    const setupIncrease = Math.max(0, propSetup - actSetup);
    return Math.round(otdDrop * 10 + setupIncrease * 15 + cascadeCount * 5);
  }, [actOTD, propOTD, actSetup, propSetup, cascadeCount]);

  const govLevel = governanceLevel(deviationCost, move.isFrozen);
  const requiresContrafactual = govLevel >= 'L3';

  async function handleConfirm() {
    if (!justification.trim()) return;
    setSubmitting(true);
    try {
      // Call firewall assessment (best-effort)
      await assessDeviation({
        optimal_state: { otd: actOTD, setup: actSetup },
        proposed_state: { otd: propOTD, setup: propSetup },
        incentive_category: category,
        governance_level: govLevel,
      }).catch(() => {});

      // Log to Decision Ledger
      await createLedgerEntry({
        tenant_id: 'incompol',
        user_id: 'planner-001',
        decision_type: 'manual_move',
        optimal_state: {
          opId: move.block.opId,
          machineId: move.block.machineId,
          startMin: move.block.startMin,
          otd: actOTD,
        },
        proposed_state: {
          opId: move.block.opId,
          machineId: move.toMachineId,
          startMin: move.toStartMin,
          otd: propOTD,
        },
        deviation_cost: deviationCost,
        incentive_category: category,
        declared_reason: justification,
        governance_level: govLevel,
        contrafactual: requiresContrafactual
          ? { otdDelta: propOTD - actOTD, setupDelta: propSetup - actSetup, cascade: cascadeCount }
          : null,
      });

      onConfirm();
    } catch {
      // Still confirm the move even if logging fails
      onConfirm();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="dev-panel__overlay" onClick={onCancel} role="presentation">
      <div
        className="dev-panel"
        role="dialog"
        aria-label="Desvio do Optimo"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dev-panel__title">
          Desvio do Optimo — {move.block.toolId} ({move.block.sku})
        </div>

        {move.isFrozen && (
          <div className="dev-panel__frozen-warn">
            Esta operação está CONGELADA (zona 0-5 dias). Requer aprovação L4+.
          </div>
        )}

        <table className="dev-panel__metrics">
          <thead>
            <tr>
              <th>Metrica</th>
              <th>Actual</th>
              <th>Proposto</th>
              <th>Delta</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>OTD-D</td>
              <td>{actOTD.toFixed(1)}%</td>
              <td>{propOTD.toFixed(1)}%</td>
              <td className={deltaClass(actOTD, propOTD, true)}>
                {fmtDelta(actOTD, propOTD, '%')}
              </td>
            </tr>
            <tr>
              <td>Setup total</td>
              <td>{actSetup.toFixed(2)}h</td>
              <td>{propSetup.toFixed(2)}h</td>
              <td className={deltaClass(actSetup, propSetup, false)}>
                {fmtDelta(actSetup, propSetup, 'h')}
              </td>
            </tr>
            <tr>
              <td>Tardiness</td>
              <td>{actTardy} dias</td>
              <td>{propTardy} dias</td>
              <td className={deltaClass(actTardy, propTardy, false)}>
                {fmtDelta(actTardy, propTardy)}
              </td>
            </tr>
            <tr>
              <td>Overflows</td>
              <td>{actOver}</td>
              <td>{propOver}</td>
              <td className={deltaClass(actOver, propOver, false)}>
                {fmtDelta(actOver, propOver)}
              </td>
            </tr>
            <tr>
              <td>Cascata</td>
              <td>—</td>
              <td>{cascadeCount} ops</td>
              <td
                className={
                  cascadeCount > 0 ? 'dev-panel__delta--worse' : 'dev-panel__delta--neutral'
                }
              >
                {cascadeCount > 0 ? `+${cascadeCount}` : '—'}
              </td>
            </tr>
            <tr>
              <td>Custo desvio</td>
              <td>—</td>
              <td
                colSpan={2}
                className={
                  deviationCost > 0 ? 'dev-panel__delta--worse' : 'dev-panel__delta--neutral'
                }
              >
                {deviationCost > 0 ? `+€${deviationCost}` : '€0'}
              </td>
            </tr>
          </tbody>
        </table>

        <div className="dev-panel__form">
          <label className="dev-panel__label">Motivo</label>
          <select
            className="dev-panel__select"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            {INCENTIVE_CATS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>

          <label className="dev-panel__label">Justificacao</label>
          <textarea
            className="dev-panel__textarea"
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
            placeholder="Descreva a razao do desvio..."
          />

          <div className="dev-panel__governance">
            Governance: {govLevel} | Custo: €{deviationCost}
            {requiresContrafactual && ' | Contrafactual obrigatorio'}
          </div>
        </div>

        <div className="dev-panel__actions">
          <button className="dev-panel__btn" onClick={onCancel}>
            Voltar ao optimo
          </button>
          <button
            className="dev-panel__btn dev-panel__btn--primary"
            onClick={handleConfirm}
            disabled={!justification.trim() || submitting}
          >
            {submitting ? 'A registar...' : 'Confirmar desvio'}
          </button>
        </div>
      </div>
    </div>
  );
}
