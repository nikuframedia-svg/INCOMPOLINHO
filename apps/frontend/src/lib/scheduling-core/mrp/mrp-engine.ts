// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — MRP Engine (Level 0)
//  Main computeMRP() + computeToolMRP() helper
//  Extracted from mrp-engine.ts (Incompol)
// ═══════════════════════════════════════════════════════════

import { DAY_CAP, DEFAULT_OEE } from '../constants.js';
import type { EngineData, EOp, ETool } from '../types/engine.js';
import type {
  MRPDayBucket,
  MRPRecord,
  MRPResult,
  MRPSkuRecord,
  MRPSummary,
  RCCPEntry,
} from '../types/mrp.js';
import type { TwinGroup } from '../types/twin.js';

// ── Main MRP ────────────────────────────────────────────────

/** Main MRP computation -- follows PP1 pseudo-code */
export function computeMRP(
  engine: EngineData,
  capacityOverrides?: Record<string, number[]>,
): MRPResult {
  const numDays = engine.dates.length;
  const records: MRPRecord[] = [];

  // RCCP accumulator: machine -> day -> { setupMin, prodMin, tools }
  const rccpMap: Record<
    string,
    Array<{ setupMin: number; prodMin: number; tools: Set<string> }>
  > = {};
  for (const m of engine.machines) {
    rccpMap[m.id] = Array.from({ length: numDays }, () => ({
      setupMin: 0,
      prodMin: 0,
      tools: new Set<string>(),
    }));
  }

  // Group operations by tool
  const opsByTool: Record<string, EOp[]> = {};
  for (const op of engine.ops) {
    if (!opsByTool[op.t]) opsByTool[op.t] = [];
    opsByTool[op.t].push(op);
  }

  // Process each tool
  for (const tool of engine.tools) {
    const toolOps = opsByTool[tool.id] || [];
    const record = computeToolMRP(
      tool,
      toolOps,
      numDays,
      engine.dates,
      engine.dnames,
      engine.twinGroups,
      engine.orderBased,
    );

    // Accumulate RCCP on primary machine (per-tool OEE → clock minutes)
    // Setup is counted per release day (each POR on a different day needs its own setup)
    const machineId = tool.m;
    if (rccpMap[machineId]) {
      const toolOee = tool.oee ?? DEFAULT_OEE;
      const daysWithPOR = new Set<number>();
      for (const bucket of record.buckets) {
        if (bucket.plannedOrderRelease > 0) {
          const releaseDay = bucket.dayIndex;
          const prodMin = tool.pH > 0 ? ((bucket.plannedOrderRelease / tool.pH) * 60) / toolOee : 0;
          rccpMap[machineId][releaseDay].prodMin += prodMin;
          if (!daysWithPOR.has(releaseDay)) {
            rccpMap[machineId][releaseDay].setupMin += tool.sH * 60;
            daysWithPOR.add(releaseDay);
          }
          rccpMap[machineId][releaseDay].tools.add(tool.id);
        }
      }
    }

    records.push(record);
  }

  // Build RCCP entries
  const rccp: RCCPEntry[] = [];
  for (const m of engine.machines) {
    const dayData = rccpMap[m.id];
    for (let d = 0; d < numDays; d++) {
      const dd = dayData[d];
      const requiredTotal = dd.setupMin + dd.prodMin;
      const avail = capacityOverrides?.[m.id]?.[d] ?? DAY_CAP;
      rccp.push({
        machine: m.id,
        area: m.area,
        dayIndex: d,
        dateLabel: engine.dates[d],
        availableMin: avail,
        requiredSetupMin: Math.round(dd.setupMin),
        requiredProdMin: Math.round(dd.prodMin),
        requiredTotalMin: Math.round(requiredTotal),
        utilization: avail > 0 ? requiredTotal / avail : requiredTotal > 0 ? Infinity : 0,
        overloaded: requiredTotal > avail,
        plannedTools: Array.from(dd.tools),
      });
    }
  }

  const summary = computeMRPSummary(records, rccp);
  return { records, rccp, summary };
}

// ── Tool MRP Netting ────────────────────────────────────────

