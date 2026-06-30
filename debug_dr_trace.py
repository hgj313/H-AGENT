"""Debug: 追踪设计审查图实际行为，找出为什么报告 items=0。"""
from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from langchain_core.messages import HumanMessage
from agent.graphs.design_review.design_review_graph import create_design_review_graph
from agent.graphs.design_review.states.dr_state import make_empty_spec_source


async def main() -> None:
    # 拿到 LLM（test_graph.py 用的）
    try:
        from llm_model.reasoning_model.minimax import MinimaxReasoningModelProvider
        llm = MinimaxReasoningModelProvider().get_model()
    except Exception as e:
        print(f"⚠️ LLM 加载失败: {e!r}")
        return

    graph = create_design_review_graph(llm=llm)

    graph_input = {
        "messages": [HumanMessage(content="")],
        "node_errors": {},
        # 新契约：API 层已经把 local:// 解析为 prd_content / image_data_uris
        # 这里直接模拟 API 层产物
        "prd_raw_text": "# PRD\n\n 这是一份模拟 PRD 文档，用于测试设计审查流程。\n\n"
                        "## 颜色/主标题颜色\n值: #1b2338\n"
                        "## 字体/正文字体\n值: PingFang SC\n"
                        "## 间距/卡片圆角\n值: 12px\n"
                        "## 按钮/主要按钮\n值: 蓝色实心按钮\n"
                        "## 列表/列表项高度\n值: 48px\n"
                        "## 导航/底部 tab 高度\n值: 56px\n",
        "image_path": [
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNgAAIAAAUAAen63NgAAAAASUVORK5CYII="
        ],
    }

    print("=" * 70)
    print("追踪 stream() 每个事件，state current_node 变化")
    print("=" * 70)

    seen_nodes: list[str] = []
    for i, event in enumerate(graph.stream(graph_input, stream_mode="values")):
        if not isinstance(event, dict):
            continue
        current_node = event.get("current_node", "<none>")
        plan = event.get("plan", [])
        prd_done = event.get("prd_done", False)
        std_done = event.get("standard_done", False)
        proto_done = event.get("prototype_done", False)
        input_validated = event.get("input_validated", False)
        prd_analysis = event.get("prd_analysis") or {}
        proto_analysis = event.get("prototype_analysis") or {}
        std_rules = event.get("standard_rules") or {}

        if current_node and current_node not in seen_nodes:
            seen_nodes.append(current_node)
            print(f"\n[Step {i}] current_node={current_node!r}")
            print(f"  plan={plan}")
            print(f"  done_flags: prd={prd_done} std={std_done} proto={proto_done}")
            print(f"  input_validated={input_validated}")
            print(f"  prd_analysis.is_ready={prd_analysis.get('is_ready')} specs_count={len(prd_analysis.get('specs', {})) if isinstance(prd_analysis.get('specs'), dict) else 'n/a'}")
            print(f"  proto_analysis.is_ready={proto_analysis.get('is_ready')} specs_count={len(proto_analysis.get('specs', {})) if isinstance(proto_analysis.get('specs'), dict) else 'n/a'}")
            print(f"  std_rules.is_ready={std_rules.get('is_ready')} specs_count={len(std_rules.get('specs', {})) if isinstance(std_rules.get('specs'), dict) else 'n/a'}")

    print("\n" + "=" * 70)
    print(f"seen_nodes: {seen_nodes}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
