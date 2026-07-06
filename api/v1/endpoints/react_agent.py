"""
ReactAgent 对话端点 - 通用对话助手的 SSE 接入。

支持：
- 单轮消息：POST /api/v1/react-agent/chat
- 多轮上下文：客户端在 body.history 传最近 N 轮
- 流式响应：Content-Type: text/event-stream
- 非流式响应：stream=false 时合并为单条 ChatResponse

设计要点：
- 复用 BaseAgent.execute() 生成的 StreamEvent
- FastAPI StreamingResponse + 同步迭代器包装 async generator
- 入参 Pydantic 严格校验
- 首轮完成时触发 SessionService 异步生成摘要（D1 决策）
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.registry.agent_registry import AgentRegistry
from core.agents.exceptions import AgentNotFoundError
from api.v1.schemas.chat import StreamEventType
from api.v1.services import SessionService, MessageService

logger = logging.getLogger(__name__)

router = APIRouter()

# 服务单例（延迟初始化，与 chat.py 保持一致）
_session_service: Optional[SessionService] = None
_message_service: Optional[MessageService] = None


def _get_session_service() -> SessionService:
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service


def _get_message_service() -> MessageService:
    global _message_service
    if _message_service is None:
        _message_service = MessageService()
    return _message_service


def _get_registry(request: Request) -> AgentRegistry:
    registry = getattr(request.app.state, "registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="AgentRegistry 未初始化")
    return registry


# ── Schema ──────────────────────────────────────────────────────────
class ReactChatRequest(BaseModel):
    """ReactAgent 对话请求。"""
    message: str = Field(..., min_length=1, max_length=8000, description="用户消息")
    session_id: Optional[str] = Field(default=None, description="会话ID（用于多轮上下文与摘要）")
    history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="历史消息列表，每条 {role, content}",
    )
    stream: bool = Field(default=True, description="是否流式响应")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReactChatResponse(BaseModel):
    """ReactAgent 对话响应（非流式聚合）。"""
    task_id: str
    session_id: Optional[str] = None
    agent_id: str
    full_text: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    duration_ms: int = 0
    message_id: Optional[str] = None


# ── 持久化辅助 ──────────────────────────────────────────────────────
async def _persist_messages(
    session_id: str,
    user_text: str,
    assistant_text: str,
) -> tuple[Optional[str], Optional[str]]:
    """持久化用户消息与助手消息，返回 (user_msg_id, assistant_msg_id)。"""
    if not session_id:
        return None, None
    try:
        msg_svc = _get_message_service()
        # 这里使用同步调用；如 MessageService 不支持 async，应放 run_in_executor
        user_msg = msg_svc.create_message(
            session_id=session_id,
            role="user",
            content=user_text,
            message_type="text",
        )
        assistant_msg = msg_svc.create_message(
            session_id=session_id,
            role="assistant",
            content=assistant_text,
            message_type="text",
            parent_message_id=user_msg.get("message_id") if user_msg else None,
        )
        return user_msg.get("message_id") if user_msg else None, (
            assistant_msg.get("message_id") if assistant_msg else None
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("持久化对话失败（非致命）: %s", exc)
        return None, None


def _maybe_trigger_title_summary(
    session_id: str,
    user_text: str,
    assistant_text: str,
) -> None:
    """首轮对话完成后异步触发摘要任务（fire-and-forget）。

    幂等性由 SessionService.summary_session_title() 内部保证：
    仅当 session.metadata.title_locked != True 且 session_title 为默认/空时执行。
    """
    if not session_id or not user_text or not assistant_text:
        return
    try:
        sess_svc = _get_session_service()
        # 避免阻塞事件循环
        asyncio.create_task(
            asyncio.to_thread(
                sess_svc.summarize_and_update_title,
                session_id=session_id,
                user_text=user_text,
                assistant_text=assistant_text,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("触发标题摘要失败（非致命）: %s", exc)


# ── SSE 端点 ────────────────────────────────────────────────────────
@router.post("/chat")
async def react_agent_chat(
    request_body: ReactChatRequest,
    request: Request,
) -> Any:
    """通用对话入口。

    - stream=true  →  返回 text/event-stream，每个事件由 ReactAgent.execute() 产生
    - stream=false →  内部消费完整事件流，聚合为 ReactChatResponse
    """
    registry = _get_registry(request)
    agent = registry.get("react")
    if agent is None:
        raise AgentNotFoundError("react", agent_id="react")

    # 1) 校验 Agent 状态
    if not agent.is_available:
        raise HTTPException(
            status_code=503,
            detail=f"ReactAgent 当前不可用：status={agent.state.status.value}",
        )

    # 2) 准备输入
    input_data: dict[str, Any] = {
        "message": request_body.message,
        "session_id": request_body.session_id or "",
        "history": request_body.history,
        "metadata": request_body.metadata,
    }

    # 3) 分支：流式 / 非流式
    if request_body.stream:
        return StreamingResponse(
            _stream_sse(agent, input_data, request_body.session_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # 非流式：聚合
    full_text = ""
    tool_calls: list[dict[str, Any]] = []
    duration_ms = 0
    task_id = ""
    error_msg: Optional[str] = None
    async for evt in agent.execute(input_data):
        if evt.event == StreamEventType.MESSAGE.value:
            payload = evt.data or {}
            if payload.get("type") == "assistant" and not payload.get("partial", True):
                full_text += payload.get("content", "")
        elif evt.event == StreamEventType.TOOL_CALL.value:
            tool_calls.append(evt.data or {})
        elif evt.event == StreamEventType.DONE.value:
            task_id = (evt.data or {}).get("task_id", "")
            duration_ms = (evt.data or {}).get("duration_ms", 0)
            full_text = (evt.data or {}).get("full_text", full_text)
        elif evt.event == StreamEventType.ERROR.value:
            error_msg = (evt.data or {}).get("error", "unknown")
    if error_msg:
        raise HTTPException(status_code=500, detail=error_msg)

    # 持久化 & 触发摘要
    user_msg_id, assistant_msg_id = await _persist_messages(
        request_body.session_id or "",
        request_body.message,
        full_text,
    )
    if request_body.session_id and full_text:
        _maybe_trigger_title_summary(
            request_body.session_id,
            request_body.message,
            full_text,
        )

    return ReactChatResponse(
        task_id=task_id,
        session_id=request_body.session_id,
        agent_id=agent.agent_id,
        full_text=full_text,
        tool_calls=tool_calls,
        duration_ms=duration_ms,
        message_id=assistant_msg_id,
    )


async def _stream_sse(
    agent: Any,
    input_data: dict[str, Any],
    session_id: Optional[str],
) -> AsyncIterator[bytes]:
    """将 ReactAgent.execute() 的事件流序列化为 SSE 字节流。

    在 DONE 事件之后做最小持久化（用户消息 + 助手消息）+ 触发摘要任务。
    """
    full_text_parts: list[str] = []
    user_text = input_data.get("message", "")

    async for evt in agent.execute(input_data):
        # BaseAgent.StreamEvent → 字节
        yield evt.to_sse_format().encode("utf-8")

        # 累计文本用于持久化
        if evt.event == StreamEventType.MESSAGE.value:
            payload = evt.data or {}
            if payload.get("type") == "assistant":
                # 流式 partial 也要累加
                full_text_parts.append(payload.get("content", ""))

        # 持久化 & 摘要触发
        elif evt.event == StreamEventType.DONE.value:
            full_text = (evt.data or {}).get("full_text") or "".join(full_text_parts)
            if session_id and full_text:
                user_msg_id, _assistant_msg_id = await _persist_messages(
                    session_id, user_text, full_text,
                )
                _maybe_trigger_title_summary(session_id, user_text, full_text)


__all__ = ["router"]
