/**
 * AcceptDelayModal — Inline modal for accepting a late delivery with
 * cost calculation, reason selection, and justification text.
 */

import { useState } from 'react';
import type { LateDeliveryEntry } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';

export const DELAY_REASONS = [
  { value: 'tecnico', label: 'Tecnico — limitacao de capacidade' },
  { value: 'comercial', label: 'Comercial — acordo com cliente' },
  { value: 'conveniencia', label: 'Conveniencia — priorizacao interna' },
  { value: 'hierarquico', label: 'Hierarquico — decisao de gestao' },
] as const;

export function computeDelayCost(entry: LateDeliveryEntry): number {
  return entry.delayDays * 50 * (6 - entry.clientTier);
}

export function governanceLevel(cost: number, highTier: boolean): string {
  if (highTier) return 'L4';
  if (cost > 200) return 'L5';
  if (cost > 100) return 'L4';
  if (cost > 50) return 'L3';
  if (cost > 20) return 'L2';
  if (cost > 0) return 'L1';
  return 'L0';
}

export const REASON_TO_INCENTIVE: Record<string, string> = {
  tecnico: 'technical',
  comercial: 'commercial_pressure',
  conveniencia: 'operational_convenience',
  hierarquico: 'hierarchical_pressure',
};

interface AcceptDelayModalProps {
  entry: LateDeliveryEntry;
  onConfirm: (reason: string, justification: string) => void;
  onCancel: () => void;
  submitting?: boolean;
}

export function AcceptDelayModal({
  entry,
  onConfirm,
  onCancel,
  submitting = false,
}: AcceptDelayModalProps) {
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
        Custo estimado: <strong style={{ color: C.rd }}>{cost} EUR</strong>
        <span style={{ opacity: 0.7 }}>
          {' '}
          ({entry.delayDays}d x 50 x (6 - Tier {entry.clientTier}))
        </span>
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
