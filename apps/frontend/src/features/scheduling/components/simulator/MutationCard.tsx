/**
 * MutationCard — single mutation in the scenario stack.
 */

import { Trash2 } from 'lucide-react';
import type { EngineData } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import type { SimMutation, SimMutationImpact } from '../../hooks/useSimulator';
import { MutationFormFields } from './MutationFormFields';

const MUTATION_LABELS: Record<string, string> = {
  machine_down: 'Máquina parada',
  tool_down: 'Ferramenta avariada',
  operator_shortage: 'Falta de operadores',
  oee_change: 'Alterar OEE',
  rush_order: 'Encomenda urgente',
  demand_change: 'Alterar procura',
  cancel_order: 'Cancelar encomenda',
  third_shift: '3º turno',
  overtime: 'Horas extra',
  add_holiday: 'Feriado',
  remove_holiday: 'Dia extra',
  force_move: 'Mover operação',
  change_dispatch_rule: 'Regra de dispatch',
};

const SEVERITY_COLORS: Record<string, string> = {
  none: C.t3,
  low: C.yl,
  medium: C.yl,
  high: C.rd,
  critical: C.rd,
};

interface Props {
  mutation: SimMutation;
  index: number;
  impact?: SimMutationImpact;
  engineData: EngineData;
  onUpdate: (idx: number, mut: SimMutation) => void;
  onRemove: (idx: number) => void;
}

export function MutationCard({ mutation, index, impact, engineData, onUpdate, onRemove }: Props) {
  return (
    <div
      style={{
        padding: '10px 12px',
        borderRadius: 8,
        border: `1px solid ${C.bd}`,
        background: C.s1,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 8,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              color: C.t3,
              background: `${C.t3}15`,
              padding: '2px 6px',
              borderRadius: 4,
            }}
          >
            #{index + 1}
          </span>
          <span style={{ fontSize: 13, fontWeight: 600, color: C.t1 }}>
            {MUTATION_LABELS[mutation.type] ?? mutation.type}
          </span>
          {impact && (
            <span
              style={{
                fontSize: 10,
                fontWeight: 600,
                color: SEVERITY_COLORS[impact.severity] ?? C.t3,
                padding: '1px 6px',
                borderRadius: 4,
                background: `${SEVERITY_COLORS[impact.severity] ?? C.t3}15`,
              }}
            >
              {impact.severity === 'none'
                ? 'Sem impacto'
                : `OTD-D ${impact.otd_d_impact >= 0 ? '+' : ''}${impact.otd_d_impact.toFixed(1)}%`}
            </span>
          )}
        </div>
        <button
          onClick={() => onRemove(index)}
          style={{
            background: 'transparent',
            border: 'none',
            color: C.t3,
            cursor: 'pointer',
            padding: 4,
          }}
          title="Remover mutação"
        >
          <Trash2 size={14} />
        </button>
      </div>
      <MutationFormFields
        type={mutation.type}
        params={mutation.params}
        onChange={(params) => onUpdate(index, { ...mutation, params })}
        engineData={engineData}
      />
    </div>
  );
}
