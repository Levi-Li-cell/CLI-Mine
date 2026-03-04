"""
Audit logging system with trace IDs for the AI Agent harness.

This module provides end-to-end audit logging with trace IDs that link
all events in a request lifecycle:
- Model calls (request/response)
- Tool executions
- Policy decisions
- Retry attempts
- Results

All events are linked by a unique trace_id, enabling:
- Full request tracing
- Replay from logs
- Debugging and analysis

Usage:
    from audit import AuditLogger, TraceContext, AuditReplay

    # Create audit logger
    logger = AuditLogger(log_path=Path(".agent/runtime/audit.jsonl"))

    # Start a new trace
    trace = logger.start_trace(
        task_id="cycle_000001",
        feature_id="M2-004",
        metadata={"source": "harness"}
    )

    # Log events linked to the trace
    logger.log_model_call(trace.trace_id, model="claude-3", prompt="...")
    logger.log_tool_call(trace.trace_id, tool="shell", args={"command": "ls"})
    logger.log_policy_decision(trace.trace_id, tool="shell", allowed=True)

    # End the trace
    logger.end_trace(trace.trace_id, status="success")

    # Replay a trace
    replay = AuditReplay(Path(".agent/runtime/audit.jsonl"))
    events = replay.get_trace_events("trace_xxx")
"""

from pathlib import Path
from typing import Optional

from .events import (
    AuditEvent,
    EventType,
    TraceContext,
    ModelCallEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    PolicyDecisionEvent,
    RetryEvent,
    ResultEvent,
)
from .logger import AuditLogger
from .replay import AuditReplay, TraceSummary


def create_default_audit_logger(
    log_path: Optional[Path] = None,
    enabled: bool = True,
) -> AuditLogger:
    """Create an AuditLogger with default configuration.

    Args:
        log_path: Path to audit log file. Defaults to .agent/runtime/audit.jsonl
        enabled: Whether audit logging is enabled

    Returns:
        Configured AuditLogger instance
    """
    if log_path is None:
        log_path = Path(".agent/runtime/audit.jsonl")
    return AuditLogger(log_path=log_path, enabled=enabled)


__all__ = [
    "AuditLogger",
    "AuditReplay",
    "TraceSummary",
    "AuditEvent",
    "EventType",
    "TraceContext",
    "ModelCallEvent",
    "ModelResponseEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "PolicyDecisionEvent",
    "RetryEvent",
    "ResultEvent",
    "create_default_audit_logger",
]
