import { Package } from 'lucide-react';
import type { ServiceLevelOption } from '../../../stores/useSettingsStore';
import useSettingsStore from '../../../stores/useSettingsStore';

export default function MRPSupplySection() {
  const {
    serviceLevel,
    coverageThresholdDays,
    abcThresholdA,
    abcThresholdB,
    xyzThresholdX,
    xyzThresholdY,
    setServiceLevel,
    setCoverageThresholdDays,
    setABCThresholds,
    setXYZThresholds,
  } = useSettingsStore();

  return (
    <div className="carregar-dados__section" data-testid="section-mrp">
      <div className="carregar-dados__section-header">
        <div className="carregar-dados__section-icon carregar-dados__section-icon--mrp">
          <Package size={16} />
        </div>
        <div>
          <div className="carregar-dados__section-title">MRP e Supply</div>
          <div className="carregar-dados__section-subtitle">
            Safety stock, classificacao ABC/XYZ, alertas de supply
          </div>
        </div>
      </div>

      <div className="carregar-dados__params-grid">
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Nivel de servico</label>
          <select
            value={serviceLevel}
            onChange={(e) => setServiceLevel(parseInt(e.target.value) as ServiceLevelOption)}
            className="carregar-dados__semantics-select"
            data-testid="service-level"
          >
            <option value={90}>90% (Z=1.28)</option>
            <option value={95}>95% (Z=1.645)</option>
            <option value={99}>99% (Z=2.33)</option>
          </select>
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Cobertura min. (dias)</label>
          <input
            type="number"
            min={1}
            max={7}
            value={coverageThresholdDays}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 1 && n <= 7) setCoverageThresholdDays(n);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="coverage-threshold"
          />
          <span className="carregar-dados__param-hint">1 — 7 dias</span>
        </div>
      </div>

      <div className="carregar-dados__params-grid carregar-dados__params-grid--4col">
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">ABC — A (%)</label>
          <input
            type="number"
            min={70}
            max={90}
            step={5}
            value={Math.round(abcThresholdA * 100)}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 70 && n <= 90) setABCThresholds(n / 100, abcThresholdB);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="abc-a"
          />
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">ABC — B (%)</label>
          <input
            type="number"
            min={90}
            max={98}
            step={1}
            value={Math.round(abcThresholdB * 100)}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 90 && n <= 98) setABCThresholds(abcThresholdA, n / 100);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="abc-b"
          />
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">XYZ — X (CV)</label>
          <input
            type="number"
            min={0.3}
            max={0.7}
            step={0.1}
            value={xyzThresholdX}
            onChange={(e) => {
              const n = parseFloat(e.target.value);
              if (!isNaN(n) && n >= 0.3 && n <= 0.7) setXYZThresholds(n, xyzThresholdY);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="xyz-x"
          />
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">XYZ — Y (CV)</label>
          <input
            type="number"
            min={0.7}
            max={1.5}
            step={0.1}
            value={xyzThresholdY}
            onChange={(e) => {
              const n = parseFloat(e.target.value);
              if (!isNaN(n) && n >= 0.7 && n <= 1.5) setXYZThresholds(xyzThresholdX, n);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="xyz-y"
          />
        </div>
      </div>
    </div>
  );
}
