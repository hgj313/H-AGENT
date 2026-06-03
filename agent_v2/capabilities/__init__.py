"""Capabilities Module

Implements the capability layer following the architecture document:
- Capability = tool set for specific domain
- Capability Resolver = resolves capabilities to tools

This layer enables the "按能力域动态绑定" (dynamic binding by capability domain) pattern.

Current capabilities:
- design_review: Design document and prototype review

Adding new capabilities:
1. Create capability module under agents/
2. Register in CapabilityRegistry
3. Define tools and nodes for the capability
"""

from typing import Optional, Callable, Any
from dataclasses import dataclass

from ..registry.capability_registry import CapabilityRegistry, get_global_capability_registry
from ..registry.tool_registry import ToolRegistry, get_global_registry


@dataclass
class Capability:
    """Base capability class
    
    All capabilities should inherit from this class.
    """
    name: str
    tools: list[Any]
    nodes: dict[str, Callable]
    
    def get_tools(self) -> list[Any]:
        """Get capability tools"""
        return self.tools
    
    def get_nodes(self) -> dict[str, Callable]:
        """Get capability nodes"""
        return self.nodes


class CapabilityResolver:
    """Resolves user requests to capabilities and tools
    
    This is the core component for implementing the dynamic binding pattern:
    
    User Request
        │
        ▼
    Intent Detection
        │
        ▼
    Capability Resolver  ← This class
        │
        ▼
    Get tools for capability
        │
        ▼
    LLM bind_tools(tools)
        │
        ▼
    Execute
    """
    
    def __init__(self, capability_registry: Optional[CapabilityRegistry] = None):
        """Initialize resolver
        
        Args:
            capability_registry: Optional capability registry
        """
        self.capability_registry = capability_registry or get_global_capability_registry()
        self.tool_registry = get_global_registry()
    
    def resolve(self, capability_name: str) -> list[Any]:
        """Resolve capability to tools
        
        Args:
            capability_name: Name of capability
            
        Returns:
            List of tools for this capability
        """
        tool_names = self.capability_registry.get_tools(capability_name)
        
        if not tool_names:
            return []
        
        tools = self.tool_registry.get_tools(names=tool_names)
        return tools
    
    def resolve_from_request(self, user_goal: str) -> tuple[str, list[Any]]:
        """Resolve user request to capability and tools
        
        Args:
            user_goal: User's goal/question
            
        Returns:
            Tuple of (capability_name, tools)
        """
        capability = self._detect_capability(user_goal)
        tools = self.resolve(capability)
        
        return capability, tools
    
    def _detect_capability(self, text: str) -> str:
        """Detect capability from text
        
        Args:
            text: User input
            
        Returns:
            Detected capability name
        """
        text_lower = text.lower()
        
        capability_keywords = {
            "design_review": ["review", "design", "prototype", "prd", "specification"],
            "coding": ["code", "implement", "function", "debug"],
            "research": ["search", "find", "research", "information"],
            "writing": ["write", "create", "draft", "document"],
            "analytics": ["analyze", "chart", "graph", "data"],
        }
        
        for capability, keywords in capability_keywords.items():
            if any(k in text_lower for k in keywords):
                return capability
        
        return "general"
    
    def bind_to_llm(self, llm, capability_name: str) -> Any:
        """Bind capability tools to LLM
        
        Args:
            llm: LLM instance
            capability_name: Capability name
            
        Returns:
            LLM with bound tools
        """
        tools = self.resolve(capability_name)
        return llm.bind_tools(tools)


_capability_resolver = None


def get_capability_resolver() -> CapabilityResolver:
    """Get global capability resolver instance
    
    Returns:
        CapabilityResolver instance
    """
    global _capability_resolver
    if _capability_resolver is None:
        _capability_resolver = CapabilityResolver()
    return _capability_resolver


__all__ = [
    "Capability",
    "CapabilityResolver",
    "get_capability_resolver",
]