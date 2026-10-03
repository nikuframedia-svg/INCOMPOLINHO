import { afterEach, describe, expect, it } from "vitest";
import { approveLoadJob, AUTOMATIC_LOAD_APPROVAL, confirmPreparedISOP, prepareISOP, uploadISOP } from "../src/api/endpoints";
import { useAppStore } from "../src/stores/useAppStore";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

describe("upload endpoints", () => {
  it("envia o ISOP com cálculo e aceitação automática atribuída ao sistema", async () => {
    let capturedUrl = "";
    let captured: FormData | undefined;
    globalThis.fetch = (async (url, init) => {
      capturedUrl = String(url);
      captured = init?.body as FormData;
      return new Response(JSON.stringify({ job: { id: "auto-1", status: "preparing" } }), { status: 202 });
    }) as typeof fetch;
    await uploadISOP(new File(["x"], "isop.xlsx"), "auto-1", 17);
    const url = new URL(capturedUrl, "http://localhost");
    expect(url.pathname).toBe("/api/data/load");
    expect(url.searchParams.get("assume_machines_free")).toBe("true");
    expect(url.searchParams.get("approve_exceptions")).toBe("true");
    expect(url.searchParams.get("approval_author")).toBe("sistema");
    expect(url.searchParams.get("approval_reason")).toBe(AUTOMATIC_LOAD_APPROVAL.reason);
    expect(url.searchParams.get("expected_revision")).toBe("17");
    expect(captured?.get("request_id")).toBe("auto-1");
    expect(captured?.get("file")).toBeInstanceOf(File);
    expect(useAppStore.getState().blockingRequests).toBe(0);
  });
  it("envia o identificador escolhido antes do upload", async () => {
    let captured: FormData | undefined;
    globalThis.fetch = (async (_url, init) => {
      captured = init?.body as FormData;
      return new Response(JSON.stringify({ job: { id: "id-1", status: "preparing" } }), { status: 202 });
    }) as typeof fetch;
    await prepareISOP(new File(["x"], "isop.xlsx"), "id-1");
    expect(captured?.get("request_id")).toBe("id-1");
    expect(captured?.get("file")).toBeInstanceOf(File);
    expect(useAppStore.getState().blockingRequests).toBe(0);
  });

  it("usa a revisão congelada do preparado e uma rota separada para aprovação", async () => {
    const calls: { url: string; body: unknown }[] = [];
    globalThis.fetch = (async (url, init) => {
      calls.push({ url: String(url), body: JSON.parse(String(init?.body)) });
      return new Response(JSON.stringify({ job: { id: "id-1", status: "running" } }), { status: 202 });
    }) as typeof fetch;
    await confirmPreparedISOP("id-1", 7);
    await approveLoadJob("id-1", 7, { reason: "Risco aceite", author: "planeador" });
    expect(calls).toEqual([
      { url: "/api/data/load/confirm", body: { token: "id-1", expected_revision: 7, mode: "all_free" } },
      { url: "/api/data/load/jobs/id-1/approve", body: { expected_revision: 7, approval_reason: "Risco aceite", approval_author: "planeador" } },
    ]);
    expect(useAppStore.getState().blockingRequests).toBe(0);
  });
});
