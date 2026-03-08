import { useCallback, useState } from 'react';
import type { KPISnapshot } from '../useConfigPreview';
import { useConfigPreview } from '../useConfigPreview';

interface Props {
  currentKpis: KPISnapshot | null;
  onApply: () => void;
  onDiscard: () => void;
}

interface KPIDef {
  label: string;
  key: keyof KPISnapshot;
  unit: string;
  decimals: number;
  higherIsBetter: boolean;
}

const KPIS: KPIDef[] = [
  { label: 'OTD', key: 'otdPct', unit: '%', decimals: 1, higherIsBetter: true },
  {
    label: 'Avg Tardiness',
    key: 'avgTardinessDays',
    unit: 'd',
    decimals: 1,
    higherIsBetter: false,
  },
  { label: 'Total Setup', key: 'totalSetupMin', unit: 'min', decimals: 0, higherIsBetter: false },
  { label: 'Utilizacao', key: 'utilizationPct', unit: '%', decimals: 1, higherIsBetter: true },
  { label: 'Overflow', key: 'overflowCount', unit: '', decimals: 0, higherIsBetter: false },
];

function formatKpi(val: number, decimals: number, unit: string): string {
  return `${val.toFixed(decimals)}${unit}`;
}

function deltaClass(delta: number, higherIsBetter: boolean): string {
  if (Math.abs(delta) < 0.01) return 'schedule-comparison__kpi-delta--neutral';
  const isBetter = higherIsBetter ? delta > 0 : delta < 0;
  return isBetter
    ? 'schedule-comparison__kpi-delta--better'
    : 'schedule-comparison__kpi-delta--worse';
}

function formatDelta(delta: number, decimals: number, unit: string): string {
  const sign = delta >= 0 ? '+' : '';
  return `${sign}${delta.toFixed(decimals)}${unit}`;
}

export function ScheduleComparison({ currentKpis, onApply, onDiscard }: Props) {
  const previewKpis = useConfigPreview((s) => s.previewKpis);
  const isComputing = useConfigPreview((s) => s.isComputing);
  const saveScenario = useConfigPreview((s) => s.saveScenario);
  const [saveName, setSaveName] = useState('');

  const handleSave = useCallback(() => {
    if (!previewKpis || !saveName.trim()) return;
    saveScenario(saveName.trim(), previewKpis);
    setSaveName('');
  }, [previewKpis, saveName, saveScenario]);

  if (!currentKpis) {
    return (
      <div className="schedule-comparison" data-testid="schedule-comparison">
        <div className="scenario-manager__empty">Sem schedule activo para comparar</div>
      </div>
    );
  }

  return (
    <div className="schedule-comparison" data-testid="schedule-comparison">
      <div className="schedule-comparison__kpis">
        {/* Header row */}
        <span className="schedule-comparison__kpi-header">KPI</span>
        <span className="schedule-comparison__kpi-header">Actual</span>
        <span className="schedule-comparison__kpi-header">Novo</span>
        <span className="schedule-comparison__kpi-header">Delta</span>

        {KPIS.map(({ label, key, unit, decimals, higherIsBetter }) => {
          const curr = currentKpis[key];
          const preview = previewKpis?.[key];
          const delta = preview != null ? preview - curr : null;

          return [
            <span key={`${key}-l`} className="schedule-comparison__kpi-label">
              {label}
            </span>,
            <span key={`${key}-c`} className="schedule-comparison__kpi-current">
              {formatKpi(curr, decimals, unit)}
            </span>,
            <span key={`${key}-n`} className="schedule-comparison__kpi-new">
              {preview != null ? formatKpi(preview, decimals, unit) : isComputing ? '...' : '—'}
            </span>,
            <span
              key={`${key}-d`}
              className={`schedule-comparison__kpi-delta ${delta != null ? deltaClass(delta, higherIsBetter) : 'schedule-comparison__kpi-delta--neutral'}`}
            >
              {delta != null ? formatDelta(delta, decimals, unit) : '—'}
            </span>,
          ];
        })}
      </div>

      <div className="schedule-comparison__actions">
        <input
          type="text"
          placeholder="Nome cenario..."
          value={saveName}
          onChange={(e) => setSaveName(e.target.value)}
          className="constraint-toggles__param-select"
          style={{ flex: 1, maxWidth: 200 }}
          data-testid="scenario-name-input"
        />
        <button
          type="button"
          className="schedule-comparison__btn"
          onClick={handleSave}
          disabled={!previewKpis || !saveName.trim()}
          data-testid="save-scenario-btn"
        >
          Guardar cenario
        </button>
        <button
          type="button"
          className="schedule-comparison__btn"
          onClick={onDiscard}
          data-testid="discard-btn"
        >
          Descartar
        </button>
        <button
          type="button"
          className="schedule-comparison__btn schedule-comparison__btn--primary"
          onClick={onApply}
          disabled={!previewKpis}
          data-testid="apply-btn"
        >
          Aplicar
        </button>
      </div>
    </div>
  );
}
