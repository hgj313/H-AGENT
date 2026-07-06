"""
通用 ReactAgent - 独立的 ReAct 模式对话 Agent。

与 DesignReviewAgent 完全解耦：自建轻量 ReAct StateGraph（llm ⇄ tools），
作为 Agent Hub / 通用对话页面的后端引擎。

设计原则：
1. 单一职责：只负责"对话 + 工具调用循环"，不做特定领域推理
2. 依赖倒置：依赖 BaseAgent 抽象与 langchain Tool 抽象
3. 流式优先：基于 BaseChatModel.stream() 产出 token 级事件
4. 独立可测：图与 Agent 分离，agent 只负责生命周期与事件封装

事件契约（沿用 api/v1/schemas/chat.py.StreamEventType）：
- THINKING  : LLM 进入推理节点
- MESSAGE   : LLM 文本流式输出（typing 效果）
- TOOL_CALL : LLM 决定调用工具
- TOOL_RESULT: 工具执行结果
- NODE_UPDATE: 图节点状态变化
- DONE      : 任务结束（带 taskId / durationMs）
- ERROR     : 异常
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from datetime import datetime
from typing import Annotated, Any, AsyncIterator, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from core.agents.base import (
    AgentConfig,
    AgentState,
    AgentStatus,
    AgentType,
    BaseAgent,
    StreamEvent,
)
from core.agents.exceptions import AgentError, AgentValidationError
from api.v1.schemas.chat import StreamEventType

logger = logging.getLogger(__name__)


# ── 1. 通用工具：当前时间（最小可用集） ──────────────────────────────
_TOOL_XML_RE = re.compile(r"<tool_call>.*?</tool_call>", re.DOTALL)


def _strip_tool_xml(text: str) -> str:
    """剥离 LLM 偶尔把工具调用当 XML 文本输出的残留（防御性）。"""
    if not text:
        return text
    return _TOOL_XML_RE.sub("", text).strip()


def get_current_time() -> str:
    """返回当前本地时间的 ISO 格式字符串。"""
    return datetime.now().isoformat(timespec="seconds")


# ── 2. ReAct 状态 ────────────────────────────────────────────────────
class ReactState(TypedDict, total=False):
    """ReAct 子图状态：仅持有消息历史 + 当前轮次工具调用计数。"""
    messages: Annotated[list[Any], lambda a, b: (a or []) + (b or [])]
    turn_count: int


# ── 3. 独立 ReAct 图（从零构建，不复用 design_review） ───────────────
def build_react_graph(llm_with_tools: Any, tool_map: dict[str, Any]):
    """构建一个最小可用的 ReAct 图：llm ⇄ tools。

    Args:
        llm_with_tools: 已通过 bind_tools() 绑定工具的 BaseChatModel。
        tool_map:      工具名 -> BaseTool 实例，用于执行。

    Returns:
        CompiledGraph，可直接 .stream() / .invoke()。
    """

    def llm_node(state: ReactState) -> dict:
        result = llm_with_tools.invoke(state["messages"])
        return {"messages": [result]}

    def tools_node(state: ReactState) -> dict:
        last_msg = state["messages"][-1]
        tool_calls = getattr(last_msg, "tool_calls", None) or []
        out: list[ToolMessage] = []
        for tc in tool_calls:
            tool = tool_map.get(tc["name"])
            if tool is None:
                out.append(
                    ToolMessage(
                        content=f"ERROR: tool '{tc['name']}' not registered",
                        tool_call_id=tc["id"],
                    )
                )
                continue
            try:
                content = tool.invoke(tc.get("args", {}))
                out.append(
                    ToolMessage(
                        content=str(content),
                        tool_call_id=tc["id"],
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("tool %s 执行失败", tc["name"])
                out.append(
                    ToolMessage(
                        content=f"ERROR: {exc!r}",
                        tool_call_id=tc["id"],
                    )
                )
        return {"messages": out}

    def should_continue(state: ReactState) -> str:
        last_msg = state["messages"][-1]
        if isinstance(last_msg, AIMessage) and getattr(last_msg, "tool_calls", None):
            return "tools"
        return END

    g = StateGraph(ReactState)
    g.add_node("llm", llm_node)
    g.add_node("tools", tools_node)
    g.add_edge(START, "llm")
    g.add_conditional_edges("llm", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "llm")
    return g.compile()


# ── 4. 默认工具集（通用对话最小集） ──────────────────────────────────
def default_react_tools() -> list[Any]:
    """MVP 默认工具集：get_current_time + read_file_tool + web_search。"""
    tools: list[Any] = []

    # 通用工具：当前时间
    from langchain_core.tools import tool

    @tool
    def get_current_time_tool() -> str:
        """获取当前本地时间（ISO8601，秒级精度）。"""
        return get_current_time()

    tools.append(get_current_time_tool)

    # 互联网搜索（Phase B 新增，依赖 duckduckgo-search 包）
    try:
        from core.agents.tools import web_search
        tools.append(web_search)
    except Exception as exc:  # noqa: BLE001
        logger.warning("web_search 加载失败，已跳过: %s", exc)

    # 复用 design_review 的 read_file 工具
    try:
        from agent.graphs.design_review.tools.read_file.read_file import read_file_tool
        tools.append(read_file_tool)
    except Exception as exc:  # noqa: BLE001
        logger.warning("read_file_tool 加载失败，已跳过: %s", exc)

    return tools


# ── 5. ReactAgent（BaseAgent 实现） ──────────────────────────────────
class ReactAgent(BaseAgent):
    """通用 React 风格对话 Agent。

    流式产出事件序列示例：
        THINKING   -> NODE_UPDATE(llm) -> MESSAGE(token 1) -> MESSAGE(token 2)
                  -> TOOL_CALL -> TOOL_RESULT -> MESSAGE(...) -> DONE
    """

    SYSTEM_PROMPT: str = (
        "你是一个通用对话助手，名字叫 MiniMax-M3 powered by MiniMax。\n"
        "回答简洁、准确，使用与用户相同的语言。\n"
        "当需要执行操作时（如读文件、获取时间），主动调用工具。\n"
        "不要捏造事实；如不知道，请明确说明。"
    )

    def __init__(self) -> None:
        # Phase C 字段（先于 super().__init__()，因为 base.on_init 会读 config）
        self._max_iterations: int = 5
        super().__init__()
        self._graph = None
        self._llm = None
        self._tools: list[Any] = []
        self._tool_map: dict[str, Any] = {}
        # Phase B 记忆/规划/执行（懒初始化）
        self._memory_manager: Any = None
        self._planner: Any = None
        self._executor: Any = None
        self._memory_ready: bool = False

    # ── Phase B 组件懒加载 ─────────────────────────────────────
    def _ensure_memory_components(self) -> bool:
        """懒初始化 MemoryManager / Planner / Executor。

        失败时返回 False，调用方回退到「无记忆/无规划」旧行为。
        """
        if self._memory_ready:
            return True
        if self._llm is None:
            return False
        try:
            from core.agents.memory_manager import MemoryManager
            from core.agents.planner import Planner
            from core.agents.executor import Executor
            from core.memory.long_term_store import LongTermStore
            from api.v1.services import MessageService, SessionService

            self._memory_manager = MemoryManager(
                llm=self._llm,
                long_term=LongTermStore(),
                message_service=MessageService(),
                session_service=SessionService(),
                k=10,
            )
            self._planner = Planner(self._llm)
            # 把 execute() 包成 runner：Callable[[dict], AsyncIterator[StreamEvent]]
            self._executor = Executor(self._react_runner)
            self._memory_ready = True
            logger.info("MemoryManager / Planner / Executor 初始化成功")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("记忆组件初始化失败，回退到无记忆模式: %s", exc)
            self._memory_ready = False
            return False

    async def _react_runner(
        self, input_data: dict[str, Any]
    ) -> AsyncIterator[StreamEvent]:
        """Executor 回调：把 execute() 的事件流重新暴露成 async iterator。

        execute() 本身是 async def（返回 AsyncIterator），
        但 Executor 期望的是 Callable[[dict], AsyncIterator]，
        所以这里加一层 async generator 桥接。
        """
        async for evt in self.execute(input_data):
            yield evt

    @staticmethod
    def _resolve_user_id(session_id: str) -> str:
        """从 session_id 解析 user_id；失败返回 default_user。"""
        if not session_id:
            return "default_user"
        try:
            from api.v1.services import SessionService

            sess = SessionService().get_session(session_id)
            if sess and isinstance(sess, dict):
                uid = sess.get("user_id")
                if uid:
                    return str(uid)
        except Exception:  # noqa: BLE001
            pass
        return "default_user"

    @property
    def config(self) -> AgentConfig:
        return AgentConfig(
            agent_id="react",
            name="通用对话助手",
            description="基于 ReAct 模式的通用对话 Agent，支持工具调用与流式响应",
            agent_type=AgentType.CUSTOM,
            version="1.1.0",
            capabilities=(
                "general_chat",
                "tool_calling",
                "streaming_response",
                "read_file",
                "current_time",
                "web_search",
                "recursive_tool_chain",
            ),
            max_concurrent=4,
            timeout=120.0,
            metadata={
                "model": "MiniMax-M2.7",
                "supported_languages": ["zh-CN", "en"],
                "max_iterations": self._max_iterations,
            },
        )

    # ── 生命周期 ────────────────────────────────────────────────
    def _ensure_graph(self) -> None:
        if self._graph is not None:
            return
        try:
            from llm_model.reasoning_model.minimax import MinimaxReasoningModelProvider
            provider = MinimaxReasoningModelProvider()
            self._llm = provider.get_model()
            self._tools = default_react_tools()
            self._tool_map = {t.name: t for t in self._tools}
            self._graph = build_react_graph(
                llm_with_tools=self._llm.bind_tools(self._tools),
                tool_map=self._tool_map,
            )
            logger.info("ReactGraph 初始化成功（tools=%d）", len(self._tools))
        except Exception as exc:  # noqa: BLE001
            logger.exception("ReactGraph 初始化失败")
            raise AgentError(
                f"ReactGraph 初始化失败: {exc}", agent_id=self.agent_id
            ) from exc

    # ── 输入校验 ────────────────────────────────────────────────
    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str | None]:
        message = (input_data.get("message") or "").strip()
        if not message:
            return False, "消息内容不能为空"
        if len(message) > 8000:
            return False, "单条消息长度不得超过 8000 字符"
        return True, None

    # ── 执行入口 ────────────────────────────────────────────────
    async def execute(
        self,
        input_data: dict[str, Any],
        task_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        task_id = task_id or f"react-{uuid.uuid4().hex[:8]}"
        self._start_task(task_id)
        start_ts = time.perf_counter()
        seq = 0

        def next_seq() -> int:
            nonlocal seq
            seq += 1
            return seq

        try:
            self._ensure_graph()

            ok, err = self.validate_input(input_data)
            if not ok:
                raise AgentValidationError(err or "输入校验失败", agent_id=self.agent_id)

            message = input_data["message"].strip()
            history: list[Any] = input_data.get("history") or []
            session_id: str = input_data.get("session_id") or ""

            # 0) 尝试初始化记忆/规划/执行组件（懒加载）
            memory_ok = self._ensure_memory_components()
            user_id = self._resolve_user_id(session_id) if memory_ok else "default_user"

            # 1) 思考中
            yield self._evt(
                StreamEventType.THINKING, next_seq(),
                {"stage": "starting", "content": "正在进入推理..."},
            )

            # 2) 进入 LLM 节点
            yield self._evt(
                StreamEventType.NODE_UPDATE, next_seq(),
                {"node": "llm", "status": "running", "message": "LLM 推理中"},
            )

            # 3) 构造消息上下文：优先使用 MemoryManager（长期事实 + 滑动窗口 + 摘要），
            #    不可用时回退到 history 参数
            from langchain_core.messages import BaseMessage
            if memory_ok and self._memory_manager is not None and session_id:
                try:
                    messages: list[BaseMessage] = self._memory_manager.build_context(
                        session_id=session_id,
                        user_id=user_id,
                        current_message=message,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("MemoryManager.build_context 失败，回退: %s", exc)
                    messages = [SystemMessage(content=self.SYSTEM_PROMPT)]
                    for m in history:
                        role = m.get("role")
                        content = m.get("content", "")
                        if role == "user":
                            messages.append(HumanMessage(content=content))
                        elif role == "assistant":
                            messages.append(AIMessage(content=content))
                    messages.append(HumanMessage(content=message))
            else:
                messages = [SystemMessage(content=self.SYSTEM_PROMPT)]
                for m in history:
                    role = m.get("role")
                    content = m.get("content", "")
                    if role == "user":
                        messages.append(HumanMessage(content=content))
                    elif role == "assistant":
                        messages.append(AIMessage(content=content))
                messages.append(HumanMessage(content=message))

            collected_text = ""
            tool_calls_seen: list[dict[str, Any]] = []

            # 第一次 LLM stream（输出 + 不带 tool_calls 决策）
            for chunk in self._llm.stream(messages):
                delta = getattr(chunk, "content", None)
                if isinstance(delta, str) and delta:
                    collected_text += delta
                    yield self._evt(
                        StreamEventType.MESSAGE, next_seq(),
                        {"content": delta, "type": "assistant", "partial": True},
                    )
                elif isinstance(delta, list):
                    for item in delta:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text = item.get("text", "")
                            if text:
                                collected_text += text
                                yield self._evt(
                                    StreamEventType.MESSAGE, next_seq(),
                                    {"content": text, "type": "assistant", "partial": True},
                                )

            # 让 LLM 知道"有工具可用"，必须用 bind_tools 后的实例来检测 tool_calls
            bound = self._llm.bind_tools(self._tools)
            try:
                decision = bound.invoke(messages)
            except Exception as exc:  # noqa: BLE001
                logger.warning("tool_calls 决策失败，跳过工具调用: %s", exc)
                decision = None
            tool_calls: list[dict[str, Any]] = (
                list(getattr(decision, "tool_calls", None) or []) if decision else []
            )

            # ── 4 + 4.5 统一为单 while 循环：递归 tool 链 ──────────
            # 每一轮：tool_calls → 执行 → 追加 AIMessage+ToolMessage →
            #         重决策 → 若有新一轮 tool_calls 则继续；
            #         无 tool_calls（final answer）则退出。
            # turn 字段：1, 2, 3, ... ；上限 = _max_iterations（生产级安全网）
            turn = 0
            last_decision_text: str = collected_text
            max_iter_reached: bool = False
            while tool_calls and turn < self._max_iterations:
                turn += 1
                yield self._evt(
                    StreamEventType.NODE_UPDATE, next_seq(),
                    {
                        "node": "llm",
                        "status": "running",
                        "message": f"第 {turn} 轮推理：执行 {len(tool_calls)} 个工具",
                        "turn": turn,
                    },
                )

                # 4) 执行工具
                executed_results: list[dict[str, Any]] = []
                for tc in tool_calls:
                    tool_name = tc.get("name", "")
                    tool_args = tc.get("args", {}) or {}
                    tool_id = tc.get("id", "")
                    tool_calls_seen.append(
                        {"tool_name": tool_name, "args": tool_args, "tool_id": tool_id, "turn": turn}
                    )
                    yield self._evt(
                        StreamEventType.TOOL_CALL, next_seq(),
                        {
                            "tool_name": tool_name,
                            "arguments": tool_args,
                            "tool_id": tool_id,
                            "turn": turn,
                            "status": "calling",
                        },
                    )
                    tool = self._tool_map.get(tool_name)
                    if tool is None:
                        result_str = f"ERROR: tool '{tool_name}' not registered"
                    else:
                        try:
                            result_str = str(tool.invoke(tool_args))
                        except Exception as exc:  # noqa: BLE001
                            logger.exception("tool %s 执行失败", tool_name)
                            result_str = f"ERROR: {exc!r}"
                    executed_results.append(
                        {"tool_name": tool_name, "tool_id": tool_id, "result": result_str}
                    )
                    yield self._evt(
                        StreamEventType.TOOL_RESULT, next_seq(),
                        {
                            "tool_name": tool_name,
                            "tool_id": tool_id,
                            "result": result_str,
                            "turn": turn,
                            "status": "completed",
                        },
                    )

                # 把本轮 AIMessage(tool_calls) + ToolMessage 追加到 messages
                messages.append(
                    AIMessage(
                        content=last_decision_text,
                        tool_calls=[
                            {
                                "name": tc.get("name", ""),
                                "args": tc.get("args", {}) or {},
                                "id": tc.get("id", ""),
                            }
                            for tc in tool_calls
                        ],
                    )
                )
                for tc, r in zip(tool_calls, executed_results):
                    messages.append(
                        ToolMessage(
                            content=r["result"],
                            tool_call_id=tc.get("id", ""),
                        )
                    )

                # 4.5) 二次/多次 LLM 决策：流式产出 + 重新 invoke 取 tool_calls
                yield self._evt(
                    StreamEventType.NODE_UPDATE, next_seq(),
                    {
                        "node": "llm",
                        "status": "running",
                        "message": f"第 {turn} 轮推理：基于工具结果重决策",
                        "turn": turn,
                    },
                )
                round_text = ""
                for chunk in self._llm.stream(messages):
                    delta = getattr(chunk, "content", None)
                    if isinstance(delta, str) and delta:
                        round_text += delta
                        yield self._evt(
                            StreamEventType.MESSAGE, next_seq(),
                            {"content": delta, "type": "assistant", "partial": True, "turn": turn},
                        )
                    elif isinstance(delta, list):
                        for item in delta:
                            if isinstance(item, dict) and item.get("type") == "text":
                                text = item.get("text", "")
                                if text:
                                    round_text += text
                                    yield self._evt(
                                        StreamEventType.MESSAGE, next_seq(),
                                        {"content": text, "type": "assistant", "partial": True, "turn": turn},
                                    )
                last_decision_text = round_text
                collected_text = round_text  # 用最新文本覆盖

                # 重新 invoke 拿新一轮 tool_calls
                try:
                    new_decision = bound.invoke(messages)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("第 %d 轮决策失败: %s", turn, exc)
                    new_decision = None
                tool_calls = (
                    list(getattr(new_decision, "tool_calls", None) or [])
                    if new_decision
                    else []
                )

                # 边界：超过 max_iterations 但 LLM 仍要调工具 → 强制收尾
                if tool_calls and turn >= self._max_iterations:
                    max_iter_reached = True
                    logger.warning(
                        "递归 tool 链达到上限 %d 轮仍有 tool_calls，强制收尾",
                        self._max_iterations,
                    )
                    yield self._evt(
                        StreamEventType.NODE_UPDATE, next_seq(),
                        {
                            "node": "llm",
                            "status": "warning",
                            "message": (
                                f"已达最大递归深度 {self._max_iterations}，"
                                "强制输出当前已收集结果"
                            ),
                            "turn": turn,
                        },
                    )
                    break

            # 防御性剥离：若 LLM 仍把工具调用当 XML 文本输出，剔除后再交付
            collected_text = _strip_tool_xml(collected_text)

            # 5) 报告最终汇总
            duration_ms = int((time.perf_counter() - start_ts) * 1000)
            yield self._evt(
                StreamEventType.NODE_UPDATE, next_seq(),
                {
                    "node": "llm",
                    "status": "completed",
                    "message": (
                        f"推理完成（{turn} 轮 tool 链）"
                        if turn > 0
                        else "推理完成（无工具调用）"
                    ),
                    "turn": turn,
                },
            )
            yield self._evt(
                StreamEventType.DONE, next_seq(),
                {
                    "task_id": task_id,
                    "session_id": session_id,
                    "duration_ms": duration_ms,
                    "tool_calls": tool_calls_seen,
                    "turn": turn,
                    "max_iterations": self._max_iterations,
                    "max_iterations_reached": max_iter_reached,
                    "full_text": collected_text,
                },
            )

            # 6) Phase B 后处理：从本轮对话抽取事实并写入长期记忆（best-effort）
            if memory_ok and self._memory_manager is not None and session_id and collected_text:
                try:
                    stored = self._memory_manager.extract_and_store_facts(
                        session_id=session_id,
                        user_id=user_id,
                        user_text=message,
                        assistant_text=collected_text,
                    )
                    if stored:
                        logger.info(
                            "抽取并存储 %d 条长期事实 (user_id=%s)", stored, user_id
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("fact 抽取/存储失败: %s", exc)

            self._complete_task()

        except AgentValidationError as exc:
            self._fail_task(str(exc))
            yield self._evt(
                StreamEventType.ERROR, next_seq(),
                {"error": str(exc), "code": "VALIDATION_ERROR"},
            )
        except Exception as exc:  # noqa: BLE001
            self._fail_task(str(exc))
            logger.exception("ReactAgent 执行异常")
            yield self._evt(
                StreamEventType.ERROR, next_seq(),
                {"error": str(exc), "code": "EXECUTION_ERROR"},
            )

    # ── 事件构造器 ──────────────────────────────────────────────
    def _evt(
        self,
        event_type: StreamEventType,
        sequence: int,
        data: dict[str, Any],
    ) -> StreamEvent:
        return StreamEvent(
            event=event_type,
            data=data,
            agent_id=self.agent_id,
            timestamp=datetime.now(),
            sequence=sequence,
        )


# ── 6. 注册函数 ────────────────────────────────────────────────────
def register_react_agent(registry: Any) -> None:
    """注册 ReactAgent 到 AgentRegistry。

    Args:
        registry: AgentRegistry 实例。
    """
    try:
        agent = ReactAgent()
        registry.register(agent)
        logger.info("ReactAgent 注册成功")
    except Exception as exc:  # noqa: BLE001
        logger.error("ReactAgent 注册失败: %s", exc)


__all__ = [
    "ReactAgent",
    "ReactState",
    "build_react_graph",
    "default_react_tools",
    "register_react_agent",
]
