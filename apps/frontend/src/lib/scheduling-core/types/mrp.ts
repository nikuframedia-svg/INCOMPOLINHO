// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — MRP Types
//  Material Requirements Planning Level 0
// ═══════════════════════════════════════════════════════════

export interface MRPDayBucket {
  dayIndex: number;
  dateLabel: string;
  grossRequirement: number;
  scheduledReceipts: number;
  projectedAvailable: number;
  netRequirement: number;
  plannedOrderReceipt: number;
  plannedOrderRelease: number;
}

export interface MRPSkuRecord {
  sku: string;
  name: string;
  opId: string;
  /** Back-reference to parent tool */
  toolCode: string;
  /** Primary machine (from parent tool) */
  machine: string;
  /** Alternative machine (from parent tool) */
  altMachine: string | null;
  /** Customer code (from EOp.cl) */
  customer?: string;
  /** Customer name (from EOp.clNm) */
  customerName?: string;
  /** Twin SKU reference (from EOp.twin) */
  twin?: string;
  /** Pieces per hour (from parent tool) */
  ratePerHour: number;
  /** Setup hours (from parent tool) */
  setupHours: number;
  /** Lot economic quantity (from parent tool) */
  lotEconomicQty: number;
  currentStock: number;
  wip: number;
  backlog: number;
  grossRequirement: number;
  projectedEnd: number;
  stockoutDay: number | null;
  coverageDays: number;
  buckets: MRPDayBucket[];
}

export interface MRPRecord {
  toolCode: string;
  skus: Array<{ sku: string; name: string }>;
  machine: string;
  altMachine: string | null;
  lotEconomicQty: number;
  currentStock: number;
  backlog: number;
  ratePerHour: number;
  setupHours: number;
  operators: number;
  productionLeadDays: number;
  buckets: MRPDayBucket[];
  totalGrossReq: number;
  totalPlannedQty: number;
  endingStock: number;
  stockoutDay: number | null;
  coverageDays: number;
  /** Per-SKU MRP breakdown (always populated) */
  skuRecords: MRPSkuRecord[];
}

export interface RCCPEntry {
  machine: string;
  area: string;
  dayIndex: number;
  dateLabel: string;
  availableMin: number;
  requiredSetupMin: number;
  requiredProdMin: number;
  requiredTotalMin: number;
  utilization: number;
  overloaded: boolean;
  plannedTools: string[];
}

export interface MRPResult {
  records: MRPRecord[];
  rccp: RCCPEntry[];
  summary: MRPSummary;
}

export interface MRPSummary {
  totalTools: number;
  toolsWithBacklog: number;
  toolsWithStockout: number;
  totalPlannedQty: number;
  totalGrossReq: number;
  avgUtilization: number;
  bottleneckMachine: string | null;
  bottleneckDay: number | null;
}

import type { FailureEvent } from './failure.js';

export type WhatIfMutationType = 'rush_order' | 'machine_down' | 'demand_factor' | 'failure_event';

export interface WhatIfMutation {
  id: string;
  type: WhatIfMutationType;
  toolCode?: string;
  rushQty?: number;
  rushDay?: number;
  machine?: string;
  downStartDay?: number;
  downEndDay?: number;
  factorToolCode?: string;
  factor?: number;
  /** Full failure event (for 'failure_event' type) */
  failureEvent?: FailureEvent;
}

export interface WhatIfDelta {
  toolCode: string;
  baselineStockout: number | null;
  modifiedStockout: number | null;
  baselineCoverage: number;
  modifiedCoverage: number;
  baselinePlannedQty: number;
  modifiedPlannedQty: number;
}

export interface WhatIfResult {
  baseline: MRPResult;
  modified: MRPResult;
  deltas: WhatIfDelta[];
  rccpDeltas: Array<{
    machine: string;
    dayIndex: number;
    baselineUtil: number;
    modifiedUtil: number;
  }>;
  summaryDelta: {
    stockoutsChange: number;
    avgUtilChange: number;
  };
}

export interface CTPInput {
  toolCode: string;
  quantity: number;
  targetDay: number;
}

export interface CTPResult {
  feasible: boolean;
  toolCode: string;
  machine: string;
  requiredMin: number;
  availableMinOnDay: number;
  capacitySlack: number;
  projectedStockOnDay: number;
  stockAfterOrder: number;
  earliestFeasibleDay: number | null;
  confidence: 'high' | 'medium' | 'low';
  reason: string;
  capacityTimeline: Array<{
    dayIndex: number;
    existingLoad: number;
    newOrderLoad: number;
    capacity: number;
  }>;
}

