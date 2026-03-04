"""
Audit event types and data structures for the AI Agent harness.

Defines the event types that can be logged and linked by trace_id.
"""

import datetime as dt
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class EventType(str, Enum):
    """Types of audit events that can be logged."""

    # Trace lifecycle
    TRACE_START = "trace_start"
    TRACE_END = "trace_end"

    # Model interactions
    MODEL_CALL = "model_call"
    MODEL_RESPONSE = "model_response"

    # Tool interactions
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # Safety/policy
    POLICY_DECISION = "policy_decision"
    RISK_CLASSIFICATION = "risk_classification"
    SANDBOX_DECISION = "sandbox_decision"

    # Retry handling
    RETRY_ATTEMPT = "retry_attempt"
    RETRY_EXHAUSTED = "retry_exhausted"

    # General result
    RESULT = "result"


@dataclass
class TraceContext:
    """Context for a trace, including unique trace_id and metadata."""

    trace_id: str
    task_id: str  # e.g., cycle_000001
    feature_id: Optional[str] = None
    started_at: str = ""
    parent_trace_id: Optional[str] = None  # For nested traces
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.started_at:
            self.started_at = dt.datetime.now().isoformat(timespec="milliseconds")

    @classmethod
    def create(
        cls,
        task_id: str,
        feature_id: Optional[str] = None,
        parent_trace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "TraceContext":
        """Create a new TraceContext with a unique trace_id."""
        return cls(
            trace_id=f"trace_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            feature_id=feature_id,
            parent_trace_id=parent_trace_id,
            metadata=metadata or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuditEvent:
    """Base class for all audit events."""

    event_type: EventType
    trace_id: str
    at: str = ""
    seq: int = 0

    def __post_init__(self):
        if not self.at:
            self.at = dt.datetime.now().isoformat(timespec="milliseconds")

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for JSON serialization."""
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d


@dataclass
class TraceStartEvent(AuditEvent):
    """Event logged when a trace starts."""

    task_id: str = ""
    feature_id: Optional[str] = None
    parent_trace_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        trace_id: str,
        task_id: str,
        feature_id: Optional[str] = None,
        parent_trace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        at: str = "",
        seq: int = 0,
    ):
        super().__init__(
            event_type=EventType.TRACE_START,
            trace_id=trace_id,
            at=at,
            seq=seq,
        )
        self.task_id = task_id
        self.feature_id = feature_id
        self.parent_trace_id = parent_trace_id
        self.metadata = metadata or {}


@dataclass
class TraceEndEvent(AuditEvent):
    """Event logged when a trace ends."""

    status: str = "unknown"  # success, failed, blocked, timeout
    duration_ms: Optional[int] = None
    summary: Optional[str] = None

    def __init__(
        self,
        trace_id: str,
        status: str = "unknown",
        duration_ms: Optional[int] = None,
        summary: Optional[str] = None,
        at: str = "",
        seq: int = 0,
    ):
        super().__init__(
            event_type=EventType.TRACE_END,
            trace_id=trace_id,
            at=at,
            seq=seq,
        )
        self.status = status
        self.duration_ms = duration_ms
        self.summary = summary


@dataclass
class ModelCallEvent(AuditEvent):
    """Event logged for model API calls."""

    model: str = ""
    provider: str = ""
    prompt: str = ""
    prompt_tokens: Optional[int] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

    def __init__(
        self,
        trace_id: str,
        model: str = "",
        provider: str = "",
        prompt: str = "",
        prompt_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        at: str = "",
        seq: int = 0,
    ):
        super().__init__(
            event_type=EventType.MODEL_CALL,
            trace_id=trace_id,
            at=at,
            seq=seq,
        )
        self.model = model
        self.provider = provider
        self.prompt = prompt[:10000] if prompt else ""  # Truncate for storage
        self.prompt_tokens = prompt_tokens
        self.temperature = temperature
        self.max_tokens = max_tokens


@dataclass
class ModelResponseEvent(AuditEvent):
    """Event logged for model API responses."""

    response: str = ""
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    finish_reason: Optional[str] = None
    error: Optional[str] = None

    def __init__(
        self,
        trace_id: str,
        response: str = "",
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        latency_ms: Optional[int] = None,
        finish_reason: Optional[str] = None,
        error: Optional[str] = None,
        at: str = "",
        seq: int = 0,
    ):
        super().__init__(
            event_type=EventType.MODEL_RESPONSE,
            trace_id=trace_id,
            at=at,
            seq=seq,
        )
        self.response = response[:10000] if response else ""  # Truncate
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.latency_ms = latency_ms
        self.finish_reason = finish_reason
        self.error = error


@dataclass
class ToolCallEvent(AuditEvent):
    """Event logged for tool executions."""

    tool_name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    call_id: Optional[str] = None  # For linking call to result

    def __init__(
        self,
        trace_id: str,
        tool_name: str = "",
        arguments: Optional[Dict[str, Any]] = None,
        call_id: Optional[str] = None,
        at: str = "",
        seq: int = 0,
    ):
        super().__init__(
            event_type=EventType.TOOL_CALL,
            trace_id=trace_id,
            at=at,
            seq=seq,
        )
        self.tool_name = tool_name
        self.arguments = arguments or {}
        self.call_id = call_id or f"call_{uuid.uuid4().hex[:8]}"


@dataclass
class ToolResultEvent(AuditEvent):
    """Event logged for tool execution results."""

    tool_name: str = ""
    call_id: Optional[str] = None  # Links to ToolCallEvent
    success: bool = False
    output: str = ""
    error: Optional[str] = None
    latency_ms: Optional[int] = None
    retries: int = 0

    def __init__(
        self,
        trace_id: str,
        tool_name: str = "",
        call_id: Optional[str] = None,
        success: bool = False,
        output: str = "",
        error: Optional[str] = None,
        latency_ms: Optional[int] = None,
        retries: int = 0,
        at: str = "",
        seq: int = 0,
    ):
        super().__init__(
            event_type=EventType.TOOL_RESULT,
            trace_id=trace_id,
            at=at,
            seq=seq,
        )
        self.tool_name = tool_name
        self.call_id = call_id
        self.success = success
        self.output = output[:5000] if output else ""  # Truncate
        self.error = error
        self.latency_ms = latency_ms
        self.retries = retries


@dataclass
class PolicyDecisionEvent(AuditEvent):
    """Event logged for policy/safety decisions."""

    tool_name: str = ""
    action: str = ""  # allow, block, confirm, degrade
    reason: str = ""
    risk_level: str = ""
    alternative: Optional[str] = None
    rule_id: Optional[str] = None

    def __init__(
        self,
        trace_id: str,
        tool_name: str = "",
        action: str = "",
        reason: str = "",
        risk_level: str = "",
        alternative: Optional[str] = None,
        rule_id: Optional[str] = None,
        at: str = "",
        seq: int = 0,
    ):
        super().__init__(
            event_type=EventType.POLICY_DECISION,
            trace_id=trace_id,
            at=at,
            seq=seq,
        )
        self.tool_name = tool_name
        self.action = action
        self.reason = reason
        self.risk_level = risk_level
        self.alternative = alternative
        self.rule_id = rule_id


@dataclass
class RetryEvent(AuditEvent):
    """Event logged for retry attempts."""

    tool_name: str = ""
    attempt: int = 0
    max_retries: int = 0
    error: str = ""
    delay_ms: int = 0
    will_retry: bool = True

    def __init__(
        self,
        trace_id: str,
        tool_name: str = "",
        attempt: int = 0,
        max_retries: int = 0,
        error: str = "",
        delay_ms: int = 0,
        will_retry: bool = True,
        at: str = "",
        seq: int = 0,
    ):
        super().__init__(
            event_type=EventType.RETRY_ATTEMPT,
            trace_id=trace_id,
            at=at,
            seq=seq,
        )
        self.tool_name = tool_name
        self.attempt = attempt
        self.max_retries = max_retries
        self.error = error[:1000] if error else ""
        self.delay_ms = delay_ms
        self.will_retry = will_retry


@dataclass
class ResultEvent(AuditEvent):
    """Event logged for final results."""

    status: str = ""  # success, failed, blocked
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        trace_id: str,
        status: str = "",
        message: str = "",
        details: Optional[Dict[str, Any]] = None,
        at: str = "",
        seq: int = 0,
    ):
        super().__init__(
            event_type=EventType.RESULT,
            trace_id=trace_id,
            at=at,
            seq=seq,
        )
        self.status = status
        self.message = message
        self.details = details or {}


# Event type mapping for deserialization
EVENT_CLASSES = {
    EventType.TRACE_START: TraceStartEvent,
    EventType.TRACE_END: TraceEndEvent,
    EventType.MODEL_CALL: ModelCallEvent,
    EventType.MODEL_RESPONSE: ModelResponseEvent,
    EventType.TOOL_CALL: ToolCallEvent,
    EventType.TOOL_RESULT: ToolResultEvent,
    EventType.POLICY_DECISION: PolicyDecisionEvent,
    EventType.RETRY_ATTEMPT: RetryEvent,
    EventType.RESULT: ResultEvent,
}


def event_from_dict(data: Dict[str, Any]) -> AuditEvent:
    """Deserialize an event from a dictionary."""
    event_type_str = data.pop("event_type", None)
    if not event_type_str:
        raise ValueError("Missing event_type in event data")

    event_type = EventType(event_type_str)
    event_class = EVENT_CLASSES.get(event_type)

    if not event_class:
        raise ValueError(f"Unknown event type: {event_type}")

    # Filter out unknown fields
    known_fields = {f.name for f in event_class.__dataclass_fields__.values()}
    filtered_data = {k: v for k, v in data.items() if k in known_fields}

    return event_class(**filtered_data)
