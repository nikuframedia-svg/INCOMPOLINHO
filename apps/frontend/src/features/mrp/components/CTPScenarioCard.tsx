/**
 * CTPScenarioCard — Card displaying one CTP scenario result.
 */

import type { EngineData } from '@/lib/engine';
import { C } from '@/lib/engine';
import type { CTPConfidenceInterval, CTPScenario } from '../utils/ctp-compute';
import { mono } from '../utils/mrp-helpers';

const SCENARIO_COLORS: Record<string, { border: string; badge: string; bg: string }> = {
  best: { border: C.ac, badge: C.ac, bg: `${C.ac}18` },
  tradeoff: { border: C.yl, badge: C.yl, bg: `${C.yl}18` },
  infeasible: { border: C.rd, badge: C.rd, bg: `${C.rd}18` },
};

export function CTPScenarioCard({
  scenario,
  confidence,
  onCommit,
}: {
  scenario: CTPScenario;
  engine: EngineData;
  confidence?: CTPConfidenceInterval | null;
  onCommit?: () => void;
}) {
  const colors = SCENARIO_COLORS[scenario.id] ?? SCENARIO_COLORS.infeasible;
  const r = scenario.result;
  const confLabel =
    r.confidence === 'high' ? 'ALTA' : r.confidence === 'medium' ? 'MÉDIA' : 'BAIXA';

  return (
    <div
      className="mrp__card"
      style={{ borderLeft: `3px solid ${colors.border}`, marginBottom: 8, padding: '12px 16px' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span
          style={{
            fontSize: 12,
            fontWeight: 700,
            padding: '2px 8px',
            borderRadius: 3,
            background: colors.bg,
            color: colors.badge,
          }}
        >
          {scenario.label}
        </span>
        {scenario.isAlt && <span style={{ fontSize: 12, color: C.yl }}>Máquina alternativa</span>}
      </div>

      <div style={{ display: 'flex', gap: 16, fontSize: 12, color: C.t2, marginBottom: 6 }}>
        <span>
          Máquina: <span style={{ ...mono, color: C.t1, fontWeight: 600 }}>{scenario.machine}</span>
        </span>
        <span>
          Dia:{' '}
          <span style={{ ...mono, color: r.feasible ? C.t1 : C.rd, fontWeight: 600 }}>
            {scenario.dateLabel ?? '-'}
          </span>
        </span>
      </div>

      <div style={{ display: 'flex', gap: 16, fontSize: 12, color: C.t2, marginBottom: 6 }}>
        <span>
          Requer: <span style={{ ...mono, color: C.t1 }}>{r.requiredMin}m</span>
        </span>
        <span>
          Disponível: <span style={{ ...mono, color: C.t1 }}>{r.availableMinOnDay}m</span>
        </span>
        <span>
          Confiança:{' '}
          <span style={{ ...mono, fontWeight: 600, color: colors.badge }}>{confLabel}</span>
        </span>
      </div>

      {confidence && (
        <div
          style={{
            fontSize: 12,
            color: C.t1,
            fontWeight: 500,
            padding: '6px 10px',
            background: `${C.ac}0a`,
            borderRadius: 4,
            marginBottom: 6,
          }}
        >
          Entrega: {confidence.earliestDate} — {confidence.latestDate}{' '}
          <span style={{ ...mono, color: C.ac }}>({confidence.confidencePercent}% confiança)</span>
        </div>
      )}

      <div style={{ fontSize: 12, color: C.t3, marginBottom: 8 }}>{r.reason}</div>

      {r.feasible && onCommit && (
        <button
          className="mrp__input"
          onClick={onCommit}
          style={{
            cursor: 'pointer',
            background: colors.bg,
            color: colors.badge,
            border: `1px solid ${colors.border}40`,
            fontWeight: 600,
            fontSize: 12,
            padding: '4px 12px',
            borderRadius: 4,
          }}
        >
          Registar compromisso
        </button>
      )}
    </div>
  );
}
