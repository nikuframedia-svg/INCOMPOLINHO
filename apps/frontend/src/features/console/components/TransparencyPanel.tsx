/**
 * TransparencyPanel — Per-operation justifications from TransparencyReport.
 * Only populated when autoReplan is enabled.
 */

import { Collapsible } from '@/components/Common/Collapsible';
import type { EngineData, FailureJustification, OrderJustification } from '@/lib/engine';
import './TransparencyPanel.css';

interface TransparencyPanelProps {
  orderJustifications: OrderJustification[];
  failureJustifications: FailureJustification[];
  engine: EngineData;
}

const START_REASON_PT: Record<string, string> = {
  urgency_slack_critical: 'Urgencia critica',
  density_heavy_load: 'Carga densa',
  free_window_available: 'Janela livre',
  setup_reduction: 'Reducao setups',
  future_load_relief: 'Alivio carga futura',
  deficit_elimination: 'Eliminacao deficit',
};

const MAX_VISIBLE = 20;

export function TransparencyPanel({
  orderJustifications,
  failureJustifications,
  engine,
}: TransparencyPanelProps) {
  const total = orderJustifications.length + failureJustifications.length;

  return (
    <div data-testid="transparency-panel">
      <Collapsible
        title="Transparencia — Justificacoes"
        defaultOpen={false}
        badge={total > 0 ? `${total}` : undefined}
      >
        {total === 0 ? (
          <div className="transp__empty">
            Sem justificacoes. Ative o Auto-Replan em Definicoes para transparencia completa.
          </div>
        ) : (
          <>
            {/* Failures first (more important) */}
            {failureJustifications.length > 0 && (
              <div className="transp__section">
                <div className="transp__section-label">
                  Infeasiveis ({failureJustifications.length})
                </div>
                {failureJustifications.map((f, i) => {
                  const op = engine.ops.find((o) => o.id === f.opId);
                  return (
                    <div key={i} className="transp__card transp__card--failure">
                      <span className="transp__op">{op?.sku ?? f.opId}</span>
                      <span className="transp__constraints">
                        Violacoes: {f.constraintsViolated.join(', ')}
                      </span>
                      <span className="transp__missing">
                        Capacidade em falta: {f.missingCapacityHours.toFixed(1)}h (
                        {f.missingCapacityPieces} pcs)
                      </span>
                      {f.suggestions.map((s, si) => (
                        <span key={si} className="transp__suggestion">
                          {s}
                        </span>
                      ))}
                    </div>
                  );
                })}
              </div>
            )}

            {/* Feasible operations */}
            {orderJustifications.length > 0 && (
              <div className="transp__section">
                <div className="transp__section-label">
                  Escalonadas ({orderJustifications.length})
                </div>
                {orderJustifications.slice(0, MAX_VISIBLE).map((j, i) => {
                  const op = engine.ops.find((o) => o.id === j.opId);
                  const reasonLabel =
                    START_REASON_PT[j.startReason] ?? j.startReason.replace(/_/g, ' ');

                  return (
                    <div key={i} className="transp__card transp__card--ok">
                      <span className="transp__op">
                        {op?.sku ?? j.opId}
                        {j.isTwinProduction && j.twinPartnerSku && ` (twin: ${j.twinPartnerSku})`}
                      </span>
                      <span className="transp__reason">{reasonLabel}</span>
                      <span className="transp__capacity">
                        {j.capacityPcsPerDay} pcs/dia · {j.allocatedHoursPerDay.toFixed(1)}h/dia ·
                        OEE {(j.oee * 100).toFixed(0)}%
                      </span>
                      <span className="transp__produced">
                        Prod: {j.totalProduced.toLocaleString()} / Demand:{' '}
                        {j.totalDemand.toLocaleString()}
                      </span>
                    </div>
                  );
                })}
                {orderJustifications.length > MAX_VISIBLE && (
                  <div className="transp__more">
                    +{orderJustifications.length - MAX_VISIBLE} mais...
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </Collapsible>
    </div>
  );
}
