// ═══════════════════════════════════════════════════════════
//  Replan Store — Minimal store for external refresh callback.
//  Legacy backend simulation/scenario logic removed (scheduling is client-side).
//  Only onApplyCallback is actively used by NikufraEngine.
// ═══════════════════════════════════════════════════════════

import { create } from 'zustand';

export interface ReplanActions {
  setOnApplyCallback: (cb: (() => void) | null) => void;
}

interface ReplanState {
  onApplyCallback: (() => void) | null;
  actions: ReplanActions;
}

export const useReplanStore = create<ReplanState>((set) => ({
  onApplyCallback: null,
  actions: {
    setOnApplyCallback: (cb) => set({ onApplyCallback: cb }),
  },
}));

// ── Atomic selector hooks ─────────────────────────────────────

export const useReplanActions = () => useReplanStore((s) => s.actions);
