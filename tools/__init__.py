"""
Tools package for the AI Agent harness.

Provides core tools for:
- File operations (read, write, list, delete)
- Shell command execution (with safety restrictions)
- Web content fetching

Usage:
    from tools import ToolRegistry, FileTool, ShellTool, WebTool

    registry = ToolRegistry()
    registry.register(FileTool())
    registry.register(ShellTool())
    registry.register(WebTool())

    # Get tool schemas for function calling
    schemas = registry.get_all_schemas()

    # Execute a tool
    result = registry.execute("file", {"operation": "read", "path": "/tmp/test.txt"})
"""

from typing import Any, Dict, List, Optional, Type

from .base import BaseTool, ToolResult, ToolSchema, SchemaValidator, ValidationError
from .file_tool import FileTool
from .shell_tool import ShellTool
from .web_tool import WebTool


class ToolRegistry:
    """Registry for managing and executing tools."""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        name = tool.schema.name
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = tool

    def unregister(self, name: str) -> bool:
        """Unregister a tool by name. Returns True if found."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_schema(self, name: str) -> Optional[ToolSchema]:
        """Get a tool's schema by name."""
        tool = self.get(name)
        return tool.schema if tool else None

    def get_all_schemas(self) -> List[Dict[str, Any]]:
        """Get all registered tool schemas as dicts."""
        return [tool.schema.to_dict() for tool in self._tools.values()]

    def list_tools(self) -> List[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def execute(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        """Execute a tool by name with given arguments.

        Arguments are validated against the tool's schema before execution.
        Validation errors are returned as ToolResult with success=False.
        """
        tool = self.get(name)
        if not tool:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown tool: {name}. Available: {', '.join(self.list_tools())}",
            )

        # Validate arguments against schema
        errors = SchemaValidator.validate(arguments, tool.schema)
        if errors:
            return ToolResult(
                success=False,
                output="",
                error=f"Validation failed: {'; '.join(errors)}",
            )

        return tool.execute(**arguments)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)


def create_default_registry(
    allowed_dir: Optional[str] = None,
    shell_timeout: int = 60,
    web_timeout: int = 30,
) -> ToolRegistry:
    """Create a registry with default tools registered.

    Args:
        allowed_dir: Optional directory to restrict shell operations to
        shell_timeout: Default timeout for shell commands
        web_timeout: Default timeout for web requests

    Returns:
        Configured ToolRegistry instance
    """
    from pathlib import Path

    registry = ToolRegistry()
    registry.register(FileTool())
    registry.register(
        ShellTool(
            allowed_dir=Path(allowed_dir) if allowed_dir else None,
            default_timeout=shell_timeout,
        )
    )
    registry.register(WebTool(default_timeout=web_timeout))
    return registry


__all__ = [
    "BaseTool",
    "ToolSchema",
    "ToolResult",
    "ToolRegistry",
    "SchemaValidator",
    "ValidationError",
    "FileTool",
    "ShellTool",
    "WebTool",
    "create_default_registry",
]
