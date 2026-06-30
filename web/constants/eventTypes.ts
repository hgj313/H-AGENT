/**
 * 事件类型常量 - 与后端 StreamEventType 一一对应
 */
export const STREAM_EVENT = {
  MESSAGE: "message",
  TOOL_CALL: "tool_call",
  TOOL_RESULT: "tool_result",
  NODE_UPDATE: "node_update",
  THINKING: "thinking",
  ERROR: "error",
  DONE: "done",
} as const;

export type StreamEventKey = keyof typeof STREAM_EVENT;
