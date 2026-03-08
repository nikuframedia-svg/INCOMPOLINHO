import type { PolicyId } from '../useConfigPreview';
import { useConfigPreview } from '../useConfigPreview';

interface PolicyOption {
  id: PolicyId;
  name: string;
  desc: string;
}

const POLICIES: PolicyOption[] = [
  { id: 'max_otd', name: 'Maximizar OTD', desc: 'Prioriza entrega a tempo' },
  { id: 'min_setups', name: 'Minimizar Setups', desc: 'Reduz trocas de ferramenta' },
  { id: 'balanced', name: 'Equilibrado', desc: 'Trade-off OTD/setup/util' },
  { id: 'urgent', name: 'Urgente', desc: 'Modo emergencia, turno noite' },
  { id: 'custom', name: 'Custom', desc: 'Sliders editaveis' },
];

export function PolicySelector() {
  const policy = useConfigPreview((s) => s.policy);
  const setPolicy = useConfigPreview((s) => s.setPolicy);

  return (
    <div className="policy-selector" data-testid="policy-selector">
      <div className="policy-selector__grid">
        {POLICIES.map((p) => (
          <button
            key={p.id}
            type="button"
            className={`policy-selector__btn${policy === p.id ? ' policy-selector__btn--active' : ''}`}
            onClick={() => setPolicy(p.id)}
            data-testid={`policy-${p.id}`}
          >
            <span className="policy-selector__btn-name">{p.name}</span>
            <span className="policy-selector__btn-desc">{p.desc}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
