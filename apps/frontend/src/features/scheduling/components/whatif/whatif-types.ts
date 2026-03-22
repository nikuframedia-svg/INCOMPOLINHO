import type { Block, EngineData, EOp, MoveAction, OptResult } from '@/domain/types/scheduling';
import type { buildResourceTimelines } from '@/utils/failure-timeline';

export type WhatIfViewProps = {
  data: EngineData;
  onApplyMoves?: (
    moves: MoveAction[],
    scenarioState: { mSt: Record<string, string>; tSt: Record<string, string> },
  ) => void;
  isSaving?: boolean;
  setResourceDown: (type: 'machine' | 'tool', id: string, days: number[]) => void;
  clearResourceDown: (type: 'machine' | 'tool', id: string) => void;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  replanTimelines: ReturnType<typeof buildResourceTimelines> | null;
  blocks?: Block[];
  allOps?: EOp[];
  neMetrics?: OptResult | null;
};

export type ScenarioConfig = {
  t1: number;
  p1: number;
  t2: number;
  p2: number;
  seed: number;
};

export type EditingDown = { type: 'machine' | 'tool'; id: string } | null;

export type QualityViolations = {
  criticalCount: number;
  highCount: number;
  warnings: string[];
};
