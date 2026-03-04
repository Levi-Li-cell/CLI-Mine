"""
Renderer for tool execution visualization (M3-003).

Provides console/terminal rendering of ToolExecutionView objects
with support for colors, status indicators, and formatted output.
"""

from typing import List, Optional

from .models import (
    ToolExecutionView,
    ToolExecutionSummary,
    ToolStatus,
    Severity,
    ArgumentDisplay,
    RetryInfo,
)


# ANSI color codes
class Colors:
    """ANSI color codes for terminal output."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground colors
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Background colors
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"


# Status indicators
STATUS_ICONS = {
    ToolStatus.PENDING: ("○", Colors.WHITE),
    ToolStatus.RUNNING: ("◐", Colors.CYAN),
    ToolStatus.SUCCESS: ("●", Colors.GREEN),
    ToolStatus.ERROR: ("●", Colors.RED),
    ToolStatus.BLOCKED: ("●", Colors.YELLOW),
    ToolStatus.RETRYING: ("◐", Colors.YELLOW),
    ToolStatus.TIMEOUT: ("●", Colors.YELLOW),
}

STATUS_LABELS = {
    ToolStatus.PENDING: "pending",
    ToolStatus.RUNNING: "running",
    ToolStatus.SUCCESS: "success",
    ToolStatus.ERROR: "error",
    ToolStatus.BLOCKED: "blocked",
    ToolStatus.RETRYING: "retrying",
    ToolStatus.TIMEOUT: "timeout",
}

SEVERITY_COLORS = {
    Severity.INFO: Colors.BLUE,
    Severity.SUCCESS: Colors.GREEN,
    Severity.WARNING: Colors.YELLOW,
    Severity.ERROR: Colors.RED,
}


class ToolExecutionRenderer:
    """
    Renders ToolExecutionView objects for console display.

    Provides formatted output including:
    - Tool name and status indicator
    - Formatted arguments
    - Execution output (truncated if needed)
    - Retry attempts
    - Error messages and alternatives
    """

    def __init__(
        self,
        use_colors: bool = True,
        indent: str = "  ",
        max_output_lines: int = 10,
    ):
        """
        Initialize the renderer.

        Args:
            use_colors: Whether to use ANSI colors in output
            indent: Indentation string for nested output
            max_output_lines: Maximum number of output lines to show
        """
        self.use_colors = use_colors
        self.indent = indent
        self.max_output_lines = max_output_lines

    def _color(self, text: str, color: str) -> str:
        """Apply color to text if colors are enabled."""
        if not self.use_colors:
            return text
        return f"{color}{text}{Colors.RESET}"

    def _dim(self, text: str) -> str:
        """Apply dim styling to text."""
        if not self.use_colors:
            return text
        return f"{Colors.DIM}{text}{Colors.RESET}"

    def _bold(self, text: str) -> str:
        """Apply bold styling to text."""
        if not self.use_colors:
            return text
        return f"{Colors.BOLD}{text}{Colors.RESET}"

    def _render_status(self, status: ToolStatus) -> str:
        """Render status indicator with color."""
        icon, color = STATUS_ICONS.get(status, ("?", Colors.WHITE))
        label = STATUS_LABELS.get(status, "unknown")
        return f"{self._color(icon, color)} {label}"

    def _render_argument(self, arg: ArgumentDisplay, indent_level: int = 1) -> str:
        """Render a single argument."""
        prefix = self.indent * indent_level
        name = self._bold(arg.name)
        value = arg.display_value
        if arg.is_sensitive:
            value = self._dim(value)
        return f"{prefix}{name}: {value}"

    def _render_arguments(self, args: List[ArgumentDisplay], indent_level: int = 1) -> List[str]:
        """Render formatted arguments."""
        lines = []
        if args:
            prefix = self.indent * indent_level
            lines.append(f"{prefix}Arguments:")
            for arg in args:
                lines.append(self._render_argument(arg, indent_level + 1))
        return lines

    def _render_output(self, output: str, truncated: bool, indent_level: int = 1) -> List[str]:
        """Render tool output."""
        lines = []
        if not output:
            return lines

        prefix = self.indent * indent_level

        # Split into lines and limit
        output_lines = output.split("\n")
        if len(output_lines) > self.max_output_lines:
            shown = output_lines[:self.max_output_lines]
            remaining = len(output_lines) - self.max_output_lines
            output_text = "\n".join(shown)
            truncated_msg = f"... ({remaining} more lines)"
        else:
            output_text = output
            truncated_msg = "... (truncated)" if truncated else ""

        lines.append(f"{prefix}Output:")
        for line in output_text.split("\n"):
            lines.append(f"{prefix}{self.indent}{self._dim(line)}")
        if truncated_msg:
            lines.append(f"{prefix}{self.indent}{self._dim(truncated_msg)}")

        return lines

    def _render_retry(self, retry: RetryInfo, indent_level: int = 1) -> List[str]:
        """Render a retry attempt."""
        prefix = self.indent * indent_level
        lines = []
        lines.append(f"{prefix}Retry {retry.attempt}/{retry.max_retries}:")
        lines.append(f"{prefix}{self.indent}Error: {self._color(retry.error, Colors.RED)}")
        if retry.delay_ms > 0:
            delay = f"{retry.delay_ms}ms" if retry.delay_ms < 1000 else f"{retry.delay_ms / 1000:.1f}s"
            lines.append(f"{prefix}{self.indent}Delay: {delay}")
        return lines

    def _render_retries(self, retries: List[RetryInfo], indent_level: int = 1) -> List[str]:
        """Render all retry attempts."""
        lines = []
        if not retries:
            return lines

        prefix = self.indent * indent_level
        lines.append(f"{prefix}Retries ({len(retries)} attempts):")
        for retry in retries:
            lines.extend(self._render_retry(retry, indent_level + 1))
        return lines

    def _render_error(
        self,
        error: str,
        blocked_reason: Optional[str],
        alternative: Optional[str],
        indent_level: int = 1,
    ) -> List[str]:
        """Render error information."""
        lines = []
        prefix = self.indent * indent_level

        if blocked_reason:
            lines.append(f"{prefix}Blocked: {self._color(blocked_reason, Colors.YELLOW)}")
            if alternative:
                lines.append(f"{prefix}Alternative: {self._color(alternative, Colors.CYAN)}")
        elif error:
            lines.append(f"{prefix}Error: {self._color(error, Colors.RED)}")

        return lines

    def render(self, view: ToolExecutionView, include_output: bool = True) -> str:
        """
        Render a ToolExecutionView to a formatted string.

        Args:
            view: The ToolExecutionView to render
            include_output: Whether to include the output in the render

        Returns:
            Formatted string ready for display
        """
        lines = []

        # Header: tool name and status
        status_str = self._render_status(view.status)
        header = f"Tool: {self._bold(view.tool_name)} [{status_str}]"
        if view.duration_str:
            header += f" ({view.duration_str})"
        if view.total_attempts > 1:
            header += f" {self._dim(f'[{view.total_attempts} attempts]')}"
        lines.append(header)

        # Arguments
        lines.extend(self._render_arguments(view.formatted_args))

        # Retries
        lines.extend(self._render_retries(view.retries))

        # Error/Blocked info
        lines.extend(self._render_error(
            view.error or "",
            view.blocked_reason,
            view.alternative,
        ))

        # Output
        if include_output and view.output:
            lines.extend(self._render_output(
                view.output,
                view.output_truncated,
            ))

        return "\n".join(lines)

    def render_compact(self, view: ToolExecutionView) -> str:
        """
        Render a compact one-line summary of a tool execution.

        Args:
            view: The ToolExecutionView to render

        Returns:
            Single-line formatted string
        """
        icon, color = STATUS_ICONS.get(view.status, ("?", Colors.WHITE))
        icon_str = self._color(icon, color)

        # Format arguments compactly
        if view.formatted_args:
            arg_strs = []
            for arg in view.formatted_args[:3]:  # Show first 3 args
                val = arg.display_value
                if len(val) > 30:
                    val = val[:27] + "..."
                arg_strs.append(f"{arg.name}={val}")
            args_str = " ".join(arg_strs)
            if len(view.formatted_args) > 3:
                args_str += " ..."
        else:
            args_str = ""

        # Duration
        duration = f" ({view.duration_str})" if view.duration_str else ""

        # Retry indicator
        retries = f" [{view.total_attempts}x]" if view.total_attempts > 1 else ""

        result = f"{icon_str} {view.tool_name}({args_str}){duration}{retries}"

        # Add error indicator
        if view.error:
            result += f" {self._color('FAILED', Colors.RED)}"
        elif view.blocked_reason:
            result += f" {self._color('BLOCKED', Colors.YELLOW)}"

        return result

    def render_summary(self, summary: ToolExecutionSummary) -> str:
        """
        Render a summary of multiple tool executions.

        Args:
            summary: The ToolExecutionSummary to render

        Returns:
            Formatted string with summary statistics
        """
        lines = []
        lines.append(self._bold(f"Tool Execution Summary (trace: {summary.trace_id})"))
        lines.append(f"  Total: {summary.total_count}")
        lines.append(f"  {self._color('Success', Colors.GREEN)}: {summary.success_count}")
        lines.append(f"  {self._color('Failed', Colors.RED)}: {summary.failure_count}")
        if summary.retry_count > 0:
            lines.append(f"  Retries: {summary.retry_count}")
        if summary.total_latency_ms > 0:
            latency = summary.total_latency_ms
            if latency < 1000:
                latency_str = f"{latency}ms"
            else:
                latency_str = f"{latency / 1000:.2f}s"
            lines.append(f"  Total time: {latency_str}")

        return "\n".join(lines)

    def render_list(
        self,
        views: List[ToolExecutionView],
        compact: bool = False,
    ) -> str:
        """
        Render a list of tool executions.

        Args:
            views: List of ToolExecutionView objects
            compact: Whether to use compact one-line format

        Returns:
            Formatted string
        """
        lines = []
        for i, view in enumerate(views, 1):
            if compact:
                lines.append(f"{i}. {self.render_compact(view)}")
            else:
                lines.append(f"--- Tool Call {i} ---")
                lines.append(self.render(view))
                lines.append("")
        return "\n".join(lines)


def render_tool_execution(
    view: ToolExecutionView,
    use_colors: bool = True,
    include_output: bool = True,
) -> str:
    """
    Convenience function to render a single tool execution.

    Args:
        view: The ToolExecutionView to render
        use_colors: Whether to use ANSI colors
        include_output: Whether to include output

    Returns:
        Formatted string
    """
    renderer = ToolExecutionRenderer(use_colors=use_colors)
    return renderer.render(view, include_output=include_output)


def render_tool_compact(view: ToolExecutionView, use_colors: bool = True) -> str:
    """
    Convenience function to render a compact tool execution summary.

    Args:
        view: The ToolExecutionView to render
        use_colors: Whether to use ANSI colors

    Returns:
        Single-line formatted string
    """
    renderer = ToolExecutionRenderer(use_colors=use_colors)
    return renderer.render_compact(view)
