"""PRD 分析工具测试脚本：调用 analyze_prd 并按 PRDAnalysis 各个属性漂亮打印。"""
from __future__ import annotations

import json
import os
import sys
import typing
from typing import Any, Iterable

if sys.platform == "win32":
    os.system("color")

from pydantic import BaseModel

from agent.graphs.design_review.schemas.prd_schema import PRDAnalysis
from agent.graphs.design_review.tools.analyze_prd.analyze_prd import analyze_prd


# ----------------------------- ANSI 颜色 -----------------------------
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


def _enable_color() -> bool:
    """简单判断是否启用颜色（TTY + 关闭 NO_COLOR）。"""
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


_COLOR = _enable_color()


def color(text: str, *codes: str) -> str:
    if not _COLOR or not codes:
        return text
    return "".join(codes) + text + C.RESET


# ----------------------------- 漂亮打印 -----------------------------
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
        # 转义 \n 以便单行显示
        compact = value.replace("\n", " ⏎ ")
        if len(compact) > 200:
            compact = compact[:200] + "…"
        return color(f'"{compact}"', C.GREEN)
    return color(repr(value), C.MAGENTA)


def _print_kv(key: str, value: Any, indent: int, level: int) -> None:
    pad = "  " * indent
    key_disp = color(f"{key}", C.CYAN, C.BOLD)
    type_disp = color(f"<{type(value).__name__}>", C.GRAY, C.DIM)
    if isinstance(value, BaseModel):
        print(f"{pad}{key_disp} {type_disp} {{")
        _print_model(value, indent + 1, level + 1)
        print(f"{pad}}}")
    elif isinstance(value, list):
        if not value:
            print(f"{pad}{key_disp} {type_disp} []")
            return
        print(f"{pad}{key_disp} {type_disp} [")
        _print_list(value, indent + 1, level + 1)
        print(f"{pad}]")
    elif isinstance(value, dict):
        if not value:
            print(f"{pad}{key_disp} {type_disp} {{}}")
            return
        print(f"{pad}{key_disp} {type_disp} {{")
        _print_dict(value, indent + 1, level + 1)
        print(f"{pad}}}")
    else:
        print(f"{pad}{key_disp} {type_disp} = {_scalar_repr(value)}")


def _print_list(items: Iterable[Any], indent: int, level: int) -> None:
    pad = "  " * indent
    for idx, item in enumerate(items, start=1):
        idx_disp = color(f"[{idx}]", C.MAGENTA, C.BOLD)
        type_disp = color(f"<{type(item).__name__}>", C.GRAY, C.DIM)
        if isinstance(item, BaseModel):
            print(f"{pad}{idx_disp} {type_disp} {{")
            _print_model(item, indent + 1, level + 1)
            print(f"{pad}}}")
        elif isinstance(item, dict):
            print(f"{pad}{idx_disp} {type_disp} {{")
            _print_dict(item, indent + 1, level + 1)
            print(f"{pad}}}")
        elif isinstance(item, list):
            print(f"{pad}{idx_disp} {type_disp} [")
            _print_list(item, indent + 1, level + 1)
            print(f"{pad}]")
        else:
            print(f"{pad}{idx_disp} {type_disp} = {_scalar_repr(item)}")


def _print_dict(d: dict[str, Any], indent: int, level: int) -> None:
    for k, v in d.items():
        _print_kv(str(k), v, indent, level)


def _format_type(annotation: Any) -> str:
    """把 typing 注解转成可读短名，如 List[str] / Optional[str] / DocMeta。"""
    if annotation is None or annotation is type(None):
        return "None"
    if isinstance(annotation, str):
        return annotation
    # typing.Generic / typing.Union / typing.Optional 兼容
    origin = typing.get_origin(annotation)
    if origin is None:
        # 普通类或 typing 的具体形态
        name = getattr(annotation, "__name__", None) or str(annotation)
        return name
    if origin is typing.Union:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return f"Optional[{_format_type(args[0])}]"
        return "Union[" + ", ".join(_format_type(a) for a in args) + "]"
    # 其它 Generic：List/Dict/Tuple...
    origin_name = getattr(origin, "__name__", str(origin))
    args = typing.get_args(annotation)
    if not args:
        return origin_name
    return f"{origin_name}[" + ", ".join(_format_type(a) for a in args) + "]"


_TYPE_CACHE: dict[type, dict[str, str]] = {}


def _field_type_name(model_cls: type, field_name: str) -> str:
    cache = _TYPE_CACHE.get(model_cls)
    if cache is None:
        try:
            cache = {
                k: _format_type(v)
                for k, v in typing.get_type_hints(model_cls).items()
            }
        except Exception:
            cache = {}
        _TYPE_CACHE[model_cls] = cache
    return cache.get(field_name, getattr(model_cls.model_fields[field_name].annotation, "__name__", str(model_cls.model_fields[field_name].annotation)))


def _print_model(model: BaseModel, indent: int, level: int = 0) -> None:
    """按模型字段声明顺序遍历，保证输出稳定。"""
    fields = model.__class__.model_fields
    type_hints = _TYPE_CACHE.get(model.__class__)
    if type_hints is None:
        try:
            type_hints = {
                k: _format_type(v)
                for k, v in typing.get_type_hints(model.__class__).items()
            }
        except Exception:
            type_hints = {}
        _TYPE_CACHE[model.__class__] = type_hints
    for name in fields.keys():
        value = getattr(model, name)
        # 空值用 DIM 灰显，便于扫读
        if _is_blank(value):
            key_disp = color(name, C.GRAY, C.DIM)
            type_disp = color(f"<{type_hints.get(name, '?')}>", C.GRAY, C.DIM)
            print(
                f"{'  ' * indent}{key_disp} {type_disp} = "
                f"{color('(empty)', C.GRAY, C.DIM)}"
            )
            continue
        _print_kv(name, value, indent, level)


def pretty_print_prd_analysis(analysis: PRDAnalysis) -> None:
    title = " PRDAnalysis "
    bar = "═" * (len(title) + 4)
    print()
    print(color(bar, C.BLUE, C.BOLD))
    print(color(f"║{title}║", C.BLUE, C.BOLD))
    print(color(bar, C.BLUE, C.BOLD))
    print(color(f"{'字段总数':<12} = {len(PRDAnalysis.model_fields)}", C.DIM))
    _print_model(analysis, indent=0)
    print(color(bar, C.BLUE, C.BOLD))
    print()


def dump_json(analysis: PRDAnalysis) -> None:
    print(color("── JSON 序列化预览 ──", C.YELLOW, C.BOLD))
    print(
        json.dumps(
            analysis.model_dump(),
            ensure_ascii=False,
            indent=2,
        )
    )
    print()


# ----------------------------- 入口 -----------------------------
def main() -> None:
    print(color("▶ 调用 analyze_prd 工具 ...", C.CYAN, C.BOLD))
    raw = analyze_prd.invoke(
        input={
            "prd_content": " 这是一个测试PRD文档",
            "file_path": "test_data\\吉盛园林里程碑看板需求文档.md",
        }
    )
    print(color("✔ 工具返回类型: ", C.GREEN, C.BOLD), type(raw).__name__)

    if not isinstance(raw, dict):
        print(color("✘ 工具未返回 dict，请检查 schema 约束。", C.RED, C.BOLD))
        print(raw)
        return

    analysis = PRDAnalysis.model_validate(raw)
    pretty_print_prd_analysis(analysis)
    dump_json(analysis)


if __name__ == "__main__":
    main()
