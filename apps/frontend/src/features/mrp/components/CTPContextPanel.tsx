import { Info } from 'lucide-react';
import type { MRPSkuViewRecord } from '@/domain/mrp/mrp-types';
import type { EngineData } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { fmtQty, mono } from '../utils/mrp-helpers';

interface CTPContextPanelProps {
  ctpKey: string;
  onCtpKeyChange: (value: string) => void;
  qty: number;
  onQtyChange: (value: number) => void;
  targetDay: number;
  onTargetDayChange: (value: number) => void;
  engine: EngineData;
  selectedOp: EngineData['ops'][number] | null;
  altMachine: string | null | undefined;
  selectedMrpRecord: MRPSkuViewRecord | null;
}

export function CTPContextPanel({
  ctpKey,
  onCtpKeyChange,
  qty,
  onQtyChange,
  targetDay,
  onTargetDayChange,
  engine,
  selectedOp,
  altMachine,
  selectedMrpRecord,
}: CTPContextPanelProps) {
  return (
    <div className="mrp__card" style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 12 }}>
        Capable-to-Promise — Verificar viabilidade de encomenda
      </div>
      <div className="mrp__ctp-form">
        <div className="mrp__ctp-field">
          <label>SKU</label>
          <select
            className="mrp__input"
            value={ctpKey}
            onChange={(e) => onCtpKeyChange(e.target.value)}
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
            onChange={(e) => onQtyChange(Number(e.target.value) || 1)}
            style={{ width: 100 }}
          />
        </div>
        <div className="mrp__ctp-field">
          <label>Dia Alvo</label>
          <select
            className="mrp__input"
            value={targetDay}
            onChange={(e) => onTargetDayChange(Number(e.target.value))}
          >
            {engine.dates.map((d, i) => (
              <option key={i} value={i}>
                {engine.dnames[i]} {d}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Client context */}
      {selectedOp && (
        <div
          style={{
            marginTop: 8,
            fontSize: 12,
            color: C.t2,
            display: 'flex',
            gap: 16,
            alignItems: 'center',
          }}
        >
          {selectedOp.clNm && (
            <span>
              Cliente: <span style={{ color: C.t1, fontWeight: 500 }}>{selectedOp.clNm}</span>
            </span>
          )}
          <span>
            Tool: <span style={{ ...mono, color: C.t1 }}>{selectedOp.t}</span>
          </span>
          <span>
            Máq: <span style={{ ...mono, color: C.t1 }}>{selectedOp.m}</span>
          </span>
          {altMachine && (
            <span>
              Alt: <span style={{ ...mono, color: C.t1 }}>{altMachine}</span>
            </span>
          )}
        </div>
      )}

      {/* Twin info banner */}
      {selectedOp?.twin && (
        <div
          style={{
            marginTop: 8,
            padding: '6px 10px',
            borderRadius: 4,
            background: `${C.ac}12`,
            border: `1px solid ${C.ac}26`,
            fontSize: 12,
            color: C.ac,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <Info size={12} />
          <span>
            Peça gémea: <span style={{ ...mono, fontWeight: 600 }}>{selectedOp.twin}</span> —
            co-produção na mesma corrida (tempo = max das demands)
          </span>
        </div>
      )}

      {/* Existing demand context */}
      {selectedMrpRecord && (
        <div style={{ marginTop: 8, fontSize: 12, color: C.t3 }}>
          <span style={{ color: C.t2, fontWeight: 500 }}>Demand existente: </span>
          {selectedMrpRecord.buckets.map((b, i) => (
            <span key={i} style={{ marginRight: 6 }}>
              <span style={{ color: C.t3 }}>D{i}:</span>{' '}
              <span style={{ ...mono, color: b.grossRequirement > 0 ? C.t2 : C.t4 }}>
                {b.grossRequirement > 0 ? fmtQty(b.grossRequirement) : '-'}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
