"""手写版 ToolNode：注册 / 校验 / 调度（并行+串行）/ 回写。"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable, Sequence

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.tools import tool as to_decorator
from langgraph.prebuilt import InjectedState


def _normalize_tools(tools: Sequence[Any]) -> list[BaseTool]:
    """把 callable 包成 BaseTool；BaseTool 原样保留。"""
    out: list[BaseTool] = []
    for t in tools:
        if isinstance(t, BaseTool):
            out.append(t)
        elif callable(t):
            out.append(to_decorator(t))
        else:
            raise TypeError(f"tool 必须是 callable 或 BaseTool，收到 {type(t)}")
    return out


def _split_args(tool_obj: BaseTool, raw: dict) -> tuple[dict, dict]:
    """从原始 args 里把'普通参数'和'注入参数（InjectedState 等）'拆开。

    实现思路：看工具的 Python 函数签名，
    如果某个参数的类型注解包含 InjectedState / InjectedToolCallId / RunnableConfig，
    就把它从 raw 里抽出来，不让 Pydantic 校验它。
    """
    fn = tool_obj.func if hasattr(tool_obj, "func") else tool_obj.run
    sig = inspect.signature(fn)
    normal: dict = {}
    injected: dict = {}
    for name, value in raw.items():
        p = sig.parameters.get(name)
        if p is None:
            normal[name] = value
            continue
        ann = p.annotation
        ann_str = str(ann)
        if (
            "InjectedState" in ann_str
            or "InjectedToolCallId" in ann_str
            or "RunnableConfig" in ann_str
        ):
            injected[name] = value
        else:
            normal[name] = value
    return normal, injected


class MiniToolNode:
    """极简版 ToolNode：演示实现，不依赖 langgraph.prebuilt.ToolNode。"""

    def __init__(self, tools: Sequence[Any], handle_tool_errors: bool = False):
        self._tools = _normalize_tools(tools)
        self._by_name: dict[str, BaseTool] = {t.name: t for t in self._tools}
        self._handle_errors = handle_tool_errors

    # ---------- 注册相关 ----------
    @property
    def by_name(self) -> dict[str, BaseTool]:
        return self._by_name

    def add_tool(self, t: Any) -> None:
        bt = t if isinstance(t, BaseTool) else to_decorator(t)
        self._tools.append(bt)
        self._by_name[bt.name] = bt

    # ---------- 校验 ----------
    def _validate(self, tool_calls: list[dict]) -> None:
        for tc in tool_calls:
            if tc["name"] not in self._by_name:
                raise ValueError(
                    f"{tc['name']} is not a valid tool, "
                    f"try one of {list(self._by_name)}"
                )

    # ---------- 单个执行（带注入参数） ----------
    def _run_one(
        self, tool_obj: BaseTool, normal_args: dict, injected_args: dict, tool_call_id: str
    ) -> ToolMessage:
        try:
            # 注入参数按签名顺序展开
            fn = tool_obj.func if hasattr(tool_obj, "func") else tool_obj.run
            sig = inspect.signature(fn)
            kwargs: dict = {}
            for name, p in sig.parameters.items():
                if name in normal_args:
                    kwargs[name] = normal_args[name]
                elif name in injected_args:
                    kwargs[name] = injected_args[name]
                else:
                    default = p.default
                    if default is inspect._empty:
                        continue
                    kwargs[name] = default
            output = fn(**kwargs) if asyncio.iscoroutinefunction(fn) is False else None
            content = str(output) if output is not None else "ok"
        except Exception as e:
            if not self._handle_errors:
                raise
            content = f"tool error: {e!r}"
        return ToolMessage(content=content, tool_call_id=tool_call_id, name=tool_obj.name)

    # ---------- 并行执行 ----------
    async def _run_one_async(self, tool_obj, normal_args, injected_args, tool_call_id):
        return self._run_one(tool_obj, normal_args, injected_args, tool_call_id)

    async def _run_parallel_async(
        self, jobs: list[tuple[BaseTool, dict, dict, str]]
    ) -> list[ToolMessage]:
        # asyncio.gather 真的并发跑；所有 tool 共享同一份 state 的"读视图"，
        # 所以"写 state"那种工具在这里就是 race condition——这正是 ToolNode
        # 让你"先回 ToolMessage 再让 LLM 下一轮" 的原因。
        return await asyncio.gather(*[self._run_one_async(*j) for j in jobs])

    # ---------- 入口 ----------
    def __call__(self, state: dict) -> dict:
        last = state["messages"][-1]
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return {"messages": []}

        self._validate(last.tool_calls)

        jobs: list[tuple[BaseTool, dict, dict, str]] = []
        for tc in last.tool_calls:
            tool_obj = self._by_name[tc["name"]]
            normal, injected = _split_args(tool_obj, tc["args"])
            injected["tool_call_id"] = tc["id"]  # 注入 tool_call_id
            jobs.append((tool_obj, normal, injected, tc["id"]))

        # 同步入口也走并行（用 asyncio.run 起一个事件循环）
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 已经在事件循环里，切换到线程池跑
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as ex:
                    results = list(ex.map(lambda j: self._run_one(*j), jobs))
            else:
                results = loop.run_until_complete(self._run_parallel_async(jobs))
        except RuntimeError:
            results = asyncio.run(self._run_parallel_async(jobs))

        return {"messages": results}
