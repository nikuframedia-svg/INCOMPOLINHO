import type { ObjectiveProfile } from '@/domain/types/scheduling';
import { DEFAULT_SCORE_WEIGHTS } from '@/domain/types/scheduling';

export const OBJECTIVE_PROFILES: ObjectiveProfile[] = [
  {
    id: 'balanced',
    label: 'Equilibrado',
    weights: { ...DEFAULT_SCORE_WEIGHTS },
  },
  {
    id: 'otd',
    label: 'Entregar a Tempo',
    weights: {
      tardiness: 200,
      setup_count: 5,
      setup_time: 0.5,
      setup_balance: 10,
      churn: 2,
      overflow: 80,
      below_min_batch: 2,
    },
  },
  {
    id: 'setup',
    label: 'Minimizar Setups',
    weights: {
      tardiness: 30,
      setup_count: 50,
      setup_time: 5,
      setup_balance: 40,
      churn: 3,
      overflow: 20,
      below_min_batch: 1,
    },
  },
];
