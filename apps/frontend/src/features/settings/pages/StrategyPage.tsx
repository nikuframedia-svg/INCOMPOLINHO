/**
 * StrategyPage — L6: Multi-step scheduling strategies (Asprova-style).
 * Route: /settings/strategy
 */

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState } from '@/components/Common/EmptyState';
import { SkeletonTable } from '@/components/Common/SkeletonLoader';
import { useScheduleData } from '@/hooks/useScheduleData';
import type { StepFilter, StrategyStep } from '../components/StrategyStepEditor';
import { StrategyStepEditor } from '../components/StrategyStepEditor';

interface StrategyPreset {
  id: string;
  name: string;
  steps: StrategyStep[];
  isCustom: boolean;
}

const INCOMPOL_STANDARD: StrategyStep[] = [
  {
    id: 's1',
    name: 'Encomendas criticas forward',
    filter: 'deadline_close',
    rule: 'ATCS',
    direction: 'forward',
    guard: 'none',
    weights: { otd: 80, setup: 10, utilization: 10 },
  },
  {
    id: 's2',
    name: 'Resto com setup grouping',
    filter: 'deadline_far',
    rule: 'ATCS',
    direction: 'forward',
    guard: 'none',
    weights: { otd: 40, setup: 40, utilization: 20 },
  },
  {
    id: 's3',
    name: 'Preencher com lote economico',
    filter: 'capacity_free',
    rule: 'WSPT',
    direction: 'forward',
    guard: 'no_delay',
    weights: { otd: 20, setup: 20, utilization: 60 },
  },
];

const DEFAULT_PRESETS: StrategyPreset[] = [
  { id: 'incompol_standard', name: 'Incompol Standard', steps: INCOMPOL_STANDARD, isCustom: false },
  {
    id: 'max_otd',
    name: 'Maximo OTD-D',
    steps: [
      {
        id: 'otd1',
        name: 'Todas por EDD',
        filter: 'all',
        rule: 'EDD',
        direction: 'forward',
        guard: 'none',
        weights: { otd: 100, setup: 0, utilization: 0 },
      },
    ],
    isCustom: false,
  },
  {
    id: 'min_setup',
    name: 'Setup Minimo',
    steps: [
      {
        id: 'su1',
        name: 'Agrupar por familia',
        filter: 'all',
        rule: 'ATCS',
        direction: 'forward',
        guard: 'none',
        weights: { otd: 10, setup: 80, utilization: 10 },
      },
    ],
    isCustom: false,
  },
];

function matchesFilter(
  filter: StepFilter,
  op: { d: number[] },
  _toolMap: Record<string, { sH: number; pH: number }>,
  nDays: number,
): boolean {
  const totalDemand = op.d.reduce((s, v) => s + Math.max(v, 0), 0);
  if (filter === 'all') return true;
  if (filter === 'deadline_close') return totalDemand > 0 && nDays <= 5;
  if (filter === 'deadline_far') return nDays > 5;
  if (filter === 'capacity_free') return totalDemand === 0;
  return true;
}

