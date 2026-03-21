/**
 * D1Preparation — D+1 workforce forecast section.
 * Shows warnings about overload windows and suggestions.
 * Integrates computeD1WorkforceRisk for overall risk indicator.
 */

import { useMemo } from 'react';
import { Collapsible } from '@/components/Common/Collapsible';
import { StatusBanner } from '@/components/Common/StatusBanner';
import type { WorkforceForecast } from '@/lib/engine';
import { C, fmtMin } from '@/lib/engine';
import './D1Preparation.css';

const SUGGESTION_ICONS: Record<string, string> = {
  ADVANCE_BLOCK: '⏩',
  MOVE_ALT: '↔',
  REPLAN_EQUIVALENT: '🔄',
  REQUEST_REINFORCEMENT: '👷',
};

interface D1PreparationProps {
  forecast: WorkforceForecast | null;
}

export function D1Preparation({ forecast }: D1PreparationProps) {
  const hasContent = forecast && forecast.nextWorkingDayIdx !== -1;

  // D1 risk derived from forecast warnings (no local engine computation)
  const d1Risk = useMemo(() => {
    if (!forecast || !forecast.hasWarnings) return 0;
    const totalExcess = forecast.warnings.reduce((sum, w) => sum + (w.excess ?? 0), 0);
    const totalCap = forecast.warnings.reduce((sum, w) => sum + (w.capacity ?? 1), 0);
    return totalCap > 0 ? Math.min(1, totalExcess / totalCap) : 0;
  }, [forecast]);

  return (
    <div data-testid="d1-preparation">
      <Collapsible
        title="Preparação D+1"
        defaultOpen={forecast?.hasWarnings ?? false}
        badge={forecast?.hasWarnings ? 'alerta' : undefined}
      >
        {!hasContent ? (
          <div className="d1prep__empty">Sem dados de previsão D+1.</div>
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
