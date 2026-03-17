/**
 * settings-sync.ts — Sync settings between frontend (localStorage) and backend.
 *
 * - fetchSettingsFromBackend(): Load settings from backend, merge into Zustand store
 * - syncSettingsToBackend(): Push current settings to backend
 *
 * localStorage remains as cache/fallback when backend is down.
 */

import { config } from '../config';
import { useSettingsStore } from './useSettingsStore';

const SETTINGS_URL = `${config.apiBaseURL}/v1/settings`;

/**
 * Fetch settings from backend and merge into Zustand store.
 * Non-destructive: only updates fields present in backend response.
 */
export async function fetchSettingsFromBackend(): Promise<boolean> {
  try {
    const res = await fetch(SETTINGS_URL);
    if (!res.ok) return false;
    const data = await res.json();

    // Merge backend settings into store (preserves actions, updates data)
    const { actions: _, ...current } = useSettingsStore.getState();
    const merged = { ...current, ...data };
    useSettingsStore.setState(merged);
    return true;
  } catch {
    // Backend unavailable — localStorage fallback active
    return false;
  }
}

/**
 * Push current settings to backend (partial update).
 */
export async function syncSettingsToBackend(): Promise<boolean> {
  try {
    const { actions: _, ...data } = useSettingsStore.getState();
    const res = await fetch(SETTINGS_URL, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.ok;
  } catch {
    return false;
  }
}
