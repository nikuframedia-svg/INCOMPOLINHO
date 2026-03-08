import { Users } from 'lucide-react';
import type { MOStrategy } from '../../../stores/useSettingsStore';
import { useSettingsStore } from '../../../stores/useSettingsStore';

const MO_OPTIONS: { value: MOStrategy; label: string; desc: string }[] = [
  {
    value: 'nominal',
    label: 'Nominal (recomendado)',
    desc: 'Usa fixture para a 1.a semana, depois capacidade fixa.',
  },
  {
    value: 'cyclic',
    label: 'Ciclico',
    desc: 'Repete o padrao semanal da fixture (pode ter dias com <1 operador).',
  },
  {
    value: 'custom',
    label: 'Personalizado',
    desc: 'Define manualmente a capacidade por area.',
  },
];

export function MOStrategySection() {
  const moStrategy = useSettingsStore((s) => s.moStrategy);
  const moNominalPG1 = useSettingsStore((s) => s.moNominalPG1);
  const moNominalPG2 = useSettingsStore((s) => s.moNominalPG2);
  const moCustomPG1 = useSettingsStore((s) => s.moCustomPG1);
  const moCustomPG2 = useSettingsStore((s) => s.moCustomPG2);
  const { setMOStrategy, setMONominal, setMOCustom } = useSettingsStore((s) => s.actions);

  const showInputs = moStrategy === 'nominal' || moStrategy === 'custom';
  const pg1Val = moStrategy === 'custom' ? moCustomPG1 : moNominalPG1;
  const pg2Val = moStrategy === 'custom' ? moCustomPG2 : moNominalPG2;

  const handlePG1 = (v: string) => {
    const n = parseFloat(v);
    if (isNaN(n) || n < 0) return;
    if (moStrategy === 'custom') setMOCustom(n, moCustomPG2);
    else setMONominal(n, moNominalPG2);
  };
  const handlePG2 = (v: string) => {
    const n = parseFloat(v);
    if (isNaN(n) || n < 0) return;
    if (moStrategy === 'custom') setMOCustom(moCustomPG1, n);
    else setMONominal(moNominalPG1, n);
  };

  return (
    <div className="carregar-dados__section">
      <div className="carregar-dados__section-header">
        <div className="carregar-dados__section-icon carregar-dados__section-icon--operators">
          <Users size={16} />
        </div>
        <div>
          <div className="carregar-dados__section-title">Capacidade de Operadores (M.O.)</div>
          <div className="carregar-dados__section-subtitle">
            Estrategia para dias alem da fixture (horizonte &gt; 8 dias)
          </div>
        </div>
      </div>

      <div className="carregar-dados__mo-options" data-testid="mo-strategy-options">
        {MO_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={`carregar-dados__mo-option${moStrategy === opt.value ? ' carregar-dados__mo-option--active' : ''}`}
            onClick={() => setMOStrategy(opt.value)}
            data-testid={`mo-option-${opt.value}`}
          >
            <span className="carregar-dados__mo-option-label">{opt.label}</span>
            <span className="carregar-dados__mo-option-desc">{opt.desc}</span>
          </button>
        ))}
      </div>

      {showInputs && (
        <div className="carregar-dados__mo-inputs" data-testid="mo-inputs">
          <div className="carregar-dados__mo-field">
            <label className="carregar-dados__mo-field-label">PG1 (operadores)</label>
            <input
              type="number"
              min={0}
              step={0.5}
              value={pg1Val}
              onChange={(e) => handlePG1(e.target.value)}
              className="carregar-dados__mo-field-input"
              data-testid="mo-input-pg1"
            />
          </div>
          <div className="carregar-dados__mo-field">
            <label className="carregar-dados__mo-field-label">PG2 (operadores)</label>
            <input
              type="number"
              min={0}
              step={0.5}
              value={pg2Val}
              onChange={(e) => handlePG2(e.target.value)}
              className="carregar-dados__mo-field-input"
              data-testid="mo-input-pg2"
            />
          </div>
          <div className="carregar-dados__mo-hint">
            {moStrategy === 'nominal'
              ? 'Capacidade constante aplicada a partir do dia 9 (apos a fixture).'
              : 'Capacidade personalizada para todos os dias alem da fixture.'}
          </div>
        </div>
      )}
    </div>
  );
}
