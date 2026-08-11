"""原型图分析测试脚本。

- 直接调用 analyze_prototype 工具：返回 dict（由 PrototypeAnalysis schema 约束）。
- 走完整 design_review_graph：prototype_analysis.analysis 即为该 dict。
- 漂亮打印 PrototypeAnalysis 的每个属性，便于人工核对。
"""
from __future__ import annotations

import json
import os
import sys
import typing
from typing import Any, Iterable

# Windows 终端：强制 stdout 为 UTF-8，避免 GBK 编码无法处理 Unicode 边框/箭头
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Windows 启用 ANSI 颜色（仅 cmd.exe 响应；PowerShell ModernHost 已天然支持 ANSI）
if sys.platform == "win32":
    try:
        os.system("color")
    except Exception:
        pass

from dotenv import load_dotenv
from langchain.messages import HumanMessage

load_dotenv()

from infrastructure import UploadService, DownloadService
from oss.base import OSSConfig, PublicURLRequest
from oss.di import OSSRegistry

from agent.graphs.design_review.schemas.prototype_schema import PrototypeAnalysis
from agent.graphs.design_review.tools.analyze_prototype.analyze_prototype import (
    analyze_prototype,
)
from agent.graphs.design_review.design_review_graph import create_design_review_graph
from llm_model.reasoning_model.minimax import MinimaxReasoningModelProvider


# ---------------------------------------------------------------------------
# 漂亮打印（与 analyze_prd 测试脚本风格保持一致）
# ---------------------------------------------------------------------------
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


_COLOR = (
    not os.environ.get("NO_COLOR")
    and sys.stdout.isatty()
)


def color(text: str, *codes: str) -> str:
    if not _COLOR or not codes:
        return text
    return "".join(codes) + text + C.RESET


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict, tuple, set)) and len(value) == 0:
        return True
    return False


def _scalar_repr(value: Any) -> str:
    if isinstance(value, bool):
        return color("True" if value else "False", C.GREEN)
    if isinstance(value, (int, float)):
        return color(repr(value), C.YELLOW)
    if isinstance(value, str):
        compact = value.replace("\n", " ⏎ ")
        if len(compact) > 200:
            compact = compact[:200] + "…"
        return color(f'"{compact}"', C.GREEN)
    return color(repr(value), C.MAGENTA)


def _format_type(annotation: Any) -> str:
    if annotation is None or annotation is type(None):
        return "None"
    if isinstance(annotation, str):
        return annotation
    origin = typing.get_origin(annotation)
    if origin is None:
        return getattr(annotation, "__name__", None) or str(annotation)
    if origin is typing.Union:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return f"Optional[{_format_type(args[0])}]"
        return "Union[" + ", ".join(_format_type(a) for a in args) + "]"
    origin_name = getattr(origin, "__name__", str(origin))
    args = typing.get_args(annotation)
    if not args:
        return origin_name
    return f"{origin_name}[" + ", ".join(_format_type(a) for a in args) + "]"


_TYPE_CACHE: dict[type, dict[str, str]] = {}


def _type_hints_of(model_cls: type) -> dict[str, str]:
    cache = _TYPE_CACHE.get(model_cls)
    if cache is not None:
        return cache
    try:
        cache = {
            k: _format_type(v) for k, v in typing.get_type_hints(model_cls).items()
        }
    except Exception:
        cache = {}
    _TYPE_CACHE[model_cls] = cache
    return cache


def _print_kv(key: str, value: Any, indent: int) -> None:
    pad = "  " * indent
    key_disp = color(key, C.CYAN, C.BOLD)
    type_disp = color(f"<{type(value).__name__}>", C.GRAY, C.DIM)
    if isinstance(value, dict):
        if not value:
            print(f"{pad}{key_disp} {type_disp} {{}}")
            return
        print(f"{pad}{key_disp} {type_disp} {{")
        for k, v in value.items():
            _print_kv(str(k), v, indent + 1)
        print(f"{pad}}}")
    elif isinstance(value, list):
        if not value:
            print(f"{pad}{key_disp} {type_disp} []")
            return
        print(f"{pad}{key_disp} {type_disp} [")
        for idx, item in enumerate(value, start=1):
            idx_disp = color(f"[{idx}]", C.MAGENTA, C.BOLD)
            t_disp = color(f"<{type(item).__name__}>", C.GRAY, C.DIM)
            if isinstance(item, dict):
                print(f"{pad}{idx_disp} {t_disp} {{")
                for k, v in item.items():
                    _print_kv(str(k), v, indent + 2)
                print(f"{pad + '  '}}}")
            else:
                print(f"{pad}{idx_disp} {t_disp} = {_scalar_repr(item)}")
        print(f"{pad}]")
    else:
        print(f"{pad}{key_disp} {type_disp} = {_scalar_repr(value)}")


