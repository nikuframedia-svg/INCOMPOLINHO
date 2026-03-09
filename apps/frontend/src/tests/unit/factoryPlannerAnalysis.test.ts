/**
 * Factory Planner Analysis — Order-by-Order Scheduling
 *
 * Logic (confirmed by user):
 * - Each distinct negative NP value = 1 independent order of |NP| pcs
 * - Each order has a DEADLINE (the day the NP goes negative)
 * - Production must be FINISHED by the deadline
 * - Each order is a SEPARATE block in the Gantt
 * - You DON'T sum all orders — you plan each one individually
 * - Effective rate = pH × OEE (0.66)
 * - Time per order = qty / effective_rate (hours)
 * - Twin co-production: same tool + same deadline → time = max(A, B)
 * - Setup: when tool changes on a machine, add setup hours
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, it } from 'vitest';
import { parseISOPFile } from '../../domain/isop';
import type { NikufraData } from '../../domain/nikufra-types';

// ── Config ──
const isopPath = '/Users/martimnicolau/Downloads/ISOP_ Nikufra_27_2-2.xlsx';
const cwd = process.cwd();
const base = cwd.endsWith('frontend') ? cwd : join(cwd, 'frontend');
const fixturePath = join(base, 'public', 'fixtures', 'nikufra', 'nikufra_data.json');

const OEE = 0.66;
const DAY_CAP_H = 1020 / 60; // 17h per day (2 shifts)

// ── Types ──

/** A single order extracted from an NP negative value */
interface RawOrder {
  opId: string;
  sku: string;
  machine: string;
  tool: string;
  qty: number;
  deadlineDay: number;
  deadlineDate: string;
  prodH: number;
  effRate: number;
  setupH: number;
  twinSku?: string;
  customer?: string;
}

/** A scheduled block on a machine (1 order or merged twin pair) */
interface GanttBlock {
  tool: string;
  skus: string[];
  opIds: string[];
  qty: number; // total pieces (sum for twins)
  prodH: number; // production hours (max for twins, single for solo)
  setupH: number; // setup hours (0 if same tool as previous)
  deadlineDay: number;
  deadlineDate: string;
  isTwin: boolean;
  // Scheduling results:
  startH: number; // cumulative start hour on machine
  endH: number; // cumulative end hour on machine
  startDay: number; // working day when production starts
  endDay: number; // working day when production ends
  latestStartDay: number; // latest day you could start and still finish on time
  onTime: boolean; // endDay <= deadlineDay
  slackDays: number; // deadlineDay - endDay (negative = late)
}

// ── Helpers ──
function line(ch = '─', len = 80): string {
  return ch.repeat(len);
}
function header(title: string): void {
  console.log(`\n${line('═')}\n  ${title}\n${line('═')}`);
}
function section(title: string): void {
  console.log(`\n${line()}\n  ${title}\n${line()}`);
}
function p(s: string, n: number, right = false): string {
  return right ? s.padEnd(n) : s.padStart(n);
}

function mergeWithMasterData(data: NikufraData, fixture: NikufraData): NikufraData {
  const fixToolMap = new Map(fixture.tools.map((t) => [t.id, t]));
  const mergedTools = data.tools.map((tool) => {
    const fix = fixToolMap.get(tool.id);
    if (!fix) return tool;
    return { ...tool, s: tool.s > 0 ? tool.s : fix.s, alt: tool.alt !== '-' ? tool.alt : fix.alt };
  });
  const toolLookup = new Map(mergedTools.map((t) => [t.id, t]));
  const mergedOps = data.operations.map((op) => {
    const tool = toolLookup.get(op.t);
    if (!tool) return op;
    return { ...op, s: op.s > 0 ? op.s : tool.s };
  });
  const parsedMoEmpty = !data.mo || data.mo.PG1.length === 0 || data.mo.PG1.every((v) => v === 0);
  const mergedMo = parsedMoEmpty && fixture.mo ? fixture.mo : data.mo;
  return { ...data, tools: mergedTools, operations: mergedOps, mo: mergedMo };
}

/**
 * Extract individual orders from raw NP values.
 * Each distinct negative NP = 1 order of |NP| pcs.
 */
