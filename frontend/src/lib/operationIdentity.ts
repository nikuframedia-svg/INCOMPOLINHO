const STORAGE_KEY = "incompolinho-pending-operations-v1";
const pending = new Map<string, string>();

function persist() {
  try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...pending])); } catch { /* In-memory retries remain idempotent. */ }
}

try {
  const stored: unknown = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "[]");
  if (Array.isArray(stored)) for (const pair of stored.slice(-100)) {
    if (Array.isArray(pair) && pair.length === 2 && pair.every((value) => typeof value === "string")) pending.set(pair[0], pair[1]);
  }
} catch { /* Session storage is optional. */ }

export function operationIdentity(url: string, body: Record<string, unknown>) {
  const ignored = new Set(["approve_exceptions", "approval_reason", "approval_author", "confirm_delivery_risk", "request_id"]);
  const canonical = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(canonical);
    if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)]));
    return value;
  };
  const key = JSON.stringify([url, canonical(Object.fromEntries(Object.entries(body).filter(([name]) => !ignored.has(name))))]);
  let id = typeof body.request_id === "string" ? body.request_id : pending.get(key);
  if (!id) {
    id = crypto.randomUUID();
    pending.set(key, id);
    while (pending.size > 100) pending.delete(pending.keys().next().value!);
    persist();
  }
  return { id, confirmed: () => { pending.delete(key); persist(); } };
}
