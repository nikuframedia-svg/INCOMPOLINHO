// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Constraint Types
//  Physical constraints (setup crew, tool/calco timeline) are HARD.
//  Operator pool is ADVISORY — warns but never blocks scheduling.
// ═══════════════════════════════════════════════════════════

/** Constraint mode: 'hard' (active) or 'disabled' (for testing/scenarios) */
export type ConstraintMode = 'hard' | 'disabled';

export type ConstraintName = 'SETUP_CREW' | 'TOOL_TIMELINE' | 'CALCO_TIMELINE' | 'OPERATOR_POOL';

export interface ConstraintConfig {
  setupCrew: { mode: ConstraintMode };
  toolTimeline: { mode: ConstraintMode };
  calcoTimeline: { mode: ConstraintMode };
  operatorPool: { mode: ConstraintMode };
}

/**
 * Default constraint configuration.
 *
 * - SetupCrew: HARD — single setup crew, physically shared
 * - ToolTimeline: HARD — tool cannot be in 2 machines simultaneously
 * - CalcoTimeline: HARD — calco cannot be in 2 machines simultaneously
 * - OperatorPool: ADVISORY — tracks capacity, warns when exceeded, never blocks
 */
export const DEFAULT_CONSTRAINT_CONFIG: ConstraintConfig = {
  setupCrew: { mode: 'hard' },
  toolTimeline: { mode: 'hard' },
  calcoTimeline: { mode: 'hard' },
  operatorPool: { mode: 'hard' },
};
