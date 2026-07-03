"""Base Extractor - 所有提取器的基类

DI 原则：提取器不应直接调用 LLM，所有外部依赖通过构造器注入。
"""

from typing import Protocol, Optional
from insurance_agent.domain import InsuredPerson


class BaseExtractor(Protocol):
    """提取器接口"""

    def extract(
        self,
        text: str,
        policy_holder: str = "",
        insurance_company: str = ""
    ) -> list[InsuredPerson]:
        """从文本中提取被保人员"""
        ...
