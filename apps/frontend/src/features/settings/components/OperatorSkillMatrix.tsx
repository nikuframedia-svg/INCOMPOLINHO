/**
 * OperatorSkillMatrix — Operator × machine skill level grid.
 * Click cycles: autonomous → supervised → unqualified → autonomous.
 */

import { useState } from 'react';
import './SetupMatrixEditor.css';

export type SkillLevel = 'autonomous' | 'supervised' | 'unqualified';

export interface OperatorEntry {
  id: string;
  name: string;
  group: string;
}

interface OperatorSkillMatrixProps {
  operators: OperatorEntry[];
  machines: string[];
}

const SKILL_CFG: Record<SkillLevel, { label: string; short: string; color: string; bg: string }> = {
  autonomous: {
    label: 'Autónomo',
    short: '100%',
    color: 'var(--accent)',
    bg: 'rgba(34,197,94,0.12)',
  },
  supervised: {
    label: 'Supervisionado',
    short: '80%',
    color: 'var(--semantic-amber)',
    bg: 'rgba(245,158,11,0.12)',
  },
  unqualified: {
    label: 'Não qualificado',
    short: '-',
    color: 'var(--semantic-red)',
    bg: 'rgba(239,68,68,0.08)',
  },
};

const CYCLE: SkillLevel[] = ['autonomous', 'supervised', 'unqualified'];

function buildDefaultSkills(
  operators: OperatorEntry[],
  machines: string[],
): Record<string, Record<string, SkillLevel>> {
  const skills: Record<string, Record<string, SkillLevel>> = {};
  for (const op of operators) {
    skills[op.id] = {};
    for (const m of machines) {
      skills[op.id][m] = 'autonomous';
    }
  }
  return skills;
}

export function OperatorSkillMatrix({ operators, machines }: OperatorSkillMatrixProps) {
  const [skills, setSkills] = useState(() => buildDefaultSkills(operators, machines));

  const cycleSkill = (opId: string, machine: string) => {
    setSkills((prev) => {
      const next = { ...prev };
      const opSkills = { ...next[opId] };
      const current = opSkills[machine] ?? 'autonomous';
      const idx = CYCLE.indexOf(current);
      opSkills[machine] = CYCLE[(idx + 1) % CYCLE.length];
      next[opId] = opSkills;
      return next;
    });
  };

  const qualifiedCount = (machine: string) =>
    operators.filter((op) => {
      const level = skills[op.id]?.[machine];
      return level === 'autonomous' || level === 'supervised';
    }).length;

  return (
    <div>
      <div style={{ overflowX: 'auto' }}>
        <table className="skill-matrix">
          <thead>
            <tr>
              <th className="skill-matrix__corner">Operador</th>
              {machines.map((m) => (
                <th key={m} className="skill-matrix__header">
                  <div>{m}</div>
                  <div style={{ fontSize: 12, fontWeight: 400, color: 'var(--text-muted)' }}>
                    {qualifiedCount(m)} qualif.
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {operators.map((op) => (
              <tr key={op.id}>
                <td className="skill-matrix__row-label">
                  <span style={{ fontWeight: 500, color: 'var(--text-primary)' }}>{op.name}</span>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 6 }}>
                    {op.group}
                  </span>
                </td>
                {machines.map((m) => {
                  const level = skills[op.id]?.[m] ?? 'autonomous';
                  const cfg = SKILL_CFG[level];
                  return (
                    <td
                      key={m}
                      className="skill-matrix__cell"
                      onClick={() => cycleSkill(op.id, m)}
                      style={{ cursor: 'pointer', background: cfg.bg, textAlign: 'center' }}
                    >
                      <span style={{ fontSize: 12, fontWeight: 600, color: cfg.color }}>
                        {cfg.short}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div
        style={{ marginTop: 12, display: 'flex', gap: 16, fontSize: 12, color: 'var(--text-muted)' }}
      >
        {CYCLE.map((level) => {
          const cfg = SKILL_CFG[level];
          return (
            <span key={level}>
              <span
                style={{
                  display: 'inline-block',
                  width: 8,
                  height: 8,
                  borderRadius: 2,
                  background: cfg.color,
                  marginRight: 4,
                }}
              />
              {cfg.label} ({cfg.short})
            </span>
          );
        })}
      </div>

      <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
        Cobertura média:{' '}
        <span
          style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', fontWeight: 600 }}
        >
          {machines.length > 0
            ? Math.round(
                ((machines.reduce((s, m) => s + qualifiedCount(m), 0) / machines.length) * 100) /
                  Math.max(operators.length, 1),
              )
            : 100}
          %
        </span>
      </div>
    </div>
  );
}
