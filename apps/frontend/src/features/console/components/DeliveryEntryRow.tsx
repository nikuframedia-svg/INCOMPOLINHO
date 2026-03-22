/**
 * DeliveryEntryRow — Single row in the DeliveryRiskPanel showing a late
 * delivery entry with status, delay info, and action buttons.
 */

import type { LateDeliveryEntry } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { AcceptDelayModal } from './AcceptDelayModal';

interface DeliveryEntryRowProps {
  entry: LateDeliveryEntry;
  onNavigate?: (opId: string) => void;
  onAcceptDelay: (opId: string) => void;
  acceptingId: string | null;
  onConfirmAccept: (reason: string, justification: string) => void;
  onCancelAccept: () => void;
  isSubmitting?: boolean;
}

export function DeliveryEntryRow({
  entry,
  onNavigate,
  onAcceptDelay,
  acceptingId,
  onConfirmAccept,
  onCancelAccept,
  isSubmitting = false,
}: DeliveryEntryRowProps) {
  const isAccepting = acceptingId === entry.opId;
  const tierColor =
    entry.clientTier <= 1 ? C.rd : entry.clientTier <= 2 ? 'var(--semantic-amber)' : C.t2;

  return (
    <div
      style={{
        padding: '6px 8px',
        borderBottom: '1px solid var(--border)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
        <span style={{ color: entry.isResolved ? 'var(--semantic-amber)' : C.rd, fontSize: 14 }}>
          {entry.isResolved ? '\u26A0' : '\uD83D\uDD34'}
        </span>
        <strong style={{ color: C.t1 }}>{entry.sku}</strong>
        {entry.clNm && (
          <span style={{ color: tierColor, fontSize: 12 }}>
            {entry.clNm} (T{entry.clientTier})
          </span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 12, color: C.t3 }}>
          {entry.deadlineDate ?? `D${entry.deadline}`}
        </span>
      </div>

      <div style={{ display: 'flex', gap: 8, fontSize: 12, color: C.t2, marginTop: 2 }}>
        <span>Atraso +{entry.delayDays}d</span>
        <span>{entry.shortfall} pcs em falta</span>
        <span>{entry.machineId}</span>
        {entry.isResolved && entry.resolvedBy && (
          <span style={{ color: C.gn }}>Resolvido: {entry.resolvedBy}</span>
        )}
      </div>

      {!entry.isResolved && !isAccepting && (
        <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
          <button
            type="button"
            onClick={() => onAcceptDelay(entry.opId)}
            style={{
              fontSize: 12,
              padding: '2px 8px',
              cursor: 'pointer',
              background: 'rgba(239,68,68,0.1)',
              color: C.rd,
              border: `1px solid ${C.rd}`,
              borderRadius: 3,
            }}
          >
            Aceitar Atraso
          </button>
          {onNavigate && (
            <button
              type="button"
              onClick={() => onNavigate(entry.opId)}
              style={{
                fontSize: 12,
                padding: '2px 8px',
                cursor: 'pointer',
                background: 'transparent',
                color: C.ac,
                border: `1px solid ${C.ac}`,
                borderRadius: 3,
              }}
            >
              Ver no Gantt
            </button>
          )}
        </div>
      )}

      {isAccepting && (
        <AcceptDelayModal
          entry={entry}
          onConfirm={onConfirmAccept}
          onCancel={onCancelAccept}
          submitting={isSubmitting}
        />
      )}
    </div>
  );
}
