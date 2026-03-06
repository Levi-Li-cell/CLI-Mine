"""Verification script for M5-001: regression eval suite."""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from regression import BenchmarkTask, EvalPersistence, RegressionEvaluator


def pass_line(msg: str) -> None:
    print(f"   [PASS] {msg}")


def fail_line(msg: str, reason: str = "") -> None:
    print(f"   [FAIL] {msg}")
    if reason:
        print(f"          Reason: {reason}")
    raise SystemExit(1)


def main() -> None:
    print("=== M5-001 VERIFICATION: Regression Eval Suite ===\n")
    tmp = Path(tempfile.mkdtemp(prefix="m5_001_test_"))

    try:
        print("1. Testing: benchmark task definitions persist...")
        persistence = EvalPersistence(tmp)
        tasks = [
            BenchmarkTask(
                task_id="t1",
                name="Task 1",
                description="Definition test",
                metadata={"command": f'"{sys.executable}" -c "print(1)"'},
            ),
            BenchmarkTask(
                task_id="t2",
                name="Task 2",
                description="Definition test 2",
                metadata={"command": f'"{sys.executable}" -c "print(2)"'},
            ),
        ]
        persistence.save_tasks(tasks)
        loaded = persistence.load_tasks()
        if len(loaded) != 2:
            fail_line("Save/load benchmark tasks", f"loaded={len(loaded)}")
        pass_line("Benchmark tasks save/load")

        print("\n2. Testing: release eval run executes cases...")
        evaluator = RegressionEvaluator(root_dir=Path(__file__).parent.resolve(), eval_dir=tmp)
        evaluator.persistence.save_tasks(
            [
                BenchmarkTask(
                    task_id="pass_case",
                    name="Pass case",
                    description="Should pass",
                    metadata={"command": f'"{sys.executable}" -c "print(123)"'},
                ),
                BenchmarkTask(
                    task_id="fail_case",
                    name="Fail case",
                    description="Should fail",
                    metadata={"command": f'"{sys.executable}" -c "import sys; sys.exit(3)"'},
                ),
            ]
        )
        run1 = evaluator.run_release_eval(release_tag="v_test_1", timeout_seconds=30)
        if run1.total != 2:
            fail_line("Eval run case count", f"total={run1.total}")
        if run1.passed != 1 or run1.failed != 1:
            fail_line("Eval run pass/fail split", f"passed={run1.passed} failed={run1.failed}")
        pass_line("Release eval executes and aggregates correctly")

        print("\n3. Testing: pass rate trend tracking...")
        evaluator.persistence.save_tasks(
            [
                BenchmarkTask(
                    task_id="all_pass_1",
                    name="All pass",
                    description="Pass",
                    metadata={"command": f'"{sys.executable}" -c "print(1)"'},
                ),
                BenchmarkTask(
                    task_id="all_pass_2",
                    name="All pass 2",
                    description="Pass",
                    metadata={"command": f'"{sys.executable}" -c "print(2)"'},
                ),
            ]
        )
        run2 = evaluator.run_release_eval(release_tag="v_test_2", timeout_seconds=30)
        if run2.pass_rate != 100.0:
            fail_line("Expected second run pass_rate 100", f"pass_rate={run2.pass_rate}")
        trend = evaluator.get_pass_rate_trend(last_n=5)
        if trend.get("count", 0) < 2:
            fail_line("Trend count", f"trend={trend}")
        if trend.get("latest") != 100.0:
            fail_line("Trend latest", f"latest={trend.get('latest')}")
        if trend.get("delta") is None:
            fail_line("Trend delta", "delta should be present with >=2 runs")
        pass_line("Pass rate trend is recorded across runs")

        print("\n4. Testing: runs history persists to JSONL...")
        runs = evaluator.persistence.load_runs()
        if len(runs) < 2:
            fail_line("Run history persistence", f"runs={len(runs)}")
        if "pass_rate" not in runs[-1]:
            fail_line("Run history fields", "latest run missing pass_rate")
        pass_line("Run history persisted with summary metrics")

        print("\n=== M5-001 VERIFICATION PASSED ===")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
