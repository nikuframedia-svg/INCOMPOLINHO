import type { ReplanActionDetail } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';

// Decision type labels & categories (28 types grouped)
export const DECISION_CATEGORIES: Record<string, { label: string; types: string[] }> = {
  scheduling: {
    label: 'Escalonamento',
    types: [
      'SCHEDULE_BLOCK',
      'SPLIT_BLOCK',
      'MERGE_BLOCKS',
      'BATCH_SCHEDULE',
      'SKIP_ZERO_DEMAND',
      'LOT_SIZE_ADJUST',
    ],
  },
  routing: {
    label: 'Routing',
    types: [
      'MOVE_TO_ALT',
      'OVERFLOW_TO_ALT',
      'ROUTE_TWIN',
      'ADVANCE_PRODUCTION',
      'DEFER_PRODUCTION',
    ],
  },
  setup: {
    label: 'Setup',
    types: ['SETUP_ASSIGN', 'SETUP_RESEQUENCE', 'SETUP_DELAY', 'SETUP_CREW_CONFLICT'],
  },
  constraint: {
    label: 'Constraints',
    types: ['TOOL_CONFLICT_DEFER', 'CALCO_CONFLICT_DEFER', 'OPERATOR_LIMIT', 'CAPACITY_OVERFLOW'],
  },
  infeasibility: {
    label: 'Inviabilidade',
    types: [
      'INFEASIBLE_NO_CAPACITY',
      'INFEASIBLE_TOOL_DOWN',
      'INFEASIBLE_MACHINE_DOWN',
      'INFEASIBLE_DEADLINE',
      'INFEASIBLE_DATA_MISSING',
    ],
  },
  replan: {
    label: 'Replan',
    types: ['REPLAN_MOVE', 'REPLAN_ADVANCE', 'REPLAN_UNDO', 'USER_MOVE'],
  },
};

export const DECISION_TYPE_LABELS: Record<string, string> = {
  SCHEDULE_BLOCK: 'Bloco escalonado',
  SPLIT_BLOCK: 'Bloco dividido',
  MERGE_BLOCKS: 'Blocos fundidos',
  BATCH_SCHEDULE: 'Batch schedule',
  SKIP_ZERO_DEMAND: 'Demand = 0',
  LOT_SIZE_ADJUST: 'Ajuste de lote',
  MOVE_TO_ALT: 'Mover para alt.',
  OVERFLOW_TO_ALT: 'Overflow → alt.',
  ROUTE_TWIN: 'Rota twin',
  ADVANCE_PRODUCTION: 'Avançar produção',
  DEFER_PRODUCTION: 'Adiar produção',
  SETUP_ASSIGN: 'Setup atribuído',
  SETUP_RESEQUENCE: 'Setup resequenciado',
  SETUP_DELAY: 'Setup adiado',
  SETUP_CREW_CONFLICT: 'Conflito crew setup',
  TOOL_CONFLICT_DEFER: 'Conflito ferramenta',
  CALCO_CONFLICT_DEFER: 'Conflito calço',
  OPERATOR_LIMIT: 'Limite operadores',
  CAPACITY_OVERFLOW: 'Overflow capacidade',
  INFEASIBLE_NO_CAPACITY: 'Sem capacidade',
  INFEASIBLE_TOOL_DOWN: 'Ferramenta down',
  INFEASIBLE_MACHINE_DOWN: 'Máquina down',
  INFEASIBLE_DEADLINE: 'Deadline impossível',
  INFEASIBLE_DATA_MISSING: 'Dados em falta',
  REPLAN_MOVE: 'Replan move',
  REPLAN_ADVANCE: 'Replan avançar',
  REPLAN_UNDO: 'Replan undo',
  USER_MOVE: 'Move manual',
};

export const DECISION_CATEGORY_COLORS: Record<string, string> = {
  scheduling: C.ac,
  routing: C.bl,
  setup: C.pp,
  constraint: C.yl,
  infeasibility: C.rd,
  replan: C.cy,
};

export interface AutoReplanSummary {
  actions: ReplanActionDetail[];
  moveCount: number;
  unresolvedCount: number;
}
