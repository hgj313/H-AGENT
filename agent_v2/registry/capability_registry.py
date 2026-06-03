"""Capability Registry Module

Manages capability registration and tool mapping.
Following the architecture: Capability Resolver for dynamic binding

This is the key component for implementing "按能力域动态绑定" (dynamic binding by capability domain).
"""

from typing import Optional, Callable, Any
from dataclasses import dataclass, field
import threading


@dataclass
class CapabilityConfig:
    """Configuration for a capability"""
    name: str
    tools: list[str] = field(default_factory=list)
    agent_nodes: list[str] = field(default_factory=list)
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class CapabilityRegistry:
    """Registry for managing capabilities and their tools
    
    This is the core component for implementing the capability-based
    tool binding pattern from the architecture document.
    
    Architecture:
    ┌─────────────────┐
    │  Tool Registry  │
    └────────┬────────┘
             │
             ▼
    ┌─────────────────────┐
    │  Capability Registry │  ← This module
    └────────┬────────────┘
             │
             ▼
    ┌─────────────────┐
    │  LLM Node       │
    │  (bind_tools)   │
    └─────────────────┘
    
    Usage:
        registry = CapabilityRegistry()
        registry.register_capability("research", tools=["web_search", "rag_search"])
        
        # Get tools for capability
        research_tools = registry.get_tools("research")
        
        # Bind to LLM
        llm.bind_tools(research_tools)
    """
    
    def __init__(self):
        self._capabilities: dict[str, CapabilityConfig] = {}
        self._tool_capability_map: dict[str, list[str]] = {}
        self._lock = threading.RLock()
        self._init_default_capabilities()
    
    def _init_default_capabilities(self):
        """Initialize default capabilities"""
        self._capabilities = {
            "coding": CapabilityConfig(
                name="coding",
                tools=["repo_search", "python_exec", "github_tool"],
                agent_nodes=["coding_agent"],
            ),
            "research": CapabilityConfig(
                name="research",
                tools=["web_search", "rag_search", "knowledge_base_search"],
                agent_nodes=["research_agent"],
            ),
            "writing": CapabilityConfig(
                name="writing",
                tools=["document_write", "content_generate"],
                agent_nodes=["writing_agent"],
            ),
            "design_review": CapabilityConfig(
                name="design_review",
                tools=["read_file", "analyze_prototype", "analyze_prd"],
                agent_nodes=["design_review_agent"],
            ),
            "analytics": CapabilityConfig(
                name="analytics",
                tools=["sql_query", "chart_generate", "data_visualize"],
                agent_nodes=["analytics_agent"],
            ),
        }
    
    def register_capability(
        self,
        name: str,
        tools: Optional[list[str]] = None,
        agent_nodes: Optional[list[str]] = None,
        **metadata
    ) -> CapabilityConfig:
        """Register a capability
        
        Args:
            name: Capability name
            tools: List of tool names
            agent_nodes: List of agent node names
            **metadata: Additional metadata
            
        Returns:
            CapabilityConfig
        """
        with self._lock:
            config = CapabilityConfig(
                name=name,
                tools=tools or [],
                agent_nodes=agent_nodes or [],
                metadata=metadata
            )
            self._capabilities[name] = config
            
            for tool in (tools or []):
                if tool not in self._tool_capability_map:
                    self._tool_capability_map[tool] = []
                self._tool_capability_map[tool].append(name)
            
            return config
    
    def get_capability(self, name: str) -> Optional[CapabilityConfig]:
        """Get capability configuration
        
        Args:
            name: Capability name
            
        Returns:
            CapabilityConfig or None
        """
        with self._lock:
            return self._capabilities.get(name)
    
    def get_tools(self, capability: str) -> list[str]:
        """Get tools for a capability
        
        Args:
            capability: Capability name
            
        Returns:
            List of tool names
        """
        with self._lock:
            config = self._capabilities.get(capability)
            return config.tools if config else []
    
    def get_capabilities_for_tool(self, tool_name: str) -> list[str]:
        """Get capabilities that include a tool
        
        Args:
            tool_name: Tool name
            
        Returns:
            List of capability names
        """
        with self._lock:
            return self._tool_capability_map.get(tool_name, [])
    
    def list_capabilities(self) -> list[str]:
        """List all registered capabilities
        
        Returns:
            List of capability names
        """
        with self._lock:
            return list(self._capabilities.keys())
    
    def enable_capability(self, name: str) -> bool:
        """Enable a capability
        
        Args:
            name: Capability name
            
        Returns:
            True if enabled
        """
        with self._lock:
            if name in self._capabilities:
                self._capabilities[name].enabled = True
                return True
            return False
    
    def disable_capability(self, name: str) -> bool:
        """Disable a capability
        
        Args:
            name: Capability name
            
        Returns:
            True if disabled
        """
        with self._lock:
            if name in self._capabilities:
                self._capabilities[name].enabled = False
                return True
            return False
    
    def is_capability_enabled(self, name: str) -> bool:
        """Check if capability is enabled
        
        Args:
            name: Capability name
            
        Returns:
            True if enabled
        """
        with self._lock:
            config = self._capabilities.get(name)
            return config.enabled if config else False
    
    def resolve_capabilities(
        self,
        capability_names: list[str]
    ) -> list[str]:
        """Resolve capabilities to tool names
        
        Args:
            capability_names: List of capability names
            
        Returns:
            List of tool names
        """
        with self._lock:
            tools = []
            for name in capability_names:
                config = self._capabilities.get(name)
                if config and config.enabled:
                    tools.extend(config.tools)
            return list(set(tools))


_global_capability_registry = CapabilityRegistry()


def get_global_capability_registry() -> CapabilityRegistry:
    """Get global capability registry instance
    
    Returns:
        Global CapabilityRegistry instance
    """
    return _global_capability_registry


def register_capability(name: str, tools: list[str], **kwargs) -> CapabilityConfig:
    """Convenience function to register capability to global registry"""
    return _global_capability_registry.register_capability(name, tools, **kwargs)


def get_capability_tools(capability: str) -> list[str]:
    """Convenience function to get tools for capability"""
    return _global_capability_registry.get_tools(capability)