def pretty_print_prototype_analysis(analysis: PrototypeAnalysis | dict) -> None:
    if isinstance(analysis, PrototypeAnalysis):
        model: PrototypeAnalysis = analysis
    elif isinstance(analysis, dict):
        model = PrototypeAnalysis.model_validate(analysis)
    else:
        print(color(f"✘ 无法渲染类型 {type(analysis).__name__}", C.RED, C.BOLD))
        return

    title = " PrototypeAnalysis "
    bar = "═" * (len(title) + 4)
    print()
    print(color(bar, C.BLUE, C.BOLD))
    print(color(f"║{title}║", C.BLUE, C.BOLD))
    print(color(bar, C.BLUE, C.BOLD))
    print(color(f"{'字段总数':<12} = {len(PrototypeAnalysis.model_fields)}", C.DIM))

    type_hints = _type_hints_of(PrototypeAnalysis)
    for name in PrototypeAnalysis.model_fields.keys():
        value = getattr(model, name)
        if _is_blank(value):
            key_disp = color(name, C.GRAY, C.DIM)
            type_disp = color(f"<{type_hints.get(name, '?')}>", C.GRAY, C.DIM)
            print(
                f"  {key_disp} {type_disp} = "
                f"{color('(empty)', C.GRAY, C.DIM)}"
            )
            continue
        _print_kv(name, value, indent=0)

    print(color(bar, C.BLUE, C.BOLD))
    print()


def dump_json(data: Any) -> None:
    print(color("── JSON 序列化预览 ──", C.YELLOW, C.BOLD))
    print(
        json.dumps(
            data if isinstance(data, (dict, list)) else data.model_dump(),
            ensure_ascii=False,
            indent=2,
        )
    )
    print()


# ---------------------------------------------------------------------------
# 直调 analyze_prototype 工具
# ---------------------------------------------------------------------------
def call_tool_directly(image_url: str) -> dict:
    print(color("▶ [A] 直接调用 analyze_prototype 工具 ...", C.CYAN, C.BOLD))
    raw = analyze_prototype.invoke({"image_urls": [image_url]})
    print(color("✔ 返回类型: ", C.GREEN, C.BOLD), type(raw).__name__)

    if not isinstance(raw, dict):
        print(color("✘ 工具未返回 dict，请检查 schema 约束。", C.RED, C.BOLD))
        return raw  # type: ignore[return-value]

    pretty_print_prototype_analysis(raw)
    dump_json(raw)
    return raw


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main() -> None:
    # OSS 上传原型图
    oss_config = OSSConfig(
        access_key_id=os.getenv("OSS_ACCESS_KEY_ID"),
        access_key_secret=os.getenv("OSS_ACCESS_KEY_SECRET"),
        endpoint=os.getenv("OSS_ENDPOINT"),
        bucket=os.getenv("OSS_BUCKET"),
        region=os.getenv("OSS_REGION"),
    )
    oss_register = OSSRegistry.get_instance()
    oss_client = oss_register.register_from_config(oss_config)
    upload_service = UploadService()

    params = {
        "file_path": "test_data\\工程看板原型图.png",
        "object_name": "测试/工程看板原型图.jpeg",
    }
    upload_result = upload_service.upload(**params)
    image_url = upload_service._oss.get_public_url(
        PublicURLRequest(object_name="测试/工程看板原型图.jpeg")
    )
    print(color(f"图床 URL: {image_url.url}", C.GRAY, C.DIM))
    print()

    # A：直接调工具
    call_tool_directly(image_url.url)

if __name__ == "__main__":
    main()
