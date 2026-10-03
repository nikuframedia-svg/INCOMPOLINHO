import assert from "node:assert/strict";
import test from "node:test";

import { ApiError, get, post, put } from "../src/api/client.ts";

test("preserva o gate report dos erros estruturados da API", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(
    JSON.stringify({
      detail: {
        message: "O candidato exige aprovação explícita.",
        gate_report: {
          requires_approval: true,
          approval_reasons: ["delivery_risk"],
        },
      },
    }),
    {
      status: 409,
      headers: { "content-type": "application/json" },
    },
  );

  try {
    await assert.rejects(
      get("/api/test"),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.status, 409);
        assert.equal(error.message, "O candidato exige aprovação explícita.");
        assert.deepEqual(error.detail, {
          message: "O candidato exige aprovação explícita.",
          gate_report: {
            requires_approval: true,
            approval_reasons: ["delivery_risk"],
          },
        });
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("modo consulta bloqueia operações mutáveis e permite previews", async () => {
  const originalWindow = (globalThis as typeof globalThis & { window?: unknown }).window;
  const originalFetch = globalThis.fetch;
  const store = new Map<string, string>([["pp1AccessMode", "view"]]);
  (globalThis as typeof globalThis & { window?: unknown }).window = {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => { store.set(key, value); },
    },
  };
  globalThis.fetch = async () => new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

  try {
    await assert.rejects(
      put("/api/data/config", {}),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.status, 403);
        assert.match(error.message, /Modo Consulta/);
        return true;
      },
    );
    await assert.doesNotReject(post("/api/data/subcontracts/preview", {}));
  } finally {
    if (originalWindow === undefined) {
      delete (globalThis as typeof globalThis & { window?: unknown }).window;
    } else {
      (globalThis as typeof globalThis & { window?: unknown }).window = originalWindow;
    }
    globalThis.fetch = originalFetch;
  }
});

for (const status of [502, 503, 504, 524]) {
  test(`não apresenta HTML de um erro ${status}`, async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => new Response("<!DOCTYPE html><html>Cloudflare private error</html>", {
      status, headers: { "content-type": "text/html" },
    });
    try {
      await assert.rejects(get("/api/test"), (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.status, status);
        assert.doesNotMatch(error.message, /html|Cloudflare|private/i);
        assert.ok(error.message.length < 200);
        return true;
      });
    } finally { globalThis.fetch = originalFetch; }
  });
}

test("trata erros vazios, HTML sem cabeçalho e JSON inesperado", async () => {
  const originalFetch = globalThis.fetch;
  try {
    for (const body of ["", "  <html>erro</html>", "null", "[]", JSON.stringify({ unexpected: true })]) {
      globalThis.fetch = async () => new Response(body, { status: 524 });
      await assert.rejects(get("/api/test"), (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.match(error.message, /demorou a responder/);
        assert.deepEqual(error.detail, { code: "timeout" });
        return true;
      });
    }
  } finally { globalThis.fetch = originalFetch; }
});

test("o limite de espera inclui a leitura do corpo da resposta", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (_url, init) => new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('{"job":'));
      init?.signal?.addEventListener("abort", () => controller.error(new DOMException("Aborted", "AbortError")));
    },
  }));
  try {
    await assert.rejects(get("/api/test", { timeoutMs: 5 }), (error: unknown) => {
      assert.ok(error instanceof ApiError);
      assert.deepEqual(error.detail, { code: "timeout" });
      return true;
    });
  } finally { globalThis.fetch = originalFetch; }
});

test("distingue falha de rede de timeout", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
    await assert.rejects(get("/api/test"), (error: unknown) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 0);
      assert.deepEqual(error.detail, { code: "network" });
      return true;
    });
    globalThis.fetch = (_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    });
    await assert.rejects(get("/api/test", { timeoutMs: 5 }), (error: unknown) => {
      assert.ok(error instanceof ApiError);
      assert.deepEqual(error.detail, { code: "timeout" });
      return true;
    });
  } finally { globalThis.fetch = originalFetch; }
});

test("trata HTML inesperado mesmo numa resposta 200", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response("<html>proxy</html>", { status: 200 });
  try {
    await assert.rejects(get("/api/test"), (error: unknown) => {
      assert.ok(error instanceof ApiError);
      assert.deepEqual(error.detail, { code: "invalid_response" });
      return true;
    });
  } finally { globalThis.fetch = originalFetch; }
});
