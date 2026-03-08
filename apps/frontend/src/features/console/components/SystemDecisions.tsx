/**
 * SystemDecisions — Automatic scheduling decisions for the selected day.
 */

import { Collapsible } from '@/components/Common/Collapsible';
import type { DecisionEntry } from '@/lib/engine';
import './SystemDecisions.css';

interface SystemDecisionsProps {
  decisions: DecisionEntry[];
}

export function SystemDecisions({ decisions }: SystemDecisionsProps) {
  return (
    <div data-testid="system-decisions">
      <Collapsible
        title="Decisoes do Sistema"
        defaultOpen={decisions.length > 0}
        badge={decisions.length > 0 ? `${decisions.length}` : undefined}
      >
        {decisions.length === 0 ? (
          <div className="sdec__empty">Sem decisoes automaticas para este dia.</div>
        ) : (
          <div className="sdec__list">
            {decisions.map((d) => (
              <div key={d.id} className="sdec__item">
                <div className="sdec__item-header">
                  <span className="sdec__type">{d.type.replace(/_/g, ' ')}</span>
                  {d.replanStrategy && <span className="sdec__strategy">{d.replanStrategy}</span>}
                  {d.reversible && <span className="sdec__reversible">reversivel</span>}
                </div>
                <span className="sdec__detail">{d.detail}</span>
                {(d.machineId || d.toolId) && (
                  <span className="sdec__meta">
                    {d.machineId}
                    {d.toolId ? ` · ${d.toolId}` : ''}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </Collapsible>
    </div>
  );
}
