"""
JARV Backend - Tool System

Core tool infrastructure for the JARV multi-agent system.
Tools enable agents to interact with files, commands, APIs, and more.
"""
from app.core.tools.base import (
    ToolBase,
    ToolConfig,
    ToolContext,
    ToolResult,
    ToolError,
    ToolValidationError,
    ToolExecutionError,
    ToolAuthorizationError,
)
from app.core.tools.registry import (
    ToolRegistry,
    ToolMetadata,
    get_registry,
    register_tool,
    create_tool,
    list_tools,
)

__all__ = [
    # Base classes
    "ToolBase",
    "ToolConfig",
    "ToolContext",
    "ToolResult",
    # Registry
    "ToolRegistry",
    "ToolMetadata",
    "get_registry",
    "register_tool",
    "create_tool",
    "list_tools",
    # Exceptions
    "ToolError",
    "ToolValidationError",
    "ToolExecutionError",
    "ToolAuthorizationError",
]
