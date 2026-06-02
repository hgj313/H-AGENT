"""Common Enums Module

Shared enumerations for the tools module.
"""

from enum import Enum


class PermissionLevel(Enum):
    """Permission levels for tool access control."""
    PUBLIC = "public"
    PROTECTED = "protected"
    PRIVATE = "private"