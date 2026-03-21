/**
 * useStockAlertGenerator — Watches MRP data and generates ISA-18.2 alerts
 * for stock risks. Runs globally (mounted in Layout).
 *
 * Thresholds:
 *   stockoutDay <= 1  → CRITICAL
 *   stockoutDay <= 3  → HIGH
 *   coverageDays < 5  → MEDIUM
 */

import { useEffect, useRef } from 'react';
import { useScheduleData } from '../../hooks/useScheduleData';
import type { MRPRecord, MRPResult } from '../../lib/engine';
import type { Alert, AlertPriority } from './alert-types';
import { useAlertStore } from './useAlertStore';

function alertIdForTool(toolCode: string): string {
  return `stock-${toolCode}`;
}

function classifyStockPriority(rec: MRPRecord): AlertPriority | null {
  if (rec.stockoutDay !== null && rec.stockoutDay <= 1) return 'CRITICAL';
  if (rec.stockoutDay !== null && rec.stockoutDay <= 3) return 'HIGH';
  if (rec.coverageDays < 5 && rec.totalGrossReq > 0) return 'MEDIUM';
  return null;
}

function buildCause(rec: MRPRecord, priority: AlertPriority): string {
  if (priority === 'CRITICAL') {
    return `Ruptura iminente: ${rec.toolCode} (${rec.skus.map((s) => s.sku).join('/')})`;
  }
  if (priority === 'HIGH') {
    const days = rec.stockoutDay ?? 0;
    return `Ruptura prevista em ${days}d: ${rec.toolCode}`;
  }
  return `Cobertura baixa (${rec.coverageDays}d): ${rec.toolCode}`;
}

function buildConsequence(rec: MRPRecord): string {
  const qty = rec.totalGrossReq - rec.totalPlannedQty;
  if (qty > 0) return `${Math.round(qty)} pecas em risco de atraso`;
  return `Stock projectado insuficiente para ${rec.coverageDays}d`;
}

function buildCorrectiveAction(rec: MRPRecord): string {
  if (rec.altMachine) return `Transferir para ${rec.altMachine} ou antecipar produção`;
  return 'Antecipar produção ou rever prioridades';
}

function buildAlert(rec: MRPRecord, priority: AlertPriority): Alert {
  return {
    id: alertIdForTool(rec.toolCode),
    state: 'UNACK_ACTIVE',
    priority,
    source: rec.machine,
    cause: buildCause(rec, priority),
    consequence: buildConsequence(rec),
    correctiveAction: buildCorrectiveAction(rec),
    activatedAt: new Date().toISOString(),
  };
}

function generateAlerts(mrp: MRPResult): Map<string, Alert> {
  const alerts = new Map<string, Alert>();
  for (const rec of mrp.records) {
    const priority = classifyStockPriority(rec);
    if (priority) {
      const alert = buildAlert(rec, priority);
      alerts.set(alert.id, alert);
    }
  }
  return alerts;
}

/**
 * Watches MRP data changes and syncs stock alerts into the ISA-18.2 store.
 * Only adds new alerts and clears resolved ones — never re-adds acknowledged alerts.
 */
export function useStockAlertGenerator(): void {
  const { mrp } = useScheduleData();
  const addAlert = useAlertStore((s) => s.addAlert);
  const removeAlert = useAlertStore((s) => s.removeAlert);
  const alerts = useAlertStore((s) => s.alerts);
  const prevIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!mrp) return;

    const desired = generateAlerts(mrp);
    const desiredIds = new Set(desired.keys());
    const existingStockIds = new Set(
      alerts.filter((a) => a.id.startsWith('stock-')).map((a) => a.id),
    );

    // Add new alerts (not already in store)
    for (const [id, alert] of desired) {
      if (!existingStockIds.has(id)) {
        addAlert(alert);
      }
    }

    // Remove alerts that are no longer relevant (were previously generated, now resolved)
    for (const prevId of prevIdsRef.current) {
      if (!desiredIds.has(prevId) && existingStockIds.has(prevId)) {
        removeAlert(prevId);
      }
    }

    prevIdsRef.current = desiredIds;
  }, [mrp, addAlert, removeAlert, alerts]);
}
