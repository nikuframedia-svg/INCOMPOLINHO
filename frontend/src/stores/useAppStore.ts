import { create } from "zustand";
import type { DatasetInfo } from "../api/types";
import { getStoredAccessMode, setStoredAccessMode, type AccessMode } from "../lib/accessMode.ts";

export const ACTIVE_DATASET_KEY = "pp1ActiveDatasetId";

interface AppState {
  activePage: string;
  chatOpen: boolean;
  hasData: boolean;
  isUploading: boolean;
  blockingRequests: number;
  blockingMessage: string;
  trustScore: number | null;
  trustGate: string | null;
  dataset: DatasetInfo | null;
  accessMode: AccessMode;

  setPage: (page: string) => void;
  toggleChat: () => void;
  setHasData: (v: boolean) => void;
  setUploading: (v: boolean) => void;
  beginBlockingRequest: (message?: string) => void;
  endBlockingRequest: () => void;
  setTrust: (score: number, gate: string) => void;
  clearTrust: () => void;
  setDataset: (dataset: DatasetInfo | null) => void;
  setAccessMode: (mode: AccessMode) => void;
}

export const useAppStore = create<AppState>((set) => ({
  activePage: "console",
  chatOpen: false,
  hasData: false,
  isUploading: false,
  blockingRequests: 0,
  blockingMessage: "",
  trustScore: null,
  trustGate: null,
  dataset: null,
  accessMode: getStoredAccessMode(),

  setPage: (page) => set({ activePage: page }),
  toggleChat: () => set((s) => ({ chatOpen: !s.chatOpen })),
  setHasData: (v) => set({ hasData: v }),
  setUploading: (v) => set({ isUploading: v }),
  beginBlockingRequest: (message = "A carregar…") => set((s) => ({
    blockingRequests: s.blockingRequests + 1,
    blockingMessage: message,
  })),
  endBlockingRequest: () => set((s) => {
    const next = Math.max(0, s.blockingRequests - 1);
    return {
      blockingRequests: next,
      blockingMessage: next > 0 ? s.blockingMessage : "",
    };
  }),
  setTrust: (score, gate) => set({ trustScore: score, trustGate: gate }),
  clearTrust: () => set({ trustScore: null, trustGate: null }),
  setDataset: (dataset) => set({ dataset }),
  setAccessMode: (mode) => {
    setStoredAccessMode(mode);
    set({ accessMode: mode });
  },
}));
