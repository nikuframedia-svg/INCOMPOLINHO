/**
 * useDeliveryAlertGenerator — Generates ISA-18.2 alerts for late deliveries.
 * One alert per unresolved late delivery entry, priority based on client tier,
 * delay severity, and L4 'urgente' definition from settings.
 * Runs globally (mounted in Layout).
 */

import { Parser } from 'expr-eval';
import { useEffect, useRef } from 'react';
import type { LateDeliveryEntry } from '@/domain/types/scheduling';
import { defaultTierFromName } from '../../domain/configurable-logic-eval';
import { useScheduleData } from '../../hooks/useScheduleData';
import { useSettingsStore } from '../../stores/useSettingsStore';
import type { Alert, AlertPriority } from './alert-types';
import { useAlertStore } from './useAlertStore';

const ALERT_PREFIX = 'delivery-late-';
const exprParser = new Parser();

function priorityFromEntry(entry: LateDeliveryEntry, urgenteExpr: string | null): AlertPriority {
  // L4 definition boost: if 'urgente' definition matches, boost to at least HIGH
  if (urgenteExpr) {
    try {
      const tier = entry.clientTier || defaultTierFromName(entry.clNm || '');
      const vars = {
        slackHours: Math.max(0, -entry.delayDays * 17),
        clientTier: tier,
        demandTotal: entry.shortfall,
        stock: 0,
      };
      const result = exprParser.parse(urgenteExpr).evaluate(vars);
      if (result && tier <= 1) return 'CRITICAL';
      if (result) return 'HIGH';
    } catch {
      /* fallback to hardcoded logic */
    }
  }
  if (entry.clientTier <= 1) return 'CRITICAL';
  if (entry.clientTier <= 2) return 'HIGH';
  if (entry.delayDays >= 5) return 'HIGH';
  if (entry.delayDays >= 2) return 'MEDIUM';
  return 'LOW';
}

function buildDeliveryAlert(entry: LateDeliveryEntry, urgenteExpr: string | null): Alert {
  const priority = priorityFromEntry(entry, urgenteExpr);
  const tierLabel = entry.clientTier <= 2 ? ` (Tier ${entry.clientTier})` : '';
  return {
    id: `${ALERT_PREFIX}${entry.opId}`,
    state: 'UNACK_ACTIVE',
    priority,
    source: entry.machineId,
    cause: `${entry.sku} — atraso +${entry.delayDays}d${tierLabel}${entry.clNm ? ` · ${entry.clNm}` : ''}`,
    consequence: `${entry.shortfall} pcs em falta. Deadline ${entry.deadlineDate ?? `D${entry.deadline}`}.`,
    correctiveAction: entry.suggestedActions
      .filter((a) => a !== 'FORMAL_ACCEPT')
      .slice(0, 2)
      .join(' ou '),
    activatedAt: new Date().toISOString(),
  };
}

/**
 * Watches late delivery analysis and syncs ISA-18.2 alerts accordingly.
 * Adds alerts for unresolved late deliveries, removes alerts when resolved.
 * Uses L4 'urgente' definition to boost alert priority.
 */
export function useDeliveryAlertGenerator(): void {
  const { lateDeliveries } = useScheduleData();
  const addAlert = useAlertStore((s) => s.addAlert);
  const removeAlert = useAlertStore((s) => s.removeAlert);
  const alerts = useAlertStore((s) => s.alerts);
  const definitions = useSettingsStore((s) => s.definitions);
  const prevIdsRef = useRef<Set<string>>(new Set());

  const urgenteExpr = definitions.find((d) => d.id === 'urgente')?.expression ?? null;

  useEffect(() => {
    if (!lateDeliveries) return;

    const unresolved = lateDeliveries.entries.filter((e) => !e.isResolved);
    const currentIds = new Set(unresolved.map((e) => `${ALERT_PREFIX}${e.opId}`));

    // Add new alerts
    for (const entry of unresolved) {
      const alertId = `${ALERT_PREFIX}${entry.opId}`;
      if (!alerts.some((a) => a.id === alertId)) {
        addAlert(buildDeliveryAlert(entry, urgenteExpr));
      }
    }

    // Remove stale alerts (were late, now resolved or gone)
    for (const prevId of prevIdsRef.current) {
      if (!currentIds.has(prevId) && alerts.some((a) => a.id === prevId)) {
        removeAlert(prevId);
      }
    }

    prevIdsRef.current = currentIds;
  }, [lateDeliveries, addAlert, removeAlert, alerts, urgenteExpr]);
}
