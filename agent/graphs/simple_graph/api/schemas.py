from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    user_id: str = Field(min_length=1)
    a: int
    b: int
    multiplier: int
    goal: str = Field(default="请总结本次图执行结果")


class InterruptRequest(BaseModel):
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
