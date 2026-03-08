import type { ConfigConstraints } from '../useConfigPreview';
import { useConfigPreview } from '../useConfigPreview';

interface ConstraintDef {
  key: keyof ConfigConstraints;
  name: string;
  desc: string;
}

const CONSTRAINTS: ConstraintDef[] = [
  { key: 'setupCrew', name: 'Setup Crew', desc: 'Max 1 setup simultaneo na fabrica' },
  { key: 'toolTimeline', name: 'Tool Timeline', desc: 'Sem conflitos de ferramenta' },
  { key: 'calcoTimeline', name: 'Calco Timeline', desc: 'Sem conflitos de codigo calco' },
  { key: 'operatorPool', name: 'Operator Pool', desc: 'Capacidade de operadores por turno' },
];

export function ConstraintToggles() {
  const constraints = useConfigPreview((s) => s.constraints);
  const setConstraint = useConfigPreview((s) => s.setConstraint);
  const frozenHorizonDays = useConfigPreview((s) => s.frozenHorizonDays);
  const setFrozenHorizonDays = useConfigPreview((s) => s.setFrozenHorizonDays);
  const lotMode = useConfigPreview((s) => s.lotMode);
  const setLotMode = useConfigPreview((s) => s.setLotMode);

  return (
    <div className="constraint-toggles" data-testid="constraint-toggles">
      {CONSTRAINTS.map((c) => (
        <div className="constraint-toggles__row" key={c.key}>
          <div className="constraint-toggles__info">
            <span className="constraint-toggles__name">{c.name}</span>
            <span className="constraint-toggles__desc">{c.desc}</span>
          </div>
          <input
            type="checkbox"
            className="constraint-toggles__switch"
            checked={constraints[c.key]}
            onChange={(e) => setConstraint(c.key, e.target.checked)}
            data-testid={`toggle-${c.key}`}
          />
        </div>
      ))}

      <div className="constraint-toggles__param">
        <span className="constraint-toggles__param-label">Horizonte frozen (dias)</span>
        <input
          type="range"
          min={0}
          max={14}
          value={frozenHorizonDays}
          onChange={(e) => setFrozenHorizonDays(Number(e.target.value))}
          className="opt-sliders__track"
          data-testid="frozen-horizon"
        />
        <span className="opt-sliders__value">{frozenHorizonDays}d</span>
      </div>

      <div className="constraint-toggles__param">
        <span className="constraint-toggles__param-label">Lote economico</span>
        <select
          className="constraint-toggles__param-select"
          value={lotMode}
          onChange={(e) => setLotMode(e.target.value as 'strict' | 'relaxed')}
          data-testid="lot-mode"
        >
          <option value="relaxed">Relaxed (qty exacta)</option>
          <option value="strict">Strict (arredonda ao lote)</option>
        </select>
      </div>
    </div>
  );
}
