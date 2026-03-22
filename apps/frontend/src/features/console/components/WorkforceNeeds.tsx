/**
 * WorkforceNeeds — D+1 workforce table: Turno × Área × Necessários × Disponíveis × Gap.
 * Alerts for night shift requirements and overload gaps.
 */

import { Collapsible } from '@/components/Common/Collapsible';
import { StatusBanner } from '@/components/Common/StatusBanner';
import type { WorkforceForecast } from '@/domain/types/scheduling';
import './WorkforceNeeds.css';

interface WorkforceNeedsProps {
  forecast: WorkforceForecast | null;
  operatorCapacity: { pg1: number; pg2: number };
}

interface WorkforceRow {
  shift: string;
  area: string;
  needed: number;
  available: number;
  gap: number;
}

function buildRows(
  forecast: WorkforceForecast,
  operatorCapacity: { pg1: number; pg2: number },
): WorkforceRow[] {
  const rows: WorkforceRow[] = [];
  const shifts = ['X', 'Y'] as const;
  const areas = ['Grandes', 'Medias'] as const;

  for (const shift of shifts) {
    for (const area of areas) {
      const warning = forecast.warnings.find((w) => w.shift === shift && w.laborGroup === area);
      const capacity = area === 'Grandes' ? operatorCapacity.pg1 : operatorCapacity.pg2;
      const needed = warning?.projectedPeak ?? 0;
      const gap = Math.max(0, needed - capacity);

      rows.push({
        shift: shift === 'X' ? 'A (07:00-15:30)' : 'B (15:30-00:00)',
        area,
        needed,
        available: capacity,
        gap,
      });
    }
  }

  return rows;
}

export function WorkforceNeeds({ forecast, operatorCapacity }: WorkforceNeedsProps) {
  const hasContent = forecast && forecast.nextWorkingDayIdx !== -1;
  const hasNightShift = forecast?.coverageMissing.some((c) => c.type === 'THIRD_SHIFT') ?? false;
  const hasWarnings = forecast?.hasWarnings ?? false;

  const rows = hasContent ? buildRows(forecast, operatorCapacity) : [];
  const hasGap = rows.some((r) => r.gap > 0);

  return (
    <div data-testid="workforce-needs">
      <Collapsible
        title="Workforce D+1"
        defaultOpen={hasWarnings || hasNightShift}
        badge={hasGap ? 'gap' : hasNightShift ? 'noite' : undefined}
      >
        {!hasContent ? (
          <div className="wfn__empty">Sem previsão de workforce para D+1.</div>
        ) : (
          <>
            <div className="wfn__header">
              <span className="wfn__date">Proximo dia util: {forecast.date}</span>
            </div>

            {hasNightShift && (
              <StatusBanner variant="critical" message="Turno noite necessario para D+1" />
            )}

            <table className="wfn__table">
              <thead>
                <tr>
                  <th>Turno</th>
                  <th>Area</th>
                  <th>Necessarios</th>
                  <th>Disponiveis</th>
                  <th>Gap</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.shift}-${r.area}`}>
                    <td className="wfn__cell-shift">{r.shift}</td>
                    <td>{r.area}</td>
                    <td className="wfn__cell-num">{r.needed}</td>
                    <td className="wfn__cell-num">{r.available}</td>
                    <td className="wfn__cell-num">
                      {r.gap > 0 ? (
                        <span className="wfn__gap-badge">+{r.gap}</span>
                      ) : (
                        <span className="wfn__ok-badge">OK</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Collapsible>
    </div>
  );
}
