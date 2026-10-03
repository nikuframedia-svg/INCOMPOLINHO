/** Base fetch wrapper for backend API. */

import { isReadOnlyMode } from "../lib/accessMode.ts";
import { useAppStore } from "../stores/useAppStore.ts";
import type { PlanIdentity } from "../lib/planRevision";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

interface RequestOptions {
  timeoutMs?: number;
  blocking?: boolean;
  planIdentity?: PlanIdentity | null;
}

const READ_TIMEOUT_MS = 15_000;
const ACTION_TIMEOUT_MS = 120_000;
const READ_RETRY_DELAYS_MS = [200, 400];

function waitForRetry(delay: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, delay);
    function abort() {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      reject(new DOMException("Aborted", "AbortError"));
    }
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
  });
}

function statusMessage(status: number): string {
  if ([408, 504, 524].includes(status)) {
    return "O servidor demorou a responder. O processamento pode continuar; verifica o estado antes de repetir.";
  }
  if ([502, 503].includes(status)) return "O servidor está temporariamente indisponível. Tenta novamente dentro de instantes.";
  return `O servidor devolveu um erro (HTTP ${status}).`;
}

async function fetchResponse<T>(
  url: string, init: RequestInit | undefined, options: RequestOptions | undefined,
  read: (response: Response) => Promise<T>,
): Promise<T> {
  const controller = options?.timeoutMs ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), options!.timeoutMs) : null;
  const retries = (init?.method ?? "GET") === "GET" ? READ_RETRY_DELAYS_MS : [];
  try {
    // Retries share the original deadline and the captured request identity.
    for (let attempt = 0; ; attempt++) {
      try {
        const response = await fetch(url, { ...init, ...(controller ? { signal: controller.signal } : {}) });
        return await read(response);
      } catch (failure) {
        const transient = failure instanceof TypeError
          || (failure instanceof ApiError && [502, 503, 504, 524].includes(failure.status));
        if (controller?.signal.aborted || !transient || attempt >= retries.length) throw failure;
        await waitForRetry(retries[attempt], controller?.signal);
      }
    }
  } catch (failure) {
    if (controller?.signal.aborted) {
      throw new ApiError(0, statusMessage(524), { code: "timeout" });
    }
    if (failure instanceof TypeError) {
      throw new ApiError(0, "Não foi possível ligar ao servidor. Tenta novamente dentro de instantes.", { code: "network" });
    }
    throw failure;
  } finally {
    if (timer !== null) clearTimeout(timer);
  }
}

function isReadOnlyAllowedPost(url: string): boolean {
  const path = new URL(url, "http://localhost").pathname;
  return (
    ["/api/data/simulate", "/api/data/ctp", "/api/data/plan/move-preview",
      "/api/data/plan/move-preview-jobs", "/api/data/subcontracts/preview"].includes(path)
    || /^\/api\/data\/plan\/move-preview-jobs\/[^/]+\/cancel$/.test(path)
    || /^\/api\/data\/skus\/[^/]+\/planning\/preview$/.test(path)
  );
}

function assertCanMutate(method: string, url: string) {
  if (!isReadOnlyMode()) return;
  if (method === "POST" && isReadOnlyAllowedPost(url)) return;
  throw new ApiError(
    403,
    "Modo Consulta ativo. Muda para Editar para guardar, aplicar ou recalcular.",
  );
}

function loadingMessage(method: string, url: string): string {
  if (url.includes("/recalculate")) return "A recalcular plano…";
  if (url.includes("/load/prepare")) return "A validar ficheiro…";
  if (url.includes("/load/confirm") || url.includes("/api/data/load")) return "A carregar ficheiro…";
  if (url.includes("/simulate-apply")) return "A aplicar cenário…";
  if (url.endsWith("/simulate")) return "A simular cenário…";
  if (url.includes("/simulate-revert")) return "A reverter cenário…";
  if (url.includes("/plan/move-preview")) return "A verificar movimento…";
  if (url.includes("/plan/move-apply")) return "A aplicar movimento…";
  if (url.includes("/replan-jobs") && url.endsWith("/apply")) return "A aplicar replaneamento…";
  if (url.includes("/replan-jobs")) return "A calcular replaneamento…";
  if (url.includes("/robustness-runs")) return "A calcular robustez…";
  if (url.includes("/plans/") && url.includes("/restore")) return "A repor plano…";
  if (url.includes("/plans")) return method === "DELETE" ? "A apagar plano…" : "A guardar plano…";
  if (url.includes("/scenarios/") && url.includes("/apply")) return "A aplicar cenário guardado…";
  if (url.includes("/scenarios")) return method === "DELETE" ? "A apagar cenário…" : "A guardar cenário…";
  if (url.includes("/ctp-apply")) return "A aplicar promessa…";
  if (url.includes("/ctp")) return "A verificar promessa…";
  if (url.includes("/copilot/chat")) return "A consultar o Copilot…";
  if (url.includes("/config") || url.includes("/machines") || url.includes("/tools")
    || url.includes("/operators") || url.includes("/holidays") || url.includes("/workdays-extra")
    || url.includes("/unavailability") || url.includes("/setup-overrides")
    || url.includes("/twins") || url.includes("/subcontracts") || url.includes("/planning")
    || url.includes("/presets")) {
    return "A aplicar alterações…";
  }
  return "A carregar…";
}