export function StrategyPage() {
  const { engine, loading, error } = useScheduleData();
  const [presets, setPresets] = useState<StrategyPreset[]>(DEFAULT_PRESETS);
  const [selectedPresetId, setSelectedPresetId] = useState('incompol_standard');
  const [steps, setSteps] = useState<StrategyStep[]>(INCOMPOL_STANDARD);
  const [isCustom, setIsCustom] = useState(false);
  const [savePresetName, setSavePresetName] = useState('');
  const [testResult, setTestResult] = useState<{ stepCounts: number[]; total: number } | null>(
    null,
  );

  const selectPreset = (id: string) => {
    const preset = presets.find((p) => p.id === id);
    if (!preset) return;
    setSelectedPresetId(id);
    setSteps(preset.steps.map((s) => ({ ...s })));
    setIsCustom(false);
    setTestResult(null);
  };

  const markCustom = () => {
    if (!isCustom) {
      setIsCustom(true);
      setSelectedPresetId('custom');
    }
  };

  const updateStep = (updated: StrategyStep) => {
    setSteps((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
    markCustom();
    setTestResult(null);
  };

  const deleteStep = (id: string) => {
    setSteps((prev) => prev.filter((s) => s.id !== id));
    markCustom();
    setTestResult(null);
  };

  const moveStep = (idx: number, dir: -1 | 1) => {
    setSteps((prev) => {
      const arr = [...prev];
      const target = idx + dir;
      if (target < 0 || target >= arr.length) return prev;
      [arr[idx], arr[target]] = [arr[target], arr[idx]];
      return arr;
    });
    markCustom();
    setTestResult(null);
  };

  const addStep = () => {
    const id = `step_${Date.now()}`;
    const newStep: StrategyStep = {
      id,
      name: `Passo ${steps.length + 1}`,
      filter: 'all',
      rule: 'ATCS',
      direction: 'forward',
      guard: 'none',
      weights: { otd: 50, setup: 30, utilization: 20 },
    };
    setSteps((prev) => [...prev, newStep]);
    markCustom();
    setTestResult(null);
  };

  const saveAsPreset = () => {
    if (!savePresetName.trim()) return;
    const id = `preset_${Date.now()}`;
    const newPreset: StrategyPreset = {
      id,
      name: savePresetName.trim(),
      steps: steps.map((s) => ({ ...s })),
      isCustom: false,
    };
    setPresets((prev) => [...prev, newPreset]);
    setSelectedPresetId(id);
    setIsCustom(false);
    setSavePresetName('');
  };

  const runTest = () => {
    if (!engine) return;
    const stepCounts: number[] = [];
    const assigned = new Set<number>();
    for (const step of steps) {
      let count = 0;
      for (let i = 0; i < engine.ops.length; i++) {
        if (assigned.has(i)) continue;
        const op = engine.ops[i];
        if (matchesFilter(step.filter, op, engine.toolMap, engine.nDays)) {
          count++;
          assigned.add(i);
        }
      }
      stepCounts.push(count);
    }
    setTestResult({ stepCounts, total: engine.ops.length });
  };

  const activePresetName = useMemo(() => {
    if (isCustom) return 'Personalizado';
    return presets.find((p) => p.id === selectedPresetId)?.name ?? 'Personalizado';
  }, [isCustom, presets, selectedPresetId]);

  if (loading)
    return (
      <div style={{ padding: 32 }}>
        <SkeletonTable rows={4} cols={3} />
      </div>
    );
  if (error || !engine) {
    return (
      <div style={{ padding: 32 }}>
        <Link
          to="/settings"
          style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}
        >
          ← Settings
        </Link>
        <EmptyState icon="error" title="Sem dados" description={error || 'Importe ISOP.'} />
      </div>
    );
  }

  return (
    <div style={{ padding: 32, display: 'flex', flexDirection: 'column', gap: 24 }}>
      <Link to="/settings" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>
        ← Settings
      </Link>
      <h2
        style={{
          color: 'var(--text-primary)',
          fontSize: 'var(--text-h3)',
          fontWeight: 600,
          margin: 0,
        }}
      >
        Estrategias Multi-Passo (L6)
      </h2>
      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
        Estrategia activa: <strong>{activePresetName}</strong> · {steps.length} passos · Cada passo
        filtra, despacha e aplica pesos
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Preset:</span>
        {presets.map((p) => (
          <button
            key={p.id}
            className={`schedule-comparison__btn${p.id === selectedPresetId && !isCustom ? ' schedule-comparison__btn--primary' : ''}`}
            onClick={() => selectPreset(p.id)}
            style={{ fontSize: 12 }}
          >
            {p.name}
          </button>
        ))}
        {isCustom && (
          <span
            style={{
              fontSize: 12,
              color: 'var(--semantic-warning)',
              fontStyle: 'italic',
            }}
          >
            (personalizado)
          </span>
        )}
      </div>

      {steps.map((step, idx) => (
        <StrategyStepEditor
          key={step.id}
          step={step}
          index={idx}
          onChange={updateStep}
          onDelete={() => deleteStep(step.id)}
          onMoveUp={() => moveStep(idx, -1)}
          onMoveDown={() => moveStep(idx, 1)}
          isFirst={idx === 0}
          isLast={idx === steps.length - 1}
        />
      ))}

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button
          className="schedule-comparison__btn schedule-comparison__btn--primary"
          onClick={addStep}
          style={{ fontSize: 12 }}
        >
          + Adicionar Passo
        </button>
        <button className="schedule-comparison__btn" onClick={runTest} style={{ fontSize: 12 }}>
          Testar Estrategia
        </button>
      </div>

      {testResult && (
        <div
          style={{
            padding: 'var(--space-12)',
            background: 'var(--accent-bg)',
            border: '1px solid var(--accent-border)',
            borderRadius: 'var(--radius-xs)',
            fontSize: 'var(--text-sm)',
            color: 'var(--accent-light)',
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 8 }}>
            Resultado: {testResult.total} operações distribuídas
          </div>
          {testResult.stepCounts.map((count, i) => (
            <div key={steps[i]?.id ?? i} style={{ marginLeft: 8 }}>
              Passo {i + 1} ({steps[i]?.name}): <strong>{count}</strong> ops
            </div>
          ))}
          {testResult.total - testResult.stepCounts.reduce((s, v) => s + v, 0) > 0 && (
            <div style={{ marginLeft: 8, color: 'var(--semantic-warning)' }}>
              Nao atribuidas: {testResult.total - testResult.stepCounts.reduce((s, v) => s + v, 0)}
            </div>
          )}
        </div>
      )}

      {isCustom && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input
            type="text"
            value={savePresetName}
            onChange={(e) => setSavePresetName(e.target.value)}
            placeholder="Nome do preset..."
            style={{
              background: 'var(--bg-raised)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 4,
              color: 'var(--text-primary)',
              padding: '4px 8px',
              fontSize: 12,
              width: 200,
            }}
          />
          <button
            className="schedule-comparison__btn"
            onClick={saveAsPreset}
            disabled={!savePresetName.trim()}
            style={{ fontSize: 12 }}
          >
            Salvar como Preset
          </button>
        </div>
      )}
    </div>
  );
}
