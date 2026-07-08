import { create } from "zustand";
import type { DatasetInfo } from "../api/types";

export const ACTIVE_DATASET_KEY = "pp1ActiveDatasetId";

interface AppState {
  activePage: string;
  chatOpen: boolean;
  hasData: boolean;
  isUploading: boolean;
  trustScore: number | null;
  trustGate: string | null;
  dataset: DatasetInfo | null;

  setPage: (page: string) => void;
  toggleChat: () => void;
  setHasData: (v: boolean) => void;
  setUploading: (v: boolean) => void;
  setTrust: (score: number, gate: string) => void;
  clearTrust: () => void;
  setDataset: (dataset: DatasetInfo | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  activePage: "console",
  chatOpen: false,
  hasData: false,
  isUploading: false,
  trustScore: null,
  trustGate: null,
  dataset: null,

  setPage: (page) => set({ activePage: page }),
  toggleChat: () => set((s) => ({ chatOpen: !s.chatOpen })),
  setHasData: (v) => set({ hasData: v }),
  setUploading: (v) => set({ isUploading: v }),
  setTrust: (score, gate) => set({ trustScore: score, trustGate: gate }),
  clearTrust: () => set({ trustScore: null, trustGate: null }),
  setDataset: (dataset) => set({ dataset }),
}));
