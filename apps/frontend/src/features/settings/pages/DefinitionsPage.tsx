/**
 * DefinitionsPage — Concept definitions (L4): what means "late", "urgent", etc.
 * Route: /settings/definitions
 * Persisted in useSettingsStore (localStorage).
 */

import { Parser } from 'expr-eval';
import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState } from '@/components/Common/EmptyState';
import { SkeletonTable } from '@/components/Common/SkeletonLoader';
import { useScheduleData } from '@/hooks/useScheduleData';
import { useSettingsStore } from '@/stores/useSettingsStore';
import { DefinitionEditor } from '../components/DefinitionEditor';

function defaultTierFromName(name: string): number {
  const n = name.toLowerCase();
  if (n.includes('faurecia') || n.includes('forvia')) return 1;
  if (n.includes('continental') || n.includes('bosch')) return 2;
  if (!name || name === 'Sem cliente') return 5;
  return 3;
}

/** Per-operation concepts: evaluate expression for each op, return count of truthy results */
function evaluatePerOp(
  expression: string,
  ops: Array<{ t: string; clNm?: string; d: number[]; stk?: number; wip?: number }>,
  toolMap: Record<string, { sH: number; pH: number }>,
  nDays: number,
): { matching: number; total: number } | null {
  try {
    const parser = new Parser();
    const expr = parser.parse(expression);
    let matching = 0;
    for (const op of ops) {
      const tool = toolMap[op.t];
      const totalDemand = op.d.reduce((s, v) => s + Math.max(v, 0), 0);
      const ph = tool?.pH ?? 100;
      const slackHours = Math.max(0, nDays * 17 - totalDemand / (ph * 0.66));
      const vars: Record<string, number> = {
        completionDay: Math.ceil(totalDemand / (ph * 0.66 * 17)),
        deadline: nDays,
        toleranceHours: 8,
        clientTier: defaultTierFromName(op.clNm || ''),
        slackHours,
        demandTotal: totalDemand,
        stock: op.stk ?? 0,
        load2Shifts: totalDemand / (ph * 0.66),
        capacity2Shifts: nDays * 17,
        pendingOrders: 1,
        stressTestOTD: 0.92,
        stressTestCascade: 2,
        bufferHours: slackHours,
        violations: 0,
      };
      try {
        const result = expr.evaluate(vars);
        if (result) matching++;
      } catch {
        /* skip */
      }
    }
    return { matching, total: ops.length };
  } catch {
    return null;
  }
}

export function DefinitionsPage() {
  const { engine, loading, error } = useScheduleData();
  const definitions = useSettingsStore((s) => s.definitions);
  const updateDefinition = useSettingsStore((s) => s.actions.updateDefinition);

  const impacts = useMemo(() => {
    if (!engine) return {};
    const result: Record<string, { matching: number; total: number } | null> = {};
    for (const def of definitions) {
      result[def.id] = evaluatePerOp(def.expression, engine.ops, engine.toolMap, engine.nDays);
    }
    return result;
  }, [engine, definitions]);

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
        Definições de Conceito (L4)
      </h2>
      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
        Cada fábrica define os seus próprios conceitos. Alterações criam nova versão com rollback
        disponível.
      </div>

      {definitions.map((def) => (
        <DefinitionEditor
          key={def.id}
          definition={def}
          onChange={updateDefinition}
          impactPreview={impacts[def.id] ?? null}
        />
      ))}
    </div>
  );
}
