/**
 * API 客户端 - 单一 fetch 入口
 *
 * 职责：
 *  - baseURL 解析（直连 / Next 代理）
 *  - 默认 header、超时、AbortController
 *  - 错误归一化为 ApiError
 *  - JSON 序列化与解析
 *  - 不缓存（除非 opts.cache = true）
 *
 * 不做：
 *  - 不做 SSE（见 sseClient）
 *  - 不做业务错误码翻译（由各 service 处理）
 */

export class ApiError extends Error {
  public readonly status: number;
  public readonly body: unknown;

  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export interface ApiRequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE" | "PATCH";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  headers?: Record<string, string>;
  /** 超时毫秒，默认 30000 */
  timeoutMs?: number;
  /** AbortSignal 用于外部取消 */
  signal?: AbortSignal;
  /** 跳过默认 Content-Type（用于上传） */
  rawBody?: BodyInit;
}

const DEFAULT_BASE_URL =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_BASE_URL) ||
  "http://localhost:8000";

const DEFAULT_TIMEOUT_MS = 30_000;

/** 解析最终 baseURL：开发环境可走 Next 代理避免 CORS */
function resolveBaseUrl(): string {
  if (typeof window === "undefined") return DEFAULT_BASE_URL;
  // 客户端：使用 Next 代理（同源），避免 CORS
  return "/api/proxy";
}

function buildUrl(
  path: string,
  query?: ApiRequestOptions["query"],
): string {
  const base = resolveBaseUrl();
  const url = new URL(
    path.startsWith("http") ? path : `${base}${path.startsWith("/") ? path : "/" + path}`,
    typeof window === "undefined" ? base : window.location.origin,
  );
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null) continue;
      url.searchParams.set(k, String(v));
    }
  }
  return url.toString();
}

export async function apiRequest<T = unknown>(
  path: string,
  opts: ApiRequestOptions = {},
): Promise<T> {
  const {
    method = "GET",
    body,
    query,
    headers = {},
    timeoutMs = DEFAULT_TIMEOUT_MS,
    signal,
    rawBody,
  } = opts;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  // 外部 signal 取消时同时取消内部
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener("abort", () => controller.abort());
  }

  try {
    const res = await fetch(buildUrl(path, query), {
      method,
      headers: {
        Accept: "application/json",
        ...(rawBody ? {} : body ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      body: rawBody ?? (body !== undefined ? JSON.stringify(body) : undefined),
      signal: controller.signal,
      credentials: "include",
    });

    const text = await res.text();
    const parsed: unknown = text ? safeParseJson(text) : null;

    if (!res.ok) {
      const msg =
        (parsed && typeof parsed === "object" && "detail" in parsed
          ? String((parsed as Record<string, unknown>).detail)
          : null) || `HTTP ${res.status}`;
      throw new ApiError(res.status, msg, parsed);
    }
    return parsed as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if ((err as { name?: string }).name === "AbortError") {
      throw new ApiError(0, "请求超时或被取消", null);
    }
    throw new ApiError(0, `网络错误: ${(err as Error).message}`, null);
  } finally {
    clearTimeout(timer);
  }
}

function safeParseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
