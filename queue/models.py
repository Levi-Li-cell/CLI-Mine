"""
Task queue models for M4-002: Task queue with priority scheduling.

Provides data structures for task representation with priority and status tracking.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskStatus(Enum):
    """Status of a task in the queue."""
    PENDING = "pending"          # Ready to be picked up
    RUNNING = "running"          # Currently being executed
    COMPLETED = "completed"      # Successfully finished
    FAILED = "failed"            # Execution failed
    BLOCKED = "blocked"          # Blocked by dependency or policy
    CANCELLED = "cancelled"      # Manually cancelled


class TaskPriority(Enum):
    """Priority levels for task scheduling."""
    CRITICAL = 0   # P0 - highest priority
    HIGH = 1       # P1
    MEDIUM = 2     # P2
    LOW = 3        # P3
    BACKGROUND = 4 # P4 - lowest priority

    @classmethod
    def from_string(cls, value: str) -> "TaskPriority":
        """Convert string priority to enum."""
        mapping = {
            "P0": cls.CRITICAL,
            "P1": cls.HIGH,
            "P2": cls.MEDIUM,
            "P3": cls.LOW,
            "P4": cls.BACKGROUND,
            "CRITICAL": cls.CRITICAL,
            "HIGH": cls.HIGH,
            "MEDIUM": cls.MEDIUM,
            "LOW": cls.LOW,
            "BACKGROUND": cls.BACKGROUND,
        }
        return mapping.get(value.upper(), cls.MEDIUM)


@dataclass
class Task:
    """
    Represents a task in the queue.

    Attributes:
        task_id: Unique identifier for the task
        feature_id: Associated feature ID from feature_list.json
        priority: Task priority level
        status: Current task status
        description: Human-readable task description
        payload: Additional task data (e.g., feature details)
        created_at: When the task was created
        started_at: When execution started (if running/completed)
        completed_at: When execution finished (if completed/failed)
        attempts: Number of execution attempts
        max_attempts: Maximum allowed attempts before marking failed
        last_error: Error message from last failed attempt
        dependencies: List of task_ids that must complete first
        metadata: Additional metadata
    """
    task_id: str
    feature_id: str
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    description: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    attempts: int = 0
    max_attempts: int = 8
    last_error: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat(timespec="seconds")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize task to dictionary."""
        return {
            "task_id": self.task_id,
            "feature_id": self.feature_id,
            "priority": self.priority.value,
            "status": self.status.value,
            "description": self.description,
            "payload": self.payload,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "last_error": self.last_error,
            "dependencies": self.dependencies,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """Deserialize task from dictionary."""
        return cls(
            task_id=data["task_id"],
            feature_id=data["feature_id"],
            priority=TaskPriority(data.get("priority", TaskPriority.MEDIUM.value)),
            status=TaskStatus(data.get("status", TaskStatus.PENDING.value)),
            description=data.get("description", ""),
            payload=data.get("payload", {}),
            created_at=data.get("created_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            attempts=data.get("attempts", 0),
            max_attempts=data.get("max_attempts", 8),
            last_error=data.get("last_error"),
            dependencies=data.get("dependencies", []),
            metadata=data.get("metadata", {}),
        )

    def can_retry(self) -> bool:
        """Check if task can be retried."""
        return self.attempts < self.max_attempts

    def mark_running(self) -> None:
        """Mark task as running."""
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.attempts += 1

    def mark_completed(self) -> None:
        """Mark task as successfully completed."""
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.now().isoformat(timespec="seconds")

    def mark_failed(self, error: Optional[str] = None) -> None:
        """Mark task as failed."""
        self.last_error = error
        self.completed_at = datetime.now().isoformat(timespec="seconds")
        if self.can_retry():
            self.status = TaskStatus.PENDING  # Allow retry
        else:
            self.status = TaskStatus.FAILED

    def mark_blocked(self, reason: Optional[str] = None) -> None:
        """Mark task as blocked."""
        self.status = TaskStatus.BLOCKED
        if reason:
            self.metadata["block_reason"] = reason

    def mark_cancelled(self, reason: Optional[str] = None) -> None:
        """Mark task as cancelled."""
        self.status = TaskStatus.CANCELLED
        if reason:
            self.metadata["cancel_reason"] = reason


@dataclass
class QueueStats:
    """Statistics about the task queue."""
    total_tasks: int = 0
    pending: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    blocked: int = 0
    cancelled: int = 0

    @classmethod
    def from_tasks(cls, tasks: List[Task]) -> "QueueStats":
        """Calculate statistics from a list of tasks."""
        counts = {status: 0 for status in TaskStatus}
        for task in tasks:
            counts[task.status] += 1
        return cls(
            total_tasks=len(tasks),
            pending=counts[TaskStatus.PENDING],
            running=counts[TaskStatus.RUNNING],
            completed=counts[TaskStatus.COMPLETED],
            failed=counts[TaskStatus.FAILED],
            blocked=counts[TaskStatus.BLOCKED],
            cancelled=counts[TaskStatus.CANCELLED],
        )

    def to_dict(self) -> Dict[str, int]:
        """Serialize to dictionary."""
        return {
            "total_tasks": self.total_tasks,
            "pending": self.pending,
            "running": self.running,
            "completed": self.completed,
            "failed": self.failed,
            "blocked": self.blocked,
            "cancelled": self.cancelled,
        }