async function withBlockingOverlay<T>(
  message: string,
  task: () => Promise<T>,
): Promise<T> {
  const { beginBlockingRequest, endBlockingRequest } = useAppStore.getState();
  beginBlockingRequest(message);
  try {
    return await task();
  } finally {
    endBlockingRequest();
  }
}

async function errorInfo(res: Response): Promise<{ message: string; detail?: unknown }> {
  const raw = await res.text().catch(() => "");
  const fallback = { message: statusMessage(res.status), detail: {
    code: [408, 504, 524].includes(res.status) ? "timeout" : "http_error",
  } };
  if (!raw.trim()) return fallback;
  if (res.headers.get("content-type")?.includes("text/html") || /^\s*</.test(raw)) return fallback;
  try {
    const parsed = JSON.parse(raw) as {
      message?: unknown;
      detail?: unknown;
    };
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return fallback;
    if (typeof parsed.message === "string") {
      return { message: parsed.message, detail: parsed.detail };
    }
    if (typeof parsed.detail === "string") {
      return { message: parsed.detail, detail: parsed.detail };
    }
    if (
      parsed.detail
      && typeof parsed.detail === "object"
      && "message" in parsed.detail
      && typeof parsed.detail.message === "string"
    ) {
      return { message: parsed.detail.message, detail: parsed.detail };
    }
    return { ...fallback, detail: parsed.detail ?? fallback.detail };
  } catch {
    // Only bounded plain text is suitable for a message, never a proxy HTML page.
  }
  if ([408, 502, 503, 504, 524].includes(res.status)) return fallback;
  return { message: raw.slice(0, 500) };
}

async function readResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const error = await errorInfo(res);
    throw new ApiError(res.status, error.message, error.detail);
  }
  try {
    return await res.json();
  } catch (failure) {
    if (!(failure instanceof SyntaxError)) throw failure;
    throw new ApiError(res.status, "O servidor devolveu uma resposta inesperada. Verifica o estado da operação.", { code: "invalid_response" });
  }
}

async function request<T>(url: string, init?: RequestInit, options?: RequestOptions): Promise<T> {
  const identity = options?.planIdentity;
  return fetchResponse(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Access-Mode": isReadOnlyMode() ? "view" : "edit",
      ...(identity ? { "X-Dataset-Id": identity.datasetId, "X-Plan-Revision": String(identity.planRevision) } : {}),
      ...init?.headers,
    },
  }, { timeoutMs: init?.method ? ACTION_TIMEOUT_MS : READ_TIMEOUT_MS, ...options }, async (response) => {
    if (response.ok && identity && (response.headers.get("X-Dataset-Id") !== identity.datasetId
      || response.headers.get("X-Plan-Revision") !== String(identity.planRevision))) {
      throw new ApiError(409, "O plano mudou. Atualiza os dados do ecrã.", { code: "stale_revision" });
    }
    return readResponse<T>(response);
  });
}

export async function get<T>(url: string, options?: RequestOptions): Promise<T> {
  return request<T>(url, undefined, options);
}

export async function post<T>(url: string, body: unknown, options?: RequestOptions): Promise<T> {
  assertCanMutate("POST", url);
  const task = () => request<T>(url, {
      method: "POST",
      body: JSON.stringify(body),
    }, options);
  return options?.blocking === false ? task() : withBlockingOverlay(loadingMessage("POST", url), task);
}

export async function put<T>(url: string, body: unknown): Promise<T> {
  assertCanMutate("PUT", url);
  return withBlockingOverlay(loadingMessage("PUT", url), () =>
    request<T>(url, {
      method: "PUT",
      body: JSON.stringify(body),
    }));
}

export async function del<T>(url: string): Promise<T> {
  assertCanMutate("DELETE", url);
  return withBlockingOverlay(loadingMessage("DELETE", url), () =>
    request<T>(url, { method: "DELETE" }));
}

export async function delWithBody<T>(url: string, body: unknown): Promise<T> {
  assertCanMutate("DELETE", url);
  return withBlockingOverlay(loadingMessage("DELETE", url), () =>
    request<T>(url, {
      method: "DELETE",
      body: JSON.stringify(body),
    }));
}

export async function upload<T>(url: string, file: File, params?: Record<string, string>, options?: RequestOptions): Promise<T> {
  assertCanMutate("POST", url);
  const task = async () => {
    const form = new FormData();
    form.append("file", file);
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        form.append(k, v);
      }
    }
    return fetchResponse(url, {
      method: "POST",
      body: form,
      headers: { "X-Access-Mode": isReadOnlyMode() ? "view" : "edit" },
    }, { timeoutMs: ACTION_TIMEOUT_MS, ...options }, readResponse<T>);
  };
  return options?.blocking === false ? task() : withBlockingOverlay(loadingMessage("POST", url), task);
}
