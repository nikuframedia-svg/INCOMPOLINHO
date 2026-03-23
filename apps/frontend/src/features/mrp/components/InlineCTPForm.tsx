/**
 * InlineCTPForm — Compact CTP (Capable-to-Promise) form.
 * Checks real schedule capacity for an additional order.
 */

import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { CTPRealResult } from '@/lib/api';
import { ctpRealApi } from '@/lib/api';
import { C } from '@/theme/color-bridge';
import { mono } from '../utils/mrp-helpers';

interface InlineCTPFormProps {
  sku: string;
  nDays: number;
}

const CONF_COLOR: Record<string, string> = {
  high: C.ac,
  medium: C.yl,
  low: C.rd,
};

export function InlineCTPForm({ sku, nDays }: InlineCTPFormProps) {
  const [qty, setQty] = useState(20000);
  const [deadline, setDeadline] = useState(15);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CTPRealResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const handleCheck = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const r = await ctpRealApi(sku, qty, deadline);
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro CTP');
    } finally {
      setLoading(false);
    }
  }, [sku, qty, deadline]);

  const handleSimulate = useCallback(() => {
    const params = new URLSearchParams({
      view: 'simulate',
      mutationType: 'increase_demand',
      sku,
      qty: String(qty),
      day: String(deadline),
    });
    navigate(`/scheduling?${params.toString()}`);
  }, [navigate, sku, qty, deadline]);

  return (
    <div className="mrp__card" style={{ padding: 12 }}>
      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: C.t2,
          textTransform: 'uppercase',
          letterSpacing: '.04em',
          marginBottom: 8,
        }}
      >
        CTP — Capacidade Real
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <label style={{ fontSize: 12, color: C.t2 }}>
          Qtd:
          <input
            type="number"
            value={qty}
            onChange={(e) => setQty(Number(e.target.value))}
            style={{
              width: 90,
              marginLeft: 4,
              padding: '4px 6px',
              fontSize: 12,
              ...mono,
              border: `1px solid ${C.bd}`,
              borderRadius: 3,
              background: 'var(--bg-card)',
              color: C.t1,
            }}
          />
        </label>
        <label style={{ fontSize: 12, color: C.t2 }}>
          até dia:
          <input
            type="number"
            min={0}
            max={nDays - 1}
            value={deadline}
            onChange={(e) => setDeadline(Number(e.target.value))}
            style={{
              width: 55,
              marginLeft: 4,
              padding: '4px 6px',
              fontSize: 12,
              ...mono,
              border: `1px solid ${C.bd}`,
              borderRadius: 3,
              background: 'var(--bg-card)',
              color: C.t1,
            }}
          />
        </label>
        <button
          onClick={handleCheck}
          disabled={loading || qty <= 0}
          style={{
            padding: '4px 12px',
            fontSize: 12,
            fontWeight: 600,
            border: `1px solid ${C.ac}`,
            borderRadius: 4,
            background: `${C.ac}15`,
            color: C.ac,
            cursor: loading ? 'wait' : 'pointer',
          }}
        >
          {loading ? '...' : 'VERIFICAR'}
        </button>
      </div>

      {error && <div style={{ marginTop: 8, fontSize: 12, color: C.rd }}>{error}</div>}

      {result && (
        <div
          style={{
            marginTop: 10,
            padding: '8px 10px',
            borderRadius: 4,
            background: result.feasible ? `${C.ac}08` : `${C.rd}08`,
            fontSize: 12,
          }}
        >
          <div style={{ fontWeight: 700, color: result.feasible ? C.ac : C.rd, marginBottom: 4 }}>
            {result.feasible ? 'Cabe' : 'Não cabe'} na {result.machine}
            {result.earliestDay != null && ` a partir do dia ${result.earliestDay}`}
          </div>
          <div style={{ color: C.t2, ...mono }}>
            {Math.round(result.freeMinOnTarget)} min livres no dia {deadline}. Precisas de{' '}
            {Math.round(result.requiredMin)} min.
          </div>
          <div style={{ color: CONF_COLOR[result.confidence], fontWeight: 600, marginTop: 2 }}>
            Confiança: {result.confidence.toUpperCase()}
          </div>
          {!result.feasible && result.altMachine && result.altEarliestDay != null && (
            <div style={{ color: C.yl, marginTop: 4 }}>
              {result.altMachine} tem espaço — primeiro dia: {result.altEarliestDay}
            </div>
          )}
          <button
            onClick={handleSimulate}
            style={{
              marginTop: 8,
              padding: '4px 10px',
              fontSize: 12,
              fontWeight: 600,
              border: `1px solid ${C.yl}`,
              borderRadius: 4,
              background: `${C.yl}15`,
              color: C.yl,
              cursor: 'pointer',
            }}
          >
            SIMULAR NO CENARIO
          </button>
        </div>
      )}
    </div>
  );
}
