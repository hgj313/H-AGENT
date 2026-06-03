"""Agents Module

Implements the agents layer following the architecture document:
- Agents = business logic (业务能力封装在节点内部)
- Capability isolation (能力隔离)

Each capability domain has its own agent module.

Current capabilities:
- design_review: Design document and prototype review

Architecture pattern:
┌─────────────────────────────────────────┐
│              Graph Layer                │
│  (routers, state, orchestration)        │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│            Nodes Layer                   │
│     (control nodes for orchestration)   │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│          Agents/Capabilities             │
│  (business logic, tools, domain state)  │
└─────────────────────────────────────────┘
"""

from .design_review import (
    DesignReviewState,
    DesignReviewCapability,
    read_file_tool,
    analyze_prototype,
    analyze_prd,
    get_all_tools,
)


class CapabilityRegistry:
    """Registry for all agent capabilities
    
    Manages capability registration and retrieval.
    Following the capability pattern from architecture doc.
    """
    
    def __init__(self):
        self._capabilities: dict[str, object] = {}
        self._register_default_capabilities()
    
    def _register_default_capabilities(self):
        """Register default capabilities"""
        self.register("design_review", DesignReviewCapability())
    
    def register(self, name: str, capability: object):
        """Register a capability
        
        Args:
            name: Capability name
            capability: Capability instance
        """
        self._capabilities[name] = capability
    
    def get(self, name: str) -> object:
        """Get capability by name
        
        Args:
            name: Capability name
            
        Returns:
            Capability instance or None
        """
        return self._capabilities.get(name)
    
    def list_capabilities(self) -> list[str]:
        """List all registered capabilities
        
        Returns:
            List of capability names
        """
        return list(self._capabilities.keys())


capability_registry = CapabilityRegistry()


__all__ = [
    "DesignReviewState",
    "DesignReviewCapability",
    "read_file_tool",
    "analyze_prototype",
    "analyze_prd",
    "get_all_tools",
    "CapabilityRegistry",
    "capability_registry",
]