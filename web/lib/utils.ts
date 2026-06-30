import clsx from "clsx";
import type { ClassValue } from "clsx";

/** className 合并：clsx 轻量封装 */
export function cn(...inputs: ClassValue[]): string {
  return clsx(...inputs);
}

/** 格式化毫秒为可读时长 */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = s / 60;
  return `${m.toFixed(1)}min`;
}

/** 格式化 ISO 时间戳为简短本地时间 */
export function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}

/** 安全 JSON 解析 */
export function safeJson<T>(raw: string, fallback: T): T {
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}
