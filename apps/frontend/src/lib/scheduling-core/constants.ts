// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Production Constants
//  Nikufra factory shift boundaries, capacity, machine IDs
// ═══════════════════════════════════════════════════════════

// ── Shift boundaries (in minutes from midnight) ──
/** Shift X start: 07:00 */
export const S0 = 7 * 60; // 420 min

/** Shift change X→Y: 15:30 */
export const T1 = 15.5 * 60; // 930 min

/** Shift Y end: 24:00 (midnight) */
export const S1 = 24 * 60; // 1440 min

/** Shift Z end: 07:00 next day (exceptional 3rd shift) */
export const S2 = S1 + S0; // 1860 min

/** Minutes in a calendar day (24h) — used for absolute time conversions */
export const MINUTES_PER_DAY = 1440;

// ── Capacity ──

/** Day capacity: 2 shifts (07:00 to 24:00) = 1020 min */
export const DAY_CAP = S1 - S0; // 1020

/** Default OEE (Overall Equipment Effectiveness) */
export const DEFAULT_OEE = 0.66;

/** Turno geral end: 16:00 — general staff leave, only affects staffing */
export const TG_END = 16 * 60; // 960 min

// ── Scheduling parameters ──

/** Default bucket window for tools with lot_economic = 0 (working days) */
export const BUCKET_WINDOW = 5;

/** Max EDD gap for tool merging (days) */
export const MAX_EDD_GAP = 5;

/** Max auto-routing moves per scheduling run */
export const MAX_AUTO_MOVES = 50;

/** Max iterations for overflow routing */
export const MAX_OVERFLOW_ITER = 3;

/** Alt machine utilization threshold (above this, don't route overflow) */
export const ALT_UTIL_THRESHOLD = 0.95;

/** Max working days to advance production (overflow resolution) — no limit */
export const MAX_ADVANCE_DAYS = Infinity;

/** Target day utilization threshold for advance production candidates.
 *  Only advance to days below this utilization. */
export const ADVANCE_UTIL_THRESHOLD = 0.95;

/** OTD tolerance (1.0 = exact match required — deadline is a hard constraint) */
export const OTD_TOLERANCE = 1.0;

// ── Load leveling parameters ──

/** Day is "light" if utilization below this threshold */
export const LEVEL_LOW_THRESHOLD = 0.6;

/** Day is "heavy" if utilization above this threshold */
export const LEVEL_HIGH_THRESHOLD = 0.75;

/** Max days to look ahead for leveling candidates */
export const LEVEL_LOOKAHEAD = 15;

// ── Risk grid thresholds ──

/** Utilization above this is "medium" risk */
export const RISK_MEDIUM_THRESHOLD = 0.85;

/** Utilization above this is "high" risk */
export const RISK_HIGH_THRESHOLD = 0.95;

/** Utilization above this is "critical" risk */
export const RISK_CRITICAL_THRESHOLD = 1.0;

// ── Machine IDs ──

/** The 6 known focus machines (main presses) */
export const KNOWN_FOCUS = new Set(['PRM019', 'PRM020', 'PRM031', 'PRM039', 'PRM042', 'PRM043']);

// ── Shipping cutoff ──

/** Default buffer hours between production end and shipping */
export const DEFAULT_SHIPPING_BUFFER_HOURS = 0;

// ── Auto-replan parameters ──

/** Default max overtime per machine per day (minutes) */
export const DEFAULT_OVERTIME_MAX_PER_MACHINE = 450;

/** Default max overtime total per day across all machines (minutes) */
export const DEFAULT_OVERTIME_MAX_TOTAL = 2700;

/** Minimum production fraction to keep on original machine during split */
export const SPLIT_MIN_FRACTION = 0.3;

/** Minimum deficit (minutes) to justify a split operation */
export const SPLIT_MIN_DEFICIT = 60;

// ── Default values for unknown data ──

/**
 * Sentinel value for MO capacity when no data available.
 * Per Normative Spec §1: We NEVER invent data.
 * This value is used to DETECT missing data, not to assume capacity.
 * When MO value >= this threshold, it is flagged as DATA_MISSING.
 */
export const DEFAULT_MO_CAPACITY = 99;
