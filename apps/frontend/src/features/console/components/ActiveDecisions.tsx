/**
 * ActiveDecisions — Scheduler decisions with Firewall info.
 * Shows decision type icon, auto/manual badge, deviation cost, and reversibility.
 * Replaces SystemDecisions.tsx.
 */

import type { LucideIcon } from 'lucide-react';
import { ArrowLeftRight, FastForward, Layers, Moon, Scissors, Zap } from 'lucide-react';
import { Collapsible } from '@/components/Common/Collapsible';
import type { DecisionEntry } from '@/lib/engine';
import './ActiveDecisions.css';

interface ActiveDecisionsProps {
  decisions: DecisionEntry[];
  onNavigateToBlock?: (opId: string) => void;
}

interface DecisionCategory {
  label: string;
  Icon: LucideIcon;
  colorVar: string;
}

const DECISION_CATEGORIES: Record<string, DecisionCategory> = {
  AUTO_REPLAN_MOVE: { label: 'Realocação', Icon: ArrowLeftRight, colorVar: 'var(--accent)' },
  ALTERNATIVE_MACHINE: { label: 'Realocação', Icon: ArrowLeftRight, colorVar: 'var(--accent)' },
  AUTO_REPLAN_ADVANCE: { label: 'Antecipação', Icon: FastForward, colorVar: 'var(--accent)' },
  ADVANCE_PRODUCTION: { label: 'Antecipação', Icon: FastForward, colorVar: 'var(--accent)' },
  AUTO_REPLAN_OVERTIME: { label: 'Turno Extra', Icon: Moon, colorVar: 'var(--semantic-amber)' },
  AUTO_REPLAN_THIRD_SHIFT: { label: 'Turno Noite', Icon: Moon, colorVar: 'var(--semantic-amber)' },
  LOAD_LEVEL: { label: 'Resequencia', Icon: Layers, colorVar: 'var(--accent)' },
  AUTO_REPLAN_SPLIT: { label: 'Divisão', Icon: Scissors, colorVar: 'var(--accent)' },
};

const DEFAULT_CATEGORY: DecisionCategory = {
  label: 'Sistema',
  Icon: Zap,
  colorVar: 'var(--text-muted)',
};

function getCategory(type: string): DecisionCategory {
  return DECISION_CATEGORIES[type] ?? DEFAULT_CATEGORY;
}

function isHumanDecision(d: DecisionEntry): boolean {
  return (d.metadata as Record<string, unknown>)?.source === 'user';
}

function getDeviationCost(d: DecisionEntry): string | null {
  const cost = (d.metadata as Record<string, unknown>)?.deviationCost;
  if (cost == null) return null;
  return `+${cost} min`;
}

function getDeviationReason(d: DecisionEntry): string | null {
  const reason = (d.metadata as Record<string, unknown>)?.deviationReason;
  if (typeof reason !== 'string') return null;
  const labels: Record<string, string> = {
    technical: 'Tecnico',
    commercial_pressure: 'Comercial',
    operational_convenience: 'Conveniencia',
    hierarchical_pressure: 'Hierarquico',
    risk_deferral: 'Risco diferido',
  };
  return labels[reason] ?? reason;
}

export function ActiveDecisions({ decisions, onNavigateToBlock }: ActiveDecisionsProps) {
  return (
    <div data-testid="active-decisions">
      <Collapsible
        title="Decisões"
        defaultOpen={decisions.length > 0}
        badge={decisions.length > 0 ? `${decisions.length}` : undefined}
      >
        {decisions.length === 0 ? (
          <div className="adec__empty">Sem decisões para este dia.</div>
        ) : (
          <div className="adec__list">
            {decisions.map((d) => {
              const cat = getCategory(d.type);
              const Icon = cat.Icon;
              const human = isHumanDecision(d);
              const cost = getDeviationCost(d);
              const reason = human ? getDeviationReason(d) : null;
              const clickable = !!onNavigateToBlock && !!d.opId;

              return (
                <div
                  key={d.id}
                  className={`adec__item${clickable ? ' adec__item--clickable' : ''}`}
                  onClick={clickable ? () => onNavigateToBlock(d.opId!) : undefined}
                  data-testid={`adec-${d.id}`}
                >
                  <div className="adec__icon" style={{ color: cat.colorVar }}>
                    <Icon size={14} />
                  </div>

                  <div className="adec__body">
                    <div className="adec__header">
                      <span className="adec__category" style={{ color: cat.colorVar }}>
                        {cat.label}
                      </span>
                      <div className="adec__badges">
                        <span
                          className={`adec__badge ${human ? 'adec__badge--manual' : 'adec__badge--auto'}`}
                        >
                          {human ? 'Manual' : 'Auto'}
                        </span>
                        {d.reversible && (
                          <span className="adec__badge adec__badge--rev">Reversivel</span>
                        )}
                        {cost && <span className="adec__badge adec__badge--cost">{cost}</span>}
                        {reason && (
                          <span className="adec__badge adec__badge--reason">{reason}</span>
                        )}
                      </div>
                    </div>
                    <span className="adec__detail">{d.detail}</span>
                    {(d.machineId || d.toolId) && (
                      <span className="adec__meta">
                        {d.machineId}
                        {d.toolId ? ` · ${d.toolId}` : ''}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Collapsible>
    </div>
  );
}
