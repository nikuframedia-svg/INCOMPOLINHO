import { Info } from 'lucide-react';
import { useMemo, useState } from 'react';
import type { CTPResult, MRPResult, MRPSkuViewResult } from '@/domain/mrp/mrp-types';
import type { EngineData } from '@/lib/engine';
import { C, computeCTP, computeCTPSku } from '@/lib/engine';
import { CTPChart } from '../components/CTPChart';
import { KCard } from '../components/KCard';
import { fmtQty, mono } from '../utils/mrp-helpers';

interface CTPTabProps {
  mrp: MRPResult;
  engine: EngineData;
  skuView: MRPSkuViewResult;
}

export function CTPTab({ mrp, engine, skuView }: CTPTabProps) {
  const [ctpKey, setCtpKey] = useState('');
  const [qty, setQty] = useState(5000);
  const [targetDay, setTargetDay] = useState(0);

  // Find operation details for selected SKU
  const selectedOp = useMemo(() => {
    if (!ctpKey) return null;
    return engine.ops.find((o) => o.sku === ctpKey) ?? null;
  }, [ctpKey, engine.ops]);

  // Find MRP record for selected SKU
  const selectedMrpRecord = useMemo(() => {
    if (!ctpKey) return null;
    return skuView.skuRecords.find((r) => r.sku === ctpKey) ?? null;
  }, [ctpKey, skuView.skuRecords]);

  // Primary CTP result (always SKU mode)
  const result = useMemo(() => {
    if (!ctpKey) return null;
    const op = engine.ops.find((o) => o.sku === ctpKey);
    if (!op) return null;
    return computeCTPSku({ sku: ctpKey, quantity: qty, targetDay }, mrp, engine);
  }, [ctpKey, qty, targetDay, mrp, engine]);

  // Alt machine CTP result for comparison
  const altResult = useMemo((): CTPResult | null => {
    if (!ctpKey || !selectedOp) return null;
    const tool = engine.tools.find((t) => t.id === selectedOp.t);
    if (!tool?.alt) return null;
    // Call CTP with primary tool code — the engine internally checks alt
    // Instead we compute for the alt machine by finding an alt tool entry
    const altTool = engine.tools.find((t) => t.id === selectedOp.t && t.m === tool.alt);
    if (altTool) {
      return computeCTP({ toolCode: altTool.id, quantity: qty, targetDay }, mrp, engine);
    }
    // If no alt tool entry, try using tool-level CTP which checks alt internally
    const primaryResult = computeCTP(
      { toolCode: selectedOp.t, quantity: qty, targetDay },
      mrp,
      engine,
    );
    // If the primary result used alt machine, show that info
    if (primaryResult && primaryResult.machine !== tool.m) {
      return primaryResult;
    }
    return null;
  }, [ctpKey, qty, targetDay, mrp, engine, selectedOp]);

  const altMachine = selectedOp ? engine.tools.find((t) => t.id === selectedOp.t)?.alt : null;

  return (
    <>
      <div className="mrp__card" style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: C.t1, marginBottom: 12 }}>
          Capable-to-Promise — Verificar viabilidade de encomenda
        </div>
        <div className="mrp__ctp-form">
          <div className="mrp__ctp-field">
            <label>SKU</label>
            <select
              className="mrp__input"
              value={ctpKey}
              onChange={(e) => setCtpKey(e.target.value)}
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
        </div>

        {/* Client context */}
        {selectedOp && (
          <div
            style={{
              marginTop: 8,
              fontSize: 10,
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
              fontSize: 10,
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
          <div style={{ marginTop: 8, fontSize: 9, color: C.t3 }}>
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

      {result && (
        <>
          {/* Primary machine result */}
          <div style={{ fontSize: 10, fontWeight: 500, color: C.t2, marginBottom: 4 }}>
            Máquina Principal: <span style={{ ...mono, color: C.t1 }}>{result.machine}</span>
          </div>
          <div className="mrp__ctp-result">
            <KCard
              label="Viável"
              value={result.feasible ? 'SIM' : 'NÃO'}
              sub=""
              color={result.feasible ? C.ac : C.rd}
            />
            <KCard
              label="Dia Mais Cedo"
              value={result.earliestFeasibleDay !== null ? `D${result.earliestFeasibleDay}` : '-'}
              sub={
                result.earliestFeasibleDay !== null
                  ? (engine.dates[result.earliestFeasibleDay] ?? `D${result.earliestFeasibleDay}`)
                  : 'sem capacidade'
              }
              color={result.earliestFeasibleDay !== null ? C.t1 : C.rd}
            />
            <KCard
              label="Confiança"
              value={
                result.confidence === 'high'
                  ? 'ALTA'
                  : result.confidence === 'medium'
                    ? 'MÉDIA'
                    : 'BAIXA'
              }
              sub=""
              color={
                result.confidence === 'high' ? C.ac : result.confidence === 'medium' ? C.yl : C.rd
              }
            />
            <KCard
              label="Capacidade"
              value={`${result.requiredMin}m`}
              sub={`disponível: ${result.availableMinOnDay}m`}
              color={C.t1}
            />
          </div>

          <div className="mrp__card" style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 10, color: C.t2, marginBottom: 12 }}>{result.reason}</div>
            <CTPChart
              timeline={result.capacityTimeline}
              dates={engine.dates}
              dnames={engine.dnames}
              targetDay={targetDay}
            />
          </div>

          {/* Alt machine comparison */}
          {altMachine && altResult && altResult.machine !== result.machine && (
            <>
              <div
                style={{
                  fontSize: 10,
                  fontWeight: 500,
                  color: C.t2,
                  marginBottom: 4,
                  marginTop: 8,
                }}
              >
                Máquina Alternativa: <span style={{ ...mono, color: C.t1 }}>{altMachine}</span>
                {altResult.earliestFeasibleDay !== null &&
                  result.earliestFeasibleDay !== null &&
                  altResult.earliestFeasibleDay < result.earliestFeasibleDay && (
                    <span style={{ fontSize: 9, color: C.ac, marginLeft: 8 }}>
                      {result.earliestFeasibleDay - altResult.earliestFeasibleDay} dia(s) mais cedo
                    </span>
                  )}
              </div>
              <div className="mrp__ctp-result">
                <KCard
                  label="Viável"
                  value={altResult.feasible ? 'SIM' : 'NÃO'}
                  sub=""
                  color={altResult.feasible ? C.ac : C.rd}
                />
                <KCard
                  label="Dia Mais Cedo"
                  value={
                    altResult.earliestFeasibleDay !== null
                      ? `D${altResult.earliestFeasibleDay}`
                      : '-'
                  }
                  sub={
                    altResult.earliestFeasibleDay !== null
                      ? (engine.dates[altResult.earliestFeasibleDay] ?? '')
                      : 'sem capacidade'
                  }
                  color={altResult.earliestFeasibleDay !== null ? C.t1 : C.rd}
                />
                <KCard
                  label="Confiança"
                  value={
                    altResult.confidence === 'high'
                      ? 'ALTA'
                      : altResult.confidence === 'medium'
                        ? 'MÉDIA'
                        : 'BAIXA'
                  }
                  sub=""
                  color={
                    altResult.confidence === 'high'
                      ? C.ac
                      : altResult.confidence === 'medium'
                        ? C.yl
                        : C.rd
                  }
                />
                <KCard
                  label="Capacidade"
                  value={`${altResult.requiredMin}m`}
                  sub={`disponível: ${altResult.availableMinOnDay}m`}
                  color={C.t1}
                />
              </div>
              <div className="mrp__card" style={{ marginBottom: 12 }}>
                <CTPChart
                  timeline={altResult.capacityTimeline}
                  dates={engine.dates}
                  dnames={engine.dnames}
                  targetDay={targetDay}
                />
              </div>
            </>
          )}
        </>
      )}

      {!result && (
        <div style={{ padding: 40, textAlign: 'center', color: C.t3, fontSize: 12 }}>
          Seleccione um SKU para verificar CTP
        </div>
      )}
    </>
  );
}
