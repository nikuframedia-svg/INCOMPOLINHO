import { ConstraintToggles } from '../components/ConstraintToggles';
import { OptimizationSliders } from '../components/OptimizationSliders';
import { PolicySelector } from '../components/PolicySelector';
import { ScenarioManager } from '../components/ScenarioManager';

export function SchedulingConfigPage() {
  return (
    <div style={{ padding: 32, display: 'flex', flexDirection: 'column', gap: 24 }}>
      <h2 style={{ color: 'var(--text-primary)', fontSize: 'var(--text-h3)', fontWeight: 600 }}>
        Configuração de Scheduling
      </h2>
      <PolicySelector />
      <OptimizationSliders />
      <ConstraintToggles />
      <ScenarioManager onPromote={() => {}} />
    </div>
  );
}