/** MRP netting for a single tool -- steps 2-5 */
export function computeToolMRP(
  tool: ETool,
  ops: EOp[],
  numDays: number,
  dates: string[],
  dnames: string[],
  twinGroups?: TwinGroup[],
  orderBased?: boolean,
): MRPRecord {
  const grossReq = new Array(numDays).fill(0) as number[];
  let totalBacklog = 0;
  const skuSet: Array<{ sku: string; name: string }> = [];
  const seenSkus = new Set<string>();

  // Identify twin pairs among this tool's operations
  const twinPairs: Array<{ opA: EOp; opB: EOp }> = [];
  const twinOpIds = new Set<string>();
  if (twinGroups) {
    for (const tg of twinGroups) {
      if (tg.tool !== tool.id) continue;
      const opA = ops.find((o) => o.sku === tg.sku1);
      const opB = ops.find((o) => o.sku === tg.sku2);
      if (opA && opB) {
        twinPairs.push({ opA, opB });
        twinOpIds.add(opA.id);
        twinOpIds.add(opB.id);
      }
    }
  }

  // For twin pairs: grossReq = max(A, B) per day (co-production)
  // For solo ops: grossReq = sum of daily demands (normal)
  for (const op of ops) {
    if (!twinOpIds.has(op.id)) {
      // Solo operation — normal accumulation
      for (let d = 0; d < numDays && d < op.d.length; d++) {
        grossReq[d] += op.d[d];
      }
      totalBacklog += op.atr;
    }
    if (!seenSkus.has(op.sku)) {
      seenSkus.add(op.sku);
      skuSet.push({ sku: op.sku, name: op.nm });
    }
  }

  // Twin pairs: use max of daily demands (one run covers both)
  for (const { opA, opB } of twinPairs) {
    for (let d = 0; d < numDays; d++) {
      const demA = d < opA.d.length ? opA.d[d] : 0;
      const demB = d < opB.d.length ? opB.d[d] : 0;
      grossReq[d] += Math.max(demA, demB);
    }
    totalBacklog += Math.max(opA.atr, opB.atr);
  }

  const buckets: MRPDayBucket[] = [];
  const totalWip = ops.reduce((s: number, op: EOp) => s + (op.wip ?? 0), 0);
  let projected = tool.stk + totalWip - totalBacklog;
  let stockoutDay: number | null = null;
  let totalPlannedQty = 0;
  let totalGrossReq = totalBacklog;

  // When ISOP provides lt=0 (no economic lot defined), use order-for-order
  // sizing (lotQty = netReq) at netting time.
  // For lead time estimation, use average daily demand as proxy.
  const grossTotal = grossReq.reduce((s, v) => s + v, 0);
  const avgDailyGross = grossTotal > 0 ? grossTotal / numDays : 0;
  const leadEstQty = tool.lt > 0 ? tool.lt : Math.max(avgDailyGross, 1);
  const setupMin = tool.sH * 60;
  const safePH = tool.pH > 0 ? tool.pH : 1;
  const effectiveOee = tool.oee ?? DEFAULT_OEE;
  const prodMinPerLot = ((leadEstQty / safePH) * 60) / effectiveOee; // clock time (OEE-adjusted)
  const leadDays = Math.max(1, Math.ceil((setupMin + prodMinPerLot) / DAY_CAP));

  for (let d = 0; d < numDays; d++) {
    const gr = grossReq[d];
    totalGrossReq += gr;
    projected -= gr;

    let netReq = 0;
    let plannedReceipt = 0;

    if (projected < 0) {
      if (stockoutDay === null) stockoutDay = d;
      netReq = Math.abs(projected);

      if (tool.lt > 0 && !orderBased) {
        plannedReceipt = Math.ceil(netReq / tool.lt) * tool.lt;
      } else {
        plannedReceipt = netReq;
      }
      projected += plannedReceipt;
      totalPlannedQty += plannedReceipt;
    }

    const releaseDay = Math.max(0, d - leadDays);

    buckets.push({
      dayIndex: d,
      dateLabel: `${dnames[d]} ${dates[d]}`,
      grossRequirement: gr,
      scheduledReceipts: d === 0 ? totalWip : 0,
      projectedAvailable: projected,
      netRequirement: netReq,
      plannedOrderReceipt: plannedReceipt,
      plannedOrderRelease: 0,
    });

    if (plannedReceipt > 0) {
      const clampedRelease = Math.min(releaseDay, buckets.length - 1);
      buckets[clampedRelease].plannedOrderRelease += plannedReceipt;
    }
  }

  // Coverage days: count how many days stock (after backlog) covers cumulative demand
  const netStock = Math.max(0, tool.stk - totalBacklog);
  let coverageDays: number;
  if (netStock <= 0) {
    coverageDays = 0;
  } else {
    let cumDemand = 0;
    coverageDays = numDays; // default if stock covers entire horizon
    for (let d = 0; d < numDays; d++) {
      cumDemand += grossReq[d];
      if (cumDemand > netStock) {
        // Interpolate: partial day coverage
        const prevCum = cumDemand - grossReq[d];
        const remaining = netStock - prevCum;
        const fraction = grossReq[d] > 0 ? remaining / grossReq[d] : 0;
        coverageDays = Math.round((d + fraction) * 10) / 10;
        break;
      }
    }
  }

  // ── Per-SKU netting (always computed) ──
  const altMachine = tool.alt !== '-' ? tool.alt : null;
  const skuRecords: MRPSkuRecord[] = [];

  // Distribute tool-level stock proportionally when per-SKU stock is unavailable
  const totalOpDemand = ops.reduce((s, o) => s + o.d.reduce((a, v) => a + Math.max(v, 0), 0), 0);

  for (const op of ops) {
    // Per-SKU stock: use op.stk if available, else proportional share of tool.stk
    const opStock =
      op.stk !== undefined
        ? op.stk
        : totalOpDemand > 0
          ? Math.round(tool.stk * (op.d.reduce((a, v) => a + Math.max(v, 0), 0) / totalOpDemand))
          : ops.length > 0
            ? Math.round(tool.stk / ops.length)
            : tool.stk;
    const opWip = op.wip ?? 0;

    // Per-SKU gross requirements
    const skuGross = new Array(numDays).fill(0) as number[];
    for (let d = 0; d < numDays && d < op.d.length; d++) {
      skuGross[d] = op.d[d];
    }

    // Per-SKU netting loop (same algorithm as tool-level)
    const skuBuckets: MRPDayBucket[] = [];
    let skuProjected = opStock + opWip - op.atr;
    let skuStockoutDay: number | null = null;
    let skuTotalGross = op.atr;

    for (let d = 0; d < numDays; d++) {
      const gr = skuGross[d];
      skuTotalGross += gr;
      skuProjected -= gr;
      let netReq = 0,
        plannedReceipt = 0;
      if (skuProjected < 0) {
        if (skuStockoutDay === null) skuStockoutDay = d;
        netReq = Math.abs(skuProjected);
        plannedReceipt =
          tool.lt > 0 && !orderBased ? Math.ceil(netReq / tool.lt) * tool.lt : netReq;
        skuProjected += plannedReceipt;
      }
      skuBuckets.push({
        dayIndex: d,
        dateLabel: `${dnames[d]} ${dates[d]}`,
        grossRequirement: gr,
        scheduledReceipts: d === 0 ? opWip : 0,
        projectedAvailable: skuProjected,
        netRequirement: netReq,
        plannedOrderReceipt: plannedReceipt,
        plannedOrderRelease: 0,
      });
    }

    // Per-SKU coverage
    const skuNetStock = Math.max(0, opStock - op.atr);
    let skuCoverage = numDays;
    if (skuNetStock <= 0) {
      skuCoverage = 0;
    } else {
      let cum = 0;
      for (let d = 0; d < numDays; d++) {
        cum += skuGross[d];
        if (cum > skuNetStock) {
          const prev = cum - skuGross[d];
          const frac = skuGross[d] > 0 ? (skuNetStock - prev) / skuGross[d] : 0;
          skuCoverage = Math.round((d + frac) * 10) / 10;
          break;
        }
      }
    }

    skuRecords.push({
      sku: op.sku,
      name: op.nm,
      opId: op.id,
      toolCode: tool.id,
      machine: tool.m,
      altMachine,
      customer: op.cl,
      customerName: op.clNm,
      twin: op.twin,
      ratePerHour: tool.pH,
      setupHours: tool.sH,
      lotEconomicQty: tool.lt,
      currentStock: opStock,
      wip: opWip,
      backlog: op.atr,
      grossRequirement: skuTotalGross,
      projectedEnd:
        skuBuckets.length > 0 ? skuBuckets[skuBuckets.length - 1].projectedAvailable : opStock,
      stockoutDay: skuStockoutDay,
      coverageDays: skuCoverage,
      buckets: skuBuckets,
    });
  }

  return {
    toolCode: tool.id,
    skus: skuSet,
    machine: tool.m,
    altMachine,
    lotEconomicQty: tool.lt,
    currentStock: tool.stk,
    backlog: totalBacklog,
    ratePerHour: tool.pH,
    setupHours: tool.sH,
    operators: tool.op,
    productionLeadDays: leadDays,
    buckets,
    totalGrossReq,
    totalPlannedQty,
    endingStock: buckets.length > 0 ? buckets[buckets.length - 1].projectedAvailable : tool.stk,
    stockoutDay,
    coverageDays,
    skuRecords,
  };
}

