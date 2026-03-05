#!/usr/bin/env python
"""Verification for autopilot failure guard and state persistence."""

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
    print("=== verify_autopilot_guard ===")
    temp_dir = Path(tempfile.mkdtemp(prefix="autopilot_guard_"))

    old_root = autopilot.ROOT
    old_state = autopilot.STATE_FILE
    old_log = autopilot.LOG_FILE
    old_debug = autopilot.DEBUG_LOG_FILE
    try:
        autopilot.ROOT = temp_dir
        autopilot.STATE_FILE = temp_dir / ".agent" / "runtime" / "autopilot_state.json"
        autopilot.LOG_FILE = temp_dir / ".agent" / "runtime" / "autopilot.log"
        autopilot.DEBUG_LOG_FILE = temp_dir / ".agent" / "runtime" / "autopilot.debug.log"

        state = autopilot.load_state()
        if state.get("consecutive_failures") != 0:
            fail("initial failure count should be 0")
        ok("initial state is empty")

        autopilot.record_failure(state, "test_one")
        state = autopilot.load_state()
        if state.get("consecutive_failures") != 1:
            fail("failure count should become 1")
        if state.get("last_failure") != "test_one":
            fail("last_failure should be test_one")
        ok("record_failure increments state")

        autopilot.record_failure(state, "test_two")
        state = autopilot.load_state()
        if state.get("consecutive_failures") != 2:
            fail("failure count should become 2")
        if state.get("last_failure") != "test_two":
            fail("last_failure should be test_two")
        ok("state persists across writes")

        autopilot.reset_failure_state(state)
        state = autopilot.load_state()
        if state.get("consecutive_failures") != 0:
            fail("failure count should reset to 0")
        if state.get("last_failure") != "":
            fail("last_failure should reset to empty")
        ok("reset_failure_state clears counters")

        print("=== verify_autopilot_guard PASSED ===")
    finally:
        autopilot.ROOT = old_root
        autopilot.STATE_FILE = old_state
        autopilot.LOG_FILE = old_log
        autopilot.DEBUG_LOG_FILE = old_debug


if __name__ == "__main__":
    main()
