/**
 * isop/helpers.ts — Parse helpers, normalizers, date utilities, and shared types.
 */

import * as XLSX from 'xlsx';

// ── Machine → Area mapping (claude-bdmestre.md §2) ──

export const MACHINE_AREA: Record<string, 'PG1' | 'PG2'> = {
  PRM019: 'PG1',
  PRM020: 'PG1',
  PRM043: 'PG1',
  PRM031: 'PG2',
  PRM039: 'PG2',
  PRM042: 'PG2',
};

// ── Day name helper ──

const DAY_NAMES_PT = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];

export function dayLabel(d: Date): string {
  return DAY_NAMES_PT[d.getDay()];
}

export function formatDate(d: Date): string {
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  return `${dd}/${mm}`;
}

// ── Parse helpers ──

export function parseNumeric(value: unknown, fallback: number = 0): number {
  if (value == null) return fallback;
  if (typeof value === 'number') return value;
  if (typeof value === 'string') {
    const cleaned = value.replace(',', '.').trim();
    const n = Number(cleaned);
    return isNaN(n) ? fallback : n;
  }
  return fallback;
}

export function parseInteger(value: unknown, fallback: number = 1): number {
  return Math.round(parseNumeric(value, fallback));
}

export function normalizeCode(value: unknown): string {
  if (value == null) return '';
  return String(value).trim().toUpperCase();
}

export function normalizeString(value: unknown): string {
  if (value == null) return '';
  return String(value).trim();
}

// ── Date parsing from Excel ──

export function parseDateCell(value: unknown): Date | null {
  if (value == null) return null;
  if (value instanceof Date) {
    return isNaN(value.getTime()) ? null : value;
  }
  if (typeof value === 'number') {
    const d = XLSX.SSF.parse_date_code(value);
    if (d) return new Date(d.y, d.m - 1, d.d);
    return null;
  }
  if (typeof value === 'string') {
    const iso = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (iso) return new Date(Number(iso[1]), Number(iso[2]) - 1, Number(iso[3]));

    const dmyFull = value.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
    if (dmyFull) return new Date(Number(dmyFull[3]), Number(dmyFull[2]) - 1, Number(dmyFull[1]));

    const dm = value.match(/^(\d{1,2})\/(\d{1,2})$/);
    if (dm) {
      const year = new Date().getFullYear();
      return new Date(year, Number(dm[2]) - 1, Number(dm[1]));
    }
    return null;
  }
  return null;
}

// ── Shared types ──

export interface ParsedRow {
  customer_code: string;
  customer_name: string;
  parent_sku: string;
  item_sku: string;
  item_name: string;
  lot_economic_qty: number;
  lead_time_days: number;
  resource_code: string;
  alt_resource: string;
  tool_code: string;
  setup_time: number;
  rate: number;
  operators_required: number;
  qtd_exp: number;
  stock: number;
  wip: number;
  atraso: number;
  daily_quantities: (number | null)[];
  machine_down: boolean;
  tool_down: boolean;
  twin: string;
}
