/**
 * useCopilot — Zustand store for copilot chat state.
 *
 * Manages conversation history, loading state, and schedule invalidation.
 */

import { create } from 'zustand';
import { type ChatMessage, sendCopilotMessage } from './copilotApi';

export interface DisplayMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: number;
  timestamp: number;
}

interface CopilotState {
  messages: DisplayMessage[];
  isLoading: boolean;
  error: string | null;
  scheduleVersion: number;
}

interface CopilotActions {
  sendMessage: (text: string) => Promise<void>;
  clearMessages: () => void;
  clearError: () => void;
}

type CopilotStore = CopilotState & { actions: CopilotActions };

let _msgCounter = 0;
function nextId(): string {
  return `msg_${++_msgCounter}_${Date.now()}`;
}

export const useCopilotStore = create<CopilotStore>((set, get) => ({
  messages: [],
  isLoading: false,
  error: null,
  scheduleVersion: 0,

  actions: {
    sendMessage: async (text: string) => {
      const userMsg: DisplayMessage = {
        id: nextId(),
        role: 'user',
        content: text,
        timestamp: Date.now(),
      };

      set((s) => ({
        messages: [...s.messages, userMsg],
        isLoading: true,
        error: null,
      }));

      try {
        // Build conversation history for API
        const history: ChatMessage[] = get().messages.map((m) => ({
          role: m.role,
          content: m.content,
        }));

        const response = await sendCopilotMessage(history);

        const assistantMsg: DisplayMessage = {
          id: nextId(),
          role: 'assistant',
          content: response.response,
          toolCalls: response.tool_calls_made,
          timestamp: Date.now(),
        };

        set((s) => ({
          messages: [...s.messages, assistantMsg],
          isLoading: false,
          // Bump schedule version if tools were called (triggers refresh)
          scheduleVersion: response.tool_calls_made > 0 ? s.scheduleVersion + 1 : s.scheduleVersion,
        }));
      } catch (err) {
        const errorMsg = err instanceof Error ? err.message : 'Erro desconhecido';
        set({ isLoading: false, error: errorMsg });
      }
    },

    clearMessages: () => set({ messages: [], error: null }),

    clearError: () => set({ error: null }),
  },
}));

// ── Atomic selectors ─────────────────────────────────────────
export const useCopilotMessages = () => useCopilotStore((s) => s.messages);
export const useCopilotLoading = () => useCopilotStore((s) => s.isLoading);
export const useCopilotError = () => useCopilotStore((s) => s.error);
export const useCopilotScheduleVersion = () => useCopilotStore((s) => s.scheduleVersion);
export const useCopilotActions = () => useCopilotStore((s) => s.actions);
