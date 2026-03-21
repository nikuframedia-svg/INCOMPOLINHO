/**
 * DeliveryRiskPanel — Collapsible panel showing late delivery entries.
 * Unresolved (red) listed first, resolved-with-cost (amber) collapsed below.
 * "Aceitar Atraso" inline modal with cost calculation + ledger entry.
 */

import { useState } from 'react';
import { Collapsible } from '@/components/Common/Collapsible';
import type { LateDeliveryAnalysis, LateDeliveryEntry } from '@/lib/engine';
import { C } from '@/lib/engine';
import { assessDeviation, createLedgerEntry } from '@/features/scheduling';

interface DeliveryRiskPanelProps {
  lateDeliveries: LateDeliveryAnalysis;
  onNavigateToBlock?: (opId: string) => void;
}

// ── Acceptance Modal ──

const DELAY_REASONS = [
  { value: 'tecnico', label: 'Tecnico — limitacao de capacidade' },
  { value: 'comercial', label: 'Comercial — acordo com cliente' },
  { value: 'conveniencia', label: 'Conveniencia — priorizacao interna' },
  { value: 'hierarquico', label: 'Hierarquico — decisao de gestao' },
] as const;

function computeDelayCost(entry: LateDeliveryEntry): number {
  return entry.delayDays * 50 * (6 - entry.clientTier);
}

function governanceLevel(cost: number, highTier: boolean): string {
  if (highTier) return 'L4';
  if (cost > 200) return 'L5';
  if (cost > 100) return 'L4';
  if (cost > 50) return 'L3';
  if (cost > 20) return 'L2';
  if (cost > 0) return 'L1';
  return 'L0';
}

const REASON_TO_INCENTIVE: Record<string, string> = {
  tecnico: 'technical',
  comercial: 'commercial_pressure',
  conveniencia: 'operational_convenience',
  hierarquico: 'hierarchical_pressure',
};

function AcceptDelayModal({
  entry,
  onConfirm,
  onCancel,
  submitting = false,
}: {
  entry: LateDeliveryEntry;
  onConfirm: (reason: string, justification: string) => void;
  onCancel: () => void;
  submitting?: boolean;
}) {
  const [reason, setReason] = useState(DELAY_REASONS[0].value);
  const [justification, setJustification] = useState('');
  const cost = computeDelayCost(entry);
  const canSubmit = justification.trim().length >= 20;

  return (
    <div
      style={{
        background: 'var(--bg-raised)',
        border: '1px solid var(--border-strong)',
        borderRadius: 6,
        padding: 12,
        marginTop: 8,
      }}
    >
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8, color: C.t1 }}>
        Aceitar Atraso — {entry.sku}
      </div>

      <div style={{ fontSize: 12, color: C.t2, marginBottom: 6 }}>
        Custo estimado:{' '}
        <strong style={{ color: C.rd }}>{cost} EUR</strong>
        <span style={{ opacity: 0.7 }}> ({entry.delayDays}d x 50 x (6 - Tier {entry.clientTier}))</span>
      </div>

      <select
        value={reason}
        onChange={(e) => setReason(e.target.value as typeof reason)}
        style={{
          width: '100%',
          fontSize: 12,
          padding: '4px 6px',
          marginBottom: 6,
          background: 'var(--bg-base)',
          color: C.t1,
          border: '1px solid var(--border)',
          borderRadius: 4,
        }}
      >
        {DELAY_REASONS.map((r) => (
          <option key={r.value} value={r.value}>
            {r.label}
          </option>
        ))}
      </select>

      <textarea
        placeholder="Justificacao (min 20 caracteres)"
        value={justification}
        onChange={(e) => setJustification(e.target.value)}
        rows={2}
        style={{
          width: '100%',
          fontSize: 12,
          padding: '4px 6px',
          marginBottom: 6,
          background: 'var(--bg-base)',
          color: C.t1,
          border: '1px solid var(--border)',
          borderRadius: 4,
          resize: 'vertical',
        }}
      />

      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
        <button
          type="button"
          onClick={onCancel}
          style={{ fontSize: 12, padding: '3px 10px', cursor: 'pointer' }}
        >
          Cancelar
        </button>
        <button
          type="button"
          disabled={!canSubmit || submitting}
          onClick={() => onConfirm(reason, justification.trim())}
          style={{
            fontSize: 12,
            padding: '3px 10px',
            cursor: canSubmit && !submitting ? 'pointer' : 'not-allowed',
            background: canSubmit && !submitting ? C.rd : 'var(--bg-card)',
            color: canSubmit && !submitting ? 'var(--text-inverse, #fff)' : C.t3,
            border: 'none',
            borderRadius: 4,
          }}
        >
          {submitting ? 'A registar...' : `Confirmar Aceite (${cost} EUR)`}
        </button>
      </div>
    </div>
  );
}

// ── Entry Row ──

function EntryRow({
  entry,
  onNavigate,
  onAcceptDelay,
  acceptingId,
  onConfirmAccept,
  onCancelAccept,
  isSubmitting = false,
}: {
  entry: LateDeliveryEntry;
  onNavigate?: (opId: string) => void;
  onAcceptDelay: (opId: string) => void;
  acceptingId: string | null;
  onConfirmAccept: (reason: string, justification: string) => void;
  onCancelAccept: () => void;
  isSubmitting?: boolean;
}) {
  const isAccepting = acceptingId === entry.opId;
  const tierColor = entry.clientTier <= 1 ? C.rd : entry.clientTier <= 2 ? 'var(--semantic-amber)' : C.t2;

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

// ── Main Panel ──

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
    if (!entry) { setAcceptingId(null); return; }

    const cost = computeDelayCost(entry);
    const highTier = entry.clientTier <= 2;
    const govLevel = governanceLevel(cost, highTier);
    const incentive = REASON_TO_INCENTIVE[reason] ?? 'technical';

    setSubmitting(true);
    try {
      await assessDeviation({
        optimal_state: { opId: entry.opId, sku: entry.sku, delayDays: 0, shortfallPcs: 0 },
        proposed_state: { opId: entry.opId, sku: entry.sku, delayDays: entry.delayDays, shortfallPcs: entry.shortfall },
        incentive_category: incentive,
        governance_level: govLevel,
      }).catch(() => {});

      await createLedgerEntry({
        tenant_id: 'incompol',
        user_id: 'planner-001',
        decision_type: 'accept_delay',
        optimal_state: { opId: entry.opId, sku: entry.sku, deadline: entry.deadlineDate, shortfallPcs: 0 },
        proposed_state: { opId: entry.opId, sku: entry.sku, deadline: entry.deadlineDate, delayDays: entry.delayDays, shortfallPcs: entry.shortfall },
        deviation_cost: cost,
        incentive_category: incentive,
        declared_reason: justification,
        governance_level: govLevel,
        contrafactual: govLevel >= 'L3' ? { delayDays: entry.delayDays, shortfallPcs: entry.shortfall, clientTier: entry.clientTier } : null,
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
          <EntryRow
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
                <EntryRow
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
