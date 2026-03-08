import { create } from 'zustand';
import { MockDataSource } from '../adapters/MockDataSource';
import type { PlanState } from '../domain/nikufra-types';
import type {
  CreatePRParams,
  CreateScenarioParams,
  KPIPack,
  Plan,
  ScenarioExtended,
} from '../domain/types';

// Interface — only methods actually called in the codebase
export interface IDataSource {
  // Plans (used by useReplanStore)
  getPlan: (id: string) => Promise<Plan | null>;

  // Scenarios (used by useReplanStore)
  getScenarioDiff: (id: string) => Promise<ScenarioExtended | null>;
  createScenario?: (params: CreateScenarioParams) => Promise<{
    success: boolean;
    scenario_id: string;
    correlation_id: string;
  }>;
  runScenario?: (scenarioId: string) => Promise<{
    success: boolean;
    scenario_id: string;
    result_plan_id: string;
    kpi_delta: Partial<KPIPack>;
    correlation_id: string;
  }>;

  // PRs (used by useReplanStore fallback)
  createPR?: (params: CreatePRParams) => Promise<{
    success: boolean;
    pr_id: string;
    correlation_id: string;
  }>;

  // Events (used by useReplanStore)
  createEvent?: (event: {
    event_type: string;
    resource_code?: string;
    description: string;
    start_time: string;
    end_time?: string;
    severity?: string;
  }) => Promise<unknown>;

  // Planning Engine (used by useScheduleData + NikufraEngine)
  getPlanState?: () => Promise<PlanState>;
  applyReplan?: (params: {
    moves: Array<{ op_id: string; from_machine: string; to_machine: string }>;
    machine_status: Record<string, string>;
    tool_status: Record<string, string>;
    author: string;
    description: string;
  }) => Promise<PlanState>;
}

const initialDataSource: IDataSource = MockDataSource as IDataSource;

export interface AppActions {
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  initializeDataSource: () => void;
  setCurrentUser: (user: AppState['currentUser']) => void;
}

interface AppState {
  dataSource: IDataSource;
  isLoading: boolean;
  error: string | null;
  currentUser: {
    id: string;
    name: string;
    role: 'VIEWER' | 'PLANNER' | 'APPROVER' | 'ADMIN';
  };
  actions: AppActions;
}

export const useAppStore = create<AppState>((set) => ({
  dataSource: initialDataSource,
  isLoading: false,
  error: null,
  currentUser: {
    id: 'planner-001',
    name: 'Default Planner',
    role: 'PLANNER',
  },

  actions: {
    setLoading: (loading) => set({ isLoading: loading }),
    setError: (error) => set({ error }),
    initializeDataSource: () => {
      // Data source is initialized at module load time via initialDataSource.
      // No-op to prevent infinite re-render loops when called from useEffect.
    },
    setCurrentUser: (user) => set({ currentUser: user }),
  },
}));

// ── Atomic selector hooks ─────────────────────────────────────

export const useDataSource = () => useAppStore((s) => s.dataSource);
export const useAppActions = () => useAppStore((s) => s.actions);
