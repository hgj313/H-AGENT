/**
 * sseClient 单测 - 验证 SSE 块解析、数据提取、stream 行为
 */
import { describe, it, expect } from "vitest";
import { __testing } from "@/api/sseClient";

const { parseSseBlocks, safeParse } = __testing;

describe("parseSseBlocks", () => {
  it("解析单条标准事件", () => {
    const input = 'event: thinking\ndata: {"stage":"llm"}\n\n';
    const { events, rest } = parseSseBlocks(input);
    expect(events).toEqual([
      { event: "thinking", data: '{"stage":"llm"}', id: undefined },
    ]);
    expect(rest).toBe("");
  });

  it("解析多条事件 + 残留缓冲", () => {
    const input =
      'event: a\ndata: 1\n\nevent: b\ndata: 2\n\nevent: c\ndata: 3';
    const { events, rest } = parseSseBlocks(input);
    expect(events).toHaveLength(2);
    expect(events[0]).toEqual({ event: "a", data: "1", id: undefined });
    expect(events[1]).toEqual({ event: "b", data: "2", id: undefined });
    expect(rest).toBe("event: c\ndata: 3");
  });

  it("data 多行用 \\n 拼接", () => {
    const input = 'event: x\ndata: line1\ndata: line2\n\n';
    const { events } = parseSseBlocks(input);
    expect(events[0]?.data).toBe("line1\nline2");
  });

  it("注释行 (以 : 开头) 被忽略", () => {
    const input = ": comment\nevent: ok\ndata: yep\n\n";
    const { events } = parseSseBlocks(input);
    expect(events).toHaveLength(1);
    expect(events[0]?.event).toBe("ok");
  });

  it("支持 CRLF 行尾", () => {
    const input = "event: a\r\ndata: 1\r\n\r\n";
    const { events } = parseSseBlocks(input);
    expect(events[0]).toEqual({ event: "a", data: "1", id: undefined });
  });

  it("空块被忽略", () => {
    const input = "\n\n\nevent: x\ndata: 1\n\n\n\n";
    const { events } = parseSseBlocks(input);
    expect(events).toHaveLength(1);
  });
});

describe("safeParse", () => {
  it("合法 JSON 解析为对象", () => {
    expect(safeParse<{ a: number }>('{"a":1}')).toEqual({ a: 1 });
  });
  it("非法 JSON 返回原字符串", () => {
    expect(safeParse("not json")).toBe("not json");
  });
});
