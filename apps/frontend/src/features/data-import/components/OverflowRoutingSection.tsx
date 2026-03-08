import { GitBranch } from 'lucide-react';
import { useSettingsStore } from '../../../stores/useSettingsStore';

export function OverflowRoutingSection() {
  const altUtilThreshold = useSettingsStore((s) => s.altUtilThreshold);
  const maxAutoMoves = useSettingsStore((s) => s.maxAutoMoves);
  const maxOverflowIter = useSettingsStore((s) => s.maxOverflowIter);
  const otdTolerance = useSettingsStore((s) => s.otdTolerance);
  const loadBalanceThreshold = useSettingsStore((s) => s.loadBalanceThreshold);
  const {
    setAltUtilThreshold,
    setMaxAutoMoves,
    setMaxOverflowIter,
    setOTDTolerance,
    setLoadBalanceThreshold,
  } = useSettingsStore((s) => s.actions);

  return (
    <div className="carregar-dados__section" data-testid="section-overflow">
      <div className="carregar-dados__section-header">
        <div className="carregar-dados__section-icon carregar-dados__section-icon--routing">
          <GitBranch size={16} />
        </div>
        <div>
          <div className="carregar-dados__section-title">Overflow e Routing</div>
          <div className="carregar-dados__section-subtitle">
            Redistribuicao automatica para maquinas alternativas
          </div>
        </div>
      </div>

      <div className="carregar-dados__params-grid">
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Threshold sat. alt. (%)</label>
          <input
            type="number"
            min={80}
            max={100}
            step={1}
            value={Math.round(altUtilThreshold * 100)}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 80 && n <= 100) setAltUtilThreshold(n / 100);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="alt-util-threshold"
          />
          <span className="carregar-dados__param-hint">80% — 100%</span>
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Max auto-moves</label>
          <input
            type="number"
            min={4}
            max={32}
            value={maxAutoMoves}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 4 && n <= 32) setMaxAutoMoves(n);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="max-auto-moves"
          />
          <span className="carregar-dados__param-hint">4 — 32 operacoes</span>
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Max iteracoes</label>
          <input
            type="number"
            min={1}
            max={5}
            value={maxOverflowIter}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 1 && n <= 5) setMaxOverflowIter(n);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="max-overflow-iter"
          />
          <span className="carregar-dados__param-hint">1 — 5 passagens</span>
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Tolerancia OTD (%)</label>
          <input
            type="number"
            min={80}
            max={100}
            step={1}
            value={Math.round(otdTolerance * 100)}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 80 && n <= 100) setOTDTolerance(n / 100);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="otd-tolerance"
          />
          <span className="carregar-dados__param-hint">80% — 100%</span>
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Threshold rebal. (%)</label>
          <input
            type="number"
            min={5}
            max={30}
            step={1}
            value={Math.round(loadBalanceThreshold * 100)}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 5 && n <= 30) setLoadBalanceThreshold(n / 100);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="load-balance-threshold"
          />
          <span className="carregar-dados__param-hint">5% — 30%</span>
        </div>
      </div>
    </div>
  );
}
