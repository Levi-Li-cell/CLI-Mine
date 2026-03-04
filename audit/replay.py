"""
Audit replay functionality for the AI Agent harness.

Provides tools to replay and analyze traces from audit logs.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .events import EventType, event_from_dict


@dataclass
class TraceSummary:
    """Summary of a trace's execution."""

    trace_id: str
    task_id: str
    feature_id: Optional[str]
    started_at: str
    ended_at: Optional[str]
    status: str
    duration_ms: Optional[int]
    event_count: int
    tool_calls: List[str]
    model_calls: int
    policy_blocks: int
    retries: int
    errors: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "feature_id": self.feature_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "event_count": self.event_count,
            "tool_calls": self.tool_calls,
            "model_calls": self.model_calls,
            "policy_blocks": self.policy_blocks,
            "retries": self.retries,
            "errors": self.errors,
        }


@dataclass
class ReplayStep:
    """A single step in a trace replay."""

    seq: int
    event_type: str
    at: str
    summary: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seq": self.seq,
            "event_type": self.event_type,
            "at": self.at,
            "summary": self.summary,
            "details": self.details,
        }


class AuditReplay:
    """Replay and analyze traces from audit logs.

    Provides functionality to:
    - List all traces
    - Get trace summaries
    - Replay trace step-by-step
    - Find related events
    - Export traces for analysis

    Usage:
        replay = AuditReplay(Path(".agent/runtime/audit.jsonl"))

        # List all traces
        traces = replay.list_traces()

        # Get a summary
        summary = replay.get_trace_summary("trace_xxx")

        # Replay step by step
        steps = replay.replay_trace("trace_xxx")
        for step in steps:
            print(f"{step.seq}: {step.summary}")
    """

    def __init__(self, log_path: Path):
        """Initialize the replay reader.

        Args:
            log_path: Path to the JSONL audit log file
        """
        self.log_path = Path(log_path)
        self._events: Optional[List[Dict[str, Any]]] = None

    def _load_events(self) -> List[Dict[str, Any]]:
        """Load all events from the log file."""
        if self._events is not None:
            return self._events

        if not self.log_path.exists():
            self._events = []
            return self._events

        events = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    events.append(event)
                except json.JSONDecodeError:
                    continue

        self._events = events
        return self._events

    def _clear_cache(self) -> None:
        """Clear the event cache to reload from file."""
        self._events = None

    def list_traces(self) -> List[str]:
        """List all unique trace IDs in the log.

        Returns:
            List of trace_id strings
        """
        events = self._load_events()
        trace_ids: Set[str] = set()
        for event in events:
            trace_id = event.get("trace_id")
            if trace_id:
                trace_ids.add(trace_id)
        return sorted(trace_ids)

    def get_trace_events(self, trace_id: str) -> List[Dict[str, Any]]:
        """Get all events for a specific trace.

        Args:
            trace_id: The trace to retrieve

        Returns:
            List of events sorted by sequence number
        """
        events = self._load_events()
        trace_events = [
            e for e in events if e.get("trace_id") == trace_id
        ]
        trace_events.sort(key=lambda e: e.get("seq", 0))
        return trace_events

    def get_trace_summary(self, trace_id: str) -> Optional[TraceSummary]:
        """Get a summary of a trace's execution.

        Args:
            trace_id: The trace to summarize

        Returns:
            TraceSummary or None if trace not found
        """
        events = self.get_trace_events(trace_id)
        if not events:
            return None

        # Extract trace info from TRACE_START
        start_event = next(
            (e for e in events if e.get("event_type") == EventType.TRACE_START.value),
            None,
        )
        end_event = next(
            (e for e in events if e.get("event_type") == EventType.TRACE_END.value),
            None,
        )

        if not start_event:
            return None

        # Count various event types
        tool_calls = []
        model_calls = 0
        policy_blocks = 0
        retries = 0
        errors = []

        for event in events:
            event_type = event.get("event_type", "")

            if event_type == EventType.TOOL_CALL.value:
                tool_name = event.get("tool_name", "unknown")
                if tool_name not in tool_calls:
                    tool_calls.append(tool_name)

            elif event_type == EventType.MODEL_CALL.value:
                model_calls += 1

            elif event_type == EventType.POLICY_DECISION.value:
                if event.get("action") == "block":
                    policy_blocks += 1

            elif event_type == EventType.RETRY_ATTEMPT.value:
                retries += 1

            elif event_type == EventType.TOOL_RESULT.value:
                if not event.get("success"):
                    error = event.get("error", "Unknown error")
                    if error and error not in errors:
                        errors.append(error[:100])

            elif event_type == EventType.MODEL_RESPONSE.value:
                if event.get("error"):
                    errors.append(event.get("error")[:100])

        return TraceSummary(
            trace_id=trace_id,
            task_id=start_event.get("task_id", ""),
            feature_id=start_event.get("feature_id"),
            started_at=start_event.get("at", ""),
            ended_at=end_event.get("at") if end_event else None,
            status=end_event.get("status", "unknown") if end_event else "in_progress",
            duration_ms=end_event.get("duration_ms") if end_event else None,
            event_count=len(events),
            tool_calls=tool_calls,
            model_calls=model_calls,
            policy_blocks=policy_blocks,
            retries=retries,
            errors=errors,
        )

    def replay_trace(self, trace_id: str) -> List[ReplayStep]:
        """Replay a trace step by step.

        Args:
            trace_id: The trace to replay

        Returns:
            List of ReplayStep objects representing the trace execution
        """
        events = self.get_trace_events(trace_id)
        steps = []

        for event in events:
            step = self._event_to_step(event)
            if step:
                steps.append(step)

        return steps

    def _event_to_step(self, event: Dict[str, Any]) -> Optional[ReplayStep]:
        """Convert an event to a human-readable replay step."""
        event_type = event.get("event_type", "")
        seq = event.get("seq", 0)
        at = event.get("at", "")

        if event_type == EventType.TRACE_START.value:
            summary = f"Trace started for task '{event.get('task_id', 'unknown')}'"
            if event.get("feature_id"):
                summary += f" (feature: {event.get('feature_id')})"
            return ReplayStep(seq, event_type, at, summary, {
                "task_id": event.get("task_id"),
                "feature_id": event.get("feature_id"),
            })

        elif event_type == EventType.TRACE_END.value:
            status = event.get("status", "unknown")
            duration = event.get("duration_ms")
            summary = f"Trace ended with status: {status}"
            if duration:
                summary += f" ({duration}ms)"
            return ReplayStep(seq, event_type, at, summary, {
                "status": status,
                "duration_ms": duration,
            })

        elif event_type == EventType.MODEL_CALL.value:
            model = event.get("model", "unknown")
            summary = f"Model call to '{model}'"
            return ReplayStep(seq, event_type, at, summary, {
                "model": model,
                "provider": event.get("provider"),
                "prompt_preview": (event.get("prompt") or "")[:100] + "...",
            })

        elif event_type == EventType.MODEL_RESPONSE.value:
            if event.get("error"):
                summary = f"Model response error: {event.get('error')}"
            else:
                tokens = event.get("completion_tokens", "?")
                summary = f"Model response received ({tokens} tokens)"
            return ReplayStep(seq, event_type, at, summary, {
                "completion_tokens": event.get("completion_tokens"),
                "latency_ms": event.get("latency_ms"),
                "error": event.get("error"),
            })

        elif event_type == EventType.TOOL_CALL.value:
            tool = event.get("tool_name", "unknown")
            args = event.get("arguments", {})
            # Truncate argument values for display
            args_preview = {k: str(v)[:50] for k, v in list(args.items())[:3]}
            summary = f"Tool call: {tool}({args_preview})"
            return ReplayStep(seq, event_type, at, summary, {
                "tool_name": tool,
                "arguments": args,
                "call_id": event.get("call_id"),
            })

        elif event_type == EventType.TOOL_RESULT.value:
            tool = event.get("tool_name", "unknown")
            success = event.get("success", False)
            status = "success" if success else "failed"
            latency = event.get("latency_ms")
            summary = f"Tool result for {tool}: {status}"
            if latency:
                summary += f" ({latency}ms)"
            if event.get("retries", 0) > 0:
                summary += f" [after {event.get('retries')} retries]"
            return ReplayStep(seq, event_type, at, summary, {
                "tool_name": tool,
                "success": success,
                "error": event.get("error"),
                "output_preview": (event.get("output") or "")[:100],
            })

        elif event_type == EventType.POLICY_DECISION.value:
            tool = event.get("tool_name", "unknown")
            action = event.get("action", "unknown")
            reason = event.get("reason", "")
            summary = f"Policy decision for {tool}: {action}"
            if action == "block":
                summary += f" - {reason[:50]}"
            return ReplayStep(seq, event_type, at, summary, {
                "action": action,
                "reason": reason,
                "risk_level": event.get("risk_level"),
                "alternative": event.get("alternative"),
            })

        elif event_type == EventType.RETRY_ATTEMPT.value:
            tool = event.get("tool_name", "unknown")
            attempt = event.get("attempt", 0)
            max_retries = event.get("max_retries", 0)
            summary = f"Retry attempt {attempt}/{max_retries} for {tool}"
            return ReplayStep(seq, event_type, at, summary, {
                "attempt": attempt,
                "max_retries": max_retries,
                "error": event.get("error"),
                "will_retry": event.get("will_retry"),
            })

        elif event_type == EventType.RESULT.value:
            status = event.get("status", "unknown")
            message = event.get("message", "")
            summary = f"Result: {status}"
            if message:
                summary += f" - {message[:50]}"
            return ReplayStep(seq, event_type, at, summary, {
                "status": status,
                "message": message,
                "details": event.get("details"),
            })

        # Unknown event type
        return ReplayStep(seq, event_type, at, f"Event: {event_type}", event)

    def find_traces_by_feature(self, feature_id: str) -> List[str]:
        """Find all traces for a specific feature.

        Args:
            feature_id: The feature to search for

        Returns:
            List of trace_id strings
        """
        events = self._load_events()
        trace_ids = set()
        for event in events:
            if (
                event.get("event_type") == EventType.TRACE_START.value
                and event.get("feature_id") == feature_id
            ):
                trace_ids.add(event.get("trace_id"))
        return sorted(trace_ids)

    def find_traces_by_status(self, status: str) -> List[str]:
        """Find all traces with a specific status.

        Args:
            status: Status to search for (success, failed, blocked, etc.)

        Returns:
            List of trace_id strings
        """
        events = self._load_events()
        trace_ids = set()
        for event in events:
            if (
                event.get("event_type") == EventType.TRACE_END.value
                and event.get("status") == status
            ):
                trace_ids.add(event.get("trace_id"))
        return sorted(trace_ids)

    def find_traces_with_errors(self) -> List[str]:
        """Find all traces that have errors.

        Returns:
            List of trace_id strings
        """
        events = self._load_events()
        trace_ids = set()
        for event in events:
            event_type = event.get("event_type", "")
            if event_type in (
                EventType.TOOL_RESULT.value,
                EventType.MODEL_RESPONSE.value,
            ):
                if event.get("error") or not event.get("success", True):
                    trace_id = event.get("trace_id")
                    if trace_id:
                        trace_ids.add(trace_id)
        return sorted(trace_ids)

    def get_statistics(self) -> Dict[str, Any]:
        """Get overall statistics from the audit log.

        Returns:
            Dictionary with statistics about all traces
        """
        events = self._load_events()
        if not events:
            return {
                "total_traces": 0,
                "total_events": 0,
                "statuses": {},
                "tools_used": {},
                "errors": 0,
            }

        traces = set()
        statuses = {}
        tools: Dict[str, int] = {}
        errors = 0

        for event in events:
            trace_id = event.get("trace_id")
            if trace_id:
                traces.add(trace_id)

            event_type = event.get("event_type", "")

            if event_type == EventType.TRACE_END.value:
                status = event.get("status", "unknown")
                statuses[status] = statuses.get(status, 0) + 1

            elif event_type == EventType.TOOL_CALL.value:
                tool = event.get("tool_name", "unknown")
                tools[tool] = tools.get(tool, 0) + 1

            elif event_type in (EventType.TOOL_RESULT.value, EventType.MODEL_RESPONSE.value):
                if event.get("error") or not event.get("success", True):
                    errors += 1

        return {
            "total_traces": len(traces),
            "total_events": len(events),
            "statuses": statuses,
            "tools_used": tools,
            "errors": errors,
        }

    def export_trace(self, trace_id: str, output_path: Path) -> bool:
        """Export a single trace to a separate file.

        Args:
            trace_id: The trace to export
            output_path: Path to write the exported trace

        Returns:
            True if export succeeded, False if trace not found
        """
        events = self.get_trace_events(trace_id)
        if not events:
            return False

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event, ensure_ascii=True) + "\n")

        return True

    def export_summary(self, output_path: Path) -> bool:
        """Export summaries of all traces to a file.

        Args:
            output_path: Path to write the summaries

        Returns:
            True if export succeeded
        """
        trace_ids = self.list_traces()
        summaries = []

        for trace_id in trace_ids:
            summary = self.get_trace_summary(trace_id)
            if summary:
                summaries.append(summary.to_dict())

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(summaries, f, ensure_ascii=True, indent=2)

        return True
