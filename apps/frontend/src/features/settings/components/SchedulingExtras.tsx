/**
 * SchedulingExtras — Dispatch rule + direction dropdowns for SchedulingConfigPage.
 * AUTO mode resolves to EDD on the backend (learning engine handles selection server-side).
 */

import type { DispatchRule, PreStartStrategy } from '@/stores/useSettingsStore';
import { useSettingsStore } from '@/stores/useSettingsStore';

const DISPATCH_RULES: { value: DispatchRule; label: string }[] = [
  { value: 'AUTO', label: 'AUTO — Selecção adaptativa (backend)' },
  { value: 'ATCS', label: 'ATCS — Apparent Tardiness Cost with Setups' },
  { value: 'EDD', label: 'EDD — Earliest Due Date' },
  { value: 'CR', label: 'CR — Critical Ratio' },
  { value: 'SPT', label: 'SPT — Shortest Processing Time' },
  { value: 'WSPT', label: 'WSPT — Weighted Shortest Processing Time' },
];

const SOLVER_OBJECTIVES: { value: string; label: string }[] = [
  { value: 'weighted_tardiness', label: 'Weighted Tardiness (minimizar atrasos ponderados)' },
  { value: 'makespan', label: 'Makespan (minimizar duração total)' },
  { value: 'tardiness', label: 'Tardiness (minimizar atrasos)' },
];

export function SchedulingExtras() {
  const dispatchRule = useSettingsStore((s) => s.dispatchRule);
  const setDispatchRule = useSettingsStore((s) => s.actions.setDispatchRule);
  const preStartBufferDays = useSettingsStore((s) => s.preStartBufferDays);
  const setPreStartBufferDays = useSettingsStore((s) => s.actions.setPreStartBufferDays);
  const preStartStrategy = useSettingsStore((s) => s.preStartStrategy);
  const setPreStartStrategy = useSettingsStore((s) => s.actions.setPreStartStrategy);
  const useServerSolver = useSettingsStore((s) => s.useServerSolver);
  const setUseServerSolver = useSettingsStore((s) => s.actions.setUseServerSolver);
  const solverTimeLimit = useSettingsStore((s) => s.serverSolverTimeLimit);
  const setSolverTimeLimit = useSettingsStore((s) => s.actions.setServerSolverTimeLimit);
  const solverObjective = useSettingsStore((s) => s.serverSolverObjective);
  const setSolverObjective = useSettingsStore((s) => s.actions.setServerSolverObjective);

  return (
    <div className="constraint-toggles" data-testid="scheduling-extras">
      <div className="constraint-toggles__param">
        <span className="constraint-toggles__param-label">Regra de despacho</span>
        <select
          className="constraint-toggles__param-select"
          value={dispatchRule}
          onChange={(e) => setDispatchRule(e.target.value as DispatchRule)}
          data-testid="dispatch-rule"
        >
          {DISPATCH_RULES.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </div>

      {dispatchRule === 'AUTO' && (
        <div style={{ fontSize: 12, opacity: 0.7, marginTop: 4, lineHeight: 1.5 }}>
          AUTO resolve para EDD no backend. Aprendizagem UCB1 gerida pelo servidor.
        </div>
      )}

      <div className="constraint-toggles__param">
        <span className="constraint-toggles__param-label">Direcção de scheduling</span>
        <select
          className="constraint-toggles__param-select"
          defaultValue="forward"
          data-testid="scheduling-direction"
        >
          <option value="forward">Forward (do presente para o futuro)</option>
          <option value="backward">Backward (da deadline para trás)</option>
        </select>
      </div>

      <div className="constraint-toggles__param">
        <span className="constraint-toggles__param-label">Buffer pré-produção (dias)</span>
        <input
          type="number"
          className="constraint-toggles__param-select"
          value={preStartBufferDays}
          min={0}
          max={10}
          onChange={(e) => setPreStartBufferDays(Math.max(0, Math.min(10, Number(e.target.value) || 0)))}
          data-testid="pre-start-buffer-days"
          style={{ width: 80 }}
        />
        <span style={{ fontSize: 12, opacity: 0.7, marginLeft: 8 }}>
          Dias uteis antes da 1a data ISOP
        </span>
      </div>

      <div className="constraint-toggles__param">
        <span className="constraint-toggles__param-label">Estrategia pre-start</span>
        <select
          className="constraint-toggles__param-select"
          value={preStartStrategy}
          onChange={(e) => setPreStartStrategy(e.target.value as PreStartStrategy)}
          data-testid="pre-start-strategy"
        >
          <option value="auto">Auto — preenche urgentes automaticamente</option>
          <option value="manual">Manual — apenas expande timeline</option>
        </select>
      </div>

      {/* CP-SAT Solver section */}
      <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--border, #e0e0e0)' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
          Solver CP-SAT (Backend)
        </div>
        <div className="constraint-toggles__param">
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={useServerSolver}
              onChange={(e) => setUseServerSolver(e.target.checked)}
              data-testid="use-server-solver"
            />
            <span className="constraint-toggles__param-label" style={{ margin: 0 }}>
              Usar CP-SAT para scheduling
            </span>
          </label>
        </div>
        {useServerSolver && (
          <>
            <div className="constraint-toggles__param">
              <span className="constraint-toggles__param-label">Time limit (segundos)</span>
              <input
                type="range"
                min={10}
                max={120}
                step={5}
                value={solverTimeLimit}
                onChange={(e) => setSolverTimeLimit(Number(e.target.value))}
                data-testid="solver-time-limit"
                style={{ width: 160 }}
              />
              <span style={{ fontSize: 12, minWidth: 40, textAlign: 'right' }}>
                {solverTimeLimit}s
              </span>
            </div>
            <div className="constraint-toggles__param">
              <span className="constraint-toggles__param-label">Objectivo</span>
              <select
                className="constraint-toggles__param-select"
                value={solverObjective}
                onChange={(e) => setSolverObjective(e.target.value as 'weighted_tardiness' | 'makespan' | 'tardiness')}
                data-testid="solver-objective"
              >
                {SOLVER_OBJECTIVES.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div style={{ fontSize: 12, opacity: 0.7, marginTop: 4, lineHeight: 1.5 }}>
              CP-SAT e usado para problemas &lt;200 ops. Acima disso, fallback para ATCS client-side.
            </div>
          </>
        )}
      </div>
    </div>
  );
}
