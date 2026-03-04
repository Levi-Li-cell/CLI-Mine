"""Data models for tool execution visualization (M3-003)."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ToolStatus(str, Enum):
    """Status of a tool execution."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    BLOCKED = "blocked"
    RETRYING = "retrying"
    TIMEOUT = "timeout"


class Severity(str, Enum):
    """Severity level for display purposes."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


@dataclass
class RetryInfo:
    """Information about a retry attempt."""
    attempt: int
    max_retries: int
    error: str
    delay_ms: int
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat(timespec="milliseconds")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt": self.attempt,
            "max_retries": self.max_retries,
            "error": self.error,
            "delay_ms": self.delay_ms,
            "timestamp": self.timestamp,
        }


@dataclass
class ArgumentDisplay:
    """Formatted argument for display."""
    name: str
    value: Any
    display_value: str  # Human-readable representation
    is_sensitive: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value if not self.is_sensitive else "***",
            "display_value": "***" if self.is_sensitive else self.display_value,
            "is_sensitive": self.is_sensitive,
        }


@dataclass
class ToolExecutionView:
    """
    Complete view of a tool execution for visualization.

    Captures all information needed to render a tool call:
    - Tool name and arguments
    - Execution status and output
    - Retry attempts and failures
    """
    # Identity
    call_id: str
    tool_name: str
    trace_id: Optional[str] = None

    # Arguments
    arguments: Dict[str, Any] = field(default_factory=dict)
    formatted_args: List[ArgumentDisplay] = field(default_factory=list)

    # Execution
    status: ToolStatus = ToolStatus.PENDING
    started_at: str = ""
    completed_at: str = ""
    latency_ms: Optional[int] = None

    # Result
    output: str = ""
    error: Optional[str] = None
    output_truncated: bool = False
    output_length: int = 0

    # Retries
    retries: List[RetryInfo] = field(default_factory=list)
    total_attempts: int = 1

    # Policy/Safety
    blocked_reason: Optional[str] = None
    alternative: Optional[str] = None

    # Display metadata
    severity: Severity = Severity.INFO
    is_sensitive: bool = False

    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.now().isoformat(timespec="milliseconds")

    @property
    def success(self) -> bool:
        """Check if execution was successful."""
        return self.status == ToolStatus.SUCCESS

    @property
    def failed(self) -> bool:
        """Check if execution failed."""
        return self.status in (ToolStatus.ERROR, ToolStatus.BLOCKED, ToolStatus.TIMEOUT)

    @property
    def has_retries(self) -> bool:
        """Check if there were retry attempts."""
        return len(self.retries) > 0

    @property
    def duration_str(self) -> str:
        """Human-readable duration."""
        if self.latency_ms is None:
            return ""
        if self.latency_ms < 1000:
            return f"{self.latency_ms}ms"
        return f"{self.latency_ms / 1000:.2f}s"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "trace_id": self.trace_id,
            "arguments": self.arguments,
            "formatted_args": [a.to_dict() for a in self.formatted_args],
            "status": self.status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "latency_ms": self.latency_ms,
            "output": self.output,
            "error": self.error,
            "output_truncated": self.output_truncated,
            "output_length": self.output_length,
            "retries": [r.to_dict() for r in self.retries],
            "total_attempts": self.total_attempts,
            "blocked_reason": self.blocked_reason,
            "alternative": self.alternative,
            "severity": self.severity.value,
            "is_sensitive": self.is_sensitive,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolExecutionView":
        """Create from dictionary."""
        formatted_args = [
            ArgumentDisplay(
                name=a["name"],
                value=a["value"],
                display_value=a["display_value"],
                is_sensitive=a.get("is_sensitive", False),
            )
            for a in data.get("formatted_args", [])
        ]
        retries = [
            RetryInfo(
                attempt=r["attempt"],
                max_retries=r["max_retries"],
                error=r["error"],
                delay_ms=r["delay_ms"],
                timestamp=r.get("timestamp", ""),
            )
            for r in data.get("retries", [])
        ]
        return cls(
            call_id=data["call_id"],
            tool_name=data["tool_name"],
            trace_id=data.get("trace_id"),
            arguments=data.get("arguments", {}),
            formatted_args=formatted_args,
            status=ToolStatus(data.get("status", "pending")),
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at", ""),
            latency_ms=data.get("latency_ms"),
            output=data.get("output", ""),
            error=data.get("error"),
            output_truncated=data.get("output_truncated", False),
            output_length=data.get("output_length", 0),
            retries=retries,
            total_attempts=data.get("total_attempts", 1),
            blocked_reason=data.get("blocked_reason"),
            alternative=data.get("alternative"),
            severity=Severity(data.get("severity", "info")),
            is_sensitive=data.get("is_sensitive", False),
        )


@dataclass
class ToolExecutionSummary:
    """Summary of multiple tool executions for a trace/session."""
    trace_id: str
    executions: List[ToolExecutionView] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return len(self.executions)

    @property
    def success_count(self) -> int:
        return sum(1 for e in self.executions if e.success)

    @property
    def failure_count(self) -> int:
        return sum(1 for e in self.executions if e.failed)

    @property
    def retry_count(self) -> int:
        return sum(len(e.retries) for e in self.executions)

    @property
    def total_latency_ms(self) -> int:
        return sum(e.latency_ms or 0 for e in self.executions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "executions": [e.to_dict() for e in self.executions],
            "summary": {
                "total": self.total_count,
                "success": self.success_count,
                "failure": self.failure_count,
                "retries": self.retry_count,
                "total_latency_ms": self.total_latency_ms,
            },
        }
