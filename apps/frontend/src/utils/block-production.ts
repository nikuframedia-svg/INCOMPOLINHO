// ═══════════════════════════════════════════════════════════
//  Block Production Helpers
//  Twin-aware production attribution for co-production blocks.
// ═══════════════════════════════════════════════════════════

import type { Block } from '@/domain/types/scheduling';

/**
 * Get total 'ok' production for an operation, handling twin co-production.
 */
export function getBlockProductionForOp(blocks: Block[], opId: string): number {
  let total = 0;
  for (const b of blocks) {
    if (b.type !== 'ok') continue;
    if (b.isTwinProduction && b.outputs) {
      const output = b.outputs.find((o: { opId: string; qty: number }) => o.opId === opId);
      if (output) total += output.qty;
    } else if (b.opId === opId) {
      total += b.qty;
    }
  }
  return total;
}

/**
 * Get all 'ok' blocks that contribute production for an operation.
 */
export function getBlocksForOp(blocks: Block[], opId: string): Block[] {
  return blocks.filter((b) => {
    if (b.type !== 'ok') return false;
    if (b.isTwinProduction && b.outputs) {
      return b.outputs.some((o: { opId: string; qty: number }) => o.opId === opId);
    }
    return b.opId === opId;
  });
}

/**
 * Get the production quantity for a specific operation from a single block.
 */
export function getBlockQtyForOp(block: Block, opId: string): number {
  if (block.isTwinProduction && block.outputs) {
    return block.outputs.find((o: { opId: string; qty: number }) => o.opId === opId)?.qty ?? 0;
  }
  return block.opId === opId ? block.qty : 0;
}
