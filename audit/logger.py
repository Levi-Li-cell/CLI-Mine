"""
Audit logger for the AI Agent harness.

Provides centralized audit logging with trace_id linking all events.
"""

import datetime as dt
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from .events import (
    EventType,
    TraceContext,
    TraceStartEvent,
    TraceEndEvent,
    ModelCallEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    PolicyDecisionEvent,
    RetryEvent,
    ResultEvent,
    AuditEvent,
)


class AuditLogger:
    """Centralized audit logger with trace_id support.

    All events logged through this class are linked by trace_id,
    enabling full request tracing and replay.

    Thread-safe: Uses a lock for file writes and sequence numbering.

    Usage:
        logger = AuditLogger(Path(".agent/runtime/audit.jsonl"))

        # Start a trace
        trace = logger.start_trace(task_id="cycle_000001", feature_id="M2-004")

        # Log events
        logger.log_model_call(trace.trace_id, model="claude-3", prompt="...")
        logger.log_tool_call(trace.trace_id, tool="shell", args={"command": "ls"})

        # End trace
        logger.end_trace(trace.trace_id, status="success")
    """

    def __init__(
        self,
        log_path: Path,
        enabled: bool = True,
        buffer_size: int = 0,
    ):
        """Initialize the audit logger.

        Args:
            log_path: Path to the JSONL audit log file
            enabled: Whether logging is enabled (useful for testing)
            buffer_size: Number of events to buffer before flush (0 = no buffering)
        """
        self.log_path = Path(log_path)
        self.enabled = enabled
        self.buffer_size = buffer_size
        self._buffer: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._seq_counter: Dict[str, int] = {}  # trace_id -> next seq
        self._trace_start_times: Dict[str, str] = {}  # trace_id -> start timestamp

        # Ensure directory exists
        if self.enabled:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_next_seq(self, trace_id: str) -> int:
        """Get the next sequence number for a trace."""
        with self._lock:
            seq = self._seq_counter.get(trace_id, 0)
            self._seq_counter[trace_id] = seq + 1
            return seq

    def _write_event(self, event: AuditEvent) -> None:
        """Write an event to the log file."""
        if not self.enabled:
            return

        event_dict = event.to_dict()

        if self.buffer_size > 0:
            self._buffer.append(event_dict)
            if len(self._buffer) >= self.buffer_size:
                self._flush_buffer()
        else:
            self._write_direct(event_dict)

    def _write_direct(self, event_dict: Dict[str, Any]) -> None:
        """Write an event directly to the log file."""
        with self._lock:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event_dict, ensure_ascii=True) + "\n")

    def _flush_buffer(self) -> None:
        """Flush the buffer to the log file."""
        with self._lock:
            if not self._buffer:
                return
            with open(self.log_path, "a", encoding="utf-8") as f:
                for event_dict in self._buffer:
                    f.write(json.dumps(event_dict, ensure_ascii=True) + "\n")
            self._buffer.clear()

    def flush(self) -> None:
        """Public method to flush any buffered events."""
        self._flush_buffer()

    def start_trace(
        self,
        task_id: str,
        feature_id: Optional[str] = None,
        parent_trace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TraceContext:
        """Start a new trace and log the start event.

        Args:
            task_id: Identifier for the task (e.g., cycle_000001)
            feature_id: Optional feature being worked on
            parent_trace_id: Optional parent trace for nested operations
            metadata: Optional additional metadata

        Returns:
            TraceContext with the new trace_id
        """
        trace = TraceContext.create(
            task_id=task_id,
            feature_id=feature_id,
            parent_trace_id=parent_trace_id,
            metadata=metadata,
        )

        # Store start time for duration calculation
        with self._lock:
            self._trace_start_times[trace.trace_id] = trace.started_at

        event = TraceStartEvent(
            trace_id=trace.trace_id,
            task_id=task_id,
            feature_id=feature_id,
            parent_trace_id=parent_trace_id,
            metadata=metadata,
            seq=self._get_next_seq(trace.trace_id),
        )
        self._write_event(event)

        return trace

    def end_trace(
        self,
        trace_id: str,
        status: str = "success",
        summary: Optional[str] = None,
    ) -> None:
        """End a trace and log the end event.

        Args:
            trace_id: The trace to end
            status: Final status (success, failed, blocked, timeout)
            summary: Optional summary of what happened
        """
        # Calculate duration
        duration_ms = None
        with self._lock:
            start_time_str = self._trace_start_times.pop(trace_id, None)
            if start_time_str:
                try:
                    start_time = dt.datetime.fromisoformat(start_time_str)
                    duration_ms = int(
                        (dt.datetime.now() - start_time).total_seconds() * 1000
                    )
                except Exception:
                    pass
            # Clean up seq counter
            self._seq_counter.pop(trace_id, None)

        event = TraceEndEvent(
            trace_id=trace_id,
            status=status,
            duration_ms=duration_ms,
            summary=summary,
            seq=self._get_next_seq(trace_id),
        )
        self._write_event(event)
        self.flush()

    def log_model_call(
        self,
        trace_id: str,
        model: str,
        prompt: str,
        provider: str = "",
        prompt_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Log a model API call.

        Args:
            trace_id: The trace to link to
            model: Model identifier (e.g., claude-3-opus)
            prompt: The prompt sent to the model
            provider: Provider name (anthropic, openai, etc.)
            prompt_tokens: Optional token count for prompt
            temperature: Optional temperature setting
            max_tokens: Optional max tokens setting

        Returns:
            The trace_id for convenience
        """
        event = ModelCallEvent(
            trace_id=trace_id,
            model=model,
            provider=provider,
            prompt=prompt,
            prompt_tokens=prompt_tokens,
            temperature=temperature,
            max_tokens=max_tokens,
            seq=self._get_next_seq(trace_id),
        )
        self._write_event(event)
        return trace_id

    def log_model_response(
        self,
        trace_id: str,
        response: str,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        latency_ms: Optional[int] = None,
        finish_reason: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Log a model API response.

        Args:
            trace_id: The trace to link to
            response: The model's response
            completion_tokens: Optional token count for completion
            total_tokens: Optional total token count
            latency_ms: Optional latency in milliseconds
            finish_reason: Optional finish reason (stop, length, etc.)
            error: Optional error message if failed
        """
        event = ModelResponseEvent(
            trace_id=trace_id,
            response=response,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            error=error,
            seq=self._get_next_seq(trace_id),
        )
        self._write_event(event)

    def log_tool_call(
        self,
        trace_id: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Log a tool execution call.

        Args:
            trace_id: The trace to link to
            tool_name: Name of the tool being called
            arguments: Arguments passed to the tool

        Returns:
            A call_id for linking to the result
        """
        event = ToolCallEvent(
            trace_id=trace_id,
            tool_name=tool_name,
            arguments=arguments,
            seq=self._get_next_seq(trace_id),
        )
        self._write_event(event)
        return event.call_id

    def log_tool_result(
        self,
        trace_id: str,
        tool_name: str,
        success: bool,
        output: str = "",
        error: Optional[str] = None,
        call_id: Optional[str] = None,
        latency_ms: Optional[int] = None,
        retries: int = 0,
    ) -> None:
        """Log a tool execution result.

        Args:
            trace_id: The trace to link to
            tool_name: Name of the tool that was called
            success: Whether execution succeeded
            output: Tool output (truncated if too long)
            error: Error message if failed
            call_id: ID from log_tool_call to link call and result
            latency_ms: Optional execution latency
            retries: Number of retries that occurred
        """
        event = ToolResultEvent(
            trace_id=trace_id,
            tool_name=tool_name,
            call_id=call_id,
            success=success,
            output=output,
            error=error,
            latency_ms=latency_ms,
            retries=retries,
            seq=self._get_next_seq(trace_id),
        )
        self._write_event(event)

    def log_policy_decision(
        self,
        trace_id: str,
        tool_name: str,
        action: str,
        reason: str,
        risk_level: str = "",
        alternative: Optional[str] = None,
        rule_id: Optional[str] = None,
    ) -> None:
        """Log a policy/safety decision.

        Args:
            trace_id: The trace to link to
            tool_name: Name of the tool being checked
            action: Action taken (allow, block, confirm, degrade)
            reason: Reason for the decision
            risk_level: Risk level (low, medium, high, critical)
            alternative: Suggested alternative if blocked
            rule_id: ID of the rule that triggered
        """
        event = PolicyDecisionEvent(
            trace_id=trace_id,
            tool_name=tool_name,
            action=action,
            reason=reason,
            risk_level=risk_level,
            alternative=alternative,
            rule_id=rule_id,
            seq=self._get_next_seq(trace_id),
        )
        self._write_event(event)

    def log_retry(
        self,
        trace_id: str,
        tool_name: str,
        attempt: int,
        max_retries: int,
        error: str,
        delay_ms: int = 0,
        will_retry: bool = True,
    ) -> None:
        """Log a retry attempt.

        Args:
            trace_id: The trace to link to
            tool_name: Name of the tool being retried
            attempt: Current attempt number
            max_retries: Maximum retries allowed
            error: Error that triggered retry
            delay_ms: Delay before next retry
            will_retry: Whether another retry will be attempted
        """
        event = RetryEvent(
            trace_id=trace_id,
            tool_name=tool_name,
            attempt=attempt,
            max_retries=max_retries,
            error=error,
            delay_ms=delay_ms,
            will_retry=will_retry,
            seq=self._get_next_seq(trace_id),
        )
        self._write_event(event)

    def log_result(
        self,
        trace_id: str,
        status: str,
        message: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a final result.

        Args:
            trace_id: The trace to link to
            status: Result status (success, failed, blocked)
            message: Human-readable message
            details: Additional structured details
        """
        event = ResultEvent(
            trace_id=trace_id,
            status=status,
            message=message,
            details=details,
            seq=self._get_next_seq(trace_id),
        )
        self._write_event(event)

    def log_custom_event(
        self,
        trace_id: str,
        event_type: str,
        data: Dict[str, Any],
    ) -> None:
        """Log a custom event.

        Args:
            trace_id: The trace to link to
            event_type: Custom event type string
            data: Event data dictionary
        """
        event_dict = {
            "event_type": event_type,
            "trace_id": trace_id,
            "at": dt.datetime.now().isoformat(timespec="milliseconds"),
            "seq": self._get_next_seq(trace_id),
            **data,
        }
        self._write_direct(event_dict)

    def get_trace_events(self, trace_id: str) -> List[Dict[str, Any]]:
        """Read all events for a given trace_id from the log file.

        Args:
            trace_id: The trace to retrieve events for

        Returns:
            List of event dictionaries, sorted by sequence number
        """
        if not self.log_path.exists():
            return []

        events = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if event.get("trace_id") == trace_id:
                        events.append(event)
                except json.JSONDecodeError:
                    continue

        # Sort by sequence number
        events.sort(key=lambda e: e.get("seq", 0))
        return events
