"""
DesignReviewAgent - 设计审查 Agent 实现。

将现有的 design_review_graph 封装为 BaseAgent 接口，
支持流式输出和事件驱动。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, AsyncIterator

from langchain_core.messages import HumanMessage

from core.agents.base import (
    BaseAgent,
    AgentConfig,
    AgentType,
    AgentStatus,
    StreamEvent,
)
from core.agents.exceptions import AgentError, AgentValidationError
from api.v1.schemas.chat import StreamEventType

logger = logging.getLogger(__name__)


class DesignReviewAgent(BaseAgent):
    """
    设计审查 Agent。

    封装 design_review_graph，提供标准化的 Agent 接口。
    """

    def __init__(self) -> None:
        super().__init__()
        self._graph = None
        self._model = None

    @property
    def config(self) -> AgentConfig:
        return AgentConfig(
            agent_id="design_review",
            name="设计审查助手",
            description="分析PRD文档和原型图，生成设计审查报告",
            agent_type=AgentType.DESIGN_REVIEW,
            version="1.0.0",
            capabilities=(
                "prd_analysis",
                "prototype_analysis",
                "standard_retrieval",
                "report_generation",
            ),
            max_concurrent=1,
            timeout=600.0,
            metadata={
                "supported_formats": ["md", "txt", "pdf", "jpg", "png"],
                "requires_files": True,
            },
        )

    def _ensure_graph(self):
        """延迟初始化图。"""
        if self._graph is None:
            try:
                from llm_model.reasoning_model.minimax import MinimaxReasoningModelProvider
                from agent.graphs.design_review.design_review_graph import (
                    create_design_review_graph,
                )

                self._model = MinimaxReasoningModelProvider().get_model()
                self._graph = create_design_review_graph(self._model)
                logger.info("DesignReviewGraph 初始化成功")
            except Exception as e:
                logger.error(f"DesignReviewGraph 初始化失败: {e}")
                raise AgentError(f"图初始化失败: {e}", agent_id=self.agent_id)

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str | None]:
        """验证输入数据。"""
        message = input_data.get("message", "")
        file_paths = input_data.get("file_paths", [])
        image_urls = input_data.get("image_urls", [])

        # 至少需要一个输入源
        if not message and not file_paths and not image_urls:
            return False, "请提供消息、文件或图片中的至少一个"

        return True, None

    async def execute(
        self,
        input_data: dict[str, Any],
        task_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """执行设计审查任务。

        事件流典型序列：
          THINKING  -> NODE_UPDATE(start) -> TOOL_CALL(read_file) -> ...
                    -> NODE_UPDATE(analyze_prd|standard|prototype)
                    -> NODE_UPDATE(barrier) -> NODE_UPDATE(generate_report)
                    -> MESSAGE(type=report) -> DONE
        """
        import time
        task_id = task_id or f"dr-{uuid.uuid4().hex[:8]}"
        self._start_task(task_id)
        start_ts = time.perf_counter()
        seq = 0

        def next_seq() -> int:
            nonlocal seq
            seq += 1
            return seq

        def _evt(event_type: StreamEventType, data: dict[str, Any]) -> StreamEvent:
            return StreamEvent(
                event=event_type.value,
                data=data,
                agent_id=self.agent_id,
                timestamp=datetime.now(),
                sequence=next_seq(),
            )

        try:
            # 确保图已初始化
            self._ensure_graph()

            # 构建输入状态
            # 输入契约（与 api/v1/endpoints/design_review.py 对齐）：
            #   input_data["message"]:      str          —— 用户补充说明
            #   input_data["prd_content"]:  str          —— 已解析的 PRD 纯文本（API 层负责解析）
            #   input_data["image_urls"]:   list[str]    —— 视觉模型可 fetch 的公网 URL 列表
            #                                              （presigned URL 流程产物，agent 不感知 IO 协议）
            #
            # 注意：domain 层不感知 local:// / OSS / 物理路径 / data URI —— 全部由 API 层预先适配。
            # 这里把内容直接写入 state 的 prd_raw_text / image_path 字段，
            # 让 analyze_prd_node / analyze_prototype_node 走"已有内容"分支。
            message = input_data.get("message", "")
            prd_content = input_data.get("prd_content", "") or ""
            image_urls: list[str] = list(input_data.get("image_urls") or [])

            # 1) 思考中
            yield _evt(
                StreamEventType.THINKING,
                {"stage": "initializing", "content": "正在初始化设计审查..."},
            )
            yield _evt(
                StreamEventType.MESSAGE,
                {"content": "正在初始化设计审查...", "type": "status"},
            )

            # 2) 构建 LangGraph 输入
            graph_input: dict[str, Any] = {
                "messages": [HumanMessage(content=message)],
                "node_errors": {},
            }

            # PRD：把 API 层已解析好的纯文本直接喂给 state.prd_raw_text
            if prd_content:
                graph_input["prd_raw_text"] = prd_content
                yield _evt(
                    StreamEventType.TOOL_CALL,
                    {
                        "tool_name": "analyze_prd",
                        "arguments": {"prd_content_length": len(prd_content)},
                        "status": "ready",
                    },
                )

            # 原型图：把 API 层准备好的公网 URL 列表写入 state.image_path
            # 视觉模型（如 qwen-vl）会直接 fetch 这些 URL
            if image_urls:
                graph_input["image_path"] = image_urls
                yield _evt(
                    StreamEventType.TOOL_CALL,
                    {
                        "tool_name": "analyze_prototype",
                        "arguments": {"image_count": len(image_urls)},
                        "status": "ready",
                    },
                )

            # 3) 进入图执行
            yield _evt(
                StreamEventType.NODE_UPDATE,
                {
                    "node": "start",
                    "status": "running",
                    "message": "开始执行设计审查流程",
                },
            )

            # 流式执行
            events = self._graph.stream(graph_input, stream_mode="values")
            final_state: dict[str, Any] | None = None
            last_emitted_node = ""

            for event in events:
                final_state = event

                # 节点切换：先 THINKING，再 NODE_UPDATE(running)
                current_node = event.get("current_node", "")
                if current_node and current_node != last_emitted_node:
                    yield _evt(
                        StreamEventType.THINKING,
                        {"stage": current_node, "content": f"进入节点: {current_node}"},
                    )
                    yield _evt(
                        StreamEventType.NODE_UPDATE,
                        {
                            "node": current_node,
                            "status": "running",
                            "message": f"正在执行: {current_node}",
                        },
                    )
                    last_emitted_node = current_node

                # 消息流
                messages = event.get("messages", [])
                if messages:
                    last_msg = messages[-1]
                    if hasattr(last_msg, "content") and last_msg.content:
                        yield _evt(
                            StreamEventType.MESSAGE,
                            {"content": last_msg.content, "type": "assistant"},
                        )
                    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                        for tc in last_msg.tool_calls:
                            yield _evt(
                                StreamEventType.TOOL_CALL,
                                {
                                    "tool_name": tc.get("name", ""),
                                    "arguments": tc.get("args", {}),
                                    "status": "completed",
                                },
                            )

            # 4) 报告生成
            duration_ms = int((time.perf_counter() - start_ts) * 1000)
            report_id = ""
            if final_state:
                yield _evt(
                    StreamEventType.NODE_UPDATE,
                    {
                        "node": "generate_report",
                        "status": "completed",
                        "message": "报告生成完成",
                    },
                )
                report_data = self._extract_report_data(final_state)
                report_id = report_data.get("report_meta", {}).get("report_id", "")
                yield _evt(
                    StreamEventType.MESSAGE,
                    {
                        "content": "设计审查完成！报告已生成。",
                        "type": "report",
                        "report_data": report_data,
                    },
                )

            # 5) DONE
            yield _evt(
                StreamEventType.DONE,
                {
                    "task_id": task_id,
                    "report_id": report_id,
                    "duration_ms": duration_ms,
                    "agent_id": self.agent_id,
                },
            )
            self._complete_task()

        except Exception as e:
            self._fail_task(str(e))
            yield _evt(
                StreamEventType.ERROR,
                {"error": str(e), "code": "EXECUTION_ERROR"},
            )
            raise

    def _extract_report_data(self, state: dict[str, Any]) -> dict[str, Any]:
        """从最终状态提取报告数据。"""
        from datetime import datetime

        report_data = {
            "report_meta": {
                "report_id": f"DR-{datetime.now().strftime('%Y%m%d-%H%M%S')}-AUTO",
                "generated_at": datetime.now().isoformat(),
                "prd_source": state.get("prd_file_path", ""),
                "prototype_source": str(state.get("image_path", [])),
                "total_items": 0,
                "compliance_rate": 0,
            },
            "summary": {
                "by_outcome": {"pass": 0, "deviation": 0, "violation": 0, "missing": 0, "unspecified": 0, "prd_override": 0},
                "by_severity": {"critical": 0, "major": 0, "minor": 0, "info": 0},
                "by_category": {},
            },
            "top_issues": [],
            "action_items": [],
            "items": [],
        }

        # 从 analysis_result 提取数据
        analysis_result = state.get("analysis_result")
        if isinstance(analysis_result, dict):
            report_data.update(analysis_result)
        elif isinstance(analysis_result, list):
            report_data["items"] = analysis_result
            report_data["report_meta"]["total_items"] = len(analysis_result)

        return report_data


def register_design_review_agent(registry) -> None:
    """注册设计审查 Agent 到注册器。"""
    try:
        agent = DesignReviewAgent()
        registry.register(agent)
        logger.info("DesignReviewAgent 注册成功")
    except Exception as e:
        logger.error(f"DesignReviewAgent 注册失败: {e}")
