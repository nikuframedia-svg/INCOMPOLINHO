/**
 * useUIStore — Shared UI state across all pages.
 *
 * Manages: command palette visibility, focus strip context,
 * context panel state, temporal zoom level.
 * Persists user preferences (zoom, collapse states) via localStorage.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type TemporalZoom = 'shift' | 'day' | 'week';
export type ThemeMode = 'light' | 'dark';

export interface FocusContext {
  machine?: string | null;
  day?: string | null;
  dayIdx?: number | null;
  scenario?: string | null;
  toolId?: string | null;
}

export interface UIActions {
  openCommandPalette: () => void;
  closeCommandPalette: () => void;
  toggleCommandPalette: () => void;
  setFocus: (ctx: Partial<FocusContext>) => void;
  clearFocus: () => void;
  openContextPanel: (entity: { type: string; id: string }) => void;
  closeContextPanel: () => void;
  setTemporalZoom: (zoom: TemporalZoom) => void;
  setSelectedDayIdx: (idx: number) => void;
  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  openMobileSidebar: () => void;
  closeMobileSidebar: () => void;
  setMrpRiskCount: (count: number) => void;
  toggleCopilotPanel: () => void;
  openCopilotPanel: () => void;
  closeCopilotPanel: () => void;
}

interface UIStoreState {
  commandPaletteOpen: boolean;
  focus: FocusContext;
  contextPanelOpen: boolean;
  contextEntity: { type: string; id: string } | null;
  temporalZoom: TemporalZoom;
  selectedDayIdx: number;
  theme: ThemeMode;
  sidebarCollapsed: boolean;
  sidebarMobileOpen: boolean;
  mrpRiskCount: number;
  copilotPanelOpen: boolean;
  actions: UIActions;
}

export const useUIStore = create<UIStoreState>()(
  persist(
    (set) => ({
      commandPaletteOpen: false,
      focus: {},
      contextPanelOpen: false,
      contextEntity: null,
      temporalZoom: 'day',
      selectedDayIdx: 0,
      theme: 'light',
      sidebarCollapsed: false,
      sidebarMobileOpen: false,
      mrpRiskCount: 0,
      copilotPanelOpen: false,

      actions: {
        openCommandPalette: () => set({ commandPaletteOpen: true }),
        closeCommandPalette: () => set({ commandPaletteOpen: false }),
        toggleCommandPalette: () => set((s) => ({ commandPaletteOpen: !s.commandPaletteOpen })),
        setFocus: (ctx) => set((s) => ({ focus: { ...s.focus, ...ctx } })),
        clearFocus: () => set({ focus: {} }),
        openContextPanel: (entity) => set({ contextPanelOpen: true, contextEntity: entity }),
        closeContextPanel: () => set({ contextPanelOpen: false, contextEntity: null }),
        setTemporalZoom: (zoom) => set({ temporalZoom: zoom }),
        setSelectedDayIdx: (idx) => set({ selectedDayIdx: idx }),
        setTheme: (theme) => set({ theme }),
        toggleTheme: () => set((s) => ({ theme: s.theme === 'light' ? 'dark' : 'light' })),
        toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
        setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
        openMobileSidebar: () => set({ sidebarMobileOpen: true }),
        closeMobileSidebar: () => set({ sidebarMobileOpen: false }),
        setMrpRiskCount: (count) => set({ mrpRiskCount: count }),
        toggleCopilotPanel: () => set((s) => ({ copilotPanelOpen: !s.copilotPanelOpen })),
        openCopilotPanel: () => set({ copilotPanelOpen: true }),
        closeCopilotPanel: () => set({ copilotPanelOpen: false }),
      },
    }),
    {
      name: 'pp1-ui-state',
      partialize: (state) => ({
        temporalZoom: state.temporalZoom,
        selectedDayIdx: state.selectedDayIdx,
        theme: state.theme,
        sidebarCollapsed: state.sidebarCollapsed,
      }),
    },
  ),
);

// ── Atomic selector hooks ─────────────────────────────────────

export const useCommandPaletteOpen = () => useUIStore((s) => s.commandPaletteOpen);
export const useContextPanelOpen = () => useUIStore((s) => s.contextPanelOpen);
export const useContextEntity = () => useUIStore((s) => s.contextEntity);
export const useFocus = () => useUIStore((s) => s.focus);
export const useSelectedDayIdx = () => useUIStore((s) => s.selectedDayIdx);
export const useTheme = () => useUIStore((s) => s.theme);
export const useSidebarCollapsed = () => useUIStore((s) => s.sidebarCollapsed);
export const useSidebarMobileOpen = () => useUIStore((s) => s.sidebarMobileOpen);
export const useMrpRiskCount = () => useUIStore((s) => s.mrpRiskCount);
export const useCopilotPanelOpen = () => useUIStore((s) => s.copilotPanelOpen);
export const useUIActions = () => useUIStore((s) => s.actions);
