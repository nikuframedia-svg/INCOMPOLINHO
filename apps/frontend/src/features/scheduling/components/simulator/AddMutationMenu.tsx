/**
 * AddMutationMenu — dropdown to add a mutation to the scenario stack.
 */

import { Plus } from 'lucide-react';
import { useState } from 'react';
import { C } from '@/theme/color-bridge';
import type { SimMutation } from '../../hooks/useSimulator';

const MUTATION_GROUPS = [
  {
    label: 'Disrupções',
    items: [
      { type: 'machine_down', label: 'Máquina parada' },
      { type: 'tool_down', label: 'Ferramenta avariada' },
      { type: 'operator_shortage', label: 'Falta de operadores' },
    ],
  },
  {
    label: 'Procura',
    items: [
      { type: 'rush_order', label: 'Encomenda urgente' },
      { type: 'demand_change', label: 'Alterar procura' },
      { type: 'cancel_order', label: 'Cancelar encomenda' },
    ],
  },
  {
    label: 'Capacidade',
    items: [
      { type: 'third_shift', label: '3º turno' },
      { type: 'overtime', label: 'Horas extra' },
      { type: 'oee_change', label: 'Alterar OEE' },
      { type: 'add_holiday', label: 'Adicionar feriado' },
      { type: 'remove_holiday', label: 'Dia extra' },
    ],
  },
  {
    label: 'Configuração',
    items: [
      { type: 'force_move', label: 'Mover operação' },
      { type: 'change_dispatch_rule', label: 'Regra de dispatch' },
    ],
  },
] as const;

function defaultParams(type: string): Record<string, unknown> {
  switch (type) {
    case 'machine_down':
      return { machine_id: 'PRM031', start_day: 5, end_day: 7, capacity_factor: 0 };
    case 'tool_down':
      return { tool_id: '', start_day: 0, end_day: 0 };
    case 'operator_shortage':
      return { labor_group: 'Grandes', reduction: 1 };
    case 'rush_order':
      return { sku: '', qty: 10000, deadline_day: 5 };
    case 'demand_change':
      return { sku: '', factor: 1.5 };
    case 'cancel_order':
      return { sku: '', from_day: 0, to_day: 80 };
    case 'third_shift':
      return { machine_id: '__all__' };
    case 'overtime':
      return { machine_id: '__all__', extra_min: 120 };
    case 'oee_change':
      return { tool_id: '__all__', new_oee: 0.55 };
    case 'add_holiday':
      return { day_idx: 0 };
    case 'remove_holiday':
      return { day_idx: 0 };
    case 'force_move':
      return { op_id: '', to_machine: '' };
    case 'change_dispatch_rule':
      return { rule: 'EDD' };
    default:
      return {};
  }
}

interface Props {
  onAdd: (mut: SimMutation) => void;
}

export function AddMutationMenu({ onAdd }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '6px 14px',
          borderRadius: 6,
          border: `1px solid ${C.ac}44`,
          background: `${C.ac}10`,
          color: C.ac,
          fontSize: 12,
          fontWeight: 600,
          cursor: 'pointer',
          fontFamily: 'inherit',
        }}
      >
        <Plus size={14} /> Adicionar mutação
      </button>
      {open && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            zIndex: 50,
            marginTop: 4,
            minWidth: 220,
            background: C.s1,
            border: `1px solid ${C.bd}`,
            borderRadius: 8,
            boxShadow: '0 8px 24px #00000040',
            padding: '6px 0',
          }}
        >
          {MUTATION_GROUPS.map((g) => (
            <div key={g.label}>
              <div
                style={{
                  padding: '6px 12px 2px',
                  fontSize: 10,
                  fontWeight: 700,
                  color: C.t3,
                  textTransform: 'uppercase',
                  letterSpacing: '.06em',
                }}
              >
                {g.label}
              </div>
              {g.items.map((item) => (
                <button
                  key={item.type}
                  onClick={() => {
                    onAdd({ type: item.type, params: defaultParams(item.type) });
                    setOpen(false);
                  }}
                  style={{
                    display: 'block',
                    width: '100%',
                    padding: '6px 12px',
                    textAlign: 'left',
                    background: 'transparent',
                    border: 'none',
                    color: C.t1,
                    fontSize: 12,
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = `${C.ac}15`)}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  {item.label}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
