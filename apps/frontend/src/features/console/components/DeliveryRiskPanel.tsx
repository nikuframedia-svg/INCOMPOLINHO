/**
 * DeliveryRiskPanel — Collapsible panel showing late delivery entries.
 * Unresolved (red) listed first, resolved-with-cost (amber) collapsed below.
 * "Aceitar Atraso" inline modal with cost calculation + ledger entry.
 */

import { useState } from 'react';
import { Collapsible } from '@/components/Common/Collapsible';
import type { LateDeliveryAnalysis } from '@/domain/types/scheduling';
import { assessDeviation, createLedgerEntry } from '@/features/scheduling';
import { C } from '@/theme/color-bridge';
import { computeDelayCost, governanceLevel, REASON_TO_INCENTIVE } from './AcceptDelayModal';
import { DeliveryEntryRow } from './DeliveryEntryRow';

interface DeliveryRiskPanelProps {
  lateDeliveries: LateDeliveryAnalysis;
  onNavigateToBlock?: (opId: string) => void;
}

export function DeliveryRiskPanel({ lateDeliveries, onNavigateToBlock }: DeliveryRiskPanelProps) {
  const [acceptingId, setAcceptingId] = useState<string | null>(null);
  const [showResolved, setShowResolved] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const { entries, unresolvedCount, resolvedWithCostCount } = lateDeliveries;
  const unresolved = entries.filter((e) => !e.isResolved);
  const resolved = entries.filter((e) => e.isResolved);
  const total = entries.length;

  const handleConfirmAccept = async (reason: string, justification: string) => {
    const entry = entries.find((e) => e.opId === acceptingId);
    if (!entry) {
      setAcceptingId(null);
      return;
    }

    const cost = computeDelayCost(entry);
    const highTier = entry.clientTier <= 2;
    const govLevel = governanceLevel(cost, highTier);
    const incentive = REASON_TO_INCENTIVE[reason] ?? 'technical';

    setSubmitting(true);
    try {
      await assessDeviation({
        optimal_state: { opId: entry.opId, sku: entry.sku, delayDays: 0, shortfallPcs: 0 },
        proposed_state: {
          opId: entry.opId,
          sku: entry.sku,
          delayDays: entry.delayDays,
          shortfallPcs: entry.shortfall,
        },
        incentive_category: incentive,
        governance_level: govLevel,
      }).catch(() => {});

      await createLedgerEntry({
        tenant_id: 'incompol',
        user_id: 'planner-001',
        decision_type: 'accept_delay',
        optimal_state: {
          opId: entry.opId,
          sku: entry.sku,
          deadline: entry.deadlineDate,
          shortfallPcs: 0,
        },
        proposed_state: {
          opId: entry.opId,
          sku: entry.sku,
          deadline: entry.deadlineDate,
          delayDays: entry.delayDays,
          shortfallPcs: entry.shortfall,
        },
        deviation_cost: cost,
        incentive_category: incentive,
        declared_reason: justification,
        governance_level: govLevel,
        contrafactual:
          govLevel >= 'L3'
            ? {
                delayDays: entry.delayDays,
                shortfallPcs: entry.shortfall,
                clientTier: entry.clientTier,
              }
            : null,
      });
    } catch {
      // Accept goes through even if logging fails
    } finally {
      setSubmitting(false);
      setAcceptingId(null);
    }
  };

  if (total === 0) return null;

  return (
    <div data-testid="delivery-risk-panel">
      <Collapsible
        title="Entregas em Risco"
        defaultOpen={unresolvedCount > 0}
        badge={unresolvedCount > 0 ? `${unresolvedCount}` : undefined}
      >
        {/* Summary header */}
        <div
          style={{
            display: 'flex',
            gap: 12,
            padding: '6px 8px',
            fontSize: 12,
            color: C.t2,
            borderBottom: '1px solid var(--border)',
          }}
        >
          {unresolvedCount > 0 && (
            <span style={{ color: C.rd }}>
              {unresolvedCount} critico{unresolvedCount !== 1 ? 's' : ''}
            </span>
          )}
          {resolvedWithCostCount > 0 && (
            <span style={{ color: 'var(--semantic-amber)' }}>
              {resolvedWithCostCount} resolvido{resolvedWithCostCount !== 1 ? 's' : ''}
            </span>
          )}
          <span style={{ marginLeft: 'auto' }}>
            OTD-D: {lateDeliveries.otdDelivery.toFixed(1)}%
          </span>
        </div>

        {/* Unresolved entries */}
        {unresolved.map((entry) => (
          <DeliveryEntryRow
            key={entry.opId}
            entry={entry}
            onNavigate={onNavigateToBlock}
            onAcceptDelay={setAcceptingId}
            acceptingId={acceptingId}
            onConfirmAccept={handleConfirmAccept}
            onCancelAccept={() => setAcceptingId(null)}
            isSubmitting={submitting}
          />
        ))}

        {/* Resolved section (collapsed) */}
        {resolved.length > 0 && (
          <div style={{ marginTop: 4 }}>
            <button
              type="button"
              onClick={() => setShowResolved(!showResolved)}
              style={{
                fontSize: 12,
                color: C.t3,
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                padding: '4px 8px',
              }}
            >
              {showResolved ? '\u25BC' : '\u25B6'} {resolved.length} resolvido
              {resolved.length !== 1 ? 's' : ''} (com custo)
            </button>
            {showResolved &&
              resolved.map((entry) => (
                <DeliveryEntryRow
                  key={entry.opId}
                  entry={entry}
                  onNavigate={onNavigateToBlock}
                  onAcceptDelay={setAcceptingId}
                  acceptingId={acceptingId}
                  onConfirmAccept={handleConfirmAccept}
                  onCancelAccept={() => setAcceptingId(null)}
                  isSubmitting={submitting}
                />
              ))}
          </div>
        )}
      </Collapsible>
    </div>
  );
}
