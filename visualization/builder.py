"""
Builder for ToolExecutionView from audit events and tool results (M3-003).

Converts raw audit events and tool execution data into structured
ToolExecutionView objects ready for visualization.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    ToolExecutionView,
    ToolExecutionSummary,
    ToolStatus,
    Severity,
    RetryInfo,
    ArgumentDisplay,
)


# Sensitive argument names that should be masked
SENSITIVE_ARG_NAMES = {
    "password", "passwd", "pwd", "secret", "token", "api_key", "apikey",
    "auth", "credential", "private_key", "access_token", "refresh_token",
}

# Maximum output length before truncation
MAX_OUTPUT_DISPLAY = 500


class ToolExecutionBuilder:
    """
    Builds ToolExecutionView objects from audit events and tool results.

    This class handles:
    - Converting audit TOOL_CALL/TOOL_RESULT events into views
    - Formatting arguments for display
    - Tracking retry attempts
    - Computing execution status and severity
    """

    def __init__(self, max_output_length: int = MAX_OUTPUT_DISPLAY):
        self.max_output_length = max_output_length

    def _is_sensitive_arg(self, name: str) -> bool:
        """Check if an argument name is sensitive."""
        return name.lower() in SENSITIVE_ARG_NAMES

    def _format_arg_value(self, value: Any, max_len: int = 100) -> str:
        """Format an argument value for display."""
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            if len(value) > max_len:
                return f'"{value[:max_len]}..."'
            return f'"{value}"'
        if isinstance(value, list):
            if len(value) == 0:
                return "[]"
            if len(value) <= 3:
                items = ", ".join(self._format_arg_value(v, max_len // 2) for v in value)
                return f"[{items}]"
            return f"[{len(value)} items]"
        if isinstance(value, dict):
            if len(value) == 0:
                return "{}"
            keys = list(value.keys())[:3]
            return "{" + ", ".join(f"{k}: ..." for k in keys) + "}"
        return str(value)

    def _format_arguments(
        self, arguments: Dict[str, Any]
    ) -> List[ArgumentDisplay]:
        """Format arguments into display-friendly form."""
        formatted = []
        for name, value in arguments.items():
            is_sensitive = self._is_sensitive_arg(name)
            display_value = "***" if is_sensitive else self._format_arg_value(value)
            formatted.append(ArgumentDisplay(
                name=name,
                value=value,
                display_value=display_value,
                is_sensitive=is_sensitive,
            ))
        return formatted

    def _truncate_output(self, output: str) -> Tuple[str, bool, int]:
        """Truncate output if needed. Returns (output, truncated, length)."""
        length = len(output)
        if length <= self.max_output_length:
            return output, False, length
        return output[:self.max_output_length] + "...", True, length

    def _determine_status(
        self,
        success: bool,
        error: Optional[str],
        blocked_reason: Optional[str],
        retries: int,
    ) -> ToolStatus:
        """Determine the tool execution status."""
        if blocked_reason:
            return ToolStatus.BLOCKED
        if success:
            return ToolStatus.SUCCESS
        if error:
            if "timeout" in error.lower():
                return ToolStatus.TIMEOUT
            if retries > 0:
                return ToolStatus.ERROR
            return ToolStatus.ERROR
        return ToolStatus.PENDING

    def _determine_severity(self, status: ToolStatus) -> Severity:
        """Determine display severity based on status."""
        severity_map = {
            ToolStatus.SUCCESS: Severity.SUCCESS,
            ToolStatus.ERROR: Severity.ERROR,
            ToolStatus.BLOCKED: Severity.WARNING,
            ToolStatus.TIMEOUT: Severity.WARNING,
            ToolStatus.RETRYING: Severity.WARNING,
            ToolStatus.RUNNING: Severity.INFO,
            ToolStatus.PENDING: Severity.INFO,
        }
        return severity_map.get(status, Severity.INFO)

    def build_from_result(
        self,
        call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        success: bool,
        output: str = "",
        error: Optional[str] = None,
        latency_ms: Optional[int] = None,
        retries: Optional[List[RetryInfo]] = None,
        blocked_reason: Optional[str] = None,
        alternative: Optional[str] = None,
        trace_id: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> ToolExecutionView:
        """
        Build a ToolExecutionView from a tool execution result.

        Args:
            call_id: Unique identifier for this tool call
            tool_name: Name of the tool that was executed
            arguments: Arguments passed to the tool
            success: Whether execution succeeded
            output: Tool output (will be truncated if too long)
            error: Error message if failed
            latency_ms: Execution time in milliseconds
            retries: List of retry attempts
            blocked_reason: Reason if blocked by policy
            alternative: Suggested alternative if blocked
            trace_id: Audit trace ID
            started_at: ISO timestamp when execution started
            completed_at: ISO timestamp when execution completed

        Returns:
            ToolExecutionView ready for visualization
        """
        # Format arguments
        formatted_args = self._format_arguments(arguments)

        # Truncate output
        truncated_output, output_truncated, output_length = self._truncate_output(output)

        # Determine status
        status = self._determine_status(success, error, blocked_reason, len(retries or []))

        # Determine severity
        severity = self._determine_severity(status)

        # Check for sensitive data in tool name (e.g., credential tools)
        is_sensitive = any(s in tool_name.lower() for s in ["credential", "secret", "token"])

        return ToolExecutionView(
            call_id=call_id,
            tool_name=tool_name,
            trace_id=trace_id,
            arguments=arguments,
            formatted_args=formatted_args,
            status=status,
            started_at=started_at or "",
            completed_at=completed_at or "",
            latency_ms=latency_ms,
            output=truncated_output,
            error=error,
            output_truncated=output_truncated,
            output_length=output_length,
            retries=retries or [],
            total_attempts=(len(retries) + 1) if retries else 1,
            blocked_reason=blocked_reason,
            alternative=alternative,
            severity=severity,
            is_sensitive=is_sensitive,
        )

    def build_from_audit_events(
        self,
        tool_call_event: Dict[str, Any],
        tool_result_event: Optional[Dict[str, Any]] = None,
        retry_events: Optional[List[Dict[str, Any]]] = None,
        policy_event: Optional[Dict[str, Any]] = None,
    ) -> ToolExecutionView:
        """
        Build a ToolExecutionView from audit events.

        Args:
            tool_call_event: TOOL_CALL audit event
            tool_result_event: Optional TOOL_RESULT audit event
            retry_events: Optional list of RETRY_ATTEMPT events
            policy_event: Optional POLICY_DECISION event

        Returns:
            ToolExecutionView ready for visualization
        """
        call_id = tool_call_event.get("call_id", "unknown")
        tool_name = tool_call_event.get("tool_name", "unknown")
        arguments = tool_call_event.get("arguments", {})
        trace_id = tool_call_event.get("trace_id")
        started_at = tool_call_event.get("at", "")

        # Build retry info
        retries = []
        if retry_events:
            for re in retry_events:
                retries.append(RetryInfo(
                    attempt=re.get("attempt", 0),
                    max_retries=re.get("max_retries", 0),
                    error=re.get("error", ""),
                    delay_ms=re.get("delay_ms", 0),
                    timestamp=re.get("at", ""),
                ))

        # Get result info
        success = False
        output = ""
        error = None
        latency_ms = None
        completed_at = ""

        if tool_result_event:
            success = tool_result_event.get("success", False)
            output = tool_result_event.get("output", "")
            error = tool_result_event.get("error")
            latency_ms = tool_result_event.get("latency_ms")
            completed_at = tool_result_event.get("at", "")

        # Get policy info
        blocked_reason = None
        alternative = None
        if policy_event:
            action = policy_event.get("action", "")
            if action == "block":
                blocked_reason = policy_event.get("reason", "Blocked by policy")
                alternative = policy_event.get("alternative")

        return self.build_from_result(
            call_id=call_id,
            tool_name=tool_name,
            arguments=arguments,
            success=success,
            output=output,
            error=error,
            latency_ms=latency_ms,
            retries=retries,
            blocked_reason=blocked_reason,
            alternative=alternative,
            trace_id=trace_id,
            started_at=started_at,
            completed_at=completed_at,
        )

    def build_summary(
        self,
        trace_id: str,
        executions: List[ToolExecutionView],
    ) -> ToolExecutionSummary:
        """
        Build a summary of multiple tool executions.

        Args:
            trace_id: The trace ID these executions belong to
            executions: List of ToolExecutionView objects

        Returns:
            ToolExecutionSummary with statistics
        """
        return ToolExecutionSummary(
            trace_id=trace_id,
            executions=executions,
        )


def build_tool_view(
    call_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
    success: bool,
    output: str = "",
    error: Optional[str] = None,
    **kwargs,
) -> ToolExecutionView:
    """
    Convenience function to build a ToolExecutionView.

    Args:
        call_id: Unique identifier for this tool call
        tool_name: Name of the tool
        arguments: Arguments passed to the tool
        success: Whether execution succeeded
        output: Tool output
        error: Error message if failed
        **kwargs: Additional arguments passed to build_from_result

    Returns:
        ToolExecutionView ready for visualization
    """
    builder = ToolExecutionBuilder()
    return builder.build_from_result(
        call_id=call_id,
        tool_name=tool_name,
        arguments=arguments,
        success=success,
        output=output,
        error=error,
        **kwargs,
    )
