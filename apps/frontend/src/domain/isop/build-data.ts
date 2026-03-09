/**
 * isop/build-data.ts — Build NikufraData from parsed rows.
 */

import type { LoadMeta } from '../../stores/useDataStore';
import type {
  NikufraCustomer,
  NikufraData,
  NikufraMachine,
  NikufraMOLoad,
  NikufraOperation,
  NikufraTool,
} from '../nikufra-types';
import { dayLabel, formatDate, MACHINE_AREA, type ParsedRow } from './helpers';
import { computeTrustScore } from './trust-score';

export interface BuildDataInput {
  parsedRows: ParsedRow[];
  dates: Date[];
  workdayFlags: boolean[];
  warnings: string[];
  headerRowIndex: number;
  dataStartRow: number;
  sourceColumns: {
    hasSetup: boolean;
    hasAltMachine: boolean;
    hasRate: boolean;
    hasParentSku: boolean;
    hasLeadTime: boolean;
    hasQtdExp: boolean;
    hasTwin: boolean;
  };
}

export interface BuildDataResult {
  data: NikufraData;
  meta: LoadMeta;
  sourceColumns: BuildDataInput['sourceColumns'];
}

export function buildNikufraData(input: BuildDataInput): BuildDataResult {
  const { parsedRows, dates, workdayFlags, warnings, sourceColumns } = input;
  const nDays = dates.length;

  // -- Machines: deduplicate and assign areas
  const machineSet = new Set<string>();
  parsedRows.forEach((r) => {
    machineSet.add(r.resource_code);
    if (r.alt_resource) machineSet.add(r.alt_resource);
  });

  const machinesDown = new Set<string>();
  parsedRows.forEach((r) => {
    if (r.machine_down) machinesDown.add(r.resource_code);
  });
  if (machinesDown.size > 0) {
    warnings.push(
      `Máquinas inoperacionais detectadas (texto/cor): ${Array.from(machinesDown).join(', ')}`,
    );
  }

  const unknownMachines = Array.from(machineSet).filter((id) => !MACHINE_AREA[id]);
  if (unknownMachines.length > 0) {
    warnings.push(
      `Máquina(s) desconhecida(s) atribuída(s) a PG1 por defeito: ${unknownMachines.join(', ')}. ` +
        `Verifique se a área está correcta.`,
    );
  }

  const machines: NikufraMachine[] = Array.from(machineSet)
    .sort()
    .map((id) => ({
      id,
      area: MACHINE_AREA[id] || 'PG1',
      man: new Array(nDays).fill(0),
      ...(machinesDown.has(id) ? { status: 'down' as const } : {}),
    }));

  // -- Tools: group by tool code, collect SKUs
  const toolMap = new Map<
    string,
    {
      id: string;
      m: string;
      alt: string;
      s: number;
      pH: number;
      op: number;
      skus: string[];
      nm: string[];
      lt: number;
      stk: number;
      wip: number;
    }
  >();

  for (const row of parsedRows) {
    if (!row.tool_code) continue;
    const existing = toolMap.get(row.tool_code);
    if (existing) {
      if (!existing.skus.includes(row.item_sku)) {
        existing.skus.push(row.item_sku);
        existing.nm.push(row.item_name);
      }
      if (row.resource_code !== existing.m) {
        warnings.push(
          `Ferramenta "${row.tool_code}" aparece com máquinas diferentes: ` +
            `${existing.m} (mantida) vs ${row.resource_code} (SKU ${row.item_sku}) — a usar ${existing.m}.`,
        );
      }
      existing.wip = Math.max(existing.wip, row.wip);
    } else {
      toolMap.set(row.tool_code, {
        id: row.tool_code,
        m: row.resource_code,
        alt: row.alt_resource || '-',
        s: row.setup_time,
        pH: row.rate,
        op: row.operators_required,
        skus: [row.item_sku],
        nm: [row.item_name],
        lt: row.lot_economic_qty,
        stk: 0,
        wip: row.wip,
      });
    }
  }

  const toolsDown = new Set<string>();
  parsedRows.forEach((r) => {
    if (r.tool_down && r.tool_code) toolsDown.add(r.tool_code);
  });
  if (toolsDown.size > 0) {
    warnings.push(
      `Ferramentas inoperacionais detectadas (texto/cor): ${Array.from(toolsDown).join(', ')}`,
    );
  }

  const tools: NikufraTool[] = Array.from(toolMap.values()).map((t) =>
    toolsDown.has(t.id) ? { ...t, status: 'down' as const } : t,
  );

  // -- Customers: deduplicate
  const customerMap = new Map<string, string>();
  for (const row of parsedRows) {
    if (row.customer_code && !customerMap.has(row.customer_code)) {
      customerMap.set(row.customer_code, row.customer_name);
    }
  }
  const customers: NikufraCustomer[] = Array.from(customerMap.entries())
    .map(([code, name]) => ({ code, name }))
    .sort((a, b) => a.code.localeCompare(b.code));

  const opsWithoutTool = parsedRows.filter((r) => !r.tool_code);
  if (opsWithoutTool.length > 0) {
    warnings.push(
      `${opsWithoutTool.length} operação(ões) sem código de ferramenta — não serão agendadas: ` +
        `${opsWithoutTool
          .slice(0, 5)
          .map((r) => r.item_sku)
          .join(', ')}${opsWithoutTool.length > 5 ? '…' : ''}`,
    );
  }

  // -- Operations: one per ISOP row
  const operations: NikufraOperation[] = parsedRows.map((row, idx) => ({
    id: `OP${String(idx + 1).padStart(2, '0')}`,
    m: row.resource_code,
    t: row.tool_code,
    sku: row.item_sku,
    nm: row.item_name,
    pH: row.rate,
    atr: row.atraso,
    d: row.daily_quantities,
    s: row.setup_time,
    op: row.operators_required,
    cl: row.customer_code || undefined,
    clNm: row.customer_name || undefined,
    pa: row.parent_sku || undefined,
    wip: row.wip || undefined,
    qe: row.qtd_exp || undefined,
    ltDays: row.lead_time_days || undefined,
    twin: row.twin || undefined,
  }));

  const mo: NikufraMOLoad = { PG1: [], PG2: [] };

  const dateLabels = dates.map((d) => formatDate(d));
  const dayLabels = dates.map((d) => dayLabel(d));

  const nikufraData: NikufraData = {
    dates: dateLabels,
    days_label: dayLabels,
    mo,
    machines,
    tools,
    operations,
    history: [],
    customers,
    workday_flags: workdayFlags,
  };

  // Trust score
  const trustResult = computeTrustScore(parsedRows, tools, operations, nDays);

  const uniqueSkus = new Set(parsedRows.map((r) => r.item_sku));
  const uniqueMachines = new Set(parsedRows.map((r) => r.resource_code));
  const uniqueTools = new Set(parsedRows.filter((r) => r.tool_code).map((r) => r.tool_code));
  const workdayCount = workdayFlags.filter(Boolean).length;

  const meta: LoadMeta = {
    rows: parsedRows.length,
    machines: uniqueMachines.size,
    tools: uniqueTools.size,
    skus: uniqueSkus.size,
    dates: nDays,
    workdays: workdayCount,
    trustScore: trustResult.score,
    trustDimensions: trustResult.dimensions,
    warnings,
  };

  const missing = Object.entries(sourceColumns)
    .filter(([, v]) => !v)
    .map(([k]) => k);
  if (missing.length > 0) {
    warnings.push(
      `Colunas não detectadas: ${missing.join(', ')} — serão preenchidas pelo ISOP Mestre ou defaults.`,
    );
  }

  return { data: nikufraData, meta, sourceColumns };
}
