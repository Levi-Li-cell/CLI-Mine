"""
Queue persistence for M4-002: Task queue with priority scheduling.

Provides atomic file-based persistence for the task queue, ensuring
queue state survives process restart.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Task, TaskStatus, TaskPriority, QueueStats


class QueuePersistence:
    """
    Manages persistent storage of the task queue.

    Uses atomic file writes to ensure consistency during crashes.
    Queue state is stored as JSON with an index for fast lookups.
    """

    def __init__(self, queue_dir: Path):
        """
        Initialize persistence with a queue directory.

        Args:
            queue_dir: Directory to store queue files
        """
        self.queue_dir = Path(queue_dir)
        self.queue_file = self.queue_dir / "queue.json"
        self.index_file = self.queue_dir / "index.json"
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """Ensure queue directory exists."""
        self.queue_dir.mkdir(parents=True, exist_ok=True)

    def _atomic_write(self, path: Path, content: str) -> None:
        """Write file atomically to prevent corruption."""
        # Write to temp file then rename for atomicity
        fd, temp_path = tempfile.mkstemp(
            dir=self.queue_dir,
            prefix=".tmp_",
            suffix=".json"
        )
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(content)
            # Atomic rename
            os.replace(temp_path, str(path))
        except Exception:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    def load_queue(self) -> List[Task]:
        """
        Load all tasks from queue file.

        Returns:
            List of Task objects, empty list if no queue exists
        """
        if not self.queue_file.exists():
            return []

        try:
            with self.queue_file.open('r', encoding='utf-8') as f:
                data = json.load(f)

            if not isinstance(data, dict) or "tasks" not in data:
                return []

            tasks = []
            for task_data in data.get("tasks", []):
                try:
                    tasks.append(Task.from_dict(task_data))
                except (KeyError, ValueError):
                    # Skip malformed tasks
                    continue

            return tasks
        except (json.JSONDecodeError, IOError):
            return []

    def save_queue(self, tasks: List[Task]) -> None:
        """
        Save all tasks to queue file atomically.

        Args:
            tasks: List of Task objects to persist
        """
        data = {
            "version": 1,
            "tasks": [task.to_dict() for task in tasks],
            "updated_at": self._now_iso(),
        }
        self._atomic_write(self.queue_file, json.dumps(data, indent=2, ensure_ascii=True))

    def load_index(self) -> Dict[str, Any]:
        """
        Load queue index for fast lookups.

        Returns:
            Index dictionary with task_id -> task_file mappings
        """
        if not self.index_file.exists():
            return {"version": 1, "by_feature": {}, "by_status": {}}

        try:
            with self.index_file.open('r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"version": 1, "by_feature": {}, "by_status": {}}

    def save_index(self, tasks: List[Task]) -> None:
        """
        Rebuild and save the queue index.

        Args:
            tasks: List of tasks to index
        """
        by_feature: Dict[str, List[str]] = {}
        by_status: Dict[str, List[str]] = {}

        for task in tasks:
            # Index by feature_id
            if task.feature_id not in by_feature:
                by_feature[task.feature_id] = []
            by_feature[task.feature_id].append(task.task_id)

            # Index by status
            status_key = task.status.value
            if status_key not in by_status:
                by_status[status_key] = []
            by_status[status_key].append(task.task_id)

        index = {
            "version": 1,
            "by_feature": by_feature,
            "by_status": by_status,
            "updated_at": self._now_iso(),
        }
        self._atomic_write(self.index_file, json.dumps(index, indent=2))

    def _now_iso(self) -> str:
        """Return current timestamp in ISO format."""
        from datetime import datetime
        return datetime.now().isoformat(timespec="seconds")

    def append_task_log(self, task: Task, event: str, details: Optional[Dict] = None) -> None:
        """
        Append a task event to the history log.

        Args:
            task: Task involved in the event
            event: Event type (created, started, completed, failed, etc.)
            details: Additional event details
        """
        log_file = self.queue_dir / "task_history.jsonl"
        entry = {
            "at": self._now_iso(),
            "task_id": task.task_id,
            "feature_id": task.feature_id,
            "event": event,
            "status": task.status.value,
            "details": details or {},
        }
        with log_file.open('a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=True) + "\n")

    def get_stats(self) -> QueueStats:
        """
        Get queue statistics.

        Returns:
            QueueStats with current counts
        """
        tasks = self.load_queue()
        return QueueStats.from_tasks(tasks)

    def export_queue(self, export_path: Path) -> None:
        """
        Export queue to a file for backup or migration.

        Args:
            export_path: Path to export file
        """
        tasks = self.load_queue()
        data = {
            "version": 1,
            "exported_at": self._now_iso(),
            "tasks": [task.to_dict() for task in tasks],
            "stats": QueueStats.from_tasks(tasks).to_dict(),
        }
        self._atomic_write(export_path, json.dumps(data, indent=2, ensure_ascii=True))

    def import_queue(self, import_path: Path, merge: bool = True) -> int:
        """
        Import tasks from a file.

        Args:
            import_path: Path to import file
            merge: If True, merge with existing tasks; if False, replace

        Returns:
            Number of tasks imported
        """
        with import_path.open('r', encoding='utf-8') as f:
            data = json.load(f)

        imported_tasks = []
        for task_data in data.get("tasks", []):
            try:
                imported_tasks.append(Task.from_dict(task_data))
            except (KeyError, ValueError):
                continue

        if merge:
            existing = self.load_queue()
            existing_ids = {t.task_id for t in existing}
            # Add only new tasks
            for task in imported_tasks:
                if task.task_id not in existing_ids:
                    existing.append(task)
            self.save_queue(existing)
            self.save_index(existing)
            return len([t for t in imported_tasks if t.task_id not in existing_ids])
        else:
            self.save_queue(imported_tasks)
            self.save_index(imported_tasks)
            return len(imported_tasks)

    def clear_completed(self, keep_days: int = 7) -> int:
        """
        Remove completed tasks older than keep_days.

        Args:
            keep_days: Number of days to keep completed tasks

        Returns:
            Number of tasks removed
        """
        from datetime import datetime, timedelta

        tasks = self.load_queue()
        cutoff = datetime.now() - timedelta(days=keep_days)
        cutoff_str = cutoff.isoformat(timespec="seconds")

        remaining = []
        removed = 0
        for task in tasks:
            if task.status == TaskStatus.COMPLETED and task.completed_at:
                if task.completed_at < cutoff_str:
                    removed += 1
                    continue
            remaining.append(task)

        if removed > 0:
            self.save_queue(remaining)
            self.save_index(remaining)

        return removed
