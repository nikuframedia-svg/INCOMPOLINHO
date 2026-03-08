import { ListOrdered } from 'lucide-react';
import type { DispatchRule } from '../../../stores/useSettingsStore';
import { useSettingsStore } from '../../../stores/useSettingsStore';

const DISPATCH_OPTIONS: { value: DispatchRule; label: string; desc: string }[] = [
  {
    value: 'EDD',
    label: 'EDD — Earliest Due Date',
    desc: 'Prioriza prazos de entrega (recomendado OTD)',
  },
  {
    value: 'CR',
    label: 'CR — Critical Ratio',
    desc: 'Prioriza racio prazo / tempo de processamento',
  },
  { value: 'WSPT', label: 'WSPT — Weighted SPT', desc: 'Prioriza maior volume/tempo (throughput)' },
  { value: 'SPT', label: 'SPT — Shortest Processing Time', desc: 'Minimiza tempo total de fluxo' },
  {
    value: 'ATCS',
    label: 'ATCS — Apparent Tardiness Cost w/ Setups',
    desc: 'Combina urgencia com custo de setup (grid search k1/k2)',
  },
];

export function PlanningRulesSection() {
  const dispatchRule = useSettingsStore((s) => s.dispatchRule);
  const bucketWindowDays = useSettingsStore((s) => s.bucketWindowDays);
  const maxEddGapDays = useSettingsStore((s) => s.maxEddGapDays);
  const defaultSetupHours = useSettingsStore((s) => s.defaultSetupHours);
  const { setDispatchRule, setBucketWindowDays, setMaxEddGapDays, setDefaultSetupHours } =
    useSettingsStore((s) => s.actions);

  return (
    <div className="carregar-dados__section" data-testid="section-planning">
      <div className="carregar-dados__section-header">
        <div className="carregar-dados__section-icon carregar-dados__section-icon--planning">
          <ListOrdered size={16} />
        </div>
        <div>
          <div className="carregar-dados__section-title">Regras de Planeamento</div>
          <div className="carregar-dados__section-subtitle">
            Logica base do algoritmo de scheduling
          </div>
        </div>
      </div>

      <div className="carregar-dados__dispatch-options" data-testid="dispatch-options">
        {DISPATCH_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={`carregar-dados__mo-option${dispatchRule === opt.value ? ' carregar-dados__mo-option--active' : ''}`}
            onClick={() => setDispatchRule(opt.value)}
            data-testid={`dispatch-${opt.value}`}
          >
            <span className="carregar-dados__mo-option-label">{opt.label}</span>
            <span className="carregar-dados__mo-option-desc">{opt.desc}</span>
          </button>
        ))}
      </div>

      <div className="carregar-dados__params-grid">
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Janela agrupamento (dias)</label>
          <input
            type="number"
            min={2}
            max={10}
            value={bucketWindowDays}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 2 && n <= 10) setBucketWindowDays(n);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="bucket-window"
          />
          <span className="carregar-dados__param-hint">2 — 10 dias uteis</span>
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Gap max. EDD (dias)</label>
          <input
            type="number"
            min={2}
            max={7}
            value={maxEddGapDays}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 2 && n <= 7) setMaxEddGapDays(n);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="edd-gap"
          />
          <span className="carregar-dados__param-hint">2 — 7 dias</span>
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Setup padrao (h)</label>
          <input
            type="number"
            min={0.25}
            max={3.0}
            step={0.25}
            value={defaultSetupHours}
            onChange={(e) => {
              const n = parseFloat(e.target.value);
              if (!isNaN(n) && n >= 0.25 && n <= 3.0) setDefaultSetupHours(n);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="default-setup"
          />
          <span className="carregar-dados__param-hint">0.25 — 3.0 horas</span>
        </div>
      </div>
    </div>
  );
}
