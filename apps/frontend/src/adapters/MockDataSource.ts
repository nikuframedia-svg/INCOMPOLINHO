/**
 * MockDataSource — Loads ONLY real Nikufra data from nikufra_data.json.
 *
 * MANDATO §22: Dados 100% reais. Nenhum valor é inventado ou hardcoded.
 * - Routing, tools, machines, setup, rates, operators → real (ISOP / bdmestre)
 * - Schedule, KPIs → NOT fabricated here; computed by NikufraEngine at runtime
 */

import type { NikufraDataPayload } from '../domain/api-types';
import type {
  NikufraData,
  NikufraTool,
  PlanningMachine,
  PlanningOperation,
  PlanningTool,
  PlanState,
} from '../domain/nikufra-types';
import type { Plan } from '../domain/types';
import type { IDataSource } from '../stores/useAppStore';

// Re-export types that other files import from this module
export type { CreatePRParams, CreateScenarioParams, ScenarioExtended } from '../domain/types';

// ── Data Store (user-loaded ISOP data) ──
import { applyMasterOverrides } from '../domain/apply-master-overrides';
import { useDataStore } from '../stores/useDataStore';
import { useMasterDataStore } from '../stores/useMasterDataStore';

// ── Fixture loader ──

let nikufraCache: NikufraData | null = null;

async function loadNikufraData(): Promise<NikufraData> {
  // Priority: user-loaded data from ISOP upload > fixture
  const userData = useDataStore.getState().nikufraData;
  if (userData) return userData;

  if (nikufraCache) return nikufraCache;
  const res = await fetch('/fixtures/nikufra/nikufra_data.json');
  if (!res.ok) throw new Error('nikufra_data.json not found');
  nikufraCache = (await res.json()) as NikufraData;
  return nikufraCache;
}

// ── Shared PlanState builder ──

function buildPlanState(nk: NikufraData): PlanState {
  const machines: PlanningMachine[] = nk.machines.map((m) => ({
    id: m.id,
    area: m.area as 'PG1' | 'PG2',
    man_minutes: m.man,
  }));

  const tools: PlanningTool[] = nk.tools.map((t) => ({
    id: t.id,
    machine: t.m,
    alt_machine: t.alt,
    setup_hours: t.s,
    pcs_per_hour: t.pH,
    operators: t.op,
    skus: t.skus,
    names: t.nm,
    lot_economic_qty: t.lt,
    stock: 0, // Stock-A eliminado
    wip: t.wip,
  }));

  // Build tool lookup for stock propagation
  const toolLookup: Record<string, NikufraTool> = {};
  nk.tools.forEach((t) => {
    toolLookup[t.id] = t;
  });

  const operations: PlanningOperation[] = nk.operations.map((op) => {
    const tool = toolLookup[op.t];
    return {
      id: op.id,
      machine: op.m,
      tool: op.t,
      sku: op.sku,
      name: op.nm,
      pcs_per_hour: op.pH,
      atraso: op.atr,
      daily_qty: op.d,
      setup_hours: op.s,
      operators: op.op,
      stock: 0, // Stock-A eliminado
      status: 'PLANNED' as const,
      customer_code: op.cl,
      customer_name: op.clNm,
      parent_sku: op.pa,
      wip: op.wip ?? tool?.wip ?? 0,
      qtd_exp: op.qe,
      lead_time_days: op.ltDays,
      twin: op.twin,
    };
  });

  const machineStatus: Record<string, 'running' | 'down'> = {};
  nk.machines.forEach((m) => {
    if (m.status === 'down') machineStatus[m.id] = 'down';
  });
  const toolStatus: Record<string, 'running' | 'down'> = {};
  nk.tools.forEach((t) => {
    if (t.status === 'down') toolStatus[t.id] = 'down';
  });

  return {
    dates: nk.dates,
    days_label: nk.days_label,
    machines,
    tools,
    operations,
    schedule: [],
    machine_loads: [],
    kpis: null,
    parsed_at: new Date().toISOString(),
    data_hash: null,
    mo: nk.mo
      ? {
          PG1: nk.mo.PG1,
          PG2: nk.mo.PG2,
          ...(nk.mo.poolPG1 ? { poolPG1: nk.mo.poolPG1 } : {}),
          ...(nk.mo.poolPG2 ? { poolPG2: nk.mo.poolPG2 } : {}),
        }
      : undefined,
    workday_flags: nk.workday_flags,
    ...(Object.keys(machineStatus).length > 0 ? { machineStatus } : {}),
    ...(Object.keys(toolStatus).length > 0 ? { toolStatus } : {}),
  };
}

// ── MockDataSource ──

export const MockDataSource: IDataSource = {
  // Plans — no backend data (replanStore uses this with null-safe handling)
  async getPlan(): Promise<Plan | null> {
    return null;
  },

  // Scenarios — no backend data
  async getScenarioDiff() {
    return null;
  },

  // NikufraData for backend pipeline (returns null if no user-loaded data)
  getNikufraData(): NikufraDataPayload | null {
    const userData = useDataStore.getState().nikufraData;
    return userData ? (userData as unknown as NikufraDataPayload) : null;
  },

  // Planning Engine — transforms nikufra_data.json SHORT→LONG names
  // Schedule and KPIs are NOT fabricated here; NikufraEngine computes them.
  async getPlanState(): Promise<PlanState> {
    const nk = await loadNikufraData();
    const { toolOverrides, machineOverrides } = useMasterDataStore.getState();
    const overridden = applyMasterOverrides(nk, toolOverrides, machineOverrides);
    return buildPlanState(overridden);
  },

  // Replan — apply moves + machine/tool status, persist to data store
  async applyReplan(params: {
    moves: Array<{ op_id: string; from_machine: string; to_machine: string }>;
    machine_status: Record<string, string>;
    tool_status: Record<string, string>;
    author: string;
    description: string;
  }): Promise<PlanState> {
    const nk = await loadNikufraData();
    const modified: NikufraData = JSON.parse(JSON.stringify(nk));

    // Apply moves: reassign operations to new machines
    for (const move of params.moves) {
      const op = modified.operations.find((o) => o.id === move.op_id);
      if (op) op.m = move.to_machine;
    }

    // Apply machine status (mark machines as down/running)
    for (const [id, status] of Object.entries(params.machine_status)) {
      const machine = modified.machines.find((m) => m.id === id);
      if (machine) machine.status = status as 'running' | 'down';
    }

    // Apply tool status (mark tools as down/running)
    for (const [id, status] of Object.entries(params.tool_status)) {
      const tool = modified.tools.find((t) => t.id === id);
      if (tool) tool.status = status as 'running' | 'down';
    }

    // Persist modified data (survives page reload via localStorage)
    useDataStore.setState({ nikufraData: modified });
    nikufraCache = null;

    const { toolOverrides, machineOverrides } = useMasterDataStore.getState();
    const overridden = applyMasterOverrides(modified, toolOverrides, machineOverrides);
    return buildPlanState(overridden);
  },
};
