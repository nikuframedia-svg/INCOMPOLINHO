/**
 * Shared types for ReplanAdvancedView, derived from useReplanOrchestrator.
 */
import type React from 'react';
import type { Block, DayLoad, EngineData, MoveAction, OptResult } from '@/domain/types/scheduling';
import type { ReplanHistoryEntry, ReplanKPISnapshot } from '../../hooks/useReplanHistory';
import type { useReplanOrchestrator } from '../../hooks/useReplanOrchestrator';

type OrchestratorReturn = ReturnType<typeof useReplanOrchestrator>;

export type ReplanRpc = OrchestratorReturn['rpc'];
export type ReplanRpcActions = OrchestratorReturn['rpcActions'];

export interface ReplanPreview {
  before: ReplanKPISnapshot;
  after: ReplanKPISnapshot;
  movesCount: number;
  pendingApply: (() => void) | null;
}

export interface ReplanAdvancedViewProps {
  data: EngineData;
  blocks: Block[];
  cap: Record<string, DayLoad[]>;
  mSt: Record<string, string>;
  tSt: Record<string, string>;
  moves: MoveAction[];
  applyMove: (opId: string, toM: string) => void;
  undoMove: (opId: string) => void;
  onApplyAndSave?: () => void;
  isSaving?: boolean;
  setResourceDown: (type: 'machine' | 'tool', id: string, days: number[]) => void;
  clearResourceDown: (type: 'machine' | 'tool', id: string) => void;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  rushOrders: Array<{ toolId: string; sku: string; qty: number; deadline: number }>;
  neMetrics: (OptResult & { blocks: Block[] }) | null;
  rpc: ReplanRpc;
  rpcActions: ReplanRpcActions;
  replanEntries: ReplanHistoryEntry[];
  undoEntry: (id: string) => ReplanHistoryEntry | null;
  clearHistory: () => void;
  replanPreview: ReplanPreview | null;
  setReplanPreview: React.Dispatch<React.SetStateAction<ReplanPreview | null>>;
  onSwitchSimple: () => void;
  profiles: Array<{ id: string; label: string; weights: Record<string, number> }>;
}
