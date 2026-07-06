"""
设计审查图测试脚本。

运行: python -m agent.graphs.design_review.tests.test_graph2
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from langchain.messages import HumanMessage
from agent.graphs.design_review.design_review_graph import create_design_review_graph
from llm_model.reasoning_model.minimax import MinimaxReasoningModelProvider

# Windows 终端：强制 stdout 为 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ── 主测试 ───────────────────────────────────────────────────────────
model_minimax = MinimaxReasoningModelProvider().get_model()
graph = create_design_review_graph(model_minimax)

events = graph.stream(
    {
        "messages": [
            HumanMessage(
                content="原型图地址：https://dr-2.oss-cn-beijing.aliyuncs.com/%E6%B5%8B%E8%AF%95/%E5%B7%A5%E7%A8%8B%E7%9C%8B%E6%9D%BF%E5%8E%9F%E5%9E%8B%E5%9B%BE.jpeg ，prd文档地址：test_data\吉盛园林里程碑看板需求文档.md"
            ),
        ],
        "node_errors": {},
        "image_path": ["https://dr-2.oss-cn-beijing.aliyuncs.com/%E6%B5%8B%E8%AF%95/%E5%B7%A5%E7%A8%8B%E7%9C%8B%E6%9D%BF%E5%8E%9F%E5%9E%8B%E5%9B%BE.jpeg"],
        "prd_file_path": r"test_data\吉盛园林里程碑看板需求文档.md",
    },
    stream_mode="values",
)

final_state = None
for event in events:
    print(event)
    print("="*50)
    print("\n")
