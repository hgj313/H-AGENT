"""
设计审查图测试脚本。

运行: python -m agent.graphs.design_review.tests.test_graph
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

# Windows 终端：强制 stdout 为 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Windows 启用 ANSI 颜色
if sys.platform == "win32":
    try:
        os.system("color")
    except Exception:
        pass

from langchain.messages import HumanMessage
from agent.graphs.design_review.design_review_graph import create_design_review_graph
from llm_model.reasoning_model.minimax import MinimaxReasoningModelProvider


# ── 颜色常量 ─────────────────────────────────────────────────────────
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    GRAY = "\033[90m"
    RED = "\033[91m"


_COLOR = not os.environ.get("NO_COLOR") and sys.stdout.isatty()


def color(text: str, *codes: str) -> str:
    if not _COLOR or not codes:
        return text
    return "".join(codes) + text + C.RESET


def _print_header(title: str) -> None:
    bar = "═" * (len(title) + 4)
    print()
    print(color(bar, C.BLUE, C.BOLD))
    print(color(f"║ {title} ║", C.BLUE, C.BOLD))
    print(color(bar, C.BLUE, C.BOLD))


def _print_section(title: str) -> None:
    print()
    print(color(f"── {title} ──", C.CYAN, C.BOLD))


def _print_kv(key: str, value: Any, indent: int = 0) -> None:
    pad = "  " * indent
    key_disp = color(key, C.CYAN, C.BOLD)
    if isinstance(value, dict):
        if not value:
            print(f"{pad}{key_disp} = {{}}")
            return
        print(f"{pad}{key_disp} = {{")
        for k, v in value.items():
            _print_kv(str(k), v, indent + 1)
        print(f"{pad}}}")
    elif isinstance(value, list):
        if not value:
            print(f"{pad}{key_disp} = []")
            return
        print(f"{pad}{key_disp} = [")
        for idx, item in enumerate(value, start=1):
            idx_disp = color(f"[{idx}]", C.MAGENTA, C.BOLD)
            if isinstance(item, dict):
                print(f"{pad}  {idx_disp} {{")
                for k, v in item.items():
                    _print_kv(str(k), v, indent + 2)
                print(f"{pad}  }}")
            else:
                print(f"{pad}  {idx_disp} = {color(repr(item), C.GREEN)}")
        print(f"{pad}]")
    elif isinstance(value, bool):
        print(f"{pad}{key_disp} = {color(str(value), C.YELLOW)}")
    elif isinstance(value, (int, float)):
        print(f"{pad}{key_disp} = {color(repr(value), C.YELLOW)}")
    elif isinstance(value, str):
        compact = value.replace("\n", " ⏎ ")
        if len(compact) > 150:
            compact = compact[:150] + "…"
        print(f"{pad}{key_disp} = {color(compact, C.GREEN)}")
    else:
        print(f"{pad}{key_disp} = {color(repr(value), C.MAGENTA)}")


def pretty_print_state(state: dict) -> None:
    """漂亮打印最终状态。"""
    _print_header("设计审查结果")

    # 基本信息
    _print_section("流程状态")
    _print_kv("current_node", state.get("current_node", ""))
    _print_kv("prd_done", state.get("prd_done", False))
    _print_kv("prototype_done", state.get("prototype_done", False))
    _print_kv("standard_done", state.get("standard_done", False))
    _print_kv("report_done", state.get("report_done", False))
    _print_kv("llm_calls", state.get("llm_calls", 0))

    # 错误信息
    node_errors = state.get("node_errors") or {}
    if node_errors:
        _print_section("节点错误")
        for node, err in node_errors.items():
            print(f"  {color(node, C.RED, C.BOLD)}: {color(err, C.RED)}")

    # 原型分析
    prototype = state.get("prototype_analysis") or {}
    if prototype.get("is_ready"):
        _print_section("原型分析")
        analysis = prototype.get("analysis") or {}
        if isinstance(analysis, dict):
            specs = analysis.get("specs") or {}
            if specs:
                print(color("  规格值:", C.YELLOW))
                for k, v in list(specs.items())[:10]:
                    if isinstance(v, dict):
                        val = v.get("value", "")
                        print(f"    {color(k, C.CYAN)}: {color(val, C.GREEN)}")
                    else:
                        print(f"    {color(k, C.CYAN)}: {color(str(v), C.GREEN)}")
                if len(specs) > 10:
                    print(color(f"  ... 共 {len(specs)} 项", C.DIM))

            compliance = analysis.get("compliance_summary") or {}
            if compliance:
                print(color("  符合性总览:", C.YELLOW))
                _print_kv("total", compliance.get("total", ""), indent=2)
                _print_kv("compliant", compliance.get("compliant", ""), indent=2)
                _print_kv("non_compliant", compliance.get("non_compliant", ""), indent=2)
                _print_kv("overall", compliance.get("overall", ""), indent=2)

    # PRD 分析
    prd = state.get("prd_analysis") or {}
    if prd.get("is_ready"):
        _print_section("PRD 分析")
        specs = prd.get("specs") or {}
        if specs:
            print(color("  规格值:", C.YELLOW))
            for k, v in list(specs.items())[:10]:
                if isinstance(v, dict):
                    val = v.get("value", "")
                    print(f"    {color(k, C.CYAN)}: {color(val, C.GREEN)}")
                else:
                    print(f"    {color(k, C.CYAN)}: {color(str(v), C.GREEN)}")
            if len(specs) > 10:
                print(color(f"  ... 共 {len(specs)} 项", C.DIM))

    # 生成报告
    report = state.get("analysis_result")
    if report:
        _print_section("生成报告")
        if isinstance(report, list):
            for idx, item in enumerate(report, start=1):
                print(color(f"\n  报告 [{idx}]:", C.MAGENTA, C.BOLD))
                if isinstance(item, dict):
                    for k, v in item.items():
                        _print_kv(k, v, indent=2)
                else:
                    print(f"    {color(repr(item), C.GREEN)}")
        elif isinstance(report, dict):
            for k, v in report.items():
                _print_kv(k, v, indent=1)
        else:
            print(f"  {color(repr(report), C.GREEN)}")

    # JSON 预览
    _print_section("JSON 预览")
    try:
        json_str = json.dumps(state, indent=2, ensure_ascii=False, default=str)
        # 只显示前 2000 字符
        if len(json_str) > 2000:
            print(json_str[:2000])
            print(color(f"\n... (截断，共 {len(json_str)} 字符)", C.DIM))
        else:
            print(json_str)
    except Exception as e:
        print(color(f"  JSON 序列化失败: {e}", C.RED))

    print()


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
    final_state = event

if final_state:
    pretty_print_state(final_state)
else:
    print(color("✘ 未获取到最终状态", C.RED, C.BOLD))
