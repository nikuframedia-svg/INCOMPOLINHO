/**
 * ShiftAlertsList — Alerts, late orders, and shift decisions sections.
 * Extracted from ShiftSummary to keep files under 300 LOC.
 */

import type { LucideIcon } from 'lucide-react';
import { ArrowLeftRight, FastForward, Layers, Moon, Scissors, Zap } from 'lucide-react';
import type { Block, DecisionEntry } from '@/domain/types/scheduling';
import type { Alert } from '@/features/alerts';

// ── Decision categories (same as ActiveDecisions) ──

interface DecCat {
  label: string;
  Icon: LucideIcon;
  colorVar: string;
}

const DEC_CATS: Record<string, DecCat> = {
  AUTO_REPLAN_MOVE: { label: 'Realocacao', Icon: ArrowLeftRight, colorVar: 'var(--accent)' },
  ALTERNATIVE_MACHINE: { label: 'Realocacao', Icon: ArrowLeftRight, colorVar: 'var(--accent)' },
  AUTO_REPLAN_ADVANCE: { label: 'Antecipacao', Icon: FastForward, colorVar: 'var(--accent)' },
  ADVANCE_PRODUCTION: { label: 'Antecipacao', Icon: FastForward, colorVar: 'var(--accent)' },
  AUTO_REPLAN_OVERTIME: { label: 'Turno Extra', Icon: Moon, colorVar: 'var(--semantic-amber)' },
  AUTO_REPLAN_THIRD_SHIFT: { label: 'Turno Noite', Icon: Moon, colorVar: 'var(--semantic-amber)' },
  LOAD_LEVEL: { label: 'Resequencia', Icon: Layers, colorVar: 'var(--accent)' },
  AUTO_REPLAN_SPLIT: { label: 'Divisão', Icon: Scissors, colorVar: 'var(--accent)' },
};

const DEF_CAT: DecCat = { label: 'Sistema', Icon: Zap, colorVar: 'var(--text-muted)' };

function getCat(type: string): DecCat {
  return DEC_CATS[type] ?? DEF_CAT;
}

// ── Alerts & Late Orders ──

interface ShiftAlertsProps {
  lateBlocks: Block[];
  activeAlerts: Alert[];
  onNavigateToBlock?: (opId: string) => void;
}

export function ShiftAlertsSection({
  lateBlocks,
  activeAlerts,
  onNavigateToBlock,
}: ShiftAlertsProps) {
  return (
    <div className="shsm__section">
      <div className="shsm__section-title">
        Alertas / Ordens Atrasadas ({activeAlerts.length + lateBlocks.length})
      </div>
      {activeAlerts.length === 0 && lateBlocks.length === 0 ? (
        <div className="shsm__empty">Sem alertas ou atrasos neste turno.</div>
      ) : (
        <div className="shsm__alert-list">
          {lateBlocks.map((b) => (
            <div
              key={b.opId}
              className="shsm__alert-item"
              style={{ cursor: onNavigateToBlock ? 'pointer' : undefined }}
              onClick={onNavigateToBlock ? () => onNavigateToBlock(b.opId) : undefined}
            >
              <span
                className="shsm__alert-badge"
                style={{ background: 'rgba(239,68,68,0.12)', color: 'var(--semantic-red)' }}
              >
                ATRASO
              </span>
              {b.sku} — {b.machineId} — {b.overflowMin ?? 0}min overflow
            </div>
          ))}
          {activeAlerts.slice(0, 5).map((a) => (
            <div key={a.id} className="shsm__alert-item">
              <span
                className="shsm__alert-badge"
                style={{
                  background:
                    a.priority === 'CRITICAL' ? 'rgba(239,68,68,0.12)' : 'rgba(245,158,11,0.12)',
                  color:
                    a.priority === 'CRITICAL' ? 'var(--semantic-red)' : 'var(--semantic-amber)',
                }}
              >
                {a.priority}
              </span>
              {a.cause}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Shift Decisions ──

interface ShiftDecisionsProps {
  shiftDecisions: DecisionEntry[];
  totalDeviationCost: number;
}

export function ShiftDecisionsSection({ shiftDecisions, totalDeviationCost }: ShiftDecisionsProps) {
  return (
    <div className="shsm__section">
      <div className="shsm__section-title">
        Decisões do Turno
        {totalDeviationCost > 0 && (
          <span className="shsm__cost-total" style={{ marginLeft: 8 }}>
            Custo total: +{totalDeviationCost} min
          </span>
        )}
      </div>
      {shiftDecisions.length === 0 ? (
        <div className="shsm__empty">Todas as decisões foram automáticas.</div>
      ) : (
        <div className="shsm__alert-list">
          {shiftDecisions.map((d) => {
            const cat = getCat(d.type);
            const Icon = cat.Icon;
            const cost = (d.metadata as Record<string, unknown>)?.deviationCost as
              | number
              | undefined;
            return (
              <div key={d.id} className="shsm__decision-item">
                <Icon size={12} style={{ color: cat.colorVar, flexShrink: 0 }} />
                <span style={{ color: cat.colorVar, fontWeight: 600 }}>{cat.label}</span>
                <span>{d.detail}</span>
                {cost != null && <span className="shsm__cost-total">+{cost} min</span>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
