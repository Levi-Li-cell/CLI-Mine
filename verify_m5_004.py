"""Verification script for M5-004: deployment runbook and rollback procedure."""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ops import RUNTIME_CLEANUP_TARGETS, build_rollback_plan, choose_known_good_commit


def ok(msg: str) -> None:
    print(f"   [PASS] {msg}")


def fail(msg: str, reason: str = "") -> None:
    print(f"   [FAIL] {msg}")
    if reason:
        print(f"          Reason: {reason}")
    raise SystemExit(1)


def main() -> None:
    print("=== M5-004 VERIFICATION: Deployment Runbook and Rollback ===\n")

    root = Path(__file__).parent.resolve()

    print("1. Testing: runbook file exists and has required sections...")
    runbook = root / "deployment_runbook.md"
    if not runbook.exists():
        fail("Runbook exists", "deployment_runbook.md not found")
    text = runbook.read_text(encoding="utf-8")
    required_sections = [
        "## Deployment Steps",
        "## Rollback Criteria",
        "## Rollback Procedure",
    ]
    for section in required_sections:
        if section not in text:
            fail("Runbook sections", f"missing section: {section}")
    ok("Runbook contains deployment/rollback guidance")

    print("\n2. Testing: known-good commit selection...")
    commit = choose_known_good_commit(root)
    if not commit or len(commit) < 7:
        fail("Known-good commit selection", f"commit={commit}")
    ok("Known-good commit can be selected from history")

    print("\n3. Testing: rollback plan generation...")
    plan = build_rollback_plan(root, known_good_commit=commit)
    if plan.get("known_good_commit") != commit:
        fail("Rollback plan commit", f"plan={plan}")
    if not plan.get("checkout_command", "").startswith("git checkout "):
        fail("Rollback checkout command", f"cmd={plan.get('checkout_command')}")
    cleanup_targets = plan.get("cleanup_targets", [])
    for required in RUNTIME_CLEANUP_TARGETS:
        if required not in cleanup_targets:
            fail("Rollback cleanup targets", f"missing={required}")
    commands = plan.get("post_rollback_commands", [])
    if len(commands) < 3:
        fail("Rollback post commands", f"commands={commands}")
    ok("Rollback plan includes commit, cleanup targets, and validation commands")

    print("\n4. Testing: rollback procedure test marker in runbook...")
    if "Rollback Validation (Tested Once)" not in text:
        fail("Rollback validation section")
    if "python verify_m5_004.py" not in text:
        fail("Rollback verification command")
    ok("Runbook documents tested rollback validation")

    print("\n=== M5-004 VERIFICATION PASSED ===")


if __name__ == "__main__":
    main()
