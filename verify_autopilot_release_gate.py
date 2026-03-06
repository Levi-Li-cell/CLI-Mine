#!/usr/bin/env python
"""Verification for autopilot release gate and budget guard."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import autopilot


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    raise SystemExit(1)


def ok(msg: str) -> None:
    print(f"[PASS] {msg}")


def main() -> None:
    print("=== verify_autopilot_release_gate ===")
    temp_dir = Path(tempfile.mkdtemp(prefix="autopilot_gate_"))

    old_root = autopilot.ROOT
    old_log = autopilot.LOG_FILE
    old_debug = autopilot.DEBUG_LOG_FILE
    old_obs = autopilot.OBSERVABILITY_STATUS_FILE
    try:
        autopilot.ROOT = temp_dir
        autopilot.LOG_FILE = temp_dir / ".agent" / "runtime" / "autopilot.log"
        autopilot.DEBUG_LOG_FILE = temp_dir / ".agent" / "runtime" / "autopilot.debug.log"
        autopilot.OBSERVABILITY_STATUS_FILE = temp_dir / ".agent" / "runtime" / "cost_latency_status.json"

        cfg_pass = {
            "autopilot_release_gate_commands": [f'"{sys.executable}" -c "print(123)"'],
            "autopilot_release_gate_timeout_seconds": 20,
        }
        if not autopilot.run_release_gate(temp_dir, cfg_pass):
            fail("release gate should pass for successful command")
        ok("release gate passes on successful commands")

        cfg_fail = {
            "autopilot_release_gate_commands": [f'"{sys.executable}" -c "import sys; sys.exit(3)"'],
            "autopilot_release_gate_timeout_seconds": 20,
        }
        if autopilot.run_release_gate(temp_dir, cfg_fail):
            fail("release gate should fail for non-zero command")
        ok("release gate fails on failing command")

        status_path = temp_dir / ".agent" / "runtime" / "cost_latency_status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(
            json.dumps({"metrics": {"total_cost": 0.5}}, ensure_ascii=True),
            encoding="utf-8",
        )

        cfg_budget_ok = {
            "autopilot_budget_hard_limit": 1.0,
            "observability_status_file": ".agent/runtime/cost_latency_status.json",
        }
        if not autopilot.check_budget_guard(temp_dir, cfg_budget_ok):
            fail("budget guard should pass when under hard limit")
        ok("budget guard passes when cost is below limit")

        cfg_budget_block = {
            "autopilot_budget_hard_limit": 0.1,
            "observability_status_file": ".agent/runtime/cost_latency_status.json",
        }
        if autopilot.check_budget_guard(temp_dir, cfg_budget_block):
            fail("budget guard should block when over hard limit")
        ok("budget guard blocks when cost exceeds limit")

        print("=== verify_autopilot_release_gate PASSED ===")
    finally:
        autopilot.ROOT = old_root
        autopilot.LOG_FILE = old_log
        autopilot.DEBUG_LOG_FILE = old_debug
        autopilot.OBSERVABILITY_STATUS_FILE = old_obs


if __name__ == "__main__":
    main()
