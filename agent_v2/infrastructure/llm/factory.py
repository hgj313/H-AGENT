"""LLM Factory Module

Provides LLM initialization and configuration.
Following the architecture: LLM工厂 for model management
"""

from typing import Optional, Any
from dataclasses import dataclass
from enum import Enum


class LLMProvider(Enum):
    """LLM provider types"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    GOOGLE = "google"
    LOCAL = "local"
    CUSTOM = "custom"


@dataclass
class LLMConfig:
    """Configuration for LLM"""
    provider: LLMProvider = LLMProvider.OPENAI
    model_name: str = "gpt-4"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2000
    timeout: float = 60.0
    metadata: dict = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class LLMFactory:
    """Factory for creating and managing LLM instances
    
    Following the architecture: LLM工厂
    
    Usage:
        factory = LLMFactory()
        
        # Create LLM from config
        llm = factory.create(config=LLMConfig(
            provider=LLMProvider.OPENAI,
            model_name="gpt-4"
        ))
        
        # Get model for capability
        model = factory.get_model("design_review")
    """
    
    def __init__(self):
        self._llms: dict[str, Any] = {}
        self._configs: dict[str, LLMConfig] = {}
    
    def register(
        self,
        name: str,
        llm: Any,
        config: Optional[LLMConfig] = None
    ) -> None:
        """Register an LLM instance
        
        Args:
            name: LLM name/identifier
            llm: LLM instance
            config: Optional configuration
        """
        self._llms[name] = llm
        if config:
            self._configs[name] = config
    
    def get(self, name: str) -> Optional[Any]:
        """Get LLM by name
        
        Args:
            name: LLM name
            
        Returns:
            LLM instance or None
        """
        return self._llms.get(name)
    
    def create(self, config: LLMConfig) -> Any:
        """Create LLM from configuration
        
        Args:
            config: LLM configuration
            
        Returns:
            LLM instance
        """
        if config.provider == LLMProvider.OPENAI:
            return self._create_openai(config)
        elif config.provider == LLMProvider.ANTHROPIC:
            return self._create_anthropic(config)
        elif config.provider == LLMProvider.AZURE:
            return self._create_azure(config)
        elif config.provider == LLMProvider.GOOGLE:
            return self._create_google(config)
        else:
            raise ValueError(f"Unsupported provider: {config.provider}")
    
    def _create_openai(self, config: LLMConfig) -> Any:
        """Create OpenAI LLM"""
        try:
            from langchain_openai import ChatOpenAI
            
            kwargs = {
                "model": config.model_name,
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
            }
            
            if config.api_key:
                kwargs["api_key"] = config.api_key
            
            if config.base_url:
                kwargs["base_url"] = config.base_url
            
            return ChatOpenAI(**kwargs)
        except ImportError:
            return self._create_custom(config)
    
    def _create_anthropic(self, config: LLMConfig) -> Any:
        """Create Anthropic LLM"""
        try:
            from langchain_anthropic import ChatAnthropic
            
            kwargs = {
                "model": config.model_name,
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
            }
            
            if config.api_key:
                kwargs["anthropic_api_key"] = config.api_key
            
            return ChatAnthropic(**kwargs)
        except ImportError:
            return self._create_custom(config)
    
    def _create_azure(self, config: LLMConfig) -> Any:
        """Create Azure OpenAI LLM"""
        try:
            from langchain_openai import AzureChatOpenAI
            
            kwargs = {
                "azure_deployment": config.model_name,
                "api_version": "2024-02-01",
            }
            
            if config.api_key:
                kwargs["api_key"] = config.api_key
            
            if config.base_url:
                kwargs["azure_endpoint"] = config.base_url
            
            return AzureChatOpenAI(**kwargs)
        except ImportError:
            return self._create_custom(config)
    
    def _create_google(self, config: LLMConfig) -> Any:
        """Create Google LLM"""
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            
            kwargs = {
                "model": config.model_name,
                "temperature": config.temperature,
            }
            
            if config.api_key:
                kwargs["google_api_key"] = config.api_key
            
            return ChatGoogleGenerativeAI(**kwargs)
        except ImportError:
            return self._create_custom(config)
    
    def _create_custom(self, config: LLMConfig) -> Any:
        """Create custom LLM placeholder"""
        return None
    
    def list_llms(self) -> list[str]:
        """List all registered LLM names
        
        Returns:
            List of LLM names
        """
        return list(self._llms.keys())


_global_factory = None


def get_llm_factory() -> LLMFactory:
    """Get global LLM factory instance
    
    Returns:
        LLMFactory instance
    """
    global _global_factory
    if _global_factory is None:
        _global_factory = LLMFactory()
    return _global_factory


def create_llm(config: LLMConfig) -> Any:
    """Convenience function to create LLM
    
    Args:
        config: LLM configuration
        
    Returns:
        LLM instance
    """
    factory = get_llm_factory()
    return factory.create(config)