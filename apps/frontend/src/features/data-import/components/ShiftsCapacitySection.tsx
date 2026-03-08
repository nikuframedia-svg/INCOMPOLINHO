import { Clock } from 'lucide-react';
import { useMemo } from 'react';
import {
  getEngineConfig,
  useSettingsActions,
  useSettingsStore,
} from '../../../stores/useSettingsStore';

export function ShiftsCapacitySection() {
  const shiftXStart = useSettingsStore((s) => s.shiftXStart);
  const shiftChange = useSettingsStore((s) => s.shiftChange);
  const shiftYEnd = useSettingsStore((s) => s.shiftYEnd);
  const oee = useSettingsStore((s) => s.oee);
  const thirdShiftDefault = useSettingsStore((s) => s.thirdShiftDefault);
  const { setShifts, setOEE, setThirdShiftDefault } = useSettingsActions();

  const config = useMemo(() => getEngineConfig(), [shiftXStart, shiftChange, shiftYEnd, oee]);

  return (
    <div className="carregar-dados__section" data-testid="section-shifts">
      <div className="carregar-dados__section-header">
        <div className="carregar-dados__section-icon carregar-dados__section-icon--shifts">
          <Clock size={16} />
        </div>
        <div>
          <div className="carregar-dados__section-title">Turnos e Capacidade</div>
          <div className="carregar-dados__section-subtitle">Grade temporal, OEE e 3.o turno</div>
        </div>
      </div>

      <div className="carregar-dados__params-grid">
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Turno X inicio</label>
          <input
            type="time"
            value={shiftXStart}
            onChange={(e) => setShifts(e.target.value, shiftChange, shiftYEnd)}
            className="carregar-dados__mo-field-input carregar-dados__time-input"
            data-testid="shift-x-start"
          />
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Mudanca de turno</label>
          <input
            type="time"
            value={shiftChange}
            onChange={(e) => setShifts(shiftXStart, e.target.value, shiftYEnd)}
            className="carregar-dados__mo-field-input carregar-dados__time-input"
            data-testid="shift-change"
          />
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Turno Y fim</label>
          <input
            type="time"
            value={shiftYEnd === '24:00' ? '00:00' : shiftYEnd}
            onChange={(e) => {
              const v = e.target.value === '00:00' ? '24:00' : e.target.value;
              setShifts(shiftXStart, shiftChange, v);
            }}
            className="carregar-dados__mo-field-input carregar-dados__time-input"
            data-testid="shift-y-end"
          />
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">OEE (%)</label>
          <input
            type="number"
            min={50}
            max={90}
            step={1}
            value={Math.round(oee * 100)}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 50 && n <= 90) setOEE(n / 100);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="oee-input"
          />
          <span className="carregar-dados__param-hint">50% — 90%</span>
        </div>
      </div>

      <div className="carregar-dados__param-preview" data-testid="capacity-preview">
        <span>DAY_CAP = {config.DAY_CAP} min</span>
        <span>OEE = {(config.OEE * 100).toFixed(0)}%</span>
      </div>

      <label className="carregar-dados__checkbox-row">
        <input
          type="checkbox"
          checked={thirdShiftDefault}
          onChange={(e) => setThirdShiftDefault(e.target.checked)}
          data-testid="third-shift-toggle"
        />
        <span className="carregar-dados__checkbox-label">3.o turno (Z) activo por defeito</span>
      </label>
    </div>
  );
}
