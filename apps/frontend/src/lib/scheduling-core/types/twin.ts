// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Twin Pieces Types (Pecas Gemeas)
//  Validation and normalization for 1:1 twin piece pairs
// ═══════════════════════════════════════════════════════════

/**
 * Classification codes for twin pair anomalies.
 * Each code maps to a specific validation failure.
 */
export type TwinAnomalyCode =
  | 'self_reference' // Operation references itself as twin
  | 'one_way_link' // A→B but B doesn't reference A
  | 'counterpart_missing' // Twin SKU not found in operations
  | 'machine_mismatch' // Twin found but different machine
  | 'tool_mismatch' // Twin found but different tool
  | 'rate_mismatch' // Twin found but different pieces/hour
  | 'people_mismatch'; // Twin found but different operator count

/**
 * A single twin validation anomaly entry.
 * Describes WHY a twin reference failed validation.
 */
export interface TwinAnomalyEntry {
  /** Operation ID that has the anomaly */
  opId: string;
  /** Operation SKU */
  sku: string;
  /** Twin SKU referenced */
  twinSku: string;
  /** Classification code */
  code: TwinAnomalyCode;
  /** Human-readable Portuguese detail */
  detail: string;
  /** Operation's machine */
  machine: string;
  /** Operation's tool */
  tool: string;
  /** If counterpart was found, its machine (for mismatch cases) */
  counterpartMachine?: string;
  /** If counterpart was found, its tool (for mismatch cases) */
  counterpartTool?: string;
}

/**
 * A validated twin group — two operations that share identical
 * operational parameters (machine, tool, pH, operators).
 * ONLY created when validation passes ALL checks.
 */
export interface TwinGroup {
  /** Primary operation ID */
  opId1: string;
  /** Secondary operation ID */
  opId2: string;
  /** Primary SKU */
  sku1: string;
  /** Secondary SKU */
  sku2: string;
  /** Shared machine */
  machine: string;
  /** Shared tool */
  tool: string;
  /** Shared pieces per hour */
  pH: number;
  /** Shared operator count */
  operators: number;
  /** Whether lot economic qty differs (allowed) */
  lotEconomicDiffers: boolean;
  /** Whether lead time days differs (allowed) */
  leadTimeDiffers: boolean;
}

/**
 * Complete twin validation report.
 * Generated during transform pipeline BEFORE scheduling.
 */
export interface TwinValidationReport {
  /** Total operations with twin references */
  totalTwinRefs: number;
  /** Valid twin groups created */
  validGroups: number;
  /** Operations with validation failures */
  invalidRefs: number;
  /** Detailed anomaly entries */
  anomalies: TwinAnomalyEntry[];
  /** Count by anomaly code */
  byCode: Partial<Record<TwinAnomalyCode, number>>;
  /** All validated twin groups */
  twinGroups: TwinGroup[];
}
