/**
 * RuleEditor — Visual query builder for SE/ENTÃO rules with dark theme.
 */

import type { Field, RuleGroupType } from 'react-querybuilder';
import { QueryBuilder } from 'react-querybuilder';
import type { RuleActionType, RuleConfig } from '@/stores/settings-types';
import 'react-querybuilder/dist/query-builder.css';
import './RuleEditor.css';

export type { RuleAction, RuleActionType, RuleConfig } from '@/stores/settings-types';

interface RuleEditorProps {
  rule: RuleConfig;
  onChange: (updated: RuleConfig) => void;
  onTest: () => void;
  testResult: { affected: number; breakdown: Record<string, number> } | null;
}

const RULE_FIELDS: Field[] = [
  { name: 'cliente.tier', label: 'Cliente Tier (1-5)', inputType: 'number' },
  { name: 'slack_hours', label: 'Slack (horas)', inputType: 'number' },
  { name: 'maquina.utilizacao', label: 'Utilização Máquina (%)', inputType: 'number' },
  { name: 'operacao.ferramenta_familia', label: 'Família Ferramenta', inputType: 'text' },
  {
    name: 'dia_semana',
    label: 'Dia Semana',
    valueEditorType: 'select',
    values: [
      { name: 'seg', label: 'Segunda' },
      { name: 'ter', label: 'Terça' },
      { name: 'qua', label: 'Quarta' },
      { name: 'qui', label: 'Quinta' },
      { name: 'sex', label: 'Sexta' },
      { name: 'sab', label: 'Sábado' },
      { name: 'dom', label: 'Domingo' },
    ],
  },
  {
    name: 'turno',
    label: 'Turno',
    valueEditorType: 'select',
    values: [
      { name: 'A', label: 'Turno A' },
      { name: 'B', label: 'Turno B' },
      { name: 'Noite', label: 'Noite' },
    ],
  },
  { name: 'stock_final', label: 'Stock Final', inputType: 'number' },
  {
    name: 'zona',
    label: 'Zona Planeamento',
    valueEditorType: 'select',
    values: [
      { name: 'frozen', label: 'Frozen (0-5d)' },
      { name: 'slushy', label: 'Slushy (5d-2sem)' },
      { name: 'liquid', label: 'Liquid (resto)' },
    ],
  },
];

const ACTION_OPTIONS: Array<{ value: RuleActionType; label: string }> = [
  { value: 'set_priority', label: 'Definir Prioridade' },
  { value: 'boost_priority', label: 'Aumentar Prioridade (+N)' },
  { value: 'flag_night_shift', label: 'Sinalizar Turno Noite' },
  { value: 'alert', label: 'Alerta (mensagem)' },
  { value: 'require_approval', label: 'Requer Aprovação' },
  { value: 'block', label: 'Bloquear' },
];

const PRIORITY_OPTIONS = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];

function bumpVersion(rule: RuleConfig, patch: Partial<RuleConfig>): RuleConfig {
  const prev = {
    v: rule.version,
    ts: new Date().toISOString(),
    query: rule.query,
    action: rule.action,
  };
  return { ...rule, ...patch, version: rule.version + 1, versions: [...rule.versions, prev] };
}

export function RuleEditor({ rule, onChange, onTest, testResult }: RuleEditorProps) {
  const handleQueryChange = (query: RuleGroupType) => {
    onChange(bumpVersion(rule, { query }));
  };

  const handleNameChange = (name: string) => {
    onChange({ ...rule, name });
  };

  const handleToggle = () => {
    onChange(bumpVersion(rule, { active: !rule.active }));
  };

  const handleActionType = (type: RuleActionType) => {
    const defaultVal = type === 'set_priority' ? 'CRITICAL' : type === 'boost_priority' ? 5 : '';
    onChange(bumpVersion(rule, { action: { type, value: defaultVal } }));
  };

  const handleActionValue = (value: string | number) => {
    onChange(bumpVersion(rule, { action: { ...rule.action, value } }));
  };

  return (
    <div className="rule-editor__panel">
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <input
          type="text"
          value={rule.name}
          onChange={(e) => handleNameChange(e.target.value)}
          style={{
            flex: 1,
            fontSize: 13,
            fontWeight: 600,
            background: 'transparent',
            border: 'none',
            borderBottom: '1px solid var(--border-subtle)',
            color: 'var(--text-primary)',
            padding: '4px 0',
            outline: 'none',
          }}
        />
        <label
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 12,
            color: 'var(--text-muted)',
          }}
        >
          Activa
          <input
            type="checkbox"
            className="constraint-toggles__switch"
            checked={rule.active}
            onChange={handleToggle}
          />
        </label>
      </div>

      <div style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 500 }}>SE</div>
      <QueryBuilder fields={RULE_FIELDS} query={rule.query} onQueryChange={handleQueryChange} />

      <div style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 500 }}>ENTÃO</div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <select
          className="constraint-toggles__param-select"
          value={rule.action.type}
          onChange={(e) => handleActionType(e.target.value as RuleActionType)}
          style={{ fontSize: 12 }}
        >
          {ACTION_OPTIONS.map((a) => (
            <option key={a.value} value={a.value}>
              {a.label}
            </option>
          ))}
        </select>

        {rule.action.type === 'set_priority' && (
          <select
            className="constraint-toggles__param-select"
            value={String(rule.action.value)}
            onChange={(e) => handleActionValue(e.target.value)}
            style={{ fontSize: 12 }}
          >
            {PRIORITY_OPTIONS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        )}

        {rule.action.type === 'boost_priority' && (
          <input
            type="number"
            value={rule.action.value}
            onChange={(e) => handleActionValue(Number(e.target.value) || 0)}
            style={{
              width: 60,
              fontSize: 12,
              fontFamily: 'var(--font-mono)',
              background: 'var(--bg-raised)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 4,
              color: 'var(--text-primary)',
              padding: '4px 8px',
            }}
          />
        )}

        {rule.action.type === 'alert' && (
          <input
            type="text"
            value={String(rule.action.value)}
            onChange={(e) => handleActionValue(e.target.value)}
            placeholder="Mensagem de alerta..."
            style={{
              flex: 1,
              fontSize: 12,
              background: 'var(--bg-raised)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 4,
              color: 'var(--text-primary)',
              padding: '4px 8px',
            }}
          />
        )}
      </div>

      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <button
          className="schedule-comparison__btn schedule-comparison__btn--primary"
          onClick={onTest}
          style={{ fontSize: 12 }}
        >
          Testar Regra
        </button>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          v{rule.version} · {rule.versions.length} versões
        </span>
      </div>

      {testResult && (
        <div className="rule-editor__test-bar">
          Esta regra afecta <strong>{testResult.affected}</strong> operações.
          {Object.entries(testResult.breakdown).map(([k, v]) => (
            <span key={k} style={{ marginLeft: 8 }}>
              {v} → {k}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