export type ServiceLevel = 90 | 95 | 99;

export interface ROPResult {
  toolCode: string;
  demandAvg: number;
  demandStdDev: number;
  coefficientOfVariation: number;
  leadTimeDays: number;
  safetyStock: number;
  rop: number;
  serviceLevel: ServiceLevel;
  zScore: number;
  currentStock: number;
  abcClass: 'A' | 'B' | 'C';
  xyzClass: 'X' | 'Y' | 'Z';
  stockProjection: Array<{
    dayIndex: number;
    projected: number;
    ropLine: number;
    ssLine: number;
  }>;
}

export interface ROPSummary {
  records: ROPResult[];
  abcDistribution: { A: number; B: number; C: number };
  xyzDistribution: { X: number; Y: number; Z: number };
  toolsBelowROP: number;
  toolsBelowSS: number;
}

export type ActionType =
  | 'launch_por'
  | 'transfer_tool'
  | 'advance_prod'
  | 'no_alt_risk'
  | 'failure_impact'
  | 'failure_reroute';
export type ActionSeverity = 'critical' | 'high' | 'medium' | 'low';

export interface ActionMessage {
  id: string;
  type: ActionType;
  severity: ActionSeverity;
  severityScore: number;
  toolCode: string;
  machine: string;
  dayIndex: number | null;
  /** SKU affected (populated for per-SKU action messages) */
  sku?: string;
  /** SKU name (populated for per-SKU action messages) */
  skuName?: string;
  title: string;
  description: string;
  suggestedAction: string;
  impact: {
    qtyAffected: number;
    daysAffected: number;
    capacityMinutes: number | null;
  };
}

export interface ActionMessagesSummary {
  messages: ActionMessage[];
  bySeverity: Record<ActionSeverity, number>;
  byType: Record<ActionType, number>;
  criticalCount: number;
}

export interface CoverageCell {
  toolCode: string;
  dayIndex: number;
  daysOfSupply: number;
  colorBand: 'red' | 'amber' | 'green' | 'blue';
}

export interface CoverageMatrixResult {
  tools: Array<{ toolCode: string; machine: string; urgencyScore: number }>;
  days: string[];
  cells: CoverageCell[][];
}

// ── SKU-View Types ──────────────────────────────────────────

export interface MRPSkuViewRecord {
  sku: string;
  name: string;
  opId: string;
  toolCode: string;
  machine: string;
  altMachine: string | null;
  customer?: string;
  customerName?: string;
  twin?: string;
  isTwin: boolean;
  currentStock: number;
  wip: number;
  backlog: number;
  grossRequirement: number;
  projectedEnd: number;
  stockoutDay: number | null;
  coverageDays: number;
  buckets: MRPDayBucket[];
  ratePerHour: number;
  setupHours: number;
  lotEconomicQty: number;
}

export interface MRPSkuSummary {
  totalSkus: number;
  skusWithBacklog: number;
  skusWithStockout: number;
  totalGrossReq: number;
  totalPlannedQty: number;
}

export interface MRPSkuViewResult {
  skuRecords: MRPSkuViewRecord[];
  summary: MRPSkuSummary;
}

export interface CTPSkuInput {
  sku: string;
  quantity: number;
  targetDay: number;
}

export interface CoverageSkuCell {
  sku: string;
  toolCode: string;
  dayIndex: number;
  daysOfSupply: number;
  colorBand: 'red' | 'amber' | 'green' | 'blue';
}

export interface CoverageMatrixSkuResult {
  skus: Array<{
    sku: string;
    name: string;
    toolCode: string;
    machine: string;
    urgencyScore: number;
  }>;
  days: string[];
  cells: CoverageSkuCell[][];
}

export interface ROPSkuResult {
  sku: string;
  name: string;
  opId: string;
  toolCode: string;
  machine: string;
  demandAvg: number;
  demandStdDev: number;
  coefficientOfVariation: number;
  leadTimeDays: number;
  safetyStock: number;
  rop: number;
  serviceLevel: ServiceLevel;
  zScore: number;
  currentStock: number;
  abcClass: 'A' | 'B' | 'C';
  xyzClass: 'X' | 'Y' | 'Z';
  stockProjection: Array<{
    dayIndex: number;
    projected: number;
    ropLine: number;
    ssLine: number;
  }>;
}

export interface ROPSkuSummary {
  records: ROPSkuResult[];
  abcDistribution: { A: number; B: number; C: number };
  xyzDistribution: { X: number; Y: number; Z: number };
  skusBelowROP: number;
  skusBelowSS: number;
}
