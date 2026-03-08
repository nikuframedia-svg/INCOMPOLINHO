import { SlidersHorizontal } from 'lucide-react';
import type { OptimizationProfile } from '../../../stores/useSettingsStore';
import { useSettingsStore } from '../../../stores/useSettingsStore';

const PROFILE_OPTIONS: { id: OptimizationProfile; label: string; desc: string }[] = [
  { id: 'balanced', label: 'Equilibrado', desc: 'Pesos balanceados para uso geral' },
  { id: 'otd', label: 'Entregar a Tempo', desc: 'Prioriza cumprimento de prazos' },
  { id: 'setup', label: 'Min. Setups', desc: 'Minimiza changeovers e tempo de setup' },
  { id: 'custom', label: 'Personalizado', desc: 'Ajuste fino de cada peso' },
];

const WEIGHT_DEFS: { key: string; label: string; max: number }[] = [
  { key: 'wTardiness', label: 'Atraso (tardiness)', max: 300 },
  { key: 'wSetupCount', label: 'N.o setups', max: 100 },
  { key: 'wSetupTime', label: 'Tempo setup', max: 10 },
  { key: 'wSetupBalance', label: 'Balanco turnos', max: 100 },
  { key: 'wChurn', label: 'Churn', max: 50 },
  { key: 'wOverflow', label: 'Overflow', max: 200 },
  { key: 'wBelowMinBatch', label: 'Lote minimo', max: 50 },
];

export function OptimizationProfileSection() {
  const optimizationProfile = useSettingsStore((s) => s.optimizationProfile);
  const wTardiness = useSettingsStore((s) => s.wTardiness);
  const wSetupCount = useSettingsStore((s) => s.wSetupCount);
  const wSetupTime = useSettingsStore((s) => s.wSetupTime);
  const wSetupBalance = useSettingsStore((s) => s.wSetupBalance);
  const wChurn = useSettingsStore((s) => s.wChurn);
  const wOverflow = useSettingsStore((s) => s.wOverflow);
  const wBelowMinBatch = useSettingsStore((s) => s.wBelowMinBatch);
  const { setOptimizationProfile, setWeight } = useSettingsStore((s) => s.actions);

  const weights: Record<string, number> = {
    wTardiness,
    wSetupCount,
    wSetupTime,
    wSetupBalance,
    wChurn,
    wOverflow,
    wBelowMinBatch,
  };

  return (
    <div className="carregar-dados__section" data-testid="section-optimization">
      <div className="carregar-dados__section-header">
        <div className="carregar-dados__section-icon carregar-dados__section-icon--weights">
          <SlidersHorizontal size={16} />
        </div>
        <div>
          <div className="carregar-dados__section-title">Perfil de Optimizacao</div>
          <div className="carregar-dados__section-subtitle">
            Pesos da funcao objectivo do scheduler
          </div>
        </div>
      </div>

      <div className="carregar-dados__profile-options" data-testid="profile-options">
        {PROFILE_OPTIONS.map((p) => (
          <button
            key={p.id}
            type="button"
            className={`carregar-dados__profile-btn${optimizationProfile === p.id ? ' carregar-dados__profile-btn--active' : ''}`}
            onClick={() => setOptimizationProfile(p.id)}
            data-testid={`profile-${p.id}`}
          >
            <span className="carregar-dados__profile-btn-label">{p.label}</span>
            <span className="carregar-dados__profile-btn-desc">{p.desc}</span>
          </button>
        ))}
      </div>

      {optimizationProfile === 'custom' && (
        <div className="carregar-dados__weights-grid" data-testid="weights-grid">
          {WEIGHT_DEFS.map((wd) => (
            <div key={wd.key} className="carregar-dados__weight-slider">
              <span className="carregar-dados__weight-label">{wd.label}</span>
              <input
                type="range"
                min={0}
                max={wd.max}
                step={wd.max > 50 ? 5 : wd.max > 10 ? 1 : 0.5}
                value={weights[wd.key]}
                onChange={(e) => setWeight(wd.key, parseFloat(e.target.value))}
                data-testid={`weight-${wd.key}`}
              />
              <span className="carregar-dados__weight-value">{weights[wd.key]}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
