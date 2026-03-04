#!/usr/bin/env python3
"""
Verification script for M3-003: Tool Execution Visualization.

Tests:
1. Show called tool and arguments
2. Show execution status and output
3. Display retries and failures
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


def test_imports():
    """Test that all visualization classes can be imported."""
    print("1. Testing: Imports work correctly...")

    try:
        from visualization import (
            ToolStatus,
            Severity,
            RetryInfo,
            ArgumentDisplay,
            ToolExecutionView,
            ToolExecutionSummary,
            ToolExecutionBuilder,
            build_tool_view,
            ToolExecutionRenderer,
            render_tool_execution,
            render_tool_compact,
        )
        print("   [PASS] All visualization classes imported successfully")
        return True
    except ImportError as e:
        print(f"   [FAIL] Import error: {e}")
        return False


def test_show_tool_and_arguments():
    """Test that tool name and arguments are displayed correctly."""
    print("\n2. Testing: Show called tool and arguments...")

    from visualization import ToolExecutionBuilder, ToolExecutionRenderer

    builder = ToolExecutionBuilder()

    # Test with various argument types
    view = builder.build_from_result(
        call_id="test_001",
        tool_name="shell",
        arguments={
            "command": "ls -la",
            "timeout": 30,
            "cwd": "/home/user",
        },
        success=True,
        output="file1.txt\nfile2.py",
    )

    renderer = ToolExecutionRenderer(use_colors=False)
    output = renderer.render(view)

    # Verify tool name appears
    if "shell" not in output:
        print("   [FAIL] Tool name not in output")
        return False
    print("   [PASS] Tool name displayed correctly")

    # Verify arguments appear
    if "command" not in output or "ls -la" not in output:
        print("   [FAIL] Command argument not in output")
        return False
    print("   [PASS] Arguments displayed correctly")

    # Verify argument formatting
    if "timeout" not in output or "30" not in output:
        print("   [FAIL] Numeric argument not in output")
        return False
    print("   [PASS] Numeric arguments formatted correctly")

    # Test sensitive argument masking
    view_sensitive = builder.build_from_result(
        call_id="test_002",
        tool_name="web",
        arguments={
            "url": "https://api.example.com",
            "api_key": "secret123",
        },
        success=True,
        output="{}",
    )

    output_sensitive = renderer.render(view_sensitive)

    # Verify sensitive value is masked
    if "secret123" in output_sensitive:
        print("   [FAIL] Sensitive argument not masked")
        return False
    if "api_key" not in output_sensitive:
        print("   [FAIL] Sensitive argument name missing")
        return False
    print("   [PASS] Sensitive arguments masked correctly")

    # Test compact format
    compact = renderer.render_compact(view)
    if "shell" not in compact:
        print("   [FAIL] Compact format missing tool name")
        return False
    print("   [PASS] Compact format works correctly")

    return True


def test_show_status_and_output():
    """Test that execution status and output are displayed correctly."""
    print("\n3. Testing: Show execution status and output...")

    from visualization import ToolExecutionBuilder, ToolExecutionRenderer, ToolStatus

    builder = ToolExecutionBuilder()
    renderer = ToolExecutionRenderer(use_colors=False)

    # Test success status
    view_success = builder.build_from_result(
        call_id="test_success",
        tool_name="file",
        arguments={"operation": "read", "path": "/tmp/test.txt"},
        success=True,
        output="Hello, World!",
        latency_ms=150,
    )

    output_success = renderer.render(view_success)

    if "success" not in output_success.lower():
        print("   [FAIL] Success status not displayed")
        return False
    print("   [PASS] Success status displayed correctly")

    if "Hello, World!" not in output_success:
        print("   [FAIL] Output not displayed")
        return False
    print("   [PASS] Output displayed correctly")

    if "150" not in output_success and "ms" not in output_success:
        print("   [FAIL] Latency not displayed")
        return False
    print("   [PASS] Latency displayed correctly")

    # Test error status
    view_error = builder.build_from_result(
        call_id="test_error",
        tool_name="shell",
        arguments={"command": "cat /nonexistent"},
        success=False,
        output="",
        error="No such file or directory",
    )

    output_error = renderer.render(view_error)

    if "error" not in output_error.lower():
        print("   [FAIL] Error status not displayed")
        return False
    print("   [PASS] Error status displayed correctly")

    if "No such file or directory" not in output_error:
        print("   [FAIL] Error message not displayed")
        return False
    print("   [PASS] Error message displayed correctly")

    # Test blocked status
    view_blocked = builder.build_from_result(
        call_id="test_blocked",
        tool_name="shell",
        arguments={"command": "rm -rf /"},
        success=False,
        blocked_reason="Destructive command blocked by policy",
        alternative="Use safer alternatives for file deletion",
    )

    output_blocked = renderer.render(view_blocked)

    if "blocked" not in output_blocked.lower():
        print("   [FAIL] Blocked status not displayed")
        return False
    print("   [PASS] Blocked status displayed correctly")

    if "safer alternative" not in output_blocked.lower():
        print("   [FAIL] Alternative not displayed")
        return False
    print("   [PASS] Alternative suggestion displayed correctly")

    # Test output truncation
    long_output = "x" * 1000
    view_long = builder.build_from_result(
        call_id="test_long",
        tool_name="file",
        arguments={"operation": "read", "path": "/tmp/large.txt"},
        success=True,
        output=long_output,
    )

    output_long = renderer.render(view_long)

    if view_long.output_truncated:
        print("   [PASS] Output truncation detected correctly")
    else:
        print("   [FAIL] Output truncation not detected")
        return False

    # Test summary
    summary = builder.build_summary("trace_001", [view_success, view_error])
    summary_output = renderer.render_summary(summary)

    if "Total: 2" not in summary_output:
        print("   [FAIL] Summary total count incorrect")
        return False
    print("   [PASS] Summary total count correct")

    if "Success: 1" not in summary_output:
        print("   [FAIL] Summary success count incorrect")
        return False
    print("   [PASS] Summary success count correct")

    if "Failed: 1" not in summary_output:
        print("   [FAIL] Summary failure count incorrect")
        return False
    print("   [PASS] Summary failure count correct")

    return True


def test_show_retries_and_failures():
    """Test that retry attempts and failures are displayed correctly."""
    print("\n4. Testing: Display retries and failures...")

    from visualization import ToolExecutionBuilder, ToolExecutionRenderer, RetryInfo

    builder = ToolExecutionBuilder()
    renderer = ToolExecutionRenderer(use_colors=False)

    # Create retry info
    retries = [
        RetryInfo(
            attempt=1,
            max_retries=3,
            error="Connection timeout",
            delay_ms=1000,
        ),
        RetryInfo(
            attempt=2,
            max_retries=3,
            error="Connection timeout",
            delay_ms=2000,
        ),
    ]

    # Test view with retries that eventually succeeded
    view_retry_success = builder.build_from_result(
        call_id="test_retry_success",
        tool_name="web",
        arguments={"operation": "fetch", "url": "https://example.com"},
        success=True,
        output='{"status": "ok"}',
        latency_ms=5000,
        retries=retries,
    )

    output_retry = renderer.render(view_retry_success)

    if "retry" not in output_retry.lower():
        print("   [FAIL] Retry information not displayed")
        return False
    print("   [PASS] Retry information displayed correctly")

    if "1/3" not in output_retry or "2/3" not in output_retry:
        print("   [FAIL] Retry attempt numbers not displayed")
        return False
    print("   [PASS] Retry attempt numbers displayed correctly")

    if "Connection timeout" not in output_retry:
        print("   [FAIL] Retry error message not displayed")
        return False
    print("   [PASS] Retry error message displayed correctly")

    if "3 attempts" not in output_retry:  # 2 retries + 1 original
        print("   [FAIL] Total attempts not displayed")
        return False
    print("   [PASS] Total attempts displayed correctly")

    # Test compact view with retries
    compact_retry = renderer.render_compact(view_retry_success)

    if "3x" not in compact_retry:
        print("   [FAIL] Retry indicator not in compact view")
        return False
    print("   [PASS] Retry indicator in compact view")

    # Test view with exhausted retries
    view_retry_failed = builder.build_from_result(
        call_id="test_retry_failed",
        tool_name="web",
        arguments={"operation": "fetch", "url": "https://unreliable.example.com"},
        success=False,
        error="All retries exhausted: Connection timeout (retried 3 times)",
        retries=retries,
    )

    output_failed = renderer.render(view_retry_failed)

    if "error" not in output_failed.lower():
        print("   [FAIL] Failed status after retries not displayed")
        return False
    print("   [PASS] Failed status after retries displayed correctly")

    # Test building from audit events
    tool_call_event = {
        "call_id": "audit_call_001",
        "tool_name": "shell",
        "arguments": {"command": "echo test"},
        "trace_id": "trace_002",
        "at": "2026-03-05T10:00:00",
    }

    tool_result_event = {
        "success": True,
        "output": "test\n",
        "latency_ms": 50,
        "at": "2026-03-05T10:00:00.050",
    }

    retry_events = [
        {
            "attempt": 1,
            "max_retries": 2,
            "error": "Process busy",
            "delay_ms": 500,
            "at": "2026-03-05T10:00:00.010",
        },
    ]

    view_from_audit = builder.build_from_audit_events(
        tool_call_event=tool_call_event,
        tool_result_event=tool_result_event,
        retry_events=retry_events,
    )

    if view_from_audit.call_id != "audit_call_001":
        print("   [FAIL] Call ID not preserved from audit event")
        return False
    print("   [PASS] Call ID preserved from audit event")

    if view_from_audit.tool_name != "shell":
        print("   [FAIL] Tool name not preserved from audit event")
        return False
    print("   [PASS] Tool name preserved from audit event")

    if len(view_from_audit.retries) != 1:
        print("   [FAIL] Retries not built from audit events")
        return False
    print("   [PASS] Retries built from audit events correctly")

    return True


def test_convenience_functions():
    """Test convenience functions."""
    print("\n5. Testing: Convenience functions...")

    from visualization import build_tool_view, render_tool_execution, render_tool_compact

    # Test build_tool_view
    view = build_tool_view(
        call_id="conv_001",
        tool_name="file",
        arguments={"operation": "write", "path": "/tmp/test.txt", "content": "Hello"},
        success=True,
        output="Wrote 5 bytes",
        latency_ms=25,
    )

    if view.tool_name != "file":
        print("   [FAIL] build_tool_view failed")
        return False
    print("   [PASS] build_tool_view works correctly")

    # Test render_tool_execution
    output = render_tool_execution(view, use_colors=False)
    if "file" not in output:
        print("   [FAIL] render_tool_execution failed")
        return False
    print("   [PASS] render_tool_execution works correctly")

    # Test render_tool_compact
    compact = render_tool_compact(view, use_colors=False)
    if "file" not in compact:
        print("   [FAIL] render_tool_compact failed")
        return False
    print("   [PASS] render_tool_compact works correctly")

    return True


def test_render_list():
    """Test rendering multiple tool executions."""
    print("\n6. Testing: Render list of executions...")

    from visualization import ToolExecutionBuilder, ToolExecutionRenderer

    builder = ToolExecutionBuilder()
    renderer = ToolExecutionRenderer(use_colors=False)

    views = [
        builder.build_from_result(
            call_id="list_001",
            tool_name="file",
            arguments={"operation": "read", "path": "/a.txt"},
            success=True,
            output="content a",
        ),
        builder.build_from_result(
            call_id="list_002",
            tool_name="shell",
            arguments={"command": "ls"},
            success=True,
            output="file1\nfile2",
        ),
        builder.build_from_result(
            call_id="list_003",
            tool_name="web",
            arguments={"url": "https://example.com"},
            success=False,
            error="Timeout",
        ),
    ]

    output = renderer.render_list(views, compact=True)

    # In compact mode, tool names should appear
    if "file" not in output:
        print("   [FAIL] Tool name not in compact list output")
        return False
    print("   [PASS] Tool names in compact list output")

    # Check that all tools appear in output
    if "shell" not in output or "web" not in output:
        print("   [FAIL] Not all tools in list output")
        return False
    print("   [PASS] All tools in list output")

    # Count the numbered items
    if "1." not in output or "2." not in output or "3." not in output:
        print("   [FAIL] List numbering missing")
        return False
    print("   [PASS] List numbering correct")

    return True


def main():
    """Run all verification tests."""
    print("=== M3-003 VERIFICATION: Tool Execution Visualization ===\n")

    tests = [
        test_imports,
        test_show_tool_and_arguments,
        test_show_status_and_output,
        test_show_retries_and_failures,
        test_convenience_functions,
        test_render_list,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"   [FAIL] Test raised exception: {e}")
            failed += 1

    print(f"\n=== M3-003 VERIFICATION {'PASSED' if failed == 0 else 'FAILED'} ({passed}/{len(tests)}) ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
