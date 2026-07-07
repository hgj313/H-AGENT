"""LLM Factory

创建 LLM 实例。失败透传：若依赖缺失或配置错误，**抛错**，不兜底。

支持 Provider:
- DASHSCOPE: 阿里云百炼（kimi-k2.6 等），OpenAI 兼容协议
- MINIMAX: MiniMax 多模态模型（MiniMax-M3），Anthropic 兼容协议
- OPENAI: OpenAI 原生
- ANTHROPIC: Anthropic 原生
- AZURE: Azure OpenAI
"""

from typing import Optional, Any
from dataclasses import dataclass
from enum import Enum


class LLMProvider(Enum):
    OPENAI = "openai"
    AZURE = "azure"
    DASHSCOPE = "dashscope"  # 阿里云百炼（kimi-k2.6 等）
    MINIMAX = "minimax"       # MiniMax 多模态（MiniMax-M3）
    ANTHROPIC = "anthropic"
    CUSTOM = "custom"


@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: LLMProvider = LLMProvider.MINIMAX
    model_name: str = "MiniMax-M3"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    # MiniMax 支持 openai / anthropic 两种协议
    protocol: str = "anthropic"  # minimax 用 anthropic 协议
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
        if config.provider == LLMProvider.MINIMAX:
            return self._create_minimax(config)
        elif config.provider == LLMProvider.DASHSCOPE:
            return self._create_dashscope(config)
        elif config.provider == LLMProvider.OPENAI:
            return self._create_openai(config)
        elif config.provider == LLMProvider.AZURE:
            return self._create_azure(config)
        else:
            raise ValueError(f"Unsupported LLM provider: {config.provider}")

    def _create_minimax(self, config: LLMConfig) -> Any:
        """创建 MiniMax LLM（MiniMax-M3 多模态）

        使用 langchain.chat_models.init_chat_model 统一创建，
        支持 anthropic / openai 两种协议。

        失败透传：依赖缺失立即 ImportError，不兜底。
        """
        try:
            from langchain.chat_models import init_chat_model
        except ImportError as e:
            raise ImportError(
                f"创建 MiniMax LLM 需要 langchain: {e}"
            ) from e

        # 选择协议对应的 base_url
        if config.protocol == "openai":
            base_url = config.base_url or "https://api.minimaxi.com/v1"
            provider = "openai"
        else:
            base_url = config.base_url or "https://api.minimaxi.com/anthropic"
            provider = "anthropic"

        if not config.api_key:
            raise ValueError("MiniMax LLM 创建失败：api_key 未配置")

        model = init_chat_model(
            model=config.model_name,
            model_provider=provider,
            api_key=config.api_key,
            base_url=base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.timeout,
        )
        return model

    def _create_dashscope(self, config: LLMConfig) -> Any:
        """创建 DashScope LLM（kimi-k2.6 等）
        失败透传：依赖缺失立即 ImportError，不兜底。
        """
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


def create_minimax_llm_from_env() -> Any:
    """从环境变量创建 MiniMax LLM（便捷函数）

    读取 MINIMAX_API_KEY, MINIMAX_BASE_URL_ANTHROPIC 等环境变量。
    需要先 load_dotenv() 加载 .env 文件。
    """
    import os
    api_key = os.getenv("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError("MINIMAX_API_KEY 未配置，请检查 .env 文件")

    protocol = "anthropic"
    base_url = os.getenv("MINIMAX_BASE_URL_ANTHROPIC") or os.getenv("MINIMAX_BASE_URL_OPENAI")
    if not base_url:
        base_url = "https://api.minimaxi.com/anthropic"
    elif "anthropic" in base_url:
        protocol = "anthropic"
    else:
        protocol = "openai"

    config = LLMConfig(
        provider=LLMProvider.MINIMAX,
        model_name="MiniMax-M3",
        api_key=api_key,
        base_url=base_url,
        protocol=protocol,
    )
    return create_llm(config)
