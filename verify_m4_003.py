#!/usr/bin/env python
"""
Verification script for M4-003: Multi-agent roles: coder, tester, reviewer.

Tests:
1. Dispatch tasks to role-specific prompts
2. Aggregate outputs into one decision
3. Escalate conflicts to reviewer
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agents import AgentRole, create_dispatcher, create_orchestrator


def test_passed(msg: str) -> None:
    print(f"   [PASS] {msg}")


def test_failed(msg: str) -> None:
    print(f"   [FAIL] {msg}")
    sys.exit(1)


def make_fake_executor(mode: str):
    """Build fake agent executor returning role-tagged outputs."""

    def _run(prompt_file: str, timeout_seconds: int):
        content = Path(prompt_file).read_text(encoding="utf-8")

        if "## Role: Reviewer" in content:
            return (
                "## Final Answer\n"
                "- Role: Reviewer\n"
                "- Status: REVISE\n"
                "- Summary: Conflict confirmed, revision required.\n"
                "- Files Modified: [harness.py]\n"
                "- Files Created: []\n"
                "- Issues Found: [align tests and implementation]\n"
                "- Suggestions: [address failing integration test]\n"
                "- Confidence: 0.7\n",
                "",
                0,
            )

        if "## Role: Tester" in content:
            if mode == "conflict":
                return (
                    "## Final Answer\n"
                    "- Role: Tester\n"
                    "- Status: BLOCKED\n"
                    "- Summary: Tests found failing path.\n"
                    "- Files Modified: [verify_m4_003.py]\n"
                    "- Files Created: []\n"
                    "- Issues Found: [failing integration test]\n"
                    "- Suggestions: [fix edge case]\n"
                    "- Confidence: 0.3\n",
                    "",
                    0,
                )
            return (
                "## Final Answer\n"
                "- Role: Tester\n"
                "- Status: COMPLETE\n"
                "- Summary: All tests passed.\n"
                "- Files Modified: [verify_m4_003.py]\n"
                "- Files Created: []\n"
                "- Issues Found: []\n"
                "- Suggestions: []\n"
                "- Confidence: 0.8\n",
                "",
                0,
            )

        if "## Role: Coder" in content:
            return (
                "## Final Answer\n"
                "- Role: Coder\n"
                "- Status: COMPLETE\n"
                "- Summary: Implemented feature core logic.\n"
                "- Files Modified: [harness.py]\n"
                "- Files Created: []\n"
                "- Issues Found: []\n"
                "- Suggestions: []\n"
                "- Confidence: 0.9\n",
                "",
                0,
            )

        return "", "Unknown role in prompt", 1

    return _run


def run_tests() -> None:
    print("=== M4-003 VERIFICATION: Multi-agent Roles ===\n")

    root = Path(__file__).parent
    feature = {
        "id": "M4-003",
        "priority": "P1",
        "description": "Multi-agent roles: coder, tester, reviewer",
    }
    goal_text = "Implement role-based dispatch and conflict escalation."

    print("1. Testing: Dispatch tasks to role-specific prompts...")
    dispatcher = create_dispatcher(
        command_template='python -c "print(0)"',
        root_dir=root,
        timeout_seconds=60,
        agent_executor=make_fake_executor(mode="clean"),
    )
    task, output = dispatcher.dispatch(
        role=AgentRole.CODER,
        feature_id="M4-003",
        goal_text=goal_text,
        feature=feature,
        context={"scope": "dispatch"},
        cycle_tag="verify_m4_003_coder",
    )
    if task.role != AgentRole.CODER:
        test_failed("Coder task role mismatch")
    if not output.success or output.summary == "":
        test_failed("Coder output parsing failed")
    test_passed("Role-specific dispatch and parsing work")

    print("\n2. Testing: Aggregate outputs into one decision...")
    orchestrator_clean = create_orchestrator(
        command_template='python -c "print(0)"',
        root_dir=root,
        timeout_seconds=60,
        agent_executor=make_fake_executor(mode="clean"),
    )
    wf_clean = orchestrator_clean.run_workflow(
        feature_id="M4-003",
        goal_text=goal_text,
        feature=feature,
        cycle_tag="verify_m4_003_clean",
    )
    if not wf_clean.decision or wf_clean.decision.decision.value != "approve":
        test_failed("Expected approve decision for clean workflow")
    if len(wf_clean.outputs) != 2:
        test_failed(f"Expected 2 outputs (coder+tester), got {len(wf_clean.outputs)}")
    test_passed("Outputs are aggregated into a single approve decision")

    print("\n3. Testing: Escalate conflicts to reviewer...")
    orchestrator_conflict = create_orchestrator(
        command_template='python -c "print(0)"',
        root_dir=root,
        timeout_seconds=60,
        agent_executor=make_fake_executor(mode="conflict"),
    )
    wf_conflict = orchestrator_conflict.run_workflow(
        feature_id="M4-003",
        goal_text=goal_text,
        feature=feature,
        cycle_tag="verify_m4_003_conflict",
    )
    if len(wf_conflict.conflicts) == 0:
        test_failed("Expected detected conflicts")
    if len(wf_conflict.outputs) != 3:
        test_failed(f"Expected 3 outputs (coder+tester+reviewer), got {len(wf_conflict.outputs)}")
    latest_role = wf_conflict.outputs[-1].role.value
    if latest_role != "reviewer":
        test_failed(f"Expected reviewer escalation, got {latest_role}")
    if wf_conflict.decision.decision.value not in ("revise", "reject", "escalate"):
        test_failed("Conflict workflow should require revision/reject/escalate")
    test_passed("Conflicts trigger reviewer escalation and non-approve decision")

    print("\n=== M4-003 VERIFICATION PASSED ===")


if __name__ == "__main__":
    run_tests()
