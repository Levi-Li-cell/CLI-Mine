"""Verification script for M5-002: cost and latency observability."""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from observability import CostLatencyMonitor


def pass_line(msg: str) -> None:
    print(f"   [PASS] {msg}")


def fail_line(msg: str, reason: str = "") -> None:
    print(f"   [FAIL] {msg}")
    if reason:
        print(f"          Reason: {reason}")
    raise SystemExit(1)


def write_jsonl(path: Path, rows):
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")


def main() -> None:
    print("=== M5-002 VERIFICATION: Cost and Latency Observability ===\n")
    tmp = Path(tempfile.mkdtemp(prefix="m5_002_test_"))

    try:
        audit_file = tmp / "audit.jsonl"
        status_file = tmp / "cost_latency_status.json"

        rows = [
            {"event_type": "model_response", "latency_ms": 100, "total_tokens": 1200},
            {"event_type": "model_response", "latency_ms": 200, "total_tokens": 800},
            {"event_type": "tool_call", "tool_name": "shell"},
            {"event_type": "tool_result", "tool_name": "shell", "latency_ms": 300},
            {"event_type": "tool_call", "tool_name": "file"},
            {"event_type": "tool_result", "tool_name": "file", "latency_ms": 500},
        ]
        write_jsonl(audit_file, rows)

        print("1. Testing: token/tool cost metrics...")
        monitor = CostLatencyMonitor(
            status_file=status_file,
            token_cost_per_1k=0.01,
            tool_call_cost=0.05,
            budget_threshold=1.0,
        )
        status = monitor.analyze_audit_log(audit_file)
        metrics = status.get("metrics", {})
        if metrics.get("total_tokens") != 2000:
            fail_line("Total token count", f"got={metrics.get('total_tokens')}")
        if metrics.get("tool_calls") != 2:
            fail_line("Tool call count", f"got={metrics.get('tool_calls')}")
        if metrics.get("token_cost") != 0.02:
            fail_line("Token cost", f"got={metrics.get('token_cost')}")
        if metrics.get("tool_cost") != 0.1:
            fail_line("Tool cost", f"got={metrics.get('tool_cost')}")
        if metrics.get("total_cost") != 0.12:
            fail_line("Total cost", f"got={metrics.get('total_cost')}")
        pass_line("Cost metrics computed correctly")

        print("\n2. Testing: p50/p95 latency metrics...")
        p50 = metrics.get("p50_latency_ms")
        p95 = metrics.get("p95_latency_ms")
        if not isinstance(p50, (int, float)) or not isinstance(p95, (int, float)):
            fail_line("Latency metric types", f"p50={p50}, p95={p95}")
        if p50 <= 0 or p95 <= 0:
            fail_line("Latency metric values", f"p50={p50}, p95={p95}")
        if p95 < p50:
            fail_line("Percentile ordering", f"p50={p50}, p95={p95}")
        pass_line("Latency p50/p95 metrics computed")

        print("\n3. Testing: budget threshold alerting...")
        monitor2 = CostLatencyMonitor(
            status_file=status_file,
            token_cost_per_1k=0.5,
            tool_call_cost=0.5,
            budget_threshold=0.5,
        )
        status2 = monitor2.analyze_audit_log(audit_file)
        if status2.get("ok") is not False:
            fail_line("Budget alert ok flag", f"status={status2.get('ok')}")
        alerts = status2.get("alerts", [])
        if not alerts:
            fail_line("Budget alerts", "expected at least one alert")
        if "budget threshold exceeded" not in alerts[0]:
            fail_line("Budget alert message", f"alerts={alerts}")
        pass_line("Budget threshold alert is triggered")

        print("\n4. Testing: status file is written atomically...")
        if not status_file.exists():
            fail_line("Status file exists", "file not created")
        loaded = json.loads(status_file.read_text(encoding="utf-8"))
        if "metrics" not in loaded:
            fail_line("Status file shape", "missing metrics")
        pass_line("Status file persisted with observability metrics")

        print("\n=== M5-002 VERIFICATION PASSED ===")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
