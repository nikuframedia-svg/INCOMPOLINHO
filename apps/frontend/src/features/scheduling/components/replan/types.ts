/**
 * Shared types for ReplanPanel sub-components.
 */
import type React from 'react';
import type {
  AlternativeAction,
  AutoReplanResult,
  EMachine,
  ETool,
  FailureEvent,
  ImpactReport,
  ObjectiveProfile,
  OptResult,
  ReplanActionDetail,
  ReplanProposal,
  ReplanSimulation,
} from '../../../../lib/engine';

export type { ReplanProposal };

export interface DayRangePickerProps {
  editingDown: { type: 'machine' | 'tool'; id: string };
  currentDown: Set<number>;
  dates: string[];
  dnames: string[];
  wdi: number[];
  downStartDay: number;
  downEndDay: number;
  setDownStartDay: React.Dispatch<React.SetStateAction<number>>;
  setDownEndDay: React.Dispatch<React.SetStateAction<number>>;
  setEditingDown: React.Dispatch<
    React.SetStateAction<{ type: 'machine' | 'tool'; id: string } | null>
  >;
  setResourceDown: (type: 'machine' | 'tool', id: string, days: number[]) => void;
  clearResourceDown: (type: 'machine' | 'tool', id: string) => void;
}

export interface AutoReplanCardProps {
  wdi: number[];
  dates: string[];
  dnames: string[];
  nDays: number;
  tools: ETool[];
  focusIds: string[];
  arRunning: boolean;
  arResult: AutoReplanResult | null;
  arActions: ReplanActionDetail[];
  arSim: ReplanSimulation | null;
  arSimId: string | null;
  arExclude: Set<string>;
  arDayFrom: number;
  arDayTo: number;
  arExpanded: string | null;
  arShowExclude: boolean;
  setArExclude: React.Dispatch<React.SetStateAction<Set<string>>>;
  setArDayFrom: React.Dispatch<React.SetStateAction<number>>;
  setArDayTo: React.Dispatch<React.SetStateAction<number>>;
  setArExpanded: React.Dispatch<React.SetStateAction<string | null>>;
  setArShowExclude: React.Dispatch<React.SetStateAction<boolean>>;
  setArResult: React.Dispatch<React.SetStateAction<AutoReplanResult | null>>;
  runAutoReplan: () => void;
  handleArUndo: (decisionId: string) => void;
  handleArAlt: (decisionId: string, alt: AlternativeAction) => void;
  handleArSimulate: (decisionId: string) => void;
  handleArUndoAll: () => void;
  handleArApplyAll: () => void;
}

export interface FailureFormCardProps {
  machines: EMachine[];
  tools: ETool[];
  focusIds: string[];
  failures: FailureEvent[];
  failureImpacts: ImpactReport[];
  showFailureForm: boolean;
  ffResType: 'machine' | 'tool';
  ffResId: string;
  ffSev: 'total' | 'partial' | 'degraded';
  ffCap: number;
  ffStartDay: number;
  ffEndDay: number;
  ffDesc: string;
  cascRunning: boolean;
  wdi: number[];
  dates: string[];
  dnames: string[];
  setShowFailureForm: React.Dispatch<React.SetStateAction<boolean>>;
  setFfResType: React.Dispatch<React.SetStateAction<'machine' | 'tool'>>;
  setFfResId: React.Dispatch<React.SetStateAction<string>>;
  setFfSev: React.Dispatch<React.SetStateAction<'total' | 'partial' | 'degraded'>>;
  setFfCap: React.Dispatch<React.SetStateAction<number>>;
  setFfStartDay: React.Dispatch<React.SetStateAction<number>>;
  setFfEndDay: React.Dispatch<React.SetStateAction<number>>;
  setFfDesc: React.Dispatch<React.SetStateAction<string>>;
  addFailure: () => void;
  removeFailure: (id: string) => void;
  runCascadingReplan: () => void;
}

export interface OptimalRoutingCardProps {
  tools: ETool[];
  optRunning: boolean;
  optResults: OptResult[];
  optProgress: number;
  optN: number;
  optProfile: string;
  optMoveable: Array<{
    opId: string;
    toolId: string;
    primaryM: string;
    altM: string;
    totalPcs: number;
    hrs: number;
  }>;
  setOptN: React.Dispatch<React.SetStateAction<number>>;
  setOptProfile: React.Dispatch<React.SetStateAction<string>>;
  setOptResults: React.Dispatch<React.SetStateAction<OptResult[]>>;
  runOpt: () => void;
  applyOptResult: (r: OptResult) => void;
  profiles: ObjectiveProfile[];
}

export interface RushOrderCardProps {
  tools: ETool[];
  focusIds: string[];
  toolMap: Record<string, ETool>;
  rushOrders: Array<{ toolId: string; sku: string; qty: number; deadline: number }>;
  roTool: string;
  roQty: number;
  roDeadline: number;
  wdi: number[];
  dates: string[];
  dnames: string[];
  setRoTool: React.Dispatch<React.SetStateAction<string>>;
  setRoQty: React.Dispatch<React.SetStateAction<number>>;
  setRoDeadline: React.Dispatch<React.SetStateAction<number>>;
  addRushOrder: () => void;
  removeRushOrder: (idx: number) => void;
}
