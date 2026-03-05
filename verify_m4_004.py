#!/usr/bin/env python
"""
Verification script for M4-004: Health checks and alerting.

Tests:
1. Heartbeat detects stalled loop
2. Alert on repeated failures
3. Expose health status file
"""

import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from health import HealthMonitor


def test_passed(msg: str) -> None:
    print(f"   [PASS] {msg}")


def test_failed(msg: str) -> None:
    print(f"   [FAIL] {msg}")
    raise SystemExit(1)


def run_tests() -> None:
    print("=== M4-004 VERIFICATION: Health Checks and Alerting ===\n")

    temp_dir = Path(tempfile.mkdtemp(prefix="m4_004_"))
    status_file = temp_dir / "health_status.json"
    log_file = temp_dir / "harness.log"
    monitor = HealthMonitor(status_file=status_file)

    print("1. Testing: Heartbeat detects stalled loop...")
    old_ts = (datetime.now() - timedelta(seconds=1200)).isoformat(timespec="seconds")
    log_file.write_text(f"[{old_ts}] cycle start cycle_000001 feature_id=M4-004\n", encoding="utf-8")
    stalled = monitor.analyze_harness_log(
        log_path=log_file,
        stalled_after_seconds=300,
        failure_alert_threshold=5,
        now=datetime.now(),
    )
    if not stalled["metrics"].get("stalled"):
        test_failed("Expected stalled loop detection")
    if not stalled.get("alerts"):
        test_failed("Expected stalled alert message")
    test_passed("Stalled loop detected via heartbeat gap")

    print("\n2. Testing: Alert on repeated failures...")
    now = datetime.now()
    lines = []
    for i in range(1, 5):
        ts = (now - timedelta(seconds=(10 - i))).isoformat(timespec="seconds")
        lines.append(f"[{ts}] cycle end cycle_{i:06d} rc=1")
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    failures = monitor.analyze_harness_log(
        log_path=log_file,
        stalled_after_seconds=10000,
        failure_alert_threshold=3,
        now=datetime.now(),
    )
    if failures["metrics"].get("consecutive_failed_cycles", 0) < 3:
        test_failed("Expected consecutive failure count >= 3")
    if not any("repeated failures" in a for a in failures.get("alerts", [])):
        test_failed("Expected repeated failure alert")
    test_passed("Repeated failure alert triggered")

    print("\n3. Testing: Expose health status file...")
    ok_status = monitor.update_heartbeat(source="verify")
    if not status_file.exists():
        test_failed("health_status.json should exist")
    loaded = monitor.load_status()
    if not loaded or loaded.get("source") != "verify":
        test_failed("Health status file load mismatch")
    if not ok_status.get("heartbeat_at"):
        test_failed("Expected heartbeat timestamp")
    test_passed("Health status file is written and readable")

    print("\n=== M4-004 VERIFICATION PASSED ===")


if __name__ == "__main__":
    run_tests()