function extractOrders(
  rawNP: (number | null)[],
  dates: string[],
  op: {
    id: string;
    sku: string;
    m: string;
    t: string;
    pH: number;
    s: number;
    twin?: string;
    cl?: string;
  },
): RawOrder[] {
  const effRate = op.pH * OEE;
  const orders: RawOrder[] = [];
  let prevNP: number | null = null;
  let currentOrderNP: number | null = null;

  for (let day = 0; day < rawNP.length; day++) {
    let np = rawNP[day];
    if (np === null || np === undefined) np = prevNP;

    if (np !== null && np < 0) {
      if (currentOrderNP !== np) {
        const qty = Math.abs(np);
        orders.push({
          opId: op.id,
          sku: op.sku,
          machine: op.m,
          tool: op.t,
          qty,
          deadlineDay: day,
          deadlineDate: dates[day] || `d${day}`,
          prodH: effRate > 0 ? qty / effRate : 0,
          effRate,
          setupH: op.s > 0 ? op.s : 0,
          twinSku: op.twin || undefined,
          customer: op.cl || undefined,
        });
        currentOrderNP = np;
      }
    } else {
      currentOrderNP = null;
    }
    prevNP = np;
  }
  return orders;
}

// ── Main Analysis ──
describe('Factory Planner — Order-by-Order Schedule', () => {
  it('schedules each order individually per machine', () => {
    // 1. Parse
    const buf = readFileSync(isopPath);
    const ab = new ArrayBuffer(buf.length);
    const view = new Uint8Array(ab);
    for (let i = 0; i < buf.length; i++) view[i] = buf[i];

    const parseResult = parseISOPFile(ab);
    if (!parseResult.success) {
      console.error('PARSE FAILED');
      return;
    }

    const { data } = parseResult;
    const fixture = JSON.parse(readFileSync(fixturePath, 'utf-8')) as NikufraData;
    const merged = mergeWithMasterData(data, fixture);
    const dates = merged.dates;

    header('ORDER-BY-ORDER FACTORY SCHEDULE — ISOP 27/02');
    console.log(
      `  ${merged.operations.length} ops, ${merged.machines.map((m) => m.id).join(', ')}`,
    );
    console.log(`  Horizon: ${dates.length} days (${dates[0]} — ${dates[dates.length - 1]})`);
    console.log(`  OEE: ${OEE} | DAY_CAP: 17h | Effective rate = pH × ${OEE}`);

    // 2. Extract ALL individual orders from ALL operations
    const allOrders: RawOrder[] = [];
    for (const op of merged.operations) {
      const orders = extractOrders(op.d, dates, {
        id: op.id,
        sku: op.sku,
        m: op.m,
        t: op.t,
        pH: op.pH,
        s: op.s,
        twin: op.twin,
        cl: op.cl,
      });
      allOrders.push(...orders);
    }

    section(`ALL ORDERS: ${allOrders.length} individual orders extracted`);
    console.log(
      `  From ${merged.operations.length} operations across ${merged.machines.length} machines`,
    );

    // Count by machine
    const ordersByMachine: Record<string, RawOrder[]> = {};
    for (const o of allOrders) {
      if (!ordersByMachine[o.machine]) ordersByMachine[o.machine] = [];
      ordersByMachine[o.machine].push(o);
    }
    for (const [mId, orders] of Object.entries(ordersByMachine).sort()) {
      const totalH = orders.reduce((s, o) => s + o.prodH, 0);
      console.log(`  ${mId}: ${orders.length} orders, ${totalH.toFixed(1)}h prod`);
    }

    // 3. Schedule each machine: EDD order, merge twins, track on-time
    section('PER-MACHINE GANTT SCHEDULE');

    const allBlocks: GanttBlock[] = [];

    for (const [mId, machineOrders] of Object.entries(ordersByMachine).sort()) {
      console.log(`\n  ── ${mId} ──`);

      // 3a. Merge twin orders with same deadline into co-production blocks
      // Build a map: tool+deadline → orders
      const twinMergeMap: Record<string, RawOrder[]> = {};
      for (const o of machineOrders) {
        const key = `${o.tool}|${o.deadlineDay}`;
        if (!twinMergeMap[key]) twinMergeMap[key] = [];
        twinMergeMap[key].push(o);
      }

      // Build merged order list
      interface MergedOrder {
        tool: string;
        skus: string[];
        opIds: string[];
        qty: number;
        prodH: number;
        setupH: number;
        deadlineDay: number;
        deadlineDate: string;
        isTwin: boolean;
      }

      const mergedOrders: MergedOrder[] = [];
      const processed = new Set<string>();

      for (const [, group] of Object.entries(twinMergeMap)) {
        // Find twin pairs within this group (same tool + same deadline)
        const available = group.filter((o) => !processed.has(`${o.opId}|${o.deadlineDay}`));

        const pairedInGroup = new Set<string>();
        for (let i = 0; i < available.length; i++) {
          const a = available[i];
          const keyA = `${a.opId}|${a.deadlineDay}`;
          if (pairedInGroup.has(keyA)) continue;
          if (!a.twinSku || a.twinSku === a.sku) {
            // No twin or self-ref — solo order
            mergedOrders.push({
              tool: a.tool,
              skus: [a.sku],
              opIds: [a.opId],
              qty: a.qty,
              prodH: a.prodH,
              setupH: a.setupH,
              deadlineDay: a.deadlineDay,
              deadlineDate: a.deadlineDate,
              isTwin: false,
            });
            processed.add(keyA);
            pairedInGroup.add(keyA);
            continue;
          }

          // Look for twin match
          let matched = false;
          for (let j = i + 1; j < available.length; j++) {
            const b = available[j];
            const keyB = `${b.opId}|${b.deadlineDay}`;
            if (pairedInGroup.has(keyB)) continue;
            if (a.twinSku === b.sku || b.twinSku === a.sku) {
              // Twin pair! time = max(A, B)
              mergedOrders.push({
                tool: a.tool,
                skus: [a.sku, b.sku],
                opIds: [a.opId, b.opId],
                qty: a.qty + b.qty,
                prodH: Math.max(a.prodH, b.prodH),
                setupH: a.setupH,
                deadlineDay: a.deadlineDay,
                deadlineDate: a.deadlineDate,
                isTwin: true,
              });
              processed.add(keyA);
              processed.add(keyB);
              pairedInGroup.add(keyA);
              pairedInGroup.add(keyB);
              matched = true;
              break;
            }
          }
          if (!matched) {
            // Twin SKU exists but counterpart doesn't have order on this deadline
            mergedOrders.push({
              tool: a.tool,
              skus: [a.sku],
              opIds: [a.opId],
              qty: a.qty,
              prodH: a.prodH,
              setupH: a.setupH,
              deadlineDay: a.deadlineDay,
              deadlineDate: a.deadlineDate,
              isTwin: false,
            });
            processed.add(keyA);
            pairedInGroup.add(keyA);
          }
        }
      }

      // 3b. Sort by deadline (EDD)
      mergedOrders.sort((a, b) => a.deadlineDay - b.deadlineDay || a.tool.localeCompare(b.tool));

      // 3c. Forward-schedule: place each order, add setup on tool change
      let cursorH = 0;
      let lastTool = '';
      const blocks: GanttBlock[] = [];

      for (const ord of mergedOrders) {
        const needsSetup = ord.tool !== lastTool;
        const setupH = needsSetup ? ord.setupH : 0;
        const startH = cursorH + setupH;
        const endH = startH + ord.prodH;

        const startDay = Math.floor(cursorH / DAY_CAP_H);
        const endDay = Math.floor(endH / DAY_CAP_H);
        const latestStartDay = ord.deadlineDay - Math.ceil(ord.prodH / DAY_CAP_H);
        const onTime = endDay <= ord.deadlineDay;
        const slackDays = ord.deadlineDay - endDay;

        const block: GanttBlock = {
          tool: ord.tool,
          skus: ord.skus,
          opIds: ord.opIds,
          qty: ord.qty,
          prodH: ord.prodH,
          setupH,
          deadlineDay: ord.deadlineDay,
          deadlineDate: ord.deadlineDate,
          isTwin: ord.isTwin,
          startH: cursorH,
          endH,
          startDay,
          endDay,
          latestStartDay,
          onTime,
          slackDays,
        };
        blocks.push(block);
        allBlocks.push(block);

        cursorH = endH;
        lastTool = ord.tool;
      }

      // 3d. Print machine schedule
      const onTimeCount = blocks.filter((b) => b.onTime).length;
      const lateCount = blocks.filter((b) => !b.onTime).length;
      const totalH = cursorH;
      const otd = blocks.length > 0 ? (onTimeCount / blocks.length) * 100 : 100;

      console.log(
        `  ${blocks.length} blocks | ${totalH.toFixed(1)}h = ${(totalH / DAY_CAP_H).toFixed(1)} days | ON-TIME: ${onTimeCount}/${blocks.length} (${otd.toFixed(0)}%) | LATE: ${lateCount}`,
      );
      console.log(``);
      console.log(
        `  ${p('#', 4)} ${p('Tool', 8, true)} ${p('SKU', 16, true)} ${p('Qty', 9)} ${p('ProdH', 6)} ${p('SetH', 5)} ${p('DL', 6, true)} ${p('DLday', 5)} ${p('D_S', 4)} ${p('D_E', 4)} ${p('Slack', 5)} ${p('OK?', 5)} ${p('Tw', 3)}`,
      );
      console.log(`  ${'-'.repeat(85)}`);

      for (let i = 0; i < blocks.length; i++) {
        const b = blocks[i];
        const status = b.onTime ? 'OK' : `LATE`;
        const slackStr = b.slackDays >= 0 ? `+${b.slackDays}` : `${b.slackDays}`;
        const skuStr =
          b.skus.length > 1
            ? `${b.skus[0].slice(0, 7)}+${b.skus[1].slice(0, 7)}`
            : b.skus[0].slice(0, 15);
        console.log(
          `  ${p(String(i + 1), 4)} ${p(b.tool, 8, true)} ${p(skuStr, 16, true)} ${p(b.qty.toLocaleString(), 9)} ${p(b.prodH.toFixed(1), 6)} ${p(b.setupH.toFixed(1), 5)} ${p(b.deadlineDate, 6, true)} ${p(String(b.deadlineDay), 5)} ${p(String(b.startDay), 4)} ${p(String(b.endDay), 4)} ${p(slackStr, 5)} ${p(status, 5)} ${p(b.isTwin ? 'T' : '', 3)}`,
        );
      }

      // Show LATE orders detail
      const lateBlocks = blocks.filter((b) => !b.onTime);
      if (lateBlocks.length > 0) {
        console.log(`\n  LATE ORDERS on ${mId}:`);
        for (const b of lateBlocks) {
          console.log(
            `    ${b.tool} ${b.skus.join('+')} | ${b.qty.toLocaleString()} pcs | deadline day ${b.deadlineDay} (${b.deadlineDate}) | ends day ${b.endDay} | ${Math.abs(b.slackDays)} days late`,
          );
        }
      }
    }

    // 4. Global summary
    section('GLOBAL SCHEDULE SUMMARY');

    const totalBlocks = allBlocks.length;
    const totalOnTime = allBlocks.filter((b) => b.onTime).length;
    const totalLate = allBlocks.filter((b) => !b.onTime).length;
    const globalOTD = totalBlocks > 0 ? (totalOnTime / totalBlocks) * 100 : 100;

    console.log(`  Total order blocks:   ${totalBlocks}`);
    console.log(`  On-time:              ${totalOnTime} (${globalOTD.toFixed(1)}%)`);
    console.log(`  Late:                 ${totalLate}`);

    if (totalLate > 0) {
      console.log(`\n  LATE ORDERS BY MACHINE:`);
      for (const [mId] of Object.entries(ordersByMachine).sort()) {
        const mLate = allBlocks.filter(
          (b) =>
            b.skus.length > 0 &&
            allOrders.find((o) => o.opId === b.opIds[0])?.machine === mId &&
            !b.onTime,
        );
        if (mLate.length > 0) {
          const maxLateness = Math.max(...mLate.map((b) => Math.abs(b.slackDays)));
          console.log(`    ${mId}: ${mLate.length} late (max ${maxLateness} days)`);
        }
      }
    }

    // Twin savings
    const twinBlocks = allBlocks.filter((b) => b.isTwin);
    if (twinBlocks.length > 0) {
      console.log(`\n  Twin co-production: ${twinBlocks.length} merged blocks`);
    }

    // Per machine capacity
    console.log(`\n  PER-MACHINE CAPACITY:`);
    console.log(
      `  ${p('Maq', 8, true)} ${p('Blocks', 7)} ${p('TotalH', 8)} ${p('Days', 5)} ${p('OTD%', 6)} ${p('Late', 5)}`,
    );
    console.log(`  ${'-'.repeat(42)}`);
    for (const [mId, orders] of Object.entries(ordersByMachine).sort()) {
      const mBlocks = allBlocks.filter((b) => orders.some((o) => o.opId === b.opIds[0]));
      const mTotalH = mBlocks.length > 0 ? mBlocks[mBlocks.length - 1].endH : 0;
      const mDays = Math.ceil(mTotalH / DAY_CAP_H);
      const mOnTime = mBlocks.filter((b) => b.onTime).length;
      const mLate = mBlocks.filter((b) => !b.onTime).length;
      const mOTD = mBlocks.length > 0 ? (mOnTime / mBlocks.length) * 100 : 100;
      console.log(
        `  ${p(mId, 8, true)} ${p(String(mBlocks.length), 7)} ${p(mTotalH.toFixed(1), 8)} ${p(String(mDays), 5)} ${p(mOTD.toFixed(0), 6)} ${p(String(mLate), 5)}`,
      );
    }

    header('END OF ANALYSIS');
  });
});
