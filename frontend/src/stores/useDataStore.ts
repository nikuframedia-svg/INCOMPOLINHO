import { create } from "zustand";
import { getScore, getSegments, getLots, getConfig, getLearning } from "../api/endpoints";
import type { Score, Segment, Lot, FactoryConfig, LearningInfo } from "../api/types";

interface DataState {
  score: Score | null;
  segments: Segment[] | null;
  lots: Lot[] | null;
  config: FactoryConfig | null;
  learning: LearningInfo | null;

  refreshAll: () => Promise<void>;
  clear: () => void;
}

export const useDataStore = create<DataState>((set) => ({
  score: null,
  segments: null,
  lots: null,
  config: null,
  learning: null,

  refreshAll: async () => {
    const results = await Promise.allSettled([
      getScore(),
      getSegments(),
      getLots(),
      getConfig(),
      getLearning(),
    ]);
    set({
      score: results[0].status === "fulfilled" ? results[0].value : null,
      segments: results[1].status === "fulfilled" ? results[1].value : null,
      lots: results[2].status === "fulfilled" ? results[2].value : null,
      config: results[3].status === "fulfilled" ? results[3].value : null,
      learning: results[4].status === "fulfilled" ? results[4].value : null,
    });
  },

  clear: () => set({ score: null, segments: null, lots: null, config: null, learning: null }),
}));
