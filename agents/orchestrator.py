"""
Workflow orchestrator for M4-003: Multi-agent roles.

Coordinates coder, tester, and reviewer role execution,
aggregates outputs into a single decision, and escalates conflicts.
"""

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .dispatcher import TaskDispatcher, create_dispatcher
from .models import (
    AgentRole,
    AgentOutput,
    Conflict,
    ConflictType,
    AggregatedDecision,
    DecisionType,
    WorkflowState,
)


class MultiAgentOrchestrator:
    """Run multi-agent workflows for a single feature."""

    def __init__(self, dispatcher: TaskDispatcher, max_iterations: int = 2):
        self.dispatcher = dispatcher
        self.max_iterations = max(1, int(max_iterations))

    def _new_workflow(self, feature_id: str, feature: Dict[str, Any]) -> WorkflowState:
        return WorkflowState(
            workflow_id=f"wf_{feature_id}_{uuid.uuid4().hex[:8]}",
            feature_id=feature_id,
            feature=feature,
            max_iterations=self.max_iterations,
            status="running",
            current_phase="coder",
            iteration=1,
        )

    def _detect_conflicts(
        self,
        feature_id: str,
        coder_output: AgentOutput,
        tester_output: AgentOutput,
    ) -> List[Conflict]:
        conflicts: List[Conflict] = []

        if not coder_output.success:
            conflicts.append(
                Conflict(
                    conflict_id=f"conf_{uuid.uuid4().hex[:8]}",
                    conflict_type=ConflictType.MISSING_REQUIREMENTS,
                    feature_id=feature_id,
                    description="Coder output indicates incomplete implementation.",
                    source_outputs=[coder_output.task_id],
                    severity=4,
                )
            )

        if not tester_output.success:
            conflicts.append(
                Conflict(
                    conflict_id=f"conf_{uuid.uuid4().hex[:8]}",
                    conflict_type=ConflictType.TEST_FAILURE,
                    feature_id=feature_id,
                    description="Tester output indicates failing validation.",
                    source_outputs=[tester_output.task_id],
                    severity=4,
                )
            )

        if tester_output.issues:
            conflicts.append(
                Conflict(
                    conflict_id=f"conf_{uuid.uuid4().hex[:8]}",
                    conflict_type=ConflictType.CODE_REVIEW,
                    feature_id=feature_id,
                    description="Tester reported issues requiring review.",
                    source_outputs=[coder_output.task_id, tester_output.task_id],
                    severity=3,
                    metadata={"issues": tester_output.issues[:10]},
                )
            )

        if (
            coder_output.confidence >= 0.8
            and tester_output.confidence <= 0.4
            and coder_output.success
            and not tester_output.success
        ):
            conflicts.append(
                Conflict(
                    conflict_id=f"conf_{uuid.uuid4().hex[:8]}",
                    conflict_type=ConflictType.DESIGN_DISAGREEMENT,
                    feature_id=feature_id,
                    description="Coder and tester confidence diverge significantly.",
                    source_outputs=[coder_output.task_id, tester_output.task_id],
                    severity=2,
                )
            )

        return conflicts

    def _build_decision(
        self,
        feature_id: str,
        outputs: List[AgentOutput],
        conflicts: List[Conflict],
        reviewer_output: Optional[AgentOutput] = None,
    ) -> AggregatedDecision:
        reviewer_summary = reviewer_output.summary if reviewer_output else ""
        avg_confidence = sum(o.confidence for o in outputs) / max(1, len(outputs))

        required_actions: List[str] = []
        for output in outputs:
            required_actions.extend(output.issues)

        approved_files: List[str] = []
        rejected_files: List[str] = []
        for output in outputs:
            approved_files.extend(output.files_created)
            approved_files.extend(output.files_modified)
            if output.issues:
                rejected_files.extend(output.files_modified)

        approved_files = sorted(set(approved_files))
        rejected_files = sorted(set(rejected_files))

        decision = DecisionType.APPROVE
        summary = "Coder and tester outputs are consistent."

        if conflicts:
            decision = DecisionType.REVISE
            summary = f"Detected {len(conflicts)} conflict(s); reviewer input required."

        if reviewer_output:
            reviewer_status = (reviewer_output.metadata.get("parsed_status") or "").upper()
            if reviewer_status in ("REJECT", "BLOCKED"):
                decision = DecisionType.REJECT
                summary = reviewer_output.summary or "Reviewer rejected current implementation."
            elif reviewer_status in ("REVISE", "PARTIAL"):
                decision = DecisionType.REVISE
                summary = reviewer_output.summary or "Reviewer requests revisions."
            elif reviewer_status in ("ESCALATE",):
                decision = DecisionType.ESCALATE
                summary = reviewer_output.summary or "Reviewer escalated to human decision."
            elif reviewer_output.success:
                if conflicts:
                    decision = DecisionType.REVISE
                    summary = reviewer_output.summary or "Reviewer completed, revisions still required."
                else:
                    decision = DecisionType.APPROVE
                    summary = reviewer_output.summary or "Reviewer approved implementation."

            required_actions.extend(reviewer_output.issues)
            for f in reviewer_output.files_modified:
                if f not in approved_files:
                    approved_files.append(f)

        return AggregatedDecision(
            feature_id=feature_id,
            decision=decision,
            confidence=max(0.0, min(1.0, avg_confidence)),
            summary=summary,
            outputs=outputs,
            conflicts=conflicts,
            required_actions=sorted(set(required_actions)),
            approved_files=sorted(set(approved_files)),
            rejected_files=rejected_files,
            review_notes=reviewer_summary,
            metadata={
                "escalated_to_reviewer": bool(conflicts),
                "output_count": len(outputs),
            },
        )

    def run_workflow(
        self,
        feature_id: str,
        goal_text: str,
        feature: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        cycle_tag: Optional[str] = None,
    ) -> WorkflowState:
        workflow = self._new_workflow(feature_id, feature)
        ctx = context or {}

        coder_task, coder_output = self.dispatcher.dispatch(
            role=AgentRole.CODER,
            feature_id=feature_id,
            goal_text=goal_text,
            feature=feature,
            context=ctx,
            cycle_tag=f"{cycle_tag}_coder" if cycle_tag else None,
        )
        workflow.add_task(coder_task)
        workflow.add_output(coder_output)

        tester_task, tester_output = self.dispatcher.dispatch(
            role=AgentRole.TESTER,
            feature_id=feature_id,
            goal_text=goal_text,
            feature=feature,
            previous_outputs={"coder": coder_output.content},
            context=ctx,
            cycle_tag=f"{cycle_tag}_tester" if cycle_tag else None,
        )
        workflow.add_task(tester_task)
        workflow.add_output(tester_output)

        conflicts = self._detect_conflicts(feature_id, coder_output, tester_output)
        for conflict in conflicts:
            workflow.add_conflict(conflict)

        reviewer_output: Optional[AgentOutput] = None
        if conflicts:
            workflow.current_phase = "reviewer"
            reviewer_task, reviewer_output = self.dispatcher.dispatch(
                role=AgentRole.REVIEWER,
                feature_id=feature_id,
                goal_text=goal_text,
                feature=feature,
                previous_outputs={
                    "coder": coder_output.content,
                    "tester": tester_output.content,
                },
                context={
                    **ctx,
                    "conflicts": [c.to_dict() for c in conflicts],
                },
                cycle_tag=f"{cycle_tag}_reviewer" if cycle_tag else None,
            )
            workflow.add_task(reviewer_task)
            workflow.add_output(reviewer_output)

        workflow.decision = self._build_decision(
            feature_id=feature_id,
            outputs=workflow.outputs,
            conflicts=workflow.conflicts,
            reviewer_output=reviewer_output,
        )
        workflow.current_phase = "done"
        workflow.status = "approved" if workflow.decision.is_approved else "needs_revision"
        workflow.touch()
        return workflow


def create_orchestrator(
    command_template: str,
    root_dir: Path,
    timeout_seconds: int = 1800,
    max_iterations: int = 2,
    agent_executor: Optional[Any] = None,
) -> MultiAgentOrchestrator:
    """Create orchestrator with default dispatcher."""
    dispatcher = create_dispatcher(
        command_template=command_template,
        root_dir=root_dir,
        timeout_seconds=timeout_seconds,
        agent_executor=agent_executor,
    )
    return MultiAgentOrchestrator(dispatcher=dispatcher, max_iterations=max_iterations)
