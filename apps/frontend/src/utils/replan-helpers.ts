// ═══════════════════════════════════════════════════════════
//  Replan Helpers
//  Layer thresholds and chooser (previously in scheduling-engine)
// ═══════════════════════════════════════════════════════════

import type { ReplanLayer } from '@/domain/types/scheduling';

/** Right-shift threshold: delays under 30 min */
export const LAYER_THRESHOLD_1 = 30;

/** Match-up threshold: delays under 120 min (2h) */
export const LAYER_THRESHOLD_2 = 120;

/**
 * Choose replan layer based on delay magnitude.
 * Layer 1: Right-shift (<30min)
 * Layer 2: Match-up (30min-2h)
 * Layer 3: Partial (>2h)
 */
export function chooseLayer(delayMin: number): ReplanLayer {
  if (delayMin < LAYER_THRESHOLD_1) return 1;
  if (delayMin < LAYER_THRESHOLD_2) return 2;
  return 3;
}
