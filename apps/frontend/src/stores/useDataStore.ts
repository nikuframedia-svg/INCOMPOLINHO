/**
 * useDataStore — Persistence store for user-loaded daily ISOP data.
 *
 * When the user uploads a daily ISOP XLSX, parsed NikufraData is stored here.
 * MockDataSource reads from this store before falling back to the fixture.
 * Data persists across page reloads via localStorage (Zustand persist middleware).
 *
 * After parsing, daily ISOP data is enriched with master data from:
 *   1. Fixture nikufra_data.json (embedded factory configuration)
 *   2. Factory defaults (defaultSetupHours from useSettingsStore) — last resort
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { MasterISOPData, NikufraData } from '../domain/nikufra-types';
import { useToastStore } from './useToastStore';

export interface LoadMeta {
  rows: number;
  machines: number;
  tools: number;
  skus: number;
  dates: number;
  workdays: number;
  trustScore: number;
  warnings: string[];
}

// ── Master data merge ──────────────────────────────────────────────────

import { useSettingsStore } from './useSettingsStore';

const getDefaultSetupHours = () => useSettingsStore.getState().defaultSetupHours;

export interface MergeReport {
  setupsEnriched: number;
  altsEnriched: number;
  ratesEnriched: number;
  opsEnriched: number;
  moEnriched: boolean;
  unknownTools: string[];
  zeroRateOps: string[];
  source: 'master-fixture' | 'none';
}

/**
 * Pure merge function: apply master data (setup, alt, rate, operators, MO) onto daily ISOP data.
 * Source-agnostic — works with either uploaded master or fixture.
 * Returns enriched data + a merge report for user feedback.
 */
function mergeFromMaster(
  data: NikufraData,
  master: MasterISOPData,
  source: MergeReport['source'],
): { data: NikufraData; report: MergeReport } {
  const masterToolMap = new Map(master.tools.map((t) => [t.id, t]));

  let setupsEnriched = 0;
  let altsEnriched = 0;
  let ratesEnriched = 0;

  const unknownTools = data.tools.filter((t) => !masterToolMap.has(t.id)).map((t) => t.id);
  if (unknownTools.length > 0) {
    import.meta.env.DEV &&
      console.warn(
        `[mergeFromMaster] ${unknownTools.length} tool(s) not in master: ${unknownTools.join(', ')}`,
      );
  }

  const _defSetup = getDefaultSetupHours();
  const mergedTools = data.tools.map((tool) => {
    const mst = masterToolMap.get(tool.id);
    if (!mst) {
      if (tool.s <= 0) return { ...tool, s: _defSetup };
      return tool;
    }

    const newS = tool.s > 0 ? tool.s : mst.s > 0 ? mst.s : _defSetup;
    const newAlt = tool.alt !== '-' && tool.alt !== '' ? tool.alt : mst.alt;
    const newPH = tool.pH > 0 ? tool.pH : mst.pH;
    const newOp = tool.op > 0 ? tool.op : mst.op;
    const newLt = tool.lt > 0 ? tool.lt : mst.lt;

    if (newS !== tool.s) setupsEnriched++;
    if (newAlt !== tool.alt) altsEnriched++;
    if (newPH !== tool.pH) ratesEnriched++;

    return { ...tool, s: newS, alt: newAlt, pH: newPH, op: newOp, lt: newLt };
  });

  // Merge operations: propagate enriched values from tool
  const toolLookup = new Map(mergedTools.map((t) => [t.id, t]));
  let opsEnriched = 0;
  const zeroRateOps: string[] = [];

  const mergedOps = data.operations.map((op) => {
    const tool = toolLookup.get(op.t);
    if (!tool) {
      if (op.pH <= 0) zeroRateOps.push(`${op.id}(${op.sku})`);
      return op;
    }
    const newPH = op.pH > 0 ? op.pH : tool.pH;
    const newS = op.s > 0 ? op.s : tool.s > 0 ? tool.s : _defSetup;
    const newOp = op.op > 0 ? op.op : tool.op;
    if (newPH !== op.pH || newS !== op.s) opsEnriched++;
    if (newPH <= 0) zeroRateOps.push(`${op.id}(${op.sku})`);
    return { ...op, s: newS, pH: newPH, op: newOp };
  });

  // Merge MO: daily ISOP typically lacks operator capacity
  const parsedMoEmpty = !data.mo || data.mo.PG1.length === 0 || data.mo.PG1.every((v) => v === 0);
  const moEnriched = parsedMoEmpty && master.mo != null && master.mo.PG1.length > 0;
  const mergedMo = moEnriched ? master.mo : data.mo;

  const report: MergeReport = {
    setupsEnriched,
    altsEnriched,
    ratesEnriched,
    opsEnriched,
    moEnriched,
    unknownTools,
    zeroRateOps,
    source,
  };

  import.meta.env.DEV && console.info('[mergeFromMaster] Report:', report);

  return {
    data: {
      ...data,
      tools: mergedTools,
      operations: mergedOps,
      mo: mergedMo,
      workday_flags: data.workday_flags,
    },
    report,
  };
}

