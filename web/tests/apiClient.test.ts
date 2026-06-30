/**
 * apiClient 单测 - 验证 URL 构造、错误归一化、超时、headers
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiRequest, ApiError } from "@/api/apiClient";

describe("apiRequest", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("GET 请求会拼接 query 字符串并解析 JSON", async () => {
    const mockJson = { ok: true, items: [1, 2, 3] };
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify(mockJson), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    const res = await apiRequest<typeof mockJson>("/api/v1/x", {
      query: { a: 1, b: "hello", c: undefined, d: null },
    });
    expect(res).toEqual(mockJson);
    const calledUrl = fetchMock.mock.calls[0]?.[0] as string;
    expect(calledUrl).toContain("a=1");
    expect(calledUrl).toContain("b=hello");
    expect(calledUrl).not.toContain("c=");
    expect(calledUrl).not.toContain("d=");
  });

  it("POST 会自动设置 Content-Type 并 JSON 序列化 body", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response('{"ok":true}', { status: 200 }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;
    await apiRequest("/api/v1/x", {
      method: "POST",
      body: { message: "hi" },
    });
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe(
      "application/json",
    );
    expect(init.body).toBe(JSON.stringify({ message: "hi" }));
  });

  it("非 2xx 抛 ApiError，message 优先用后端 detail", async () => {
    global.fetch = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "bad request" }), {
        status: 400,
      }),
    ) as unknown as typeof fetch;
    await expect(apiRequest("/api/v1/x")).rejects.toBeInstanceOf(ApiError);
    try {
      await apiRequest("/api/v1/x");
    } catch (e) {
      const err = e as ApiError;
      expect(err.status).toBe(400);
      expect(err.message).toBe("bad request");
    }
  });

  it("超时抛 ApiError status=0", async () => {
    global.fetch = vi.fn().mockImplementationOnce(
      (_url: RequestInfo | URL, init?: RequestInit) =>
        new Promise((_, reject) => {
          const signal = init?.signal as AbortSignal | undefined;
          signal?.addEventListener("abort", () => {
            const e = new Error("aborted");
            e.name = "AbortError";
            reject(e);
          });
        }),
    ) as unknown as typeof fetch;
    await expect(
      apiRequest("/api/v1/x", { timeoutMs: 50 }),
    ).rejects.toMatchObject({ status: 0 });
  });

  it("外部 signal 触发 abort 时同样取消", async () => {
    let aborted = false;
    global.fetch = vi.fn().mockImplementationOnce(
      (_url: RequestInfo | URL, init?: RequestInit) =>
        new Promise((_, reject) => {
          const signal = init?.signal as AbortSignal | undefined;
          signal?.addEventListener("abort", () => {
            aborted = true;
            const e = new Error("aborted");
            e.name = "AbortError";
            reject(e);
          });
        }),
    ) as unknown as typeof fetch;
    const ac = new AbortController();
    setTimeout(() => ac.abort(), 10);
    await expect(
      apiRequest("/api/v1/x", { signal: ac.signal }),
    ).rejects.toMatchObject({ status: 0 });
    expect(aborted).toBe(true);
  });
});
