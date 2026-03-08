/**
 * AlertsPanel — Violations and infeasibility entries for the selected day.
 * Shows feasibility score and suggestion call-to-actions.
 */

import { Collapsible } from '@/components/Common/Collapsible';
import type { InfeasibilityEntry, ScheduleViolation } from '@/lib/engine';
import { C } from '@/lib/engine';
import './AlertsPanel.css';

interface AlertsPanelProps {
  violations: ScheduleViolation[];
  infeasibilities: InfeasibilityEntry[];
  feasibilityScore?: number;
}

export function AlertsPanel({ violations, infeasibilities, feasibilityScore }: AlertsPanelProps) {
  const total = violations.length + infeasibilities.length;

  return (
    <div data-testid="alerts-panel">
      <Collapsible
        title="Alertas"
        defaultOpen={total > 0}
        badge={total > 0 ? `${total}` : undefined}
      >
        {/* Feasibility score header */}
        {feasibilityScore != null && feasibilityScore < 1 && (
          <div className="alerts__feasibility">
            <span className="alerts__feasibility-label">Viabilidade</span>
            <span
              className="alerts__feasibility-score"
              style={{
                color: feasibilityScore >= 0.95 ? C.ac : feasibilityScore >= 0.8 ? C.yl : C.rd,
              }}
            >
              {(feasibilityScore * 100).toFixed(0)}%
            </span>
            <div className="alerts__feasibility-bar">
              <div
                style={{
                  width: `${feasibilityScore * 100}%`,
                  background:
                    feasibilityScore >= 0.95 ? C.ac : feasibilityScore >= 0.8 ? C.yl : C.rd,
                }}
              />
            </div>
          </div>
        )}

        {total === 0 ? (
          <div className="alerts__empty">Sem alertas para este dia.</div>
        ) : (
          <div className="alerts__list">
            {infeasibilities.map((entry, i) => (
              <div key={`inf-${i}`} className="alerts__item alerts__item--critical">
                <span className="alerts__severity">INFEASIBLE</span>
                <span className="alerts__detail">{entry.detail}</span>
                <span className="alerts__meta">
                  {entry.machineId} · {entry.toolId} · {entry.reason}
                </span>
                {entry.suggestion && (
                  <div className="alerts__cta">
                    <span className="alerts__cta-label">Remediacao</span>
                    <span className="alerts__cta-text">{entry.suggestion}</span>
                  </div>
                )}
              </div>
            ))}

            {violations.map((v, i) => (
              <div key={`vio-${i}`} className={`alerts__item alerts__item--${v.severity}`}>
                <span className="alerts__severity">{v.severity.toUpperCase()}</span>
                <span className="alerts__detail">{v.title}</span>
                <span className="alerts__meta">{v.detail}</span>
                {v.suggestedFix && (
                  <div className="alerts__cta">
                    <span className="alerts__cta-label">Accao</span>
                    <span className="alerts__cta-text">{v.suggestedFix}</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Collapsible>
    </div>
  );
}
