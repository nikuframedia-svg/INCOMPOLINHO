// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Block Production Helpers
//  Twin-aware production attribution for co-production blocks.
//  Used by coverage-audit, validate-schedule, score-schedule,
//  transparency-report, and any consumer that needs per-op
//  production quantities from scheduled blocks.
// ═══════════════════════════════════════════════════════════

import type { Block } from '../types/blocks.js';

/**
 * Get total 'ok' production for an operation, handling twin co-production.
 *
 * For regular blocks: sums b.qty where b.opId matches.
 * For twin blocks: uses outputs[] to attribute qty to the correct op.
 *
 * @param blocks - All scheduled blocks
 * @param opId   - Operation ID to compute production for
 * @returns Total pieces produced for this operation
 */
export function getBlockProductionForOp(blocks: Block[], opId: string): number {
  let total = 0;
  for (const b of blocks) {
    if (b.type !== 'ok') continue;
    if (b.isTwinProduction && b.outputs) {
      const output = b.outputs.find((o) => o.opId === opId);
      if (output) total += output.qty;
    } else if (b.opId === opId) {
      total += b.qty;
    }
  }
  return total;
}

/**
 * Get all 'ok' blocks that contribute production for an operation.
 * Includes twin blocks where the op appears in outputs[].
 *
 * @param blocks - All scheduled blocks (or pre-filtered 'ok' blocks)
 * @param opId   - Operation ID
 * @returns Blocks that produce for this operation
 */
export function getBlocksForOp(blocks: Block[], opId: string): Block[] {
  return blocks.filter((b) => {
    if (b.type !== 'ok') return false;
    if (b.isTwinProduction && b.outputs) {
      return b.outputs.some((o) => o.opId === opId);
    }
    return b.opId === opId;
  });
}

/**
 * Get the production quantity for a specific operation from a single block.
 * Handles twin co-production by looking up the correct output entry.
 *
 * @param block - A single block
 * @param opId  - Operation ID
 * @returns Pieces produced for this op in this block (0 if not relevant)
 */
export function getBlockQtyForOp(block: Block, opId: string): number {
  if (block.isTwinProduction && block.outputs) {
    return block.outputs.find((o) => o.opId === opId)?.qty ?? 0;
  }
  return block.opId === opId ? block.qty : 0;
}
