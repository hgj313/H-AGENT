/**
 * SSE 客户端 - 支持 POST + SSE（浏览器 EventSource 只支持 GET）
 *
 * 用 fetch + ReadableStream 读 chunk，自行按 SSE 规范解析
 * （event/data 字段，\n\n 分隔）。
 *
 * 事件流形态：
 *   event: thinking
 *   data: {"stage":"...","sequence":1}
 *   <blank>
 *
 * 暴露的 streamPostSSE 为 async iterable，便于在 hook 中：
 *   for await (const evt of streamPostSSE(...)) { ... }
 */

import { ApiError } from "./apiClient";
import type { StreamEvent, StreamEventType } from "@/types/chat";

const DEFAULT_TIMEOUT_MS = 5 * 60_000; // 5 分钟

export interface SseRequestOptions {
  body: unknown;
  headers?: Record<string, string>;
  timeoutMs?: number;
  signal?: AbortSignal;
}

export interface RawSseEvent {
  event?: string;
  data: string;
  id?: string;
}

function resolveBaseUrl(): string {
  if (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_BASE_URL) {
    return process.env.NEXT_PUBLIC_API_BASE_URL;
  }
  if (typeof window === "undefined") return "http://localhost:8000";
  return "/api/proxy";
}

function buildUrl(path: string): string {
  const base = resolveBaseUrl();
  return path.startsWith("http")
    ? path
    : `${base}${path.startsWith("/") ? path : "/" + path}`;
}

/** 解析一段 SSE 文本块为一个或多个事件 */
function parseSseBlocks(buffer: string): {
  events: RawSseEvent[];
  rest: string;
} {
  const events: RawSseEvent[] = [];
  // 事件以 \n\n 或 \r\n\r\n 结束
  const parts = buffer.split(/\r?\n\r?\n/);
  const rest = parts.pop() ?? "";
  for (const block of parts) {
    if (!block.trim()) continue;
    const evt: RawSseEvent = { data: "" };
    const lines = block.split(/\r?\n/);
    const dataLines: string[] = [];
    for (const line of lines) {
      if (line.startsWith(":")) continue; // 注释
      const colonIdx = line.indexOf(":");
      if (colonIdx < 0) continue;
      const field = line.slice(0, colonIdx).trim();
      let value = line.slice(colonIdx + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      switch (field) {
        case "event":
          evt.event = value;
          break;
        case "data":
          dataLines.push(value);
          break;
        case "id":
          evt.id = value;
          break;
        default:
          break;
      }
    }
    evt.data = dataLines.join("\n");
    events.push(evt);
  }
  return { events, rest };
}

/** 安全 JSON 解析（解析失败保留原始字符串） */
function safeParse<T>(raw: string): T | string {
  try {
    return JSON.parse(raw) as T;
  } catch {
    return raw;
  }
}

/**
 * 流式 POST 端点，按 SSE 协议解析，产出 typed StreamEvent。
 * 使用示例：
 *   for await (const evt of streamPostSSE<MyData>('/x/y', {body:{...}})) { ... }
 */
export async function* streamPostSSE<T = Record<string, unknown>>(
  path: string,
  opts: SseRequestOptions,
): AsyncGenerator<StreamEvent<T>, void, void> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), opts.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  if (opts.signal) {
    if (opts.signal.aborted) controller.abort();
    else opts.signal.addEventListener("abort", () => controller.abort());
  }

  try {
    const res = await fetch(buildUrl(path), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...(opts.headers ?? {}),
      },
      body: JSON.stringify(opts.body),
      signal: controller.signal,
      credentials: "include",
    });

    if (!res.ok || !res.body) {
      const text = await res.text().catch(() => "");
      throw new ApiError(res.status, `SSE 握手失败: ${text || res.statusText}`, text);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const { events, rest } = parseSseBlocks(buffer);
      buffer = rest;
      for (const raw of events) {
        const eventName = (raw.event ?? "message") as StreamEventType;
        const parsed = safeParse<Record<string, unknown>>(raw.data);
        if (typeof parsed === "string") {
          // 非 JSON 文本：原样包一层
          yield {
            event: eventName,
            data: { _raw: parsed } as unknown as T,
            agent_id: "",
            timestamp: new Date().toISOString(),
            sequence: 0,
          };
          continue;
        }
        // 后端 _to_sse 把整个 StreamEvent（含 event/data/sequence/timestamp/agent_id）
        // 序列化到 SSE 的 data: 字段里，所以这里需要：
        //   1) 提取 metadata 到顶层 typed 字段
        //   2) **再 unwrap 一层 parsed.data**（业务真正的事件负载）
        // 如果后端改成只把 data 本身序列化进 SSE data: 字段（即 parsed === 业务数据），
        // 这里的 unwrap 退化为 no-op：rest 已经是真正的业务数据。
        const {
          agent_id: agentId = "",
          timestamp: ts = new Date().toISOString(),
          sequence: seq = 0,
          data: innerData,
          event: _evtDup, // 与 SSE event 字段重复，丢掉
          ...outerRest
        } = parsed as Record<string, unknown>;

        // 业务数据 = innerData ?? outerRest（兼容两种后端序列化风格）
        const businessData =
          innerData !== undefined && innerData !== null
            ? (innerData as Record<string, unknown>)
            : outerRest;

        // 临时调试：定位"前端拿不到事件数据"问题
        if (typeof window !== "undefined" && (window as unknown as { __drDebug?: boolean }).__drDebug) {
          // eslint-disable-next-line no-console
          console.log("[SSE]", eventName, "data=", JSON.stringify(businessData));
        }

        yield {
          event: eventName,
          data: businessData as T,
          agent_id: String(agentId),
          timestamp: String(ts),
          sequence: Number(seq),
        };
      }
    }
  } finally {
    clearTimeout(timer);
  }
}

/** 暴露给测试：直接解析一段 SSE 文本 */
export const __testing = { parseSseBlocks, safeParse };
