// ═══════════════════════════════════════════════════════════
//  MRP Compute Stubs
//  These functions were in the deleted scheduling-engine package.
//  Backend now handles MRP/CTP computation via API endpoints.
//  These stubs keep the UI compiling until migration to API calls.
// ═══════════════════════════════════════════════════════════

import type {
  ActionMessagesSummary,
  CTPInput,
  CTPResult,
  EngineData,
  MRPResult,
} from '@/domain/types/scheduling';

/**
 * Stub: CTP computation by tool code.
 * TODO: Replace with backend API call to POST /v1/schedule/ctp
 */
export function computeCTP(
  _input: CTPInput,
  _mrp: MRPResult,
  _engine: EngineData,
): CTPResult | null {
  return null;
}

/**
 * Stub: CTP computation by SKU.
 * TODO: Replace with backend API call to POST /v1/schedule/ctp
 */
export function computeCTPSku(
  _input: { sku: string; quantity: number; targetDay: number },
  _mrp: MRPResult,
  _engine: EngineData,
): CTPResult | null {
  return null;
}

/**
 * Stub: Action messages computation.
 * TODO: Replace with backend API call
 */
export function computeActionMessages(_mrp: MRPResult, _engine: EngineData): ActionMessagesSummary {
  return {
    messages: [],
    bySeverity: {} as ActionMessagesSummary['bySeverity'],
    byType: {} as ActionMessagesSummary['byType'],
    criticalCount: 0,
  };
}
