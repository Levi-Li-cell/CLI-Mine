"""
Multi-agent models for M4-003: Multi-agent roles: coder, tester, reviewer.

Provides data structures for agent roles, tasks, outputs, and decisions.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentRole(Enum):
    """Roles for multi-agent collaboration."""
    CODER = "coder"        # Writes implementation code
    TESTER = "tester"      # Writes tests and validates
    REVIEWER = "reviewer"  # Reviews code and resolves conflicts


class AgentTaskStatus(Enum):
    """Status of an agent task."""
    PENDING = "pending"          # Not yet dispatched
    DISPATCHED = "dispatched"    # Sent to agent, waiting for response
    COMPLETED = "completed"      # Successfully completed
    FAILED = "failed"            # Execution failed
    TIMEOUT = "timeout"          # Timed out


class ConflictType(Enum):
    """Types of conflicts between agent outputs."""
    NONE = "none"                    # No conflict
    TEST_FAILURE = "test_failure"    # Tests fail against code
    CODE_REVIEW = "code_review"      # Reviewer found issues
    SCOPE_CREEP = "scope_creep"      # Implementation exceeds scope
    MISSING_REQUIREMENTS = "missing_requirements"  # Requirements not met
    DESIGN_DISAGREEMENT = "design_disagreement"  # Agents disagree on approach


class DecisionType(Enum):
    """Final decision types after multi-agent collaboration."""
    APPROVE = "approve"              # Code approved, ready to commit
    REJECT = "reject"                # Code rejected, needs major revision
    REVISE = "revise"                # Minor revisions needed
    ESCALATE = "escalate"            # Escalate to human review
    RETRY = "retry"                  # Retry the entire workflow


@dataclass
class AgentTask:
    """
    A task to be dispatched to a specific agent role.

    Attributes:
        task_id: Unique identifier for this agent task
        role: The agent role to handle this task
        feature_id: Associated feature ID
        description: Task description
        context: Additional context (e.g., previous outputs)
        status: Current task status
        created_at: When the task was created
        started_at: When execution started
        completed_at: When execution completed
        timeout_seconds: Maximum execution time
        metadata: Additional metadata
    """
    task_id: str
    role: AgentRole
    feature_id: str
    description: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    status: AgentTaskStatus = AgentTaskStatus.PENDING
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    timeout_seconds: int = 1800
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat(timespec="seconds")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "task_id": self.task_id,
            "role": self.role.value,
            "feature_id": self.feature_id,
            "description": self.description,
            "context": self.context,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "timeout_seconds": self.timeout_seconds,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentTask":
        """Deserialize from dictionary."""
        return cls(
            task_id=data["task_id"],
            role=AgentRole(data["role"]),
            feature_id=data["feature_id"],
            description=data.get("description", ""),
            context=data.get("context", {}),
            status=AgentTaskStatus(data.get("status", AgentTaskStatus.PENDING.value)),
            created_at=data.get("created_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            timeout_seconds=data.get("timeout_seconds", 1800),
            metadata=data.get("metadata", {}),
        )

    def mark_dispatched(self) -> None:
        """Mark task as dispatched."""
        self.status = AgentTaskStatus.DISPATCHED
        self.started_at = datetime.now().isoformat(timespec="seconds")

    def mark_completed(self) -> None:
        """Mark task as completed."""
        self.status = AgentTaskStatus.COMPLETED
        self.completed_at = datetime.now().isoformat(timespec="seconds")

    def mark_failed(self, error: Optional[str] = None) -> None:
        """Mark task as failed."""
        self.status = AgentTaskStatus.FAILED
        self.completed_at = datetime.now().isoformat(timespec="seconds")
        if error:
            self.metadata["error"] = error

    def mark_timeout(self) -> None:
        """Mark task as timed out."""
        self.status = AgentTaskStatus.TIMEOUT
        self.completed_at = datetime.now().isoformat(timespec="seconds")


@dataclass
class AgentOutput:
    """
    Output from an agent execution.

    Attributes:
        task_id: Associated agent task ID
        role: The agent role that produced this output
        feature_id: Associated feature ID
        success: Whether the agent execution was successful
        content: The main output content (code, review, test results)
        summary: Brief summary of the output
        issues: List of issues found (for tester/reviewer)
        suggestions: List of suggestions for improvement
        files_modified: List of files that were modified
        files_created: List of files that were created
        test_results: Test execution results (for tester)
        confidence: Confidence level (0.0 to 1.0)
        metadata: Additional metadata
        created_at: When the output was created
    """
    task_id: str
    role: AgentRole
    feature_id: str
    success: bool = True
    content: str = ""
    summary: str = ""
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    files_created: List[str] = field(default_factory=list)
    test_results: Optional[Dict[str, Any]] = None
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat(timespec="seconds")
        # Clamp confidence to valid range
        self.confidence = max(0.0, min(1.0, self.confidence))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "task_id": self.task_id,
            "role": self.role.value,
            "feature_id": self.feature_id,
            "success": self.success,
            "content": self.content[:10000] if self.content else "",  # Truncate
            "summary": self.summary,
            "issues": self.issues,
            "suggestions": self.suggestions,
            "files_modified": self.files_modified,
            "files_created": self.files_created,
            "test_results": self.test_results,
            "confidence": self.confidence,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentOutput":
        """Deserialize from dictionary."""
        return cls(
            task_id=data["task_id"],
            role=AgentRole(data["role"]),
            feature_id=data["feature_id"],
            success=data.get("success", True),
            content=data.get("content", ""),
            summary=data.get("summary", ""),
            issues=data.get("issues", []),
            suggestions=data.get("suggestions", []),
            files_modified=data.get("files_modified", []),
            files_created=data.get("files_created", []),
            test_results=data.get("test_results"),
            confidence=data.get("confidence", 1.0),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at"),
        )


@dataclass
class Conflict:
    """
    Represents a conflict between agent outputs.

    Attributes:
        conflict_id: Unique identifier for this conflict
        conflict_type: Type of conflict
        feature_id: Associated feature ID
        description: Human-readable description of the conflict
        source_outputs: List of task_ids that are in conflict
        severity: Severity level (1-5, 5 being most severe)
        resolution: How the conflict was resolved (if resolved)
        resolved: Whether the conflict has been resolved
        metadata: Additional metadata
        created_at: When the conflict was detected
        resolved_at: When the conflict was resolved
    """
    conflict_id: str
    conflict_type: ConflictType
    feature_id: str
    description: str = ""
    source_outputs: List[str] = field(default_factory=list)
    severity: int = 3
    resolution: Optional[str] = None
    resolved: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None
    resolved_at: Optional[str] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat(timespec="seconds")
        # Clamp severity to valid range
        self.severity = max(1, min(5, self.severity))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "conflict_id": self.conflict_id,
            "conflict_type": self.conflict_type.value,
            "feature_id": self.feature_id,
            "description": self.description,
            "source_outputs": self.source_outputs,
            "severity": self.severity,
            "resolution": self.resolution,
            "resolved": self.resolved,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Conflict":
        """Deserialize from dictionary."""
        return cls(
            conflict_id=data["conflict_id"],
            conflict_type=ConflictType(data["conflict_type"]),
            feature_id=data["feature_id"],
            description=data.get("description", ""),
            source_outputs=data.get("source_outputs", []),
            severity=data.get("severity", 3),
            resolution=data.get("resolution"),
            resolved=data.get("resolved", False),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at"),
            resolved_at=data.get("resolved_at"),
        )

    def resolve(self, resolution: str) -> None:
        """Mark conflict as resolved."""
        self.resolution = resolution
        self.resolved = True
        self.resolved_at = datetime.now().isoformat(timespec="seconds")


@dataclass
class AggregatedDecision:
    """
    Final decision after aggregating multiple agent outputs.

    Attributes:
        feature_id: Associated feature ID
        decision: The final decision type
        confidence: Overall confidence in the decision (0.0 to 1.0)
        summary: Human-readable summary of the decision
        outputs: All agent outputs that contributed to this decision
        conflicts: List of conflicts that were detected (if any)
        required_actions: List of actions required before approval
        approved_files: List of files that are approved
        rejected_files: List of files that need revision
        review_notes: Notes from the reviewer (if any)
        metadata: Additional metadata
        created_at: When the decision was made
    """
    feature_id: str
    decision: DecisionType = DecisionType.REVISE
    confidence: float = 0.0
    summary: str = ""
    outputs: List[AgentOutput] = field(default_factory=list)
    conflicts: List[Conflict] = field(default_factory=list)
    required_actions: List[str] = field(default_factory=list)
    approved_files: List[str] = field(default_factory=list)
    rejected_files: List[str] = field(default_factory=list)
    review_notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat(timespec="seconds")
        # Clamp confidence to valid range
        self.confidence = max(0.0, min(1.0, self.confidence))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "feature_id": self.feature_id,
            "decision": self.decision.value,
            "confidence": self.confidence,
            "summary": self.summary,
            "outputs": [o.to_dict() for o in self.outputs],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "required_actions": self.required_actions,
            "approved_files": self.approved_files,
            "rejected_files": self.rejected_files,
            "review_notes": self.review_notes,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AggregatedDecision":
        """Deserialize from dictionary."""
        return cls(
            feature_id=data["feature_id"],
            decision=DecisionType(data.get("decision", DecisionType.REVISE.value)),
            confidence=data.get("confidence", 0.0),
            summary=data.get("summary", ""),
            outputs=[AgentOutput.from_dict(o) for o in data.get("outputs", [])],
            conflicts=[Conflict.from_dict(c) for c in data.get("conflicts", [])],
            required_actions=data.get("required_actions", []),
            approved_files=data.get("approved_files", []),
            rejected_files=data.get("rejected_files", []),
            review_notes=data.get("review_notes", ""),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at"),
        )

    @property
    def is_approved(self) -> bool:
        """Check if the decision is approved."""
        return self.decision == DecisionType.APPROVE

    @property
    def needs_revision(self) -> bool:
        """Check if revision is needed."""
        return self.decision in (DecisionType.REVISE, DecisionType.REJECT)

    @property
    def needs_escalation(self) -> bool:
        """Check if escalation is needed."""
        return self.decision == DecisionType.ESCALATE


@dataclass
class WorkflowState:
    """
    State of a multi-agent workflow execution.

    Attributes:
        workflow_id: Unique identifier for this workflow
        feature_id: Associated feature ID
        feature: The feature being implemented
        tasks: All agent tasks in this workflow
        outputs: All agent outputs in this workflow
        conflicts: All detected conflicts
        decision: The final aggregated decision (if made)
        status: Current workflow status
        current_phase: Current phase of the workflow
        iteration: Current iteration number
        max_iterations: Maximum allowed iterations
        created_at: When the workflow was created
        updated_at: When the workflow was last updated
        metadata: Additional metadata
    """
    workflow_id: str
    feature_id: str
    feature: Dict[str, Any] = field(default_factory=dict)
    tasks: List[AgentTask] = field(default_factory=list)
    outputs: List[AgentOutput] = field(default_factory=list)
    conflicts: List[Conflict] = field(default_factory=list)
    decision: Optional[AggregatedDecision] = None
    status: str = "pending"
    current_phase: str = "init"
    iteration: int = 0
    max_iterations: int = 3
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat(timespec="seconds")
        self.updated_at = self.created_at

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "workflow_id": self.workflow_id,
            "feature_id": self.feature_id,
            "feature": self.feature,
            "tasks": [t.to_dict() for t in self.tasks],
            "outputs": [o.to_dict() for o in self.outputs],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "decision": self.decision.to_dict() if self.decision else None,
            "status": self.status,
            "current_phase": self.current_phase,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowState":
        """Deserialize from dictionary."""
        decision_data = data.get("decision")
        decision = AggregatedDecision.from_dict(decision_data) if decision_data else None

        return cls(
            workflow_id=data["workflow_id"],
            feature_id=data["feature_id"],
            feature=data.get("feature", {}),
            tasks=[AgentTask.from_dict(t) for t in data.get("tasks", [])],
            outputs=[AgentOutput.from_dict(o) for o in data.get("outputs", [])],
            conflicts=[Conflict.from_dict(c) for c in data.get("conflicts", [])],
            decision=decision,
            status=data.get("status", "pending"),
            current_phase=data.get("current_phase", "init"),
            iteration=data.get("iteration", 0),
            max_iterations=data.get("max_iterations", 3),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            metadata=data.get("metadata", {}),
        )

    def touch(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.now().isoformat(timespec="seconds")

    def add_task(self, task: AgentTask) -> None:
        """Add a task to the workflow."""
        self.tasks.append(task)
        self.touch()

    def add_output(self, output: AgentOutput) -> None:
        """Add an output to the workflow."""
        self.outputs.append(output)
        self.touch()

    def add_conflict(self, conflict: Conflict) -> None:
        """Add a conflict to the workflow."""
        self.conflicts.append(conflict)
        self.touch()

    def get_outputs_by_role(self, role: AgentRole) -> List[AgentOutput]:
        """Get all outputs for a specific role."""
        return [o for o in self.outputs if o.role == role]

    def get_latest_output(self, role: AgentRole) -> Optional[AgentOutput]:
        """Get the most recent output for a specific role."""
        outputs = self.get_outputs_by_role(role)
        if outputs:
            return outputs[-1]
        return None

    def can_iterate(self) -> bool:
        """Check if more iterations are possible."""
        return self.iteration < self.max_iterations