/**
 * Resolve master data source: always from embedded fixture (nikufra_data.json).
 * Returns fixture data + source label for merge reporting.
 */
async function resolveMasterSource(): Promise<{
  data: MasterISOPData;
  source: MergeReport['source'];
} | null> {
  try {
    const res = await fetch('/fixtures/nikufra/nikufra_data.json');
    if (!res.ok) {
      import.meta.env.DEV &&
        console.warn('[mergeWithMasterData] Fixture not available — skipping merge');
      return null;
    }
    const fixture = (await res.json()) as NikufraData;
    return {
      data: {
        tools: fixture.tools.map((t) => ({
          id: t.id,
          m: t.m,
          alt: t.alt,
          s: t.s,
          pH: t.pH,
          op: t.op,
          lt: t.lt,
        })),
        machines: fixture.machines.map((m) => ({ id: m.id, area: m.area })),
        mo: fixture.mo,
      },
      source: 'master-fixture',
    };
  } catch {
    import.meta.env.DEV &&
      console.warn('[mergeWithMasterData] Failed to load fixture — skipping merge');
    return null;
  }
}

/**
 * Enrich daily ISOP data with master data (setup times, alt machines, rates, MO).
 * Shows toast notification with merge summary.
 */
async function mergeWithMasterData(data: NikufraData): Promise<NikufraData> {
  const resolved = await resolveMasterSource();
  if (!resolved) {
    useToastStore
      .getState()
      .actions.addToast(
        'Sem dados Mestre — a usar defaults (setup 45min, sem máq. alternativa).',
        'warning',
      );
    return data;
  }

  const { data: merged, report } = mergeFromMaster(data, resolved.data, resolved.source);

  // Build toast message
  const parts: string[] = [];
  if (report.setupsEnriched > 0) parts.push(`${report.setupsEnriched} setups`);
  if (report.altsEnriched > 0) parts.push(`${report.altsEnriched} alt. machines`);
  if (report.ratesEnriched > 0) parts.push(`${report.ratesEnriched} rates`);
  if (report.moEnriched) parts.push('M.O.');

  const srcLabel = 'Fixture';

  if (parts.length > 0) {
    useToastStore
      .getState()
      .actions.addToast(`Enriquecido com ${srcLabel}: ${parts.join(', ')}.`, 'success');
  }

  if (report.unknownTools.length > 0) {
    useToastStore
      .getState()
      .actions.addToast(
        `${report.unknownTools.length} ferramenta(s) sem dados Mestre (setup=45min, sem máq. alt.): ${report.unknownTools.slice(0, 5).join(', ')}${report.unknownTools.length > 5 ? '…' : ''}`,
        'warning',
        8000,
      );
  }

  if (report.zeroRateOps.length > 0) {
    useToastStore
      .getState()
      .actions.addToast(
        `${report.zeroRateOps.length} operação(ões) com rate=0 — serão ignoradas pelo scheduler.`,
        'warning',
        6000,
      );
  }

  return merged;
}

// ── Actions interface ─────────────────────────────────────────

export interface DataActions {
  setNikufraData: (data: NikufraData, fileName: string, meta: LoadMeta) => Promise<void>;
  clearData: () => void;
  hasUserData: () => boolean;
}

// ── Store ──────────────────────────────────────────────────────────────

interface DataStoreState {
  nikufraData: NikufraData | null;
  _rawDailyData: NikufraData | null;
  loadedAt: string | null;
  fileName: string | null;
  meta: LoadMeta | null;
  isMerging: boolean;
  actions: DataActions;
}

export const useDataStore = create<DataStoreState>()(
  persist(
    (set, get) => ({
      nikufraData: null,
      _rawDailyData: null,
      loadedAt: null,
      fileName: null,
      meta: null,
      isMerging: false,

      actions: {
        setNikufraData: async (data, fileName, meta) => {
          set({ isMerging: true });
          const enriched = await mergeWithMasterData(data);
          set({
            nikufraData: enriched,
            _rawDailyData: data,
            loadedAt: new Date().toISOString(),
            fileName,
            meta,
            isMerging: false,
          });
        },

        clearData: () => {
          set({
            nikufraData: null,
            _rawDailyData: null,
            loadedAt: null,
            fileName: null,
            meta: null,
          });
        },

        hasUserData: () => get().nikufraData !== null,
      },
    }),
    {
      name: 'pp1-loaded-data',
      partialize: ({ actions: _, ...data }) => data,
    },
  ),
);

// Clean up legacy master data store (removed in favour of fixture-only approach)
if (typeof window !== 'undefined') {
  localStorage.removeItem('pp1-master-data');
}

// ── Atomic selector hooks ─────────────────────────────────────

export const useNikufraData = () => useDataStore((s) => s.nikufraData);
export const useIsMerging = () => useDataStore((s) => s.isMerging);
export const useDataActions = () => useDataStore((s) => s.actions);
