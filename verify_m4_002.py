#!/usr/bin/env python
"""
Verification script for M4-002: Task queue with priority scheduling.

Tests:
1. Queue supports priority and status
2. Scheduler picks highest priority pending task
3. Queue state survives restart
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from queue import (
    Task,
    TaskStatus,
    TaskPriority,
    QueueStats,
    QueuePersistence,
    TaskScheduler,
    create_default_scheduler,
)


def test_passed(msg: str) -> None:
    print(f"   [PASS] {msg}")


def test_failed(msg: str) -> None:
    print(f"   [FAIL] {msg}")
    sys.exit(1)


def run_tests():
    print("=== M4-002 VERIFICATION: Task Queue with Priority Scheduling ===\n")

    # Create temporary directory for testing
    test_dir = Path(tempfile.mkdtemp(prefix="queue_test_"))
    try:
        # =========================================
        # Test 1: Queue supports priority and status
        # =========================================
        print("1. Testing: Queue supports priority and status...")

        persistence = QueuePersistence(test_dir)
        scheduler = TaskScheduler(persistence)

        # Add tasks with different priorities
        task_low = scheduler.add_task(
            feature_id="TEST-001",
            priority=TaskPriority.LOW,
            description="Low priority task",
        )
        task_high = scheduler.add_task(
            feature_id="TEST-002",
            priority=TaskPriority.HIGH,
            description="High priority task",
        )
        task_critical = scheduler.add_task(
            feature_id="TEST-003",
            priority=TaskPriority.CRITICAL,
            description="Critical priority task",
        )

        # Verify task statuses
        if task_low.status != TaskStatus.PENDING:
            test_failed(f"Task status should be PENDING, got {task_low.status}")
        test_passed("Task status is PENDING")

        # Verify priority values
        if task_critical.priority.value >= task_high.priority.value:
            test_failed("Critical priority should have lower value than high")
        if task_high.priority.value >= task_low.priority.value:
            test_failed("High priority should have lower value than low")
        test_passed("Priority values are correctly ordered")

        # Test status transitions
        scheduler.start_task(task_low.task_id)
        updated_task = scheduler.get_task(task_low.task_id)
        if updated_task.status != TaskStatus.RUNNING:
            test_failed(f"Task status should be RUNNING after start, got {updated_task.status}")
        test_passed("Task status transitions to RUNNING on start")

        scheduler.complete_task(task_low.task_id)
        updated_task = scheduler.get_task(task_low.task_id)
        if updated_task.status != TaskStatus.COMPLETED:
            test_failed(f"Task status should be COMPLETED, got {updated_task.status}")
        test_passed("Task status transitions to COMPLETED")

        # Test failed status
        scheduler.fail_task(task_high.task_id, "Test error")
        updated_task = scheduler.get_task(task_high.task_id)
        # Should be PENDING because it can retry
        if updated_task.status != TaskStatus.PENDING:
            test_failed(f"Task should be PENDING for retry, got {updated_task.status}")
        test_passed("Failed task with retries goes back to PENDING")

        # Test blocked status
        scheduler.block_task(task_critical.task_id, "Dependency blocked")
        updated_task = scheduler.get_task(task_critical.task_id)
        if updated_task.status != TaskStatus.BLOCKED:
            test_failed(f"Task status should be BLOCKED, got {updated_task.status}")
        test_passed("Task can be marked as BLOCKED")

        # Test queue statistics
        stats = scheduler.get_stats()
        if stats.total_tasks != 3:
            test_failed(f"Total tasks should be 3, got {stats.total_tasks}")
        if stats.completed != 1:
            test_failed(f"Completed should be 1, got {stats.completed}")
        if stats.blocked != 1:
            test_failed(f"Blocked should be 1, got {stats.blocked}")
        test_passed(f"Queue stats correct: total={stats.total_tasks}, completed={stats.completed}, blocked={stats.blocked}")

        # =========================================
        # Test 2: Scheduler picks highest priority pending task
        # =========================================
        print("\n2. Testing: Scheduler picks highest priority pending task...")

        # Clear and add fresh tasks
        scheduler.clear()

        # Add tasks in random order
        scheduler.add_task("PICK-001", TaskPriority.LOW, "Low priority")
        scheduler.add_task("PICK-002", TaskPriority.CRITICAL, "Critical priority")
        scheduler.add_task("PICK-003", TaskPriority.MEDIUM, "Medium priority")
        scheduler.add_task("PICK-004", TaskPriority.HIGH, "High priority")

        # Pick next - should be CRITICAL
        next_task = scheduler.pick_next()
        if next_task is None:
            test_failed("pick_next() returned None")
        if next_task.feature_id != "PICK-002":
            test_failed(f"Should pick CRITICAL task, got {next_task.feature_id} with priority {next_task.priority}")
        test_passed("Picks CRITICAL priority task first")

        # Complete it and pick again - should be HIGH
        scheduler.start_task(next_task.task_id)
        scheduler.complete_task(next_task.task_id)
        next_task = scheduler.pick_next()
        if next_task.feature_id != "PICK-004":
            test_failed(f"Should pick HIGH task, got {next_task.feature_id}")
        test_passed("Picks HIGH priority task next")

        # Complete and pick MEDIUM
        scheduler.start_task(next_task.task_id)
        scheduler.complete_task(next_task.task_id)
        next_task = scheduler.pick_next()
        if next_task.feature_id != "PICK-003":
            test_failed(f"Should pick MEDIUM task, got {next_task.feature_id}")
        test_passed("Picks MEDIUM priority task next")

        # Complete and pick LOW
        scheduler.start_task(next_task.task_id)
        scheduler.complete_task(next_task.task_id)
        next_task = scheduler.pick_next()
        if next_task.feature_id != "PICK-001":
            test_failed(f"Should pick LOW task, got {next_task.feature_id}")
        test_passed("Picks LOW priority task last")

        # Test with dependencies
        scheduler.clear()
        dep_task = scheduler.add_task("DEP-001", TaskPriority.CRITICAL, "Dependency task")
        waiting_task = scheduler.add_task(
            "WAIT-001",
            TaskPriority.LOW,
            "Waiting task",
            dependencies=[dep_task.task_id],
        )

        # Should pick dependency task first
        next_task = scheduler.pick_next()
        if next_task.task_id != dep_task.task_id:
            test_failed("Should pick task without dependencies first")
        test_passed("Task with dependencies waits")

        # Complete dependency
        scheduler.start_task(dep_task.task_id)
        scheduler.complete_task(dep_task.task_id)

        # Now waiting task should be picked
        next_task = scheduler.pick_next()
        if next_task.task_id != waiting_task.task_id:
            test_failed("Waiting task should be picked after dependency completes")
        test_passed("Waiting task picked after dependency completes")

        # =========================================
        # Test 3: Queue state survives restart
        # =========================================
        print("\n3. Testing: Queue state survives restart...")

        # Clear and add tasks
        scheduler.clear()
        scheduler.add_task("RESTART-001", TaskPriority.HIGH, "Task before restart")
        scheduler.add_task("RESTART-002", TaskPriority.LOW, "Another task")

        # Start one task (simulating crash)
        task = scheduler.pick_next()
        scheduler.start_task(task.task_id)

        # Simulate restart by creating new scheduler instance
        new_scheduler = TaskScheduler(QueuePersistence(test_dir))

        # Verify tasks persisted
        tasks = new_scheduler.list_tasks()
        if len(tasks) != 2:
            test_failed(f"Should have 2 tasks after restart, got {len(tasks)}")
        test_passed("Tasks persist after restart")

        # Verify running task is recovered
        running_count = sum(1 for t in tasks if t.status == TaskStatus.RUNNING)
        if running_count != 1:
            test_failed(f"Should have 1 RUNNING task, got {running_count}")
        test_passed("Running task state persists")

        # Test recovery of running tasks
        recovered = new_scheduler.recover_running_tasks()
        if recovered != 1:
            test_failed(f"Should recover 1 task, got {recovered}")
        test_passed("Running tasks recovered to PENDING")

        # Verify queue file exists
        queue_file = test_dir / "queue.json"
        if not queue_file.exists():
            test_failed("Queue file should exist")
        test_passed("Queue file persists to disk")

        # Verify index file exists
        index_file = test_dir / "index.json"
        if not index_file.exists():
            test_failed("Index file should exist")
        test_passed("Index file persists to disk")

        # Verify history log exists
        history_file = test_dir / "task_history.jsonl"
        if not history_file.exists():
            test_failed("History log should exist")
        test_passed("Task history log persists to disk")

        # =========================================
        # Test 4: Additional features
        # =========================================
        print("\n4. Testing: Additional features...")

        # Test sync_from_features
        new_scheduler.clear()
        features = [
            {"id": "FEAT-001", "priority": "P1", "description": "Feature 1", "passes": False},
            {"id": "FEAT-002", "priority": "P2", "description": "Feature 2", "passes": True},
            {"id": "FEAT-003", "priority": "P0", "description": "Feature 3", "passes": False},
        ]
        added = new_scheduler.sync_from_features(features)
        if added != 2:  # Only non-passed features
            test_failed(f"Should add 2 tasks, got {added}")
        test_passed("sync_from_features skips passed features")

        # Test TaskPriority from_string
        if TaskPriority.from_string("P0") != TaskPriority.CRITICAL:
            test_failed("P0 should map to CRITICAL")
        if TaskPriority.from_string("P1") != TaskPriority.HIGH:
            test_failed("P1 should map to HIGH")
        test_passed("TaskPriority.from_string works correctly")

        # Test max_attempts and retry logic
        new_scheduler.clear()
        retry_task = new_scheduler.add_task("RETRY-001", TaskPriority.HIGH, max_attempts=2)

        # First failure - should go back to PENDING
        new_scheduler.start_task(retry_task.task_id)
        new_scheduler.fail_task(retry_task.task_id, "Error 1")
        task = new_scheduler.get_task(retry_task.task_id)
        if task.status != TaskStatus.PENDING or task.attempts != 1:
            test_failed(f"Task should be PENDING with 1 attempt, got {task.status}/{task.attempts}")
        test_passed("Task retries on first failure")

        # Second failure - should be FAILED (max attempts reached)
        new_scheduler.start_task(retry_task.task_id)
        new_scheduler.fail_task(retry_task.task_id, "Error 2")
        task = new_scheduler.get_task(retry_task.task_id)
        if task.status != TaskStatus.FAILED:
            test_failed(f"Task should be FAILED, got {task.status}")
        test_passed("Task marked FAILED after max attempts")

        # Test export/import
        export_file = test_dir / "export.json"
        persistence.export_queue(export_file)
        if not export_file.exists():
            test_failed("Export file should exist")
        test_passed("Queue export works")

        # Test list_tasks filtering
        new_scheduler.clear()
        new_scheduler.add_task("LIST-001", TaskPriority.HIGH)
        new_scheduler.add_task("LIST-002", TaskPriority.LOW)
        new_scheduler.add_task("LIST-003", TaskPriority.HIGH)

        high_tasks = new_scheduler.list_tasks(priority=TaskPriority.HIGH)
        if len(high_tasks) != 2:
            test_failed(f"Should have 2 HIGH tasks, got {len(high_tasks)}")
        test_passed("list_tasks filters by priority")

        # Test create_default_scheduler convenience function
        default_scheduler = create_default_scheduler(str(test_dir / "default"))
        if default_scheduler is None:
            test_failed("create_default_scheduler should return scheduler")
        test_passed("create_default_scheduler works")

        # =========================================
        # Summary
        # =========================================
        print("\n=== M4-002 VERIFICATION PASSED ===")
        return True

    finally:
        # Cleanup
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
