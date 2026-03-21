// =====================================================================
//  INCOMPOL PLAN -- Replan Dispatcher (Layer Selection)
//  Pure function: chooses the appropriate replanning layer.
//  Actual replanning is done by backend CP-SAT.
// =====================================================================

import type { Block } from '../types/blocks.js';
import type { ScheduleAllInput, RightShiftResult, MatchUpResult, PartialReplanResult, FullReplanResult, ReplanEventType } from '../types/compat.js';
import type { ETool } from '../types/engine.js';

// ── Thresholds ──────────────────────────────────────────

export const LAYER_THRESHOLD_1 = 30;
export const LAYER_THRESHOLD_2 = 120;

// ── Input / Output ──────────────────────────────────────

export type ReplanLayer = 1 | 2 | 3 | 4;

export interface ReplanDispatchInput {
  blocks: Block[];
  previousBlocks: Block[];
  perturbedOpId: string;
  delayMin: number;
  machineId: string;
  scheduleInput: ScheduleAllInput;
  TM: Record<string, ETool>;
  eventType?: ReplanEventType;
  additionalAffectedOps?: string[];
  forceLayer?: ReplanLayer;
  isCatastrophe?: boolean;
}

export interface ReplanDispatchResult {
  layer: ReplanLayer;
  blocks: Block[];
  emergencyNightShift: boolean;
  layerResult: RightShiftResult | MatchUpResult | PartialReplanResult | FullReplanResult;
}

// ── Dispatcher ──────────────────────────────────────────

export function chooseLayer(delayMin: number, isCatastrophe?: boolean): ReplanLayer {
  if (isCatastrophe) return 4;
  if (delayMin < LAYER_THRESHOLD_1) return 1;
  if (delayMin < LAYER_THRESHOLD_2) return 2;
  return 3;
}
