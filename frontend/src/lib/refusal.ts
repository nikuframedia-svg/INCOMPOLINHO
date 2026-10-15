/**
 * One refusal format (decisão de 15/10/2026): a refused change shows its
 * message and the concrete causes the backend found (`causes`, plain
 * Portuguese), never a bare "Plano inválido: N conflitos." or a browser alert.
 */

import { ApiError } from "../api/client";

/** An error that already carries its causes (e.g. a failed background job). */
export class RefusalError extends Error {
  causes: string[];
  constructor(message: string, causes: readonly string[] | null | undefined) {
    super(message);
    this.causes = [...(causes ?? [])];
  }
}

/** `causes` of a refusal payload (API detail or job), only plain strings. */
export function causesOf(value: unknown): string[] {
  if (!value || typeof value !== "object" || !("causes" in value)) return [];
  const causes = (value as { causes?: unknown }).causes;
  return Array.isArray(causes)
    ? causes.filter((item): item is string => typeof item === "string" && item.trim() !== "")
    : [];
}

/** Causes of any caught error; empty when the error has none. */
export function refusalCauses(error: unknown): string[] {
  if (error instanceof RefusalError) return error.causes;
  if (error instanceof ApiError) return causesOf(error.detail);
  return [];
}

/** Message and causes as one line, for screens with a single text message. */
export function refusalText(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return [message, ...refusalCauses(error)].join(" ");
}
