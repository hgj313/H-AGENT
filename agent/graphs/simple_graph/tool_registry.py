from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agent.tools.simple_math import add, multiply, subtract


ToolCallable = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    name: str
    description: str
    callable: ToolCallable

    def invoke(self, **kwargs: Any) -> Any:
        tool = self.callable
        if hasattr(tool, "invoke"):
            return tool.invoke(kwargs)
        return tool(**kwargs)


TOOL_REGISTRY: dict[str, RegisteredTool] = {
    "add": RegisteredTool(name="add", description="Add two integers.", callable=add),
    "subtract": RegisteredTool(name="subtract", description="Subtract two integers.", callable=subtract),
    "multiply": RegisteredTool(name="multiply", description="Multiply two integers.", callable=multiply),
}


def get_tool(tool_name: str) -> RegisteredTool:
    try:
        return TOOL_REGISTRY[tool_name]
    except KeyError as exc:
        raise ValueError(f"未注册的工具: {tool_name}") from exc
