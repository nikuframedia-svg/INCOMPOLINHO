/**
 * Andon API client — registers machine downtime events.
 * Falls back to localStorage if backend unavailable.
 * Uses existing POST /v1/events with MACHINE_DOWN / MACHINE_UP types.
 */

import type { AndonCategory } from '@/stores/useAndonStore';
import { fetchWithTimeout } from '../../../lib/fetchWithTimeout';

const API_BASE = '/api/v1';
const LOCAL_KEY = 'pp1-andon-fallback';

interface EventPayload {
  event_id: string;
  event_type: string;
  resource_code: string;
  start_time: string;
  reason: string;
  event_metadata: Record<string, unknown>;
}

const CATEGORY_LABELS: Record<AndonCategory, string> = {
  avaria_mecanica: 'Avaria Mecanica/Electrica',
  setup_prolongado: 'Setup Prolongado',
  falta_material: 'Falta de Material',
  problema_qualidade: 'Problema de Qualidade',
  manutencao_preventiva: 'Manutencao Preventiva',
};

export async function postMachineDown(
  machineId: string,
  category: AndonCategory,
  estimatedMin: number | null,
): Promise<{ event_id: string }> {
  const eventId = crypto.randomUUID();
  const payload: EventPayload = {
    event_id: eventId,
    event_type: 'MACHINE_DOWN',
    resource_code: machineId,
    start_time: new Date().toISOString(),
    reason: CATEGORY_LABELS[category],
    event_metadata: { andon: true, category, estimatedMin },
  };

  try {
    const res = await fetchWithTimeout(
      `${API_BASE}/events`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
      5_000,
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch {
    const stored = JSON.parse(localStorage.getItem(LOCAL_KEY) ?? '[]') as EventPayload[];
    stored.push(payload);
    localStorage.setItem(LOCAL_KEY, JSON.stringify(stored.slice(-50)));
    return { event_id: eventId };
  }
}

export async function postMachineUp(
  machineId: string,
  downEventId: string,
): Promise<{ event_id: string }> {
  const eventId = crypto.randomUUID();
  const payload: EventPayload = {
    event_id: eventId,
    event_type: 'MACHINE_UP',
    resource_code: machineId,
    start_time: new Date().toISOString(),
    reason: 'Máquina recuperada',
    event_metadata: { andon: true, recoveryOf: downEventId },
  };

  try {
    const res = await fetchWithTimeout(
      `${API_BASE}/events`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
      5_000,
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch {
    const stored = JSON.parse(localStorage.getItem(LOCAL_KEY) ?? '[]') as EventPayload[];
    stored.push(payload);
    localStorage.setItem(LOCAL_KEY, JSON.stringify(stored.slice(-50)));
    return { event_id: eventId };
  }
}
