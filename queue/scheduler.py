"""
Task scheduler for M4-002: Task queue with priority scheduling.

Provides the TaskScheduler class that picks the highest priority pending task
and manages task lifecycle.
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from .models import Task, TaskPriority, TaskStatus, QueueStats
from .persistence import QueuePersistence


class TaskScheduler:
    """
    Priority-based task scheduler with persistent queue.

    Features:
    - Picks highest priority pending task
    - Supports task dependencies
    - Persists queue state for restart recovery
    - Tracks attempts and failure handling
    """

    def __init__(self, persistence: QueuePersistence):
        """
        Initialize scheduler with persistence layer.

        Args:
            persistence: QueuePersistence instance for storing queue state
        """
        self.persistence = persistence
        self._tasks: Optional[List[Task]] = None

    def _load_tasks(self) -> List[Task]:
        """Load tasks from persistence, caching in memory."""
        if self._tasks is None:
            self._tasks = self.persistence.load_queue()
        return self._tasks

    def _save_tasks(self) -> None:
        """Save tasks to persistence and update index."""
        if self._tasks is not None:
            self.persistence.save_queue(self._tasks)
            self.persistence.save_index(self._tasks)

    def _invalidate_cache(self) -> None:
        """Invalidate task cache to force reload."""
        self._tasks = None

    def _generate_task_id(self) -> str:
        """Generate a unique task ID."""
        return f"task_{uuid.uuid4().hex[:12]}"

    def add_task(
        self,
        feature_id: str,
        priority: TaskPriority = TaskPriority.MEDIUM,
        description: str = "",
        payload: Optional[Dict[str, Any]] = None,
        dependencies: Optional[List[str]] = None,
        max_attempts: int = 8,
    ) -> Task:
        """
        Add a new task to the queue.

        Args:
            feature_id: Associated feature ID
            priority: Task priority level
            description: Human-readable description
            payload: Additional task data
            dependencies: List of task_ids that must complete first
            max_attempts: Maximum execution attempts

        Returns:
            The created Task object
        """
        tasks = self._load_tasks()

        task = Task(
            task_id=self._generate_task_id(),
            feature_id=feature_id,
            priority=priority,
            description=description,
            payload=payload or {},
            dependencies=dependencies or [],
            max_attempts=max_attempts,
        )

        tasks.append(task)
        self._save_tasks()
        self.persistence.append_task_log(task, "created")
        return task

    def add_task_from_feature(self, feature: Dict[str, Any]) -> Task:
        """
        Create a task from a feature dictionary.

        Args:
            feature: Feature dict from feature_list.json

        Returns:
            The created Task object
        """
        priority_str = feature.get("priority", "P2")
        return self.add_task(
            feature_id=str(feature.get("id", "")),
            priority=TaskPriority.from_string(priority_str),
            description=feature.get("description", ""),
            payload=feature,
        )

    def pick_next(self) -> Optional[Task]:
        """
        Pick the highest priority pending task that is ready to run.

        Considers:
        - Priority (lower value = higher priority)
        - Status (must be PENDING)
        - Dependencies (must be completed)

        Returns:
            The next Task to execute, or None if no tasks available
        """
        tasks = self._load_tasks()

        # Get completed task IDs for dependency check
        completed_ids = {
            t.task_id for t in tasks
            if t.status == TaskStatus.COMPLETED
        }

        # Filter pending tasks with satisfied dependencies
        candidates = []
        for task in tasks:
            if task.status != TaskStatus.PENDING:
                continue

            # Check dependencies
            unsatisfied = set(task.dependencies) - completed_ids
            if unsatisfied:
                continue

            candidates.append(task)

        if not candidates:
            return None

        # Sort by priority (lower value = higher priority), then by creation time
        candidates.sort(key=lambda t: (t.priority.value, t.created_at or ""))
        return candidates[0]

    def get_task(self, task_id: str) -> Optional[Task]:
        """
        Get a task by ID.

        Args:
            task_id: Task identifier

        Returns:
            Task object or None if not found
        """
        tasks = self._load_tasks()
        for task in tasks:
            if task.task_id == task_id:
                return task
        return None

    def get_task_by_feature(self, feature_id: str) -> Optional[Task]:
        """
        Get a task by feature ID.

        Args:
            feature_id: Feature identifier

        Returns:
            Task object or None if not found
        """
        tasks = self._load_tasks()
        for task in tasks:
            if task.feature_id == feature_id:
                return task
        return None

    def start_task(self, task_id: str) -> bool:
        """
        Mark a task as running.

        Args:
            task_id: Task identifier

        Returns:
            True if task was started, False if not found or not pending
        """
        tasks = self._load_tasks()
        for task in tasks:
            if task.task_id == task_id:
                if task.status != TaskStatus.PENDING:
                    return False
                task.mark_running()
                self._save_tasks()
                self.persistence.append_task_log(task, "started")
                return True
        return False

    def complete_task(self, task_id: str) -> bool:
        """
        Mark a task as completed.

        Args:
            task_id: Task identifier

        Returns:
            True if task was completed, False if not found
        """
        tasks = self._load_tasks()
        for task in tasks:
            if task.task_id == task_id:
                task.mark_completed()
                self._save_tasks()
                self.persistence.append_task_log(task, "completed")
                return True
        return False

    def fail_task(self, task_id: str, error: Optional[str] = None) -> bool:
        """
        Mark a task as failed or retry.

        If the task has remaining attempts, it will be reset to PENDING.
        Otherwise, it will be marked as FAILED.

        Args:
            task_id: Task identifier
            error: Error message

        Returns:
            True if task was updated, False if not found
        """
        tasks = self._load_tasks()
        for task in tasks:
            if task.task_id == task_id:
                was_running = task.status == TaskStatus.RUNNING
                task.mark_failed(error)
                self._save_tasks()
                event = "failed" if task.status == TaskStatus.FAILED else "retry_scheduled"
                self.persistence.append_task_log(task, event, {"error": error})
                return True
        return False

    def block_task(self, task_id: str, reason: Optional[str] = None) -> bool:
        """
        Mark a task as blocked.

        Args:
            task_id: Task identifier
            reason: Reason for blocking

        Returns:
            True if task was blocked, False if not found
        """
        tasks = self._load_tasks()
        for task in tasks:
            if task.task_id == task_id:
                task.mark_blocked(reason)
                self._save_tasks()
                self.persistence.append_task_log(task, "blocked", {"reason": reason})
                return True
        return False

    def cancel_task(self, task_id: str, reason: Optional[str] = None) -> bool:
        """
        Cancel a task.

        Args:
            task_id: Task identifier
            reason: Reason for cancellation

        Returns:
            True if task was cancelled, False if not found
        """
        tasks = self._load_tasks()
        for task in tasks:
            if task.task_id == task_id:
                task.mark_cancelled(reason)
                self._save_tasks()
                self.persistence.append_task_log(task, "cancelled", {"reason": reason})
                return True
        return False

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        priority: Optional[TaskPriority] = None,
        limit: int = 100,
    ) -> List[Task]:
        """
        List tasks with optional filtering.

        Args:
            status: Filter by status
            priority: Filter by priority
            limit: Maximum number of tasks to return

        Returns:
            List of matching Task objects
        """
        tasks = self._load_tasks()
        result = []

        for task in tasks:
            if status and task.status != status:
                continue
            if priority and task.priority != priority:
                continue
            result.append(task)

        # Sort by priority then creation time
        result.sort(key=lambda t: (t.priority.value, t.created_at or ""))
        return result[:limit]

    def get_stats(self) -> QueueStats:
        """
        Get queue statistics.

        Returns:
            QueueStats with current counts
        """
        tasks = self._load_tasks()
        return QueueStats.from_tasks(tasks)

    def sync_from_features(
        self,
        features: List[Dict[str, Any]],
        skip_passed: bool = True,
        skip_ids: Optional[Set[str]] = None,
    ) -> int:
        """
        Synchronize queue with feature_list.json.

        Adds new features as tasks, skips features that are already queued
        or have passed.

        Args:
            features: List of feature dicts from feature_list.json
            skip_passed: Skip features with passes=true
            skip_ids: Additional feature IDs to skip

        Returns:
            Number of new tasks added
        """
        skip_ids = skip_ids or set()
        tasks = self._load_tasks()
        existing_features = {t.feature_id for t in tasks}

        added = 0
        for feature in features:
            feature_id = str(feature.get("id", ""))

            # Skip if already in queue
            if feature_id in existing_features:
                continue

            # Skip if passed
            if skip_passed and feature.get("passes", False):
                continue

            # Skip if in skip list
            if feature_id in skip_ids:
                continue

            # Add new task
            self.add_task_from_feature(feature)
            added += 1

        return added

    def recover_running_tasks(self) -> int:
        """
        Recover tasks that were running during a crash.

        Resets RUNNING tasks to PENDING so they can be retried.

        Returns:
            Number of tasks recovered
        """
        tasks = self._load_tasks()
        recovered = 0

        for task in tasks:
            if task.status == TaskStatus.RUNNING:
                task.status = TaskStatus.PENDING
                task.metadata["recovered"] = datetime.now().isoformat(timespec="seconds")
                self.persistence.append_task_log(task, "recovered")
                recovered += 1

        if recovered > 0:
            self._save_tasks()

        return recovered

    def clear(self) -> int:
        """
        Clear all tasks from the queue.

        Returns:
            Number of tasks cleared
        """
        tasks = self._load_tasks()
        count = len(tasks)
        self._tasks = []
        self._save_tasks()
        return count
