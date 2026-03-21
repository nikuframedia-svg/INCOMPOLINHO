// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Score Weights (type + defaults only)
//  Actual scoring done by backend CP-SAT pipeline.
// ═══════════════════════════════════════════════════════════

export interface ScoreWeights {
  tardiness: number;
  setup_count: number;
  setup_time: number;
  setup_balance: number;
  churn: number;
  overflow: number;
  below_min_batch: number;
  capacity_variance: number;
  setup_density: number;
}

export const DEFAULT_WEIGHTS: ScoreWeights = {
  tardiness: 100.0,
  setup_count: 10.0,
  setup_time: 1.0,
  setup_balance: 30.0,
  churn: 5.0,
  overflow: 50.0,
  below_min_batch: 5.0,
  capacity_variance: 20.0,
  setup_density: 15.0,
};
