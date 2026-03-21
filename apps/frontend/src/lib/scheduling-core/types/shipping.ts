// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Shipping Cutoff Types
//  Configuration and resolved deadlines for shipping law
// ═══════════════════════════════════════════════════════════

/**
 * Shipping cutoff configuration.
 * When provided to the scheduler, activates the shipping-as-law pipeline.
 */
export interface ShippingCutoffConfig {
  /** Default buffer hours between production end and shipping (default: 0) */
  defaultBufferHours: number;
  /** Per-SKU buffer overrides (hours). Takes precedence over default. */
  skuOverrides?: Record<string, number>;
  /** Per-order (opId) buffer overrides (hours). Takes precedence over SKU. */
  orderOverrides?: Record<string, number>;
}

/** Default shipping cutoff configuration */
export const DEFAULT_SHIPPING_CUTOFF: ShippingCutoffConfig = {
  defaultBufferHours: 0,
};

/**
 * Resolved deadline for a single operation.
 * Computed from shipping day, buffer, and shift boundaries.
 */
export interface OperationDeadline {
  /** Operation ID */
  opId: string;
  /** Day index of the last day with demand (shipping day) */
  shippingDayIdx: number;
  /** Buffer hours applied for this operation */
  bufferHours: number;
  /** Latest finish time in absolute minutes (from day 0 midnight) */
  latestFinishAbs: number;
  /** Latest finish as day index (integer part) */
  latestFinishDay: number;
  /** Latest finish minute within the day */
  latestFinishMin: number;
  /** Source of the buffer value: 'order' | 'sku' | 'default' */
  bufferSource: 'order' | 'operation' | 'sku' | 'default';
  /** Number of working days available for production (day 0 up to latestFinishDay) */
  availableWorkdays: number;
  /** Whether the shipping day itself is a working day */
  shippingDayIsWorkday: boolean;
}
