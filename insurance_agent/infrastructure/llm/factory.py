"""LLM Factory

创建 LLM 实例。失败透传：若依赖缺失或配置错误，**抛错**，不兜底。
"""

from typing import Optional, Any
from dataclasses import dataclass
from enum import Enum


class LLMProvider(Enum):
    OPENAI = "openai"
    AZURE = "azure"
    DASHSCOPE = "dashscope"  # 阿里云百炼（kimi-k2.6 等）
    ANTHROPIC = "anthropic"
    CUSTOM = "custom"


@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: LLMProvider = LLMProvider.DASHSCOPE
    model_name: str = "kimi-k2.6"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 4000
    timeout: float = 60.0
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class LLMFactory:
    """LLM 工厂：管理 LLM 实例的注册和创建"""

    def __init__(self):
        self._llms: dict[str, Any] = {}
        self._configs: dict[str, LLMConfig] = {}

    def register(self, name: str, llm: Any, config: Optional[LLMConfig] = None) -> None:
        """注册 LLM 实例"""
        self._llms[name] = llm
        if config:
            self._configs[name] = config

    def get(self, name: str) -> Optional[Any]:
        """通过名称获取 LLM"""
        return self._llms.get(name)

    def create(self, config: LLMConfig) -> Any:
        """根据配置创建 LLM（依赖缺失立即抛错）"""
        if config.provider == LLMProvider.DASHSCOPE:
            return self._create_dashscope(config)
        elif config.provider == LLMProvider.OPENAI:
            return self._create_openai(config)
        elif config.provider == LLMProvider.AZURE:
            return self._create_azure(config)
        else:
            raise ValueError(f"Unsupported LLM provider: {config.provider}")

    def _create_dashscope(self, config: LLMConfig) -> Any:
        """创建 DashScope LLM（kimi-k2.6 等）
        失败透传：依赖缺失立即 ImportError，不兜底。
        """
        # 优先尝试 langchain_openai（兼容 OpenAI 协议）
        try:
            from langchain_openai import ChatOpenAI

            kwargs = {
                "model": config.model_name,
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
                "timeout": config.timeout,
            }
            if config.api_key:
                kwargs["api_key"] = config.api_key
            if config.base_url:
                kwargs["base_url"] = config.base_url
            else:
                # DashScope 兼容 OpenAI 协议
                kwargs.setdefault("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")

            return ChatOpenAI(**kwargs)
        except ImportError as e:
            raise ImportError(
                f"创建 DashScope LLM 需要 langchain_openai: {e}"
            ) from e

    def _create_openai(self, config: LLMConfig) -> Any:
        try:
            from langchain_openai import ChatOpenAI
            kwargs = {
                "model": config.model_name,
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
                "timeout": config.timeout,
            }
            if config.api_key:
                kwargs["api_key"] = config.api_key
            if config.base_url:
                kwargs["base_url"] = config.base_url
            return ChatOpenAI(**kwargs)
        except ImportError as e:
            raise ImportError(f"创建 OpenAI LLM 需要 langchain_openai: {e}") from e

    def _create_azure(self, config: LLMConfig) -> Any:
        try:
            from langchain_openai import AzureChatOpenAI
            kwargs = {
                "azure_deployment": config.model_name,
                "api_version": "2024-02-01",
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
            }
            if config.api_key:
                kwargs["api_key"] = config.api_key
            if config.base_url:
                kwargs["azure_endpoint"] = config.base_url
            return AzureChatOpenAI(**kwargs)
        except ImportError as e:
            raise ImportError(f"创建 Azure LLM 需要 langchain_openai: {e}") from e


_global_factory: Optional[LLMFactory] = None


def get_llm_factory() -> LLMFactory:
    """获取全局 LLM 工厂单例"""
    global _global_factory
    if _global_factory is None:
        _global_factory = LLMFactory()
    return _global_factory


def create_llm(config: LLMConfig) -> Any:
    """便捷函数：通过全局工厂创建 LLM"""
    return get_llm_factory().create(config)
