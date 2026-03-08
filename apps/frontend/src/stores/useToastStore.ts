import { create } from 'zustand';

export interface Toast {
  id: string;
  message: string;
  type: 'success' | 'error' | 'info' | 'warning';
  duration?: number;
}

export interface ToastActions {
  addToast: (message: string, type: Toast['type'], duration?: number) => void;
  removeToast: (id: string) => void;
}

interface ToastState {
  toasts: Toast[];
  actions: ToastActions;
}

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],

  actions: {
    addToast: (message, type, duration = 4000) => {
      const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
      const toast: Toast = { id, message, type, duration };

      set((state) => ({ toasts: [...state.toasts, toast] }));

      setTimeout(() => {
        set((state) => ({
          toasts: state.toasts.filter((t) => t.id !== id),
        }));
      }, duration);
    },

    removeToast: (id) => {
      set((state) => ({
        toasts: state.toasts.filter((t) => t.id !== id),
      }));
    },
  },
}));

// ── Atomic selector hooks ─────────────────────────────────────

export const useToasts = () => useToastStore((s) => s.toasts);
export const useToastActions = () => useToastStore((s) => s.actions);
