"""Tool Enums

Permission levels and tool-related enumerations.
Following the architecture: Permission-based access control
"""

from enum import Enum


class PermissionLevel(Enum):
    """Tool permission levels
    
    Used for access control in multi-tenant or multi-user scenarios.
    """
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    ADMIN = "admin"
    
    def __ge__(self, other):
        if self.__class__ is other.__class__:
            return self.value >= other.value
        return NotImplemented
    
    def __gt__(self, other):
        if self.__class__ is other.__class__:
            return self.value > other.value
        return NotImplemented
    
    def __le__(self, other):
        if self.__class__ is other.__class__:
            return self.value <= other.value
        return NotImplemented
    
    def __lt__(self, other):
        if self.__class__ is other.__class__:
            return self.value < other.value
        return NotImplemented


class ToolStatus(Enum):
    """Tool operational status"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"
    MAINTENANCE = "maintenance"


class ToolCapability(Enum):
    """Tool capability categories
    
    Used for capability-based tool selection.
    """
    SEARCH = "search"
    RETRIEVE = "retrieve"
    EXECUTE = "execute"
    ANALYZE = "analyze"
    GENERATE = "generate"
    TRANSFORM = "transform"
    COMMUNICATE = "communicate"
    PERSIST = "persist"