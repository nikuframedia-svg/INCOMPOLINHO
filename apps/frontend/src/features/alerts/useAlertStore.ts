/**
 * useAlertStore — ISA-18.2 alert management store.
 *
 * Manages alarm lifecycle: activate → acknowledge → clear/shelve/suppress.
 * Tracks EEMUA 191 metrics (alarms per 10min, standing count).
 */

import { create } from 'zustand';
import type { AlarmState, Alert, AlertPriority } from './alert-types';

interface AlertState {
  alerts: Alert[];
  /** Alarms activated in the last 10 minutes (rolling count) */
  alarmsPerTenMin: number;

  // Actions
  addAlert: (alert: Alert) => void;
  acknowledge: (id: string) => void;
  clear: (id: string) => void;
  shelve: (id: string, reason: string, durationMin: number) => void;
  unshelve: (id: string) => void;
  suppress: (id: string, reason: string) => void;
  unsuppress: (id: string) => void;
  removeAlert: (id: string) => void;
  setAlarmsPerTenMin: (n: number) => void;
}

export const useAlertStore = create<AlertState>()((set) => ({
  alerts: [],
  alarmsPerTenMin: 0,

  addAlert: (alert) => set((s) => ({ alerts: [alert, ...s.alerts] })),

  acknowledge: (id) =>
    set((s) => ({
      alerts: s.alerts.map((a) => {
        if (a.id !== id) return a;
        const now = new Date().toISOString();
        if (a.state === 'UNACK_ACTIVE') {
          return { ...a, state: 'ACK_ACTIVE' as AlarmState, acknowledgedAt: now };
        }
        if (a.state === 'RTN_UNACK') {
          return { ...a, state: 'NORMAL' as AlarmState, acknowledgedAt: now };
        }
        return a;
      }),
    })),

  clear: (id) =>
    set((s) => ({
      alerts: s.alerts.map((a) => (a.id === id ? { ...a, state: 'NORMAL' as AlarmState } : a)),
    })),

  shelve: (id, reason, durationMin) =>
    set((s) => ({
      alerts: s.alerts.map((a) => {
        if (a.id !== id) return a;
        const expiresAt = new Date(Date.now() + durationMin * 60_000).toISOString();
        return {
          ...a,
          state: 'SHELVED' as AlarmState,
          shelveReason: reason,
          shelveExpiresAt: expiresAt,
        };
      }),
    })),

  unshelve: (id) =>
    set((s) => ({
      alerts: s.alerts.map((a) =>
        a.id === id && a.state === 'SHELVED'
          ? {
              ...a,
              state: 'UNACK_ACTIVE' as AlarmState,
              shelveReason: undefined,
              shelveExpiresAt: undefined,
            }
          : a,
      ),
    })),

  suppress: (id, reason) =>
    set((s) => ({
      alerts: s.alerts.map((a) =>
        a.id === id ? { ...a, state: 'SUPPRESSED' as AlarmState, suppressionReason: reason } : a,
      ),
    })),

  unsuppress: (id) =>
    set((s) => ({
      alerts: s.alerts.map((a) =>
        a.id === id && a.state === 'SUPPRESSED'
          ? { ...a, state: 'UNACK_ACTIVE' as AlarmState, suppressionReason: undefined }
          : a,
      ),
    })),

  removeAlert: (id) => set((s) => ({ alerts: s.alerts.filter((a) => a.id !== id) })),

  setAlarmsPerTenMin: (n) => set({ alarmsPerTenMin: n }),
}));

// ── Selectors ──

export const useActiveAlerts = () =>
  useAlertStore((s) => s.alerts.filter((a) => a.state !== 'NORMAL'));

export const useStandingCount = () =>
  useAlertStore(
    (s) => s.alerts.filter((a) => a.state === 'UNACK_ACTIVE' || a.state === 'ACK_ACTIVE').length,
  );

export const useUnackCount = () =>
  useAlertStore(
    (s) => s.alerts.filter((a) => a.state === 'UNACK_ACTIVE' || a.state === 'RTN_UNACK').length,
  );

export const usePriorityCount = (priority: AlertPriority) =>
  useAlertStore(
    (s) => s.alerts.filter((a) => a.priority === priority && a.state !== 'NORMAL').length,
  );
