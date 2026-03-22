/**
 * CTPForm — SKU/quantity/target day form for CTP simulation.
 */

import type { EngineData } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';

export function CTPForm({
  engine,
  sku,
  setSku,
  qty,
  setQty,
  targetDay,
  setTargetDay,
  customer,
  setCustomer,
  onRun,
}: {
  engine: EngineData;
  sku: string;
  setSku: (v: string) => void;
  qty: number;
  setQty: (v: number) => void;
  targetDay: number;
  setTargetDay: (v: number) => void;
  customer: string;
  setCustomer: (v: string) => void;
  onRun: () => void;
}) {
  return (
    <div className="mrp__card" style={{ marginBottom: 12 }}>
      <div className="mrp__ctp-form">
        <div className="mrp__ctp-field">
          <label>SKU</label>
          <select
            className="mrp__input"
            value={sku}
            onChange={(e) => setSku(e.target.value)}
            style={{ minWidth: 200 }}
          >
            <option value="">Seleccionar SKU...</option>
            {engine.ops.map((o) => (
              <option key={o.id} value={o.sku}>
                {o.sku} — {o.nm} ({o.t})
              </option>
            ))}
          </select>
        </div>
        <div className="mrp__ctp-field">
          <label>Quantidade</label>
          <input
            className="mrp__input"
            type="number"
            min={1}
            value={qty}
            onChange={(e) => setQty(Number(e.target.value) || 1)}
            style={{ width: 100 }}
          />
        </div>
        <div className="mrp__ctp-field">
          <label>Dia Alvo</label>
          <select
            className="mrp__input"
            value={targetDay}
            onChange={(e) => setTargetDay(Number(e.target.value))}
          >
            {engine.dates.map((d, i) => (
              <option key={i} value={i}>
                {engine.dnames[i]} {d}
              </option>
            ))}
          </select>
        </div>
        <div className="mrp__ctp-field">
          <label>Cliente</label>
          <input
            className="mrp__input"
            type="text"
            placeholder="Opcional"
            value={customer}
            onChange={(e) => setCustomer(e.target.value)}
            style={{ width: 140 }}
          />
        </div>
        <div className="mrp__ctp-field" style={{ alignSelf: 'flex-end' }}>
          <button
            className="mrp__input"
            onClick={onRun}
            disabled={!sku}
            style={{
              cursor: sku ? 'pointer' : 'not-allowed',
              background: sku ? `${C.ac}20` : `${C.t4}20`,
              color: sku ? C.ac : C.t3,
              border: `1px solid ${sku ? C.ac : C.t4}40`,
              fontWeight: 600,
              fontSize: 12,
              padding: '6px 16px',
              borderRadius: 4,
            }}
          >
            Verificar Viabilidade
          </button>
        </div>
      </div>
    </div>
  );
}
