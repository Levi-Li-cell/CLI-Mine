"""
Tool Execution Visualization Package (M3-003).

Provides comprehensive visualization of tool executions including:
- Tool name and arguments display
- Execution status and output
- Retry attempts and failures
- Policy blocking information

Usage:
    from visualization import ToolExecutionBuilder, ToolExecutionRenderer

    # Build a view from a tool execution
    builder = ToolExecutionBuilder()
    view = builder.build_from_result(
        call_id="call_123",
        tool_name="shell",
        arguments={"command": "ls -la"},
        success=True,
        output="file1.txt\nfile2.py",
        latency_ms=150,
    )

    # Render for display
    renderer = ToolExecutionRenderer()
    print(renderer.render(view))

    # Or use the convenience functions
    from visualization import render_tool_execution, build_tool_view

    view = build_tool_view(
        call_id="call_123",
        tool_name="file",
        arguments={"operation": "read", "path": "/tmp/test.txt"},
        success=True,
        output="Hello World",
    )
    print(render_tool_execution(view))
"""

from .models import (
    ToolStatus,
    Severity,
    RetryInfo,
    ArgumentDisplay,
    ToolExecutionView,
    ToolExecutionSummary,
)

from .builder import (
    ToolExecutionBuilder,
    build_tool_view,
)

from .renderer import (
    Colors,
    STATUS_ICONS,
    STATUS_LABELS,
    ToolExecutionRenderer,
    render_tool_execution,
    render_tool_compact,
)


__all__ = [
    # Models
    "ToolStatus",
    "Severity",
    "RetryInfo",
    "ArgumentDisplay",
    "ToolExecutionView",
    "ToolExecutionSummary",
    # Builder
    "ToolExecutionBuilder",
    "build_tool_view",
    # Renderer
    "Colors",
    "STATUS_ICONS",
    "STATUS_LABELS",
    "ToolExecutionRenderer",
    "render_tool_execution",
    "render_tool_compact",
]
