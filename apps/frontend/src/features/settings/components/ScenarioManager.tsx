import { Trash2, Upload } from 'lucide-react';
import type { SavedScenario } from '../useConfigPreview';
import { useConfigPreview } from '../useConfigPreview';

interface Props {
  onPromote?: (scenario: SavedScenario) => void;
}

export function ScenarioManager({ onPromote }: Props) {
  const scenarios = useConfigPreview((s) => s.scenarios);
  const selectedId = useConfigPreview((s) => s.selectedScenarioId);
  const selectScenario = useConfigPreview((s) => s.selectScenario);
  const loadScenario = useConfigPreview((s) => s.loadScenario);
  const deleteScenario = useConfigPreview((s) => s.deleteScenario);

  if (scenarios.length === 0) {
    return (
      <div className="scenario-manager" data-testid="scenario-manager">
        <div className="scenario-manager__empty">
          Sem cenarios guardados. Configure pesos e guarde um cenario.
        </div>
      </div>
    );
  }

  return (
    <div className="scenario-manager" data-testid="scenario-manager">
      <div className="scenario-manager__list">
        {scenarios.map((sc) => (
          <div
            key={sc.id}
            className={`scenario-manager__item${selectedId === sc.id ? ' scenario-manager__item--selected' : ''}`}
            onClick={() => selectScenario(selectedId === sc.id ? null : sc.id)}
            data-testid={`scenario-${sc.id}`}
          >
            <div className="scenario-manager__item-info">
              <span className="scenario-manager__item-name">{sc.name}</span>
              <span className="scenario-manager__item-date">
                {new Date(sc.createdAt).toLocaleDateString('pt-PT')}
              </span>
              <span className="scenario-manager__item-kpi">
                OTD {sc.kpis.otdPct.toFixed(1)}% · Setup {Math.round(sc.kpis.totalSetupMin)}min
              </span>
            </div>
            <button
              type="button"
              className="schedule-comparison__btn"
              onClick={(e) => {
                e.stopPropagation();
                loadScenario(sc.id);
              }}
              title="Carregar configuracao"
              data-testid={`load-${sc.id}`}
            >
              <Upload size={14} />
            </button>
            {onPromote && (
              <button
                type="button"
                className="schedule-comparison__btn schedule-comparison__btn--primary"
                onClick={(e) => {
                  e.stopPropagation();
                  onPromote(sc);
                }}
                title="Promover a plano oficial"
                data-testid={`promote-${sc.id}`}
              >
                Promover
              </button>
            )}
            <button
              type="button"
              className="schedule-comparison__btn"
              onClick={(e) => {
                e.stopPropagation();
                deleteScenario(sc.id);
              }}
              title="Apagar cenario"
              data-testid={`delete-${sc.id}`}
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
