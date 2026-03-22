/**
 * api.test.ts — Tests for fetch wrappers in lib/api.ts.
 * Mocks fetchWithTimeout to verify URL, method, body, and error handling.
 */

import { describe, expect, it, vi } from 'vitest';

vi.mock('../../lib/fetchWithTimeout', () => ({
  fetchWithTimeout: vi.fn(),
}));

import type { NikufraDataPayload, ScheduleBlock, ScheduleSettings } from '@/lib/api';
import { scheduleCTPApi, scheduleFullApi, scheduleReplanApi, scheduleRunApi } from '@/lib/api';
import { fetchWithTimeout } from '@/lib/fetchWithTimeout';

const mockFetch = fetchWithTimeout as ReturnType<typeof vi.fn>;

function fakeResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response;
}

describe('scheduleFullApi', () => {
  it('calls correct URL with POST + JSON body and returns parsed response', async () => {
    const payload = { blocks: [], kpis: { total_blocks: 0 } };
    mockFetch.mockResolvedValueOnce(fakeResponse(payload));

    const req = {
      nikufra_data: { foo: 1 } as unknown as NikufraDataPayload,
      settings: { dispatchRule: 'EDD' } as ScheduleSettings,
    };
    const result = await scheduleFullApi(req);

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/v1/pipeline/schedule/full'),
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req),
      }),
      30_000,
    );
    expect(result).toEqual(payload);
  });

  it('throws on HTTP 500', async () => {
    mockFetch.mockResolvedValueOnce(fakeResponse('Internal Error', false, 500));

    await expect(
      scheduleFullApi({ nikufra_data: {} as NikufraDataPayload, settings: {} as ScheduleSettings }),
    ).rejects.toThrow(/Schedule full HTTP 500/);
  });
});

describe('scheduleRunApi', () => {
  it('calls correct URL and returns parsed response', async () => {
    const payload = { blocks: [], n_blocks: 0 };
    mockFetch.mockResolvedValueOnce(fakeResponse(payload));

    const result = await scheduleRunApi(
      { x: 1 } as unknown as NikufraDataPayload,
      { rule: 'EDD' } as ScheduleSettings,
    );

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/v1/pipeline/run'),
      expect.objectContaining({ method: 'POST' }),
      30_000,
    );
    expect(result).toEqual(payload);
  });
});

describe('scheduleReplanApi', () => {
  it('calls correct URL and returns parsed response', async () => {
    const payload = { blocks: [], solve_time_s: 1.2 };
    mockFetch.mockResolvedValueOnce(fakeResponse(payload));

    const req = {
      blocks: [{ id: 'b1' }] as unknown as ScheduleBlock[],
      disruption: { type: 'machine_down', resource_id: 'PRM019', start_day: 0, end_day: 2 },
    };
    const result = await scheduleReplanApi(req);

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/v1/schedule/replan'),
      expect.objectContaining({ method: 'POST' }),
      60_000,
    );
    expect(result).toEqual(payload);
  });
});

describe('scheduleCTPApi', () => {
  it('calls correct URL and returns parsed response', async () => {
    const payload = { scenarios: [], solve_time_s: 0.5 };
    mockFetch.mockResolvedValueOnce(fakeResponse(payload));

    const req = {
      nikufra_data: {} as NikufraDataPayload,
      sku: 'SKU001',
      quantity: 1000,
      target_day: 5,
    };
    const result = await scheduleCTPApi(req);

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/v1/schedule/ctp'),
      expect.objectContaining({ method: 'POST' }),
      30_000,
    );
    expect(result).toEqual(payload);
  });
});
