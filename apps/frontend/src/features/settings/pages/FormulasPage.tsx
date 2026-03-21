/**
 * FormulasPage — Custom formula editor for priority scoring, deviation cost, etc.
 * Route: /settings/formulas
 * Persisted in useSettingsStore (localStorage).
 */

import { Parser } from 'expr-eval';
import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState } from '@/components/Common/EmptyState';
import { SkeletonTable } from '@/components/Common/SkeletonLoader';
import { useScheduleData } from '@/hooks/useScheduleData';
import { useSettingsStore } from '@/stores/useSettingsStore';
import { FormulaEditor } from '../components/FormulaEditor';

function defaultTierFromName(name: string): number {
  const n = name.toLowerCase();
  if (n.includes('faurecia') || n.includes('forvia')) return 1;
  if (n.includes('continental') || n.includes('bosch')) return 2;
  if (!name || name === 'Sem cliente') return 5;
  return 3;
}

function computePreview(
  formula: { expression: string },
  ops: Array<{ t: string; clNm?: string; d: number[]; stk?: number; wip?: number }>,
  toolMap: Record<string, { sH: number; pH: number }>,
  nDays: number,
): number[] {
  try {
    const parser = new Parser();
    const expr = parser.parse(formula.expression);
    return ops.map((op) => {
      const tool = toolMap[op.t];
      const totalDemand = op.d.reduce((s, v) => s + Math.max(v, 0), 0);
      const ph = tool?.pH ?? 100;
      const vars: Record<string, number> = {
        slack: Math.max(0, nDays * 17 - totalDemand / (ph * 0.66)),
        setup: tool?.sH ?? 1,
        clientTier: defaultTierFromName(op.clNm || ''),
        demandTotal: totalDemand,
        piecesPerHour: ph,
        stock: op.stk ?? 0,
        wip: op.wip ?? 0,
        deviationHours: 0,
        multiplier: 3,
        originalPriority: 50,
        load2Shifts: totalDemand / (ph * 0.66),
        capacity2Shifts: nDays * 17,
        pendingOrders: 1,
        avgSlack: nDays * 8,
        otdScore: 0.95,
        cascadeRisk: 2,
        bufferHours: nDays * 4,
        violations: 0,
      };
      try {
        return expr.evaluate(vars);
      } catch {
        return 0;
      }
    });
  } catch {
    return [];
  }
}

export function FormulasPage() {
  const { engine, loading, error } = useScheduleData();
  const formulas = useSettingsStore((s) => s.formulas);
  const updateFormula = useSettingsStore((s) => s.actions.updateFormula);

  const previews = useMemo(() => {
    if (!engine) return {};
    const result: Record<string, number[]> = {};
    for (const f of formulas) {
      result[f.id] = computePreview(f, engine.ops, engine.toolMap, engine.nDays);
    }
    return result;
  }, [engine, formulas]);

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
        Fórmulas Custom (L3)
      </h2>
      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
        Expressões configuráveis avaliadas com expr-eval. Variáveis derivadas dos dados ISOP.
      </div>

      {formulas.map((f) => (
        <FormulaEditor
          key={f.id}
          formula={f}
          onChange={updateFormula}
          previewData={previews[f.id] ?? null}
        />
      ))}
    </div>
  );
}
