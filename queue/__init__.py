"""
Task Queue Package for M4-002: Task queue with priority scheduling.

This package provides a priority-based task queue with persistent storage,
ensuring queue state survives process restart.

Main components:
- Task: Data model for individual tasks
- TaskStatus: Enum for task lifecycle states
- TaskPriority: Enum for priority levels
- QueuePersistence: File-based persistence layer
- TaskScheduler: Priority-based scheduler

Usage:
    from pathlib import Path
    from queue import TaskScheduler, QueuePersistence, TaskPriority

    # Create scheduler with persistence
    persistence = QueuePersistence(Path(".agent/queue"))
    scheduler = TaskScheduler(persistence)

    # Add tasks
    scheduler.add_task("M1-001", TaskPriority.HIGH, "Implement feature")

    # Pick next task (highest priority)
    task = scheduler.pick_next()
    if task:
        scheduler.start_task(task.task_id)
        # ... execute task ...
        scheduler.complete_task(task.task_id)

    # Get statistics
    stats = scheduler.get_stats()
    print(f"Pending: {stats.pending}, Completed: {stats.completed}")
"""

from .models import Task, TaskStatus, TaskPriority, QueueStats
from .persistence import QueuePersistence
from .scheduler import TaskScheduler

__all__ = [
    # Models
    "Task",
    "TaskStatus",
    "TaskPriority",
    "QueueStats",
    # Persistence
    "QueuePersistence",
    # Scheduler
    "TaskScheduler",
]


def create_default_scheduler(queue_dir: str = ".agent/queue") -> TaskScheduler:
    """
    Create a TaskScheduler with default persistence configuration.

    Args:
        queue_dir: Directory to store queue files

    Returns:
        Configured TaskScheduler instance
    """
    from pathlib import Path
    persistence = QueuePersistence(Path(queue_dir))
    return TaskScheduler(persistence)
