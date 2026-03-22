import { useMemo, useState } from 'react';
import type { CTPResult, MRPResult, MRPSkuViewResult } from '@/domain/mrp/mrp-types';
import type { EngineData } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { computeCTP, computeCTPSku } from '@/utils/mrp-compute-stubs';
import { CTPContextPanel } from '../components/CTPContextPanel';
import { CTPResultPanel } from '../components/CTPResultPanel';

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
    const altTool = engine.tools.find((t) => t.id === selectedOp.t && t.m === tool.alt);
    if (altTool) {
      return computeCTP({ toolCode: altTool.id, quantity: qty, targetDay }, mrp, engine);
    }
    const primaryResult = computeCTP(
      { toolCode: selectedOp.t, quantity: qty, targetDay },
      mrp,
      engine,
    );
    if (primaryResult && primaryResult.machine !== tool.m) {
      return primaryResult;
    }
    return null;
  }, [ctpKey, qty, targetDay, mrp, engine, selectedOp]);

  const altMachine = selectedOp ? engine.tools.find((t) => t.id === selectedOp.t)?.alt : null;

  const daysEarlier =
    altResult?.earliestFeasibleDay != null && result?.earliestFeasibleDay != null
      ? result.earliestFeasibleDay - altResult.earliestFeasibleDay
      : undefined;

  return (
    <>
      <CTPContextPanel
        ctpKey={ctpKey}
        onCtpKeyChange={setCtpKey}
        qty={qty}
        onQtyChange={setQty}
        targetDay={targetDay}
        onTargetDayChange={setTargetDay}
        engine={engine}
        selectedOp={selectedOp}
        altMachine={altMachine}
        selectedMrpRecord={selectedMrpRecord}
      />

      {result && (
        <>
          <CTPResultPanel
            result={result}
            dates={engine.dates}
            dnames={engine.dnames}
            targetDay={targetDay}
            label="Máquina Principal"
            machineName={result.machine}
          />

          {altMachine && altResult && altResult.machine !== result.machine && (
            <CTPResultPanel
              result={altResult}
              dates={engine.dates}
              dnames={engine.dnames}
              targetDay={targetDay}
              label="Máquina Alternativa"
              machineName={altMachine}
              daysEarlierThanPrimary={daysEarlier}
            />
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
