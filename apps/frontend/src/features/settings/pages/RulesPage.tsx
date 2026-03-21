/**
 * RulesPage — SE/ENTÃO rules with visual query builder (L2).
 * Route: /settings/rules
 * Persisted in useSettingsStore (localStorage).
 */

import { Trash2 } from 'lucide-react';
import { useState } from 'react';
import type { RuleGroupType } from 'react-querybuilder';
import { Link } from 'react-router-dom';
import { EmptyState } from '@/components/Common/EmptyState';
import { SkeletonTable } from '@/components/Common/SkeletonLoader';
import { useScheduleData } from '@/hooks/useScheduleData';
import type { RuleConfig } from '@/stores/settings-types';
import { useSettingsStore } from '@/stores/useSettingsStore';
import { RuleEditor } from '../components/RuleEditor';

function defaultTierFromName(name: string): number {
  const n = name.toLowerCase();
  if (n.includes('faurecia') || n.includes('forvia')) return 1;
  if (n.includes('continental') || n.includes('bosch')) return 2;
  if (!name || name === 'Sem cliente') return 5;
  return 3;
}

interface OpContext {
  'cliente.tier': number;
  slack_hours: number;
  'maquina.utilizacao': number;
  'operacao.ferramenta_familia': string;
  dia_semana: string;
  turno: string;
  stock_final: number;
  zona: string;
  [key: string]: unknown;
}

function opToContext(
  op: { t: string; clNm?: string; d: number[]; stk?: number },
  toolMap: Record<string, { sH: number; pH: number }>,
  nDays: number,
): OpContext {
  const tool = toolMap[op.t];
  const totalDemand = op.d.reduce((s, v) => s + Math.max(v, 0), 0);
  const ph = tool?.pH ?? 100;
  const slackHours = Math.max(0, nDays * 17 - totalDemand / (ph * 0.66));
  return {
    'cliente.tier': defaultTierFromName(op.clNm || ''),
    slack_hours: slackHours,
    'maquina.utilizacao': 0,
    'operacao.ferramenta_familia': op.t.substring(0, 3),
    dia_semana: 'seg',
    turno: 'A',
    stock_final: op.stk ?? 0,
    zona: slackHours < 120 ? 'frozen' : slackHours < 336 ? 'slushy' : 'liquid',
  };
}

function evaluateQuery(group: RuleGroupType, ctx: Record<string, unknown>): boolean {
  const results = (group.rules || []).map((rule) => {
    if ('rules' in rule) return evaluateQuery(rule as RuleGroupType, ctx);
    const val = ctx[rule.field];
    const rv = rule.value;
    switch (rule.operator) {
      case '=':
        return String(val) === String(rv);
      case '!=':
        return String(val) !== String(rv);
      case '>':
        return Number(val) > Number(rv);
      case '>=':
        return Number(val) >= Number(rv);
      case '<':
        return Number(val) < Number(rv);
      case '<=':
        return Number(val) <= Number(rv);
      case 'contains':
        return String(val).includes(String(rv));
      case 'beginsWith':
        return String(val).startsWith(String(rv));
      case 'endsWith':
        return String(val).endsWith(String(rv));
      default:
        return false;
    }
  });
  return group.combinator === 'and' ? results.every(Boolean) : results.some(Boolean);
}

export function RulesPage() {
  const { engine, loading, error } = useScheduleData();
  const rules = useSettingsStore((s) => s.rules);
  const updateRule = useSettingsStore((s) => s.actions.updateRule);
  const addRuleToStore = useSettingsStore((s) => s.actions.addRule);
  const deleteRuleFromStore = useSettingsStore((s) => s.actions.deleteRule);
  const [selectedId, setSelectedId] = useState<string | null>(rules[0]?.id ?? null);
  const [testResult, setTestResult] = useState<{
    affected: number;
    breakdown: Record<string, number>;
  } | null>(null);

  const selected = rules.find((r) => r.id === selectedId) ?? null;

  const addRule = () => {
    const id = `r_${Date.now()}`;
    const newRule: RuleConfig = {
      id,
      name: 'Nova regra',
      active: true,
      query: { combinator: 'and', rules: [] },
      action: { type: 'set_priority', value: 'MEDIUM' },
      version: 1,
      versions: [],
    };
    addRuleToStore(newRule);
    setSelectedId(id);
    setTestResult(null);
  };

  const deleteRule = (id: string) => {
    deleteRuleFromStore(id);
    if (selectedId === id) {
      setSelectedId(rules.find((r) => r.id !== id)?.id ?? null);
      setTestResult(null);
    }
  };

  const handleUpdateRule = (updated: RuleConfig) => {
    updateRule(updated);
    setTestResult(null);
  };

  const runTest = () => {
    if (!selected || !engine) return;
    const contexts = engine.ops.map((op) => opToContext(op, engine.toolMap, engine.nDays));
    const matching = contexts.filter((ctx) => evaluateQuery(selected.query, ctx));
    const breakdown: Record<string, number> = {};
    if (selected.action.type === 'set_priority') {
      breakdown[String(selected.action.value)] = matching.length;
    }
    setTestResult({ affected: matching.length, breakdown });
  };

  if (loading)
    return (
      <div style={{ padding: 32 }}>
        <SkeletonTable rows={5} cols={3} />
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
        Regras SE/ENTÃO (L2)
      </h2>
      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
        {rules.length} regras · {rules.filter((r) => r.active).length} activas · Condições visuais
        com acções automáticas
      </div>

      <div className="rule-editor">
        <div className="rule-editor__list">
          <button
            className="schedule-comparison__btn schedule-comparison__btn--primary"
            onClick={addRule}
            style={{ fontSize: 12, marginBottom: 8 }}
          >
            + Nova Regra
          </button>
          {rules.map((r) => (
            <div
              key={r.id}
              className={`rule-editor__list-item${r.id === selectedId ? ' rule-editor__list-item--active' : ''}${!r.active ? ' rule-editor__list-item--disabled' : ''}`}
              onClick={() => {
                setSelectedId(r.id);
                setTestResult(null);
              }}
            >
              <span className="rule-editor__list-name">{r.name}</span>
              <span
                className={`rule-editor__badge${r.active ? ' rule-editor__badge--on' : ' rule-editor__badge--off'}`}
              >
                {r.active ? 'ON' : 'OFF'}
              </span>
              <Trash2
                size={12}
                style={{ color: 'var(--text-muted)', cursor: 'pointer', flexShrink: 0 }}
                onClick={(e) => {
                  e.stopPropagation();
                  deleteRule(r.id);
                }}
              />
            </div>
          ))}
        </div>

        {selected ? (
          <RuleEditor
            rule={selected}
            onChange={handleUpdateRule}
            onTest={runTest}
            testResult={testResult}
          />
        ) : (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              Seleccione uma regra ou crie uma nova
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
