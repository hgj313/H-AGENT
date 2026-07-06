"""
Chat 端点 - 处理对话和流式响应。

集成数据库持久化，支持：
- 会话管理
- 消息持久化
- 检查点创建
- 撤销/重放功能
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.v1.schemas.chat import (
    ChatRequest,
    ChatResponse,
    StreamEvent,
    StreamEventType,
    MessageRole,
    CreateSessionRequest,
    SessionResponse,
    SessionListResponse,
    UpdateSessionRequest,
    MessageResponse,
    MessageListResponse,
    CheckpointResponse,
    CheckpointListResponse,
    UndoRequest,
    UndoResponse,
    ReplayRequest,
    ReplayResponse,
    RollbackRequest,
)
from api.v1.services import SessionService, MessageService, CheckpointService
from core.registry.agent_registry import AgentRegistry
from core.agents.base import BaseAgent, AgentStatus
from core.agents.exceptions import AgentNotFoundError, AgentStateError

logger = logging.getLogger(__name__)

router = APIRouter()

# 服务实例（延迟初始化）
_session_service = None
_message_service = None
_checkpoint_service = None


def _get_session_service() -> SessionService:
    """获取会话服务实例。"""
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service


def _get_message_service() -> MessageService:
    """获取消息服务实例。"""
    global _message_service
    if _message_service is None:
        _message_service = MessageService()
    return _message_service


def _get_checkpoint_service() -> CheckpointService:
    """获取检查点服务实例。"""
    global _checkpoint_service
    if _checkpoint_service is None:
        _checkpoint_service = CheckpointService()
    return _checkpoint_service


def _get_registry(request: Request) -> AgentRegistry:
    """从 app state 获取 registry。"""
    registry = getattr(request.app.state, "registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="AgentRegistry 未初始化")
    return registry


# ==================== 会话管理端点 ====================

@router.post("/sessions", response_model=SessionResponse)
async def create_session(request: CreateSessionRequest):
    """创建新会话。"""
    try:
        session_service = _get_session_service()
        checkpoint_service = _get_checkpoint_service()
        
        # 创建会话
        session = session_service.create_session(
            user_id=request.user_id,
            session_title=request.session_title,
            metadata=request.metadata,
        )
        
        # 创建初始检查点
        checkpoint = checkpoint_service.create_initial_checkpoint(
            session_id=session["session_id"],
            user_id=request.user_id,
        )
        
        # 更新会话的最后检查点ID
        session_service.update_session(
            session_id=session["session_id"],
            last_checkpoint_id=checkpoint["checkpoint_id"],
        )
        
        session["last_checkpoint_id"] = checkpoint["checkpoint_id"]
        
        return SessionResponse(**session)
    except Exception as e:
        logger.error(f"创建会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建会话失败: {str(e)}")


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    user_id: str = "default_user",
    is_active: int = 1,
    limit: int = 50,
    offset: int = 0,
):
    """获取会话列表。"""
    try:
        session_service = _get_session_service()
        sessions = session_service.list_sessions(
            user_id=user_id,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )
        total = session_service.get_session_count(user_id=user_id, is_active=is_active)
        
        return SessionListResponse(
            sessions=[SessionResponse(**s) for s in sessions],
            total=total,
        )
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取会话列表失败: {str(e)}")


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """获取会话详情。"""
    try:
        session_service = _get_session_service()
        session = session_service.get_session(session_id)
        
        if not session:
            raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
        
        return SessionResponse(**session)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话详情失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取会话详情失败: {str(e)}")


@router.put("/sessions/{session_id}", response_model=SessionResponse)
async def update_session(session_id: str, request: UpdateSessionRequest):
    """更新会话信息。"""
    try:
        session_service = _get_session_service()
        session = session_service.update_session(
            session_id=session_id,
            session_title=request.session_title,
            is_active=request.is_active,
            metadata=request.metadata,
        )
        
        if not session:
            raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
        
        return SessionResponse(**session)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新会话失败: {str(e)}")


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, hard_delete: bool = False):
    """删除会话。"""
    try:
        session_service = _get_session_service()
        success = session_service.delete_session(session_id, hard_delete=hard_delete)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
        
        return {"success": True, "message": "会话删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除会话失败: {str(e)}")


# ==================== 消息管理端点 ====================

@router.get("/sessions/{session_id}/messages", response_model=MessageListResponse)
async def get_session_messages(
    session_id: str,
    is_active: int = 1,
    limit: int = 100,
    offset: int = 0,
):
    """获取会话的消息列表。"""
    try:
        message_service = _get_message_service()
        
        if is_active == 1:
            messages = message_service.get_active_messages(session_id, limit, offset)
        else:
            messages = message_service.get_all_messages(session_id, limit, offset)
        
        total = message_service.get_message_count(session_id, is_active=is_active)
        
        return MessageListResponse(
            messages=[MessageResponse(**m) for m in messages],
            total=total,
        )
    except Exception as e:
        logger.error(f"获取消息列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取消息列表失败: {str(e)}")


@router.get("/messages/{message_id}", response_model=MessageResponse)
async def get_message(message_id: str):
    """获取消息详情。"""
    try:
        message_service = _get_message_service()
        message = message_service.get_message(message_id)
        
        if not message:
            raise HTTPException(status_code=404, detail=f"消息不存在: {message_id}")
        
        return MessageResponse(**message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取消息详情失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取消息详情失败: {str(e)}")


# ==================== 检查点管理端点 ====================

@router.get("/sessions/{session_id}/checkpoints", response_model=CheckpointListResponse)
async def get_session_checkpoints(
    session_id: str,
    limit: int = 50,
    offset: int = 0,
):
    """获取会话的检查点列表。"""
    try:
        checkpoint_service = _get_checkpoint_service()
        checkpoints = checkpoint_service.get_session_checkpoints(session_id, limit, offset)
        total = checkpoint_service.get_checkpoint_count(session_id)
        
        return CheckpointListResponse(
            checkpoints=[CheckpointResponse(**c) for c in checkpoints],
            total=total,
        )
    except Exception as e:
        logger.error(f"获取检查点列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取检查点列表失败: {str(e)}")


@router.get("/checkpoints/{checkpoint_id}", response_model=CheckpointResponse)
async def get_checkpoint(checkpoint_id: str):
    """获取检查点详情。"""
    try:
        checkpoint_service = _get_checkpoint_service()
        checkpoint = checkpoint_service.get_checkpoint(checkpoint_id)
        
        if not checkpoint:
            raise HTTPException(status_code=404, detail=f"检查点不存在: {checkpoint_id}")
        
        return CheckpointResponse(**checkpoint)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取检查点详情失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取检查点详情失败: {str(e)}")


@router.post("/checkpoints/rollback", response_model=CheckpointResponse)
async def rollback_to_checkpoint(request: RollbackRequest):
    """回滚到指定检查点。"""
    try:
        checkpoint_service = _get_checkpoint_service()
        checkpoint = checkpoint_service.rollback_to_checkpoint(request.checkpoint_id)
        
        if not checkpoint:
            raise HTTPException(status_code=404, detail=f"检查点不存在: {request.checkpoint_id}")
        
        return CheckpointResponse(**checkpoint)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"回滚检查点失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"回滚检查点失败: {str(e)}")


# ==================== 撤销功能端点 ====================

@router.post("/undo", response_model=UndoResponse)
async def undo_message(request: UndoRequest):
    """
    撤销消息。
    
    将指定消息之后的所有同分支消息标记为非活跃，
    并返回该消息对应的检查点用于前端状态还原。
    """
    try:
        message_service = _get_message_service()
        checkpoint_service = _get_checkpoint_service()
        session_service = _get_session_service()
        
        # 获取目标消息
        target_message = message_service.get_message(request.message_id)
        if not target_message:
            raise HTTPException(status_code=404, detail=f"消息不存在: {request.message_id}")
        
        # 检查消息是否属于指定会话
        if target_message["session_id"] != request.session_id:
            raise HTTPException(status_code=400, detail="消息不属于指定会话")
        
        # 获取关联的检查点
        checkpoint = checkpoint_service.get_checkpoint_by_message(request.message_id)
        
        # 如果没有关联检查点，查找最近的检查点
        if not checkpoint:
            checkpoint = checkpoint_service.get_latest_checkpoint(request.session_id)
        
        # 将后续消息标记为非活跃
        deactivated_count = message_service.deactivate_messages_after(
            session_id=request.session_id,
            message_id=request.message_id,
        )
        
        # 更新会话的最后检查点ID
        if checkpoint:
            session_service.update_session(
                session_id=request.session_id,
                last_checkpoint_id=checkpoint["checkpoint_id"],
            )
        
        return UndoResponse(
            success=True,
            checkpoint=CheckpointResponse(**checkpoint) if checkpoint else None,
            deactivated_count=deactivated_count,
            message=f"成功撤销 {deactivated_count} 条消息",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"撤销消息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"撤销消息失败: {str(e)}")


# ==================== 重放功能端点 ====================

@router.post("/replay", response_model=ReplayResponse)
async def replay_message(request: ReplayRequest):
    """
    重放消息。
    
    从指定消息开始，重新调用模型生成新的回复，
    支持分支对话创建。
    """
    try:
        message_service = _get_message_service()
        checkpoint_service = _get_checkpoint_service()
        
        # 获取目标消息
        target_message = message_service.get_message(request.message_id)
        if not target_message:
            raise HTTPException(status_code=404, detail=f"消息不存在: {request.message_id}")
        
        # 获取关联的检查点和模型参数
        checkpoint = checkpoint_service.get_checkpoint_by_message(request.message_id)
        model_params = target_message.get("model_params", {})
        
        # TODO: 这里应该调用Agent重新生成回复
        # 目前返回一个占位响应
        new_message = message_service.create_message(
            session_id=request.session_id,
            role="assistant",
            content="[重放功能] 此处将调用Agent重新生成回复",
            parent_message_id=request.message_id,
            model_params=model_params,
            metadata={"is_replay": True, "original_message_id": request.message_id},
        )
        
        return ReplayResponse(
            success=True,
            new_message=MessageResponse(**new_message),
            message="重放成功",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重放消息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重放消息失败: {str(e)}")


# ==================== 聊天补全端点（集成数据库） ====================

@router.post("/completions", response_model=None)
async def chat_completions(
    chat_request: ChatRequest,
    request: Request,
):
    """
    聊天补全接口（集成数据库持久化）。

    - stream=true: 返回 SSE 流式响应
    - stream=false: 返回完整响应
    """
    registry = _get_registry(request)
    message_service = _get_message_service()
    session_service = _get_session_service()
    checkpoint_service = _get_checkpoint_service()

    # 获取目标 Agent
    agent = registry.get(chat_request.agent_id)
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent 未找到: {chat_request.agent_id}",
        )

    if not agent.is_available:
        raise HTTPException(
            status_code=503,
            detail=f"Agent 不可用: {chat_request.agent_id}, 状态: {agent.state.status.value}",
        )

    # 验证输入
    is_valid, error_msg = agent.validate_input(chat_request.model_dump())
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # 生成会话ID和任务ID
    conversation_id = chat_request.conversation_id or str(uuid.uuid4())
    task_id = f"task-{uuid.uuid4().hex[:8]}"
    
    # 处理会话ID
    session_id = chat_request.session_id
    if not session_id:
        # 自动创建新会话
        session = session_service.create_session(
            user_id="default_user",
            session_title=chat_request.message[:50] if chat_request.message else "新对话",
        )
        session_id = session["session_id"]
        
        # 创建初始检查点
        checkpoint = checkpoint_service.create_initial_checkpoint(
            session_id=session_id,
            user_id="default_user",
        )
        session_service.update_session(
            session_id=session_id,
            last_checkpoint_id=checkpoint["checkpoint_id"],
        )
    
    # 获取最后一条消息作为父消息
    last_message = message_service.get_last_message(session_id)
    parent_message_id = last_message["message_id"] if last_message else None
    
    # 保存用户消息到数据库
    user_message = message_service.create_message(
        session_id=session_id,
        role="user",
        content=chat_request.message,
        parent_message_id=parent_message_id,
        metadata=chat_request.metadata,
    )
    
    # 更新会话时间戳
    session_service.update_session_timestamp(session_id)

    if chat_request.stream:
        return StreamingResponse(
            _stream_response(
                agent, chat_request, task_id, conversation_id,
                session_id, user_message["message_id"],
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        return await _complete_response(
            agent, chat_request, task_id, conversation_id,
            session_id, user_message["message_id"],
        )


async def _stream_response(
    agent: BaseAgent,
    request: ChatRequest,
    task_id: str,
    conversation_id: str,
    session_id: str,
    user_message_id: str,
) -> AsyncIterator[str]:
    """生成 SSE 流式响应（集成数据库持久化）。"""
    message_service = _get_message_service()
    checkpoint_service = _get_checkpoint_service()
    session_service = _get_session_service()
    
    assistant_content = ""
    
    try:
        # 发送开始事件
        yield StreamEvent(
            event=StreamEventType.MESSAGE,
            data={
                "content": "",
                "type": "start",
                "task_id": task_id,
                "conversation_id": conversation_id,
                "session_id": session_id,
            },
            agent_id=agent.agent_id,
        ).to_sse_format()

        # 执行 Agent 并转发事件
        input_data = {
            "message": request.message,
            "file_paths": request.file_paths,
            "image_urls": request.image_urls,
            "metadata": request.metadata,
        }

        async for event in agent.execute(input_data, task_id):
            # 收集助手回复内容
            if event.event == StreamEventType.MESSAGE:
                assistant_content += event.data.get("content", "")
            
            yield event.to_sse_format()

        # 保存助手消息到数据库
        if assistant_content:
            assistant_message = message_service.create_message(
                session_id=session_id,
                role="assistant",
                content=assistant_content,
                parent_message_id=user_message_id,
                model_params={"agent_id": agent.agent_id},
            )
            
            # 更新会话时间戳
            session_service.update_session_timestamp(session_id)
            
            # 自动创建检查点（每2轮对话）
            message_count = message_service.get_message_count(session_id)
            if message_count % 4 == 0:  # 每2轮对话（4条消息：user+assistant x 2）
                checkpoint_service.create_checkpoint(
                    session_id=session_id,
                    state_dump={
                        "session_id": session_id,
                        "message_count": message_count,
                        "last_message_id": assistant_message["message_id"],
                    },
                    message_id=assistant_message["message_id"],
                    trigger_type="auto_round",
                    description=f"自动检查点 - 第 {message_count // 4} 轮对话",
                )

        # 发送完成事件
        yield StreamEvent(
            event=StreamEventType.DONE,
            data={
                "task_id": task_id,
                "conversation_id": conversation_id,
                "session_id": session_id,
                "status": "completed",
            },
            agent_id=agent.agent_id,
        ).to_sse_format()

    except Exception as e:
        logger.error(f"Stream error: {e}", exc_info=True)
        yield StreamEvent(
            event=StreamEventType.ERROR,
            data={"error": str(e), "task_id": task_id, "session_id": session_id},
            agent_id=agent.agent_id,
        ).to_sse_format()


async def _complete_response(
    agent: BaseAgent,
    request: ChatRequest,
    task_id: str,
    conversation_id: str,
    session_id: str,
    user_message_id: str,
) -> ChatResponse:
    """生成完整响应（非流式，集成数据库持久化）。"""
    message_service = _get_message_service()
    checkpoint_service = _get_checkpoint_service()
    session_service = _get_session_service()
    
    input_data = {
        "message": request.message,
        "file_paths": request.file_paths,
        "image_urls": request.image_urls,
        "metadata": request.metadata,
    }

    messages = []
    tool_calls = []
    node_status = None

    try:
        async for event in agent.execute(input_data, task_id):
            event_data = event.data if hasattr(event, "data") else {}
            event_type = event.event if hasattr(event, "event") else ""

            if event_type == StreamEventType.MESSAGE:
                messages.append(event_data.get("content", ""))
            elif event_type == StreamEventType.TOOL_CALL:
                tool_calls.append(event_data)
            elif event_type == StreamEventType.NODE_UPDATE:
                node_status = event_data

    except Exception as e:
        logger.error(f"Execution error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    assistant_content = "".join(messages)
    
    # 保存助手消息到数据库
    if assistant_content:
        assistant_message = message_service.create_message(
            session_id=session_id,
            role="assistant",
            content=assistant_content,
            parent_message_id=user_message_id,
            model_params={"agent_id": agent.agent_id},
        )
        
        # 更新会话时间戳
        session_service.update_session_timestamp(session_id)
        
        # 自动创建检查点
        message_count = message_service.get_message_count(session_id)
        if message_count % 4 == 0:
            checkpoint_service.create_checkpoint(
                session_id=session_id,
                state_dump={
                    "session_id": session_id,
                    "message_count": message_count,
                    "last_message_id": assistant_message["message_id"],
                },
                message_id=assistant_message["message_id"],
                trigger_type="auto_round",
                description=f"自动检查点 - 第 {message_count // 4} 轮对话",
            )
        
        return ChatResponse(
            message=assistant_content,
            agent_id=agent.agent_id,
            conversation_id=conversation_id,
            session_id=session_id,
            message_id=assistant_message["message_id"],
            tool_calls=tool_calls,
            node_status=node_status,
        )
    
    return ChatResponse(
        message=assistant_content,
        agent_id=agent.agent_id,
        conversation_id=conversation_id,
        session_id=session_id,
        tool_calls=tool_calls,
        node_status=node_status,
    )


@router.post("/stop/{task_id}")
async def stop_task(task_id: str, request: Request) -> dict[str, Any]:
    """停止正在执行的任务。"""
    registry = _get_registry(request)

    # 查找运行该任务的 Agent
    for agent in registry:
        if agent.state.current_task_id == task_id:
            # TODO: 实现任务停止逻辑
            return {"status": "stopped", "task_id": task_id}

    raise HTTPException(status_code=404, detail=f"任务未找到: {task_id}")


# ==================== 人工介入端点 ====================

class InterventionRequest(BaseModel):
    """人工介入请求。"""
    session_id: str
    message_id: Optional[str] = None
    content: str
    action: str = Field(default="submit", description="操作类型: submit/cancel")


@router.post("/intervention")
async def submit_intervention(request: InterventionRequest):
    """
    提交人工介入内容。
    
    将用户补充的内容作为新的消息插入会话，
    并可触发对应 Agent 重新执行。
    """
    try:
        message_service = _get_message_service()
        session_service = _get_session_service()
        
        # 将会话标记为需要人工介入
        # 将用户输入作为新的用户消息
        new_message = message_service.create_message(
            session_id=request.session_id,
            role="user",
            content=f"[人工介入] {request.content}",
            parent_message_id=request.message_id,
            message_type="text",
            metadata={
                "is_intervention": True,
                "intervention_action": request.action,
            },
        )
        
        # 更新会话时间戳
        session_service.update_session_timestamp(request.session_id)
        
        logger.info(
            f"人工介入提交: session_id={request.session_id}, "
            f"message_id={new_message['message_id']}, action={request.action}"
        )
        
        return {
            "success": True,
            "message": "人工介入内容已提交",
            "message_id": new_message["message_id"],
        }
    except Exception as e:
        logger.error(f"人工介入失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"人工介入失败: {str(e)}")
