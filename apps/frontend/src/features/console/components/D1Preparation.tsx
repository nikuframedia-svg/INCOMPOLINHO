/**
 * D1Preparation — D+1 workforce forecast section.
 * Shows warnings about overload windows and suggestions.
 * Integrates computeD1WorkforceRisk for overall risk indicator.
 */

import { useMemo } from 'react';
import { Collapsible } from '@/components/Common/Collapsible';
import { StatusBanner } from '@/components/Common/StatusBanner';
import type { Block, WorkforceConfig, WorkforceForecast } from '@/lib/engine';
import { C, computeD1WorkforceRisk, fmtMin } from '@/lib/engine';
import './D1Preparation.css';

const SUGGESTION_ICONS: Record<string, string> = {
  ADVANCE_BLOCK: '⏩',
  MOVE_ALT: '↔',
  REPLAN_EQUIVALENT: '🔄',
  REQUEST_REINFORCEMENT: '👷',
};

interface D1PreparationProps {
  forecast: WorkforceForecast | null;
  blocks?: Block[];
  workforceConfig?: WorkforceConfig;
  workdays?: boolean[];
}

export function D1Preparation({ forecast, blocks, workforceConfig, workdays }: D1PreparationProps) {
  const hasContent = forecast && forecast.nextWorkingDayIdx !== -1;

  const d1Risk = useMemo(() => {
    if (!blocks || !workforceConfig || !workdays) return 0;
    return computeD1WorkforceRisk(blocks, workforceConfig, workdays);
  }, [blocks, workforceConfig, workdays]);

  return (
    <div data-testid="d1-preparation">
      <Collapsible
        title="Preparacao D+1"
        defaultOpen={forecast?.hasWarnings ?? false}
        badge={forecast?.hasWarnings ? 'alerta' : undefined}
      >
        {!hasContent ? (
          <div className="d1prep__empty">Sem dados de previsao D+1.</div>
        ) : (
          <>
            <div className="d1prep__header">
              <div className="d1prep__date">
                Proximo dia util: {forecast.date} (dia {forecast.nextWorkingDayIdx})
              </div>
              {d1Risk > 0 && (
                <span
                  className="d1prep__risk-badge"
                  style={{
                    background:
                      d1Risk > 0.7
                        ? 'rgba(239,68,68,0.12)'
                        : d1Risk > 0.3
                          ? 'rgba(245,158,11,0.12)'
                          : 'rgba(20,184,166,0.12)',
                    color: d1Risk > 0.7 ? C.rd : d1Risk > 0.3 ? C.yl : C.ac,
                  }}
                >
                  Risco: {(d1Risk * 100).toFixed(0)}%
                </span>
              )}
            </div>

            {forecast.hasCritical && (
              <StatusBanner
                variant="critical"
                message="Sobrecarga critica de operadores prevista para D+1"
              />
            )}

            {forecast.warnings.length > 0 ? (
              <div className="d1prep__warnings">
                {forecast.warnings.map((w, i) => (
                  <div key={i} className="d1prep__warn">
                    <span className="d1prep__warn-label">
                      {w.laborGroup} {w.shift} — {w.overloadWindow}
                    </span>
                    <span className="d1prep__warn-detail">
                      Pico: {w.projectedPeak} / Cap: {w.capacity} (+{w.excess})
                    </span>
                    <span className="d1prep__warn-detail">
                      {fmtMin(w.windowStart)}–{fmtMin(w.windowEnd)} · {w.shortageMinutes}min
                      shortage
                    </span>

                    {w.causingBlocks.length > 0 && (
                      <span className="d1prep__causing">
                        Blocos:{' '}
                        {w.causingBlocks
                          .slice(0, 3)
                          .map((c) => `${c.machineId}/${c.sku}(${c.operators}op)`)
                          .join(', ')}
                        {w.causingBlocks.length > 3 && ` +${w.causingBlocks.length - 3}`}
                      </span>
                    )}

                    {w.suggestions.length > 0 && (
                      <div className="d1prep__suggestions">
                        {w.suggestions.map((s, si) => (
                          <div key={si} className="d1prep__suggestion-card">
                            <span className="d1prep__suggestion-icon">
                              {SUGGESTION_ICONS[s.type] ?? '💡'}
                            </span>
                            <span className="d1prep__suggestion-text">{s.description}</span>
                            <span className="d1prep__suggestion-impact">
                              reduz ~{s.expectedReduction}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="d1prep__ok">D+1 sem alertas de workforce.</div>
            )}

            {forecast.coverageMissing.length > 0 && (
              <div className="d1prep__coverage">
                <div className="d1prep__coverage-title">
                  Cobertura em falta ({forecast.coverageMissing.length})
                </div>
                {forecast.coverageMissing.map((c, i) => (
                  <div key={i} className="d1prep__coverage-item">
                    <span className="d1prep__coverage-type">{c.type}</span>
                    <span className="d1prep__coverage-detail">{c.detail}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </Collapsible>
    </div>
  );
}
