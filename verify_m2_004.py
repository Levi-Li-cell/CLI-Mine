"""
Verification test for M2-004: End-to-end audit logging with trace IDs

Tests:
1. Generate trace_id per task
2. Link model, tool, and result events
3. Support replay from logs
"""

import json
import tempfile
from pathlib import Path

print("=== M2-004 VERIFICATION: End-to-end Audit Logging with Trace IDs ===\n")

# Test 1: Imports work correctly
print("1. Testing: Imports work correctly...")
try:
    from audit import (
        AuditLogger,
        AuditReplay,
        TraceContext,
        TraceSummary,
        EventType,
        ModelCallEvent,
        ToolCallEvent,
        ToolResultEvent,
        PolicyDecisionEvent,
        RetryEvent,
        ResultEvent,
        create_default_audit_logger,
    )
    print("   [PASS] All audit classes imported successfully")
except ImportError as e:
    print(f"   [FAIL] Import error: {e}")
    exit(1)

# Create temp directory for test logs
with tempfile.TemporaryDirectory() as tmpdir:
    log_path = Path(tmpdir) / "audit.jsonl"

    # Test 2: trace_id generation per task
    print("\n2. Testing: trace_id generation per task...")
    logger = AuditLogger(log_path=log_path)

    trace1 = logger.start_trace(task_id="task_001", feature_id="F1")
    trace2 = logger.start_trace(task_id="task_002", feature_id="F2")

    # Verify trace IDs are unique
    assert trace1.trace_id != trace2.trace_id, "trace_ids should be unique"
    assert trace1.trace_id.startswith("trace_"), "trace_id should have correct prefix"
    assert trace1.task_id == "task_001", "task_id should be stored"
    assert trace1.feature_id == "F1", "feature_id should be stored"

    logger.end_trace(trace1.trace_id, status="success")
    logger.end_trace(trace2.trace_id, status="success")

    # Verify traces are in log
    events = logger.get_trace_events(trace1.trace_id)
    assert len(events) >= 2, f"Should have at least 2 events (start/end), got {len(events)}"
    event_types = [e.get("event_type") for e in events]
    assert "trace_start" in event_types, "Should have trace_start event"
    assert "trace_end" in event_types, "Should have trace_end event"

    print("   [PASS] Unique trace_id generated per task")

    # Test 3: Link model, tool, and result events
    print("\n3. Testing: Link model, tool, and result events...")
    logger2 = AuditLogger(log_path=log_path)

    trace3 = logger2.start_trace(task_id="task_003", feature_id="M2-004")

    # Log model call
    logger2.log_model_call(
        trace_id=trace3.trace_id,
        model="claude-3-opus",
        provider="anthropic",
        prompt="Write hello world",
    )

    # Log tool call
    call_id = logger2.log_tool_call(
        trace_id=trace3.trace_id,
        tool_name="shell",
        arguments={"command": "echo hello"},
    )

    # Log tool result
    logger2.log_tool_result(
        trace_id=trace3.trace_id,
        tool_name="shell",
        success=True,
        output="hello",
        call_id=call_id,
    )

    # Log policy decision
    logger2.log_policy_decision(
        trace_id=trace3.trace_id,
        tool_name="shell",
        action="allow",
        reason="Command is safe",
        risk_level="low",
    )

    # Log model response
    logger2.log_model_response(
        trace_id=trace3.trace_id,
        response="Done",
        completion_tokens=10,
        latency_ms=100,
    )

    # Log result
    logger2.log_result(
        trace_id=trace3.trace_id,
        status="success",
        message="Task completed",
    )

    logger2.end_trace(trace3.trace_id, status="success", summary="All done")

    # Verify all events are linked by trace_id
    events = logger2.get_trace_events(trace3.trace_id)
    event_types = [e.get("event_type") for e in events]

    expected_types = [
        "trace_start", "model_call", "tool_call", "tool_result",
        "policy_decision", "model_response", "result", "trace_end"
    ]
    for expected in expected_types:
        assert expected in event_types, f"Missing event type: {expected}"

    # Verify all events have the same trace_id
    for event in events:
        assert event.get("trace_id") == trace3.trace_id, "All events should have same trace_id"

    # Verify call_id links tool call and result
    tool_call = next(e for e in events if e.get("event_type") == "tool_call")
    tool_result = next(e for e in events if e.get("event_type") == "tool_result")
    assert tool_call.get("call_id") == tool_result.get("call_id"), "call_id should link call and result"

    print(f"   [PASS] All {len(events)} events linked by trace_id: {trace3.trace_id}")
    print(f"   [PASS] Event types: {event_types}")
    print("   [PASS] call_id links tool_call and tool_result")

    # Test 4: Support replay from logs
    print("\n4. Testing: Support replay from logs...")
    replay = AuditReplay(log_path)

    # List traces
    traces = replay.list_traces()
    assert len(traces) >= 3, f"Should have at least 3 traces, got {len(traces)}"
    print(f"   [PASS] Found {len(traces)} traces in log")

    # Get trace summary
    summary = replay.get_trace_summary(trace3.trace_id)
    assert summary is not None, "Should get trace summary"
    assert summary.trace_id == trace3.trace_id, "Summary trace_id should match"
    assert summary.task_id == "task_003", "Summary task_id should match"
    assert summary.feature_id == "M2-004", "Summary feature_id should match"
    assert summary.status == "success", "Summary status should be success"
    assert summary.event_count >= 8, f"Should have 8+ events, got {summary.event_count}"
    assert "shell" in summary.tool_calls, "Should have shell in tool_calls"
    print(f"   [PASS] Trace summary retrieved: {summary.event_count} events")
    print(f"   [PASS] Tool calls: {summary.tool_calls}")
    print(f"   [PASS] Status: {summary.status}")

    # Replay trace step by step
    steps = replay.replay_trace(trace3.trace_id)
    assert len(steps) >= 8, f"Should have 8+ steps, got {len(steps)}"
    for i, step in enumerate(steps[:4]):  # Show first 4 steps
        print(f"   Step {step.seq}: [{step.event_type}] {step.summary[:60]}...")
    print(f"   [PASS] Replay returned {len(steps)} steps")

    # Test 5: Find traces by feature
    print("\n5. Testing: Find traces by feature...")
    feature_traces = replay.find_traces_by_feature("M2-004")
    assert len(feature_traces) >= 1, "Should find at least 1 trace for M2-004"
    assert trace3.trace_id in feature_traces, "trace3 should be in results"
    print(f"   [PASS] Found {len(feature_traces)} traces for feature M2-004")

    # Test 6: Find traces by status
    print("\n6. Testing: Find traces by status...")
    success_traces = replay.find_traces_by_status("success")
    assert len(success_traces) >= 3, f"Should have 3+ successful traces, got {len(success_traces)}"
    print(f"   [PASS] Found {len(success_traces)} successful traces")

    # Test 7: Get statistics
    print("\n7. Testing: Get statistics...")
    stats = replay.get_statistics()
    assert stats["total_traces"] >= 3, f"Should have 3+ traces, got {stats['total_traces']}"
    assert stats["total_events"] >= 10, f"Should have 10+ events, got {stats['total_events']}"
    assert "success" in stats["statuses"], "Should have success status"
    print(f"   [PASS] Statistics: {stats['total_traces']} traces, {stats['total_events']} events")
    print(f"   [PASS] Tools used: {stats['tools_used']}")

    # Test 8: Export functionality
    print("\n8. Testing: Export functionality...")
    export_path = Path(tmpdir) / "exported_trace.json"
    exported = replay.export_trace(trace3.trace_id, export_path)
    assert exported, "Export should succeed"
    assert export_path.exists(), "Export file should exist"
    with open(export_path) as f:
        exported_events = [json.loads(line) for line in f if line.strip()]
    assert len(exported_events) >= 8, f"Should export 8+ events, got {len(exported_events)}"
    print(f"   [PASS] Exported {len(exported_events)} events to {export_path.name}")

    # Test 9: Sequence ordering
    print("\n9. Testing: Sequence ordering...")
    events = logger2.get_trace_events(trace3.trace_id)
    seqs = [e.get("seq", -1) for e in events]
    assert seqs == sorted(seqs), "Events should be ordered by sequence number"
    print(f"   [PASS] Events properly ordered by sequence: {seqs}")

    # Test 10: Duration calculation
    print("\n10. Testing: Duration calculation...")
    summary = replay.get_trace_summary(trace3.trace_id)
    assert summary.duration_ms is not None, "Duration should be calculated"
    assert summary.duration_ms >= 0, "Duration should be non-negative"
    print(f"   [PASS] Duration calculated: {summary.duration_ms}ms")

print("\n=== M2-004 VERIFICATION PASSED (10/10) ===")
print("\nFeature M2-004 is complete:")
print("- trace_id generation per task: PASS")
print("- Link model, tool, and result events: PASS")
print("- Support replay from logs: PASS")