// ── Summary ─────────────────────────────────────────────────

function computeMRPSummary(records: MRPRecord[], rccp: RCCPEntry[]): MRPSummary {
  const toolsWithBacklog = records.filter((r) => r.backlog > 0).length;
  const toolsWithStockout = records.filter((r) => r.stockoutDay !== null).length;
  const totalPlannedQty = records.reduce((s, r) => s + r.totalPlannedQty, 0);
  const totalGrossReq = records.reduce((s, r) => s + r.totalGrossReq, 0);

  let maxUtil = 0;
  let bottleneckMachine: string | null = null;
  let bottleneckDay: number | null = null;
  let totalUtil = 0;
  let utilCount = 0;

  for (const entry of rccp) {
    if (entry.utilization > maxUtil && isFinite(entry.utilization)) {
      maxUtil = entry.utilization;
      bottleneckMachine = entry.machine;
      bottleneckDay = entry.dayIndex;
    }
    if (isFinite(entry.utilization) && entry.availableMin > 0) {
      totalUtil += entry.utilization;
      utilCount++;
    }
  }

  return {
    totalTools: records.length,
    toolsWithBacklog,
    toolsWithStockout,
    totalPlannedQty,
    totalGrossReq,
    avgUtilization: utilCount > 0 ? totalUtil / utilCount : 0,
    bottleneckMachine,
    bottleneckDay,
  };
}
