"""
DesignReview 端点 - 设计审查会话与流式审查。

端点：
  POST /api/v1/design-review/sessions              创建会话（传 prd_path + image_urls）
  GET  /api/v1/design-review/sessions              列出某用户会话
  GET  /api/v1/design-review/sessions/{id}         会话详情
  POST /api/v1/design-review/sessions/{id}/run     流式触发审查（SSE）
  GET  /api/v1/design-review/reports/{rid}         拉取完整报告
  GET  /api/v1/design-review/sessions/{id}/report  拉取最新报告

事件契约与 ReactAgent 复用：StreamEventType + StreamEvent（Pydantic）

设计原则（Clean Architecture）：
  - local:// 等传输层协议只在 API 层出现
  - 进入 agent/domain 前必须把 URL 解析为 content（text）或 data URI（base64）
  - agent 节点 / state / tools 不感知 local://、OSS SDK、文件路径等 IO 细节
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.v1.schemas.chat import StreamEvent, StreamEventType
from api.v1.services.design_review_service import DesignReviewService
from core.registry.agent_registry import AgentRegistry
from core.agents.exceptions import AgentNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter()

# 进程内单例
_service: Optional[DesignReviewService] = None


# ─────────────────────────────────────────────────────────────────
# 传输层 → Domain 适配：把 local:// 解析为 content/data URI
# ─────────────────────────────────────────────────────────────────

# 单文件大小上限：50 MB（与 oss 端点一致；防止 OOM）
_MAX_PRD_TEXT_BYTES = 5 * 1024 * 1024  # PRD 文本上限 5MB（足够几百页文档）
_MAX_IMAGE_BYTES = 20 * 1024 * 1024    # 单图上限 20MB

# 图片扩展名 → MIME 映射（mimetypes 在 Windows 上对 .md/.png 等可能不识别，显式兜底）
_IMAGE_EXT_TO_MIME: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}


def _local_url_to_path(object_name: str) -> Path:
    """把 local://bucket/filename 解析为本地物理路径（复用 storage_service 解析逻辑）。

    安全：使用 storage service 的实例（adapter），确保
    上传/下载路径解析完全一致（与 LocalStorageBackend._resolve_path 行为对齐）。

    注意：不能直接用 `LocalStorageBackend._resolve_path(...)` —— 该方法是
    实例方法，依赖 `self.upload_dir`；必须通过 storage service 拿到实例。
    """
    from api.v1.services.storage_service import get_storage_service
    if not object_name.startswith("local://"):
        raise ValueError(f"非 local:// 协议: {object_name}")
    svc = get_storage_service()
    return svc.adapter._resolve_path(object_name)


def _guess_image_mime(path: Path) -> str:
    """从文件后缀猜 MIME。"""
    mime, _ = mimetypes.guess_type(str(path))
    if mime and mime.startswith("image/"):
        return mime
    return _IMAGE_EXT_TO_MIME.get(path.suffix.lower(), "image/png")


def _resolve_drs_input(session: dict[str, Any]) -> dict[str, Any]:
    """把会话的 prd_path / image_urls 解析为 agent 可直接消费的形式。

    Returns:
        {
            "prd_content": str | "",          # PRD 纯文本（PRD 文档类需要读文件；其他类空）
            "image_urls": list[str],          # 视觉模型可 fetch 的公网 URL 列表
            "resolve_errors": list[str],      # 解析失败的条目（用于 SSE 错误提示）
        }

    严格遵守 Clean Architecture：
      - 输入：sess["prd_path"] / sess["image_urls"]
        - PRD：local://  / 物理路径（API 层必须先 resolve 为本地路径再读 bytes 解析文本）
        - 图片：https://  公网 URL（presigned URL 流程）直接透传给视觉模型 fetch
      - 输出：纯文本 + 公网 URL（agent/domain 不再感知 IO 协议）
      - 失败不抛异常，记入 resolve_errors 让上游 SSE 透传给前端

    设计要点：
      - **不做 data URI 转换**（base64 内联开销大；公网 URL 更通用、视觉模型更原生支持）
      - **PRD 必须解析为文本**（analyze_prd 工具要 LLM 抽 specs，需要内容字符串）
      - **图片只接收 https://**（视觉模型 fetch；不再做 base64 编码内联）
    """
    resolve_errors: list[str] = []

    # ── 1) PRD 文本 ──
    # PRD 是 LLM 要消费的内容，必须在 API 层读取为纯文本
    prd_content = ""
    prd_path = (session.get("prd_path") or "").strip()
    if prd_path:
        try:
            if prd_path.startswith("local://"):
                physical = _local_url_to_path(prd_path)
            elif prd_path.startswith(("http://", "https://")):
                raise NotImplementedError(
                    f"暂不支持远端 PRD：{prd_path}（请先上传到 OSS 拿到 object_name）"
                )
            else:
                physical = Path(prd_path)
            if not physical.is_file():
                raise FileNotFoundError(f"PRD 文件不存在：{physical}")
            data = physical.read_bytes()
            if len(data) > _MAX_PRD_TEXT_BYTES:
                raise ValueError(
                    f"PRD 文件过大 {len(data)} 字节（上限 {_MAX_PRD_TEXT_BYTES}）"
                )
            prd_content = data.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            logger.warning("PRD 解析失败: %s (%r)", prd_path, exc)
            resolve_errors.append(f"PRD 解析失败 [{prd_path}]: {exc!r}")

    # ── 2) 原型图：只接受公网 URL（presigned URL 流程产物） ──
    image_urls: list[str] = []
    for url in session.get("image_urls") or []:
        url = (url or "").strip()
        if not url:
            continue
        if url.startswith("https://") or url.startswith("http://"):
            # 视觉模型可 fetch（presigned URL 或公网 URL）
            image_urls.append(url)
        elif url.startswith("local://"):
            # legacy / 旧数据：拒收并提示用户重新上传（不再做 data URI 内联）
            resolve_errors.append(
                f"图片 URL 格式不受支持: {url}（请重新上传，前端会拿到 presigned public URL）"
            )
        else:
            resolve_errors.append(
                f"图片 URL 协议不受支持: {url}（仅接受 http:// / https://）"
            )

    return {
        "prd_content": prd_content,
        "image_urls": image_urls,
        "resolve_errors": resolve_errors,
    }


def _get_service() -> DesignReviewService:
    global _service
    if _service is None:
        _service = DesignReviewService()
    return _service


def _get_registry(request: Request) -> AgentRegistry:
    registry = getattr(request.app.state, "registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="AgentRegistry 未初始化")
    return registry


# ── Pydantic 模型 ─────────────────────────────────────────
class CreateDRSessionRequest(BaseModel):
    user_id: str = "default_user"
    prd_path: str = Field(default="", description="PRD 文件路径或 URL")
    image_urls: list[str] = Field(default_factory=list, description="原型图 URL 列表")
    session_title: Optional[str] = None


class RunDRRequest(BaseModel):
    message: str = Field(default="", description="可选补充说明")


# ── 端点 ────────────────────────────────────────────────
@router.post("/sessions")
async def create_session(req: CreateDRSessionRequest):
    """创建设计审查会话（持久化到 dr_sessions 表）。"""
    try:
        svc = _get_service()
        sess = svc.create_session(
            user_id=req.user_id,
            prd_path=req.prd_path,
            image_urls=req.image_urls,
            session_title=req.session_title,
        )
        return {"success": True, "session": sess}
    except Exception as exc:  # noqa: BLE001
        logger.exception("create DR session failed")
        raise HTTPException(status_code=500, detail=f"创建失败: {exc!r}")


@router.get("/sessions")
async def list_sessions(user_id: str = "default_user", limit: int = 20, offset: int = 0):
    """列出某用户的设计审查会话（按 created_at 倒序）。"""
    try:
        svc = _get_service()
        return {"success": True, "sessions": svc.list_sessions(user_id, limit, offset)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("list DR sessions failed")
        raise HTTPException(status_code=500, detail=f"查询失败: {exc!r}")


@router.get("/sessions/{dr_session_id}")
async def get_session(dr_session_id: str):
    """获取会话详情。"""
    svc = _get_service()
    sess = svc.get_session(dr_session_id)
    if not sess:
        raise HTTPException(status_code=404, detail=f"会话不存在: {dr_session_id}")
    return {"success": True, "session": sess}


@router.post("/sessions/{dr_session_id}/run")
async def run_session(
    dr_session_id: str,
    req: RunDRRequest,
    request: Request,
):
    """流式触发设计审查。

    SSE 事件：
      thinking / node_update / message / tool_call / tool_result / done / error
    完成后：报告 JSON 自动入库到 dr_reports，表 dr_sessions.report_id 更新。
    """
    svc = _get_service()
    sess = svc.get_session(dr_session_id)
    if not sess:
        raise HTTPException(status_code=404, detail=f"会话不存在: {dr_session_id}")

    # 标记 running
    svc.update_session_status(dr_session_id, "running")

    registry = _get_registry(request)
    try:
        agent = registry.get("design_review")
    except (AgentNotFoundError, KeyError):
        svc.update_session_status(dr_session_id, "failed", error="design_review agent 未注册")
        raise HTTPException(status_code=503, detail="design_review agent 未注册")

    async def event_stream() -> AsyncIterator[str]:
        """SSE 事件流。"""
        start_ts = time.perf_counter()
        report_data: dict[str, Any] = {}
        report_id: Optional[str] = None
        error_msg: Optional[str] = None
        try:
            # ── 关键步骤：传输层 → Domain 适配 ──
            # 把 local:// / 物理路径 解析为 PRD 文本 + 公网 URL 列表，
            # 避免 agent/domain 感知 IO 协议细节
            resolved = _resolve_drs_input(sess)

            # 关键输入解析失败 → 硬失败，绝不静默吞错
            # 区分语义：
            #   1) 用户显式提供了 prd_path/image_urls 但解析失败 → 硬失败（用户的输入有问题）
            #   2) 用户没提供 → 正常（agent 走 __FULL_STATIC__ 等兜底）
            prd_path_provided = bool((sess.get("prd_path") or "").strip())
            image_urls_provided = bool(sess.get("image_urls"))
            has_unresolvable_prd = prd_path_provided and not resolved["prd_content"]
            has_unresolvable_images = (
                image_urls_provided
                and not resolved["image_urls"]
                # 全部图片 URL 都是用户提供的（image_urls_provided=True）
                # 但解析后 image_urls 为空 → 全部解析失败
            )
            if has_unresolvable_prd or has_unresolvable_images:
                # 立即发 error 事件并终止
                err_blob = StreamEvent(
                    event=StreamEventType.ERROR.value,
                    data={
                        "code": "INPUT_RESOLVE_FAILED",
                        "message": "输入资源解析失败，已终止审查",
                        "details": resolved["resolve_errors"],
                    },
                    agent_id="design_review",
                )
                yield _to_sse(err_blob)
                err_summary = "; ".join(resolved["resolve_errors"])
                svc.update_session_status(
                    dr_session_id, "failed", error=err_summary,
                )
                # 显式 done 事件让客户端能正常关闭流
                done_blob = StreamEvent(
                    event=StreamEventType.DONE.value,
                    data={
                        "task_id": f"dr-{dr_session_id}",
                        "report_id": "",
                        "duration_ms": 0,
                        "agent_id": "design_review",
                        "status": "failed",
                        "reason": "input_resolve_failed",
                    },
                    agent_id="design_review",
                )
                yield _to_sse(done_blob)
                return

            input_data: dict[str, Any] = {
                "message": req.message or "",
                "prd_content": resolved["prd_content"],
                "image_urls": resolved["image_urls"],
            }

            # agent.execute() 是 AsyncIterator[StreamEvent]
            async for evt in agent.execute(input_data, task_id=f"dr-{dr_session_id}"):
                # 从 MESSAGE(type=report) 事件中抓出 report_data
                if evt.event == StreamEventType.MESSAGE.value:
                    data = evt.data or {}
                    if isinstance(data, dict) and "report_data" in data:
                        report_data = data["report_data"] or {}
                # DONE 事件里 report_id
                elif evt.event == StreamEventType.DONE.value:
                    rid = (evt.data or {}).get("report_id")
                    if rid:
                        report_id = str(rid)

                # 序列化为 SSE
                yield _to_sse(evt)

            # 落库报告
            duration_ms = int((time.perf_counter() - start_ts) * 1000)
            if report_data:
                report_id = svc.save_report(
                    dr_session_id=dr_session_id,
                    report_data=report_data,
                    duration_ms=duration_ms,
                    status="completed",
                )
                svc.update_session_status(dr_session_id, "completed", report_id=report_id)
            else:
                svc.update_session_status(
                    dr_session_id, "failed", error="未生成报告数据"
                )
                error_msg = "未生成报告数据"

        except Exception as exc:  # noqa: BLE001
            logger.exception("DR run failed")
            error_msg = repr(exc)
            svc.update_session_status(dr_session_id, "failed", error=error_msg)
            err_evt = StreamEvent(
                event=StreamEventType.ERROR.value,
                data={"error": error_msg, "code": "EXECUTION_ERROR"},
                agent_id="design_review",
            )
            yield _to_sse(err_evt)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/reports/{report_id}")
async def get_report(report_id: str):
    """按 report_id 拉取完整报告。"""
    svc = _get_service()
    rep = svc.get_report(report_id)
    if not rep:
        raise HTTPException(status_code=404, detail=f"报告不存在: {report_id}")
    return {"success": True, "report": rep}


@router.get("/sessions/{dr_session_id}/report")
async def get_latest_report(dr_session_id: str):
    """按会话 ID 拉取最新一份报告。"""
    svc = _get_service()
    rep = svc.get_report_by_session(dr_session_id)
    if not rep:
        raise HTTPException(
            status_code=404, detail=f"该会话暂无报告: {dr_session_id}"
        )
    return {"success": True, "report": rep}


# ── 工具：SSE 序列化 ────────────────────────────────────
def _to_sse(evt: StreamEvent) -> str:
    """把 StreamEvent 序列化为 SSE 文本（event/data 双行 + 空行）。"""
    try:
        payload = evt.model_dump(mode="json", exclude_none=True)
    except Exception:  # noqa: BLE001
        # fallback：手动构造
        payload = {
            "event": str(getattr(evt, "event", "")),
            "data": getattr(evt, "data", {}) or {},
            "sequence": getattr(evt, "sequence", 0),
            "timestamp": str(getattr(evt, "timestamp", "")),
            "agent_id": getattr(evt, "agent_id", ""),
        }
    return f"event: {payload.get('event','message')}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
