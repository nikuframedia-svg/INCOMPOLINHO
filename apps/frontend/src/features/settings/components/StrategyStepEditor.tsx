/**
 * StrategyStepEditor — Card for a single scheduling strategy step (L6).
 */

import { ArrowDown, ArrowUp, Trash2 } from 'lucide-react';
import './WorkflowTable.css';

export type DispatchRule = 'ATCS' | 'EDD' | 'CR' | 'SPT' | 'WSPT';
export type StepFilter = 'all' | 'deadline_close' | 'deadline_far' | 'capacity_free';
export type StepGuard = 'none' | 'no_delay' | 'respect_frozen';

export interface StrategyStep {
  id: string;
  name: string;
  filter: StepFilter;
  rule: DispatchRule;
  direction: 'forward' | 'backward';
  guard: StepGuard;
  weights: { otd: number; setup: number; utilization: number };
}

const FILTER_OPTIONS: { value: StepFilter; label: string }[] = [
  { value: 'all', label: 'Todas as operações' },
  { value: 'deadline_close', label: 'Deadline < 5 dias' },
  { value: 'deadline_far', label: 'Deadline >= 5 dias' },
  { value: 'capacity_free', label: 'Capacidade livre' },
];

const RULE_OPTIONS: { value: DispatchRule; label: string }[] = [
  { value: 'ATCS', label: 'ATCS (Apparent Tardiness Cost)' },
  { value: 'EDD', label: 'EDD (Earliest Due Date)' },
  { value: 'CR', label: 'CR (Critical Ratio)' },
  { value: 'SPT', label: 'SPT (Shortest Processing Time)' },
  { value: 'WSPT', label: 'WSPT (Weighted SPT)' },
];

const GUARD_OPTIONS: { value: StepGuard; label: string }[] = [
  { value: 'none', label: 'Nenhum' },
  { value: 'no_delay', label: 'Nao atrasa ninguem' },
  { value: 'respect_frozen', label: 'Respeita frozen zone' },
];

interface StrategyStepEditorProps {
  step: StrategyStep;
  index: number;
  onChange: (updated: StrategyStep) => void;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  isFirst: boolean;
  isLast: boolean;
}

export function StrategyStepEditor({
  step,
  index,
  onChange,
  onDelete,
  onMoveUp,
  onMoveDown,
  isFirst,
  isLast,
}: StrategyStepEditorProps) {
  const update = (patch: Partial<StrategyStep>) => onChange({ ...step, ...patch });
  const updateWeight = (key: keyof StrategyStep['weights'], value: number) =>
    onChange({ ...step, weights: { ...step.weights, [key]: value } });

  return (
    <div className="strategy-step">
      <div className="strategy-step__header">
        <span
          style={{
            color: 'var(--accent)',
            fontWeight: 700,
            fontSize: 'var(--text-sm)',
            flexShrink: 0,
          }}
        >
          #{index + 1}
        </span>
        <input
          value={step.name}
          onChange={(e) => update({ name: e.target.value })}
          spellCheck={false}
        />
        <div className="strategy-step__controls">
          <button type="button" onClick={onMoveUp} disabled={isFirst} aria-label="Mover acima" title="Mover acima">
            <ArrowUp size={12} />
          </button>
          <button type="button" onClick={onMoveDown} disabled={isLast} aria-label="Mover abaixo" title="Mover abaixo">
            <ArrowDown size={12} />
          </button>
          <button type="button" onClick={onDelete} aria-label="Eliminar" title="Eliminar">
            <Trash2 size={12} />
          </button>
        </div>
      </div>

      <div className="strategy-step__fields">
        <div>
          <div className="strategy-step__field-label">Filtro</div>
          <select
            className="constraint-toggles__param-select"
            value={step.filter}
            onChange={(e) => update({ filter: e.target.value as StepFilter })}
            style={{ fontSize: 12, width: '100%' }}
          >
            {FILTER_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <div className="strategy-step__field-label">Regra de Despacho</div>
          <select
            className="constraint-toggles__param-select"
            value={step.rule}
            onChange={(e) => update({ rule: e.target.value as DispatchRule })}
            style={{ fontSize: 12, width: '100%' }}
          >
            {RULE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <div className="strategy-step__field-label">Direccao</div>
          <select
            className="constraint-toggles__param-select"
            value={step.direction}
            onChange={(e) => update({ direction: e.target.value as 'forward' | 'backward' })}
            style={{ fontSize: 12, width: '100%' }}
          >
            <option value="forward">Forward</option>
            <option value="backward">Backward</option>
          </select>
        </div>
        <div>
          <div className="strategy-step__field-label">Guard</div>
          <select
            className="constraint-toggles__param-select"
            value={step.guard}
            onChange={(e) => update({ guard: e.target.value as StepGuard })}
            style={{ fontSize: 12, width: '100%' }}
          >
            {GUARD_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="strategy-step__sliders">
        <div className="strategy-step__slider-group">
          <label>OTD-D: {step.weights.otd}</label>
          <input
            type="range"
            className="opt-sliders__track"
            min={0}
            max={100}
            value={step.weights.otd}
            onChange={(e) => updateWeight('otd', Number(e.target.value))}
          />
        </div>
        <div className="strategy-step__slider-group">
          <label>Setup: {step.weights.setup}</label>
          <input
            type="range"
            className="opt-sliders__track"
            min={0}
            max={100}
            value={step.weights.setup}
            onChange={(e) => updateWeight('setup', Number(e.target.value))}
          />
        </div>
        <div className="strategy-step__slider-group">
          <label>Utilização: {step.weights.utilization}</label>
          <input
            type="range"
            className="opt-sliders__track"
            min={0}
            max={100}
            value={step.weights.utilization}
            onChange={(e) => updateWeight('utilization', Number(e.target.value))}
          />
        </div>
      </div>
    </div>
  );
}
