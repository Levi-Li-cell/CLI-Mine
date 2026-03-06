"""Regression evaluator that executes benchmark tasks and tracks trends."""

import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from .models import BenchmarkTask, EvalCaseResult, EvalRunResult, now_iso
from .persistence import EvalPersistence


DEFAULT_BENCHMARK_TASKS: List[BenchmarkTask] = [
    BenchmarkTask(
        task_id="journey_bootstrap",
        name="Bootstrap and one cycle",
        description="Harness bootstrap and a single cycle run should complete.",
        tags=["core", "harness"],
        metadata={"command": "python harness.py --bootstrap --cycles 1"},
    ),
    BenchmarkTask(
        task_id="journey_sessions_restore",
        name="Sessions restore",
        description="Session creation/persistence/restore flow remains healthy.",
        tags=["core", "sessions"],
        metadata={"command": "python verify_m3_002.py"},
    ),
    BenchmarkTask(
        task_id="journey_streaming",
        name="Streaming interruption retry",
        description="Assistant streaming interruption and retry flow passes.",
        tags=["core", "streaming"],
        metadata={"command": "python verify_m3_001.py"},
    ),
    BenchmarkTask(
        task_id="journey_health_alerting",
        name="Health monitoring",
        description="Health heartbeat and repeated-failure detection remain functional.",
        tags=["core", "health"],
        metadata={"command": "python verify_m4_004.py"},
    ),
]


class RegressionEvaluator:
    """Run regression benchmark tasks and maintain pass-rate trends."""

    def __init__(self, root_dir: Path, eval_dir: Optional[Path] = None):
        self.root_dir = Path(root_dir)
        self.persistence = EvalPersistence(eval_dir or (self.root_dir / ".agent" / "evals"))
        self._ensure_default_tasks()

    def _ensure_default_tasks(self) -> None:
        tasks = self.persistence.load_tasks()
        if tasks:
            return
        self.persistence.save_tasks(DEFAULT_BENCHMARK_TASKS)

    def list_tasks(self) -> List[BenchmarkTask]:
        return [t for t in self.persistence.load_tasks() if t.enabled]

    def run_release_eval(self, release_tag: str, timeout_seconds: int = 1200) -> EvalRunResult:
        run_id = f"eval_{uuid.uuid4().hex[:10]}"
        started_at = now_iso()
        results: List[EvalCaseResult] = []

        for task in self.list_tasks():
            command = str(task.metadata.get("command", "")).strip()
            if not command:
                results.append(
                    EvalCaseResult(
                        task_id=task.task_id,
                        passed=False,
                        duration_ms=0,
                        message="Missing command",
                    )
                )
                continue

            t0 = time.perf_counter()
            try:
                cp = subprocess.run(
                    command,
                    cwd=str(self.root_dir),
                    shell=True,
                    text=True,
                    capture_output=True,
                    timeout=max(1, int(timeout_seconds)),
                    encoding="utf-8",
                    errors="replace",
                )
                duration_ms = int((time.perf_counter() - t0) * 1000)
                passed = cp.returncode == 0
                message = "PASS" if passed else f"FAIL rc={cp.returncode}"
                results.append(
                    EvalCaseResult(
                        task_id=task.task_id,
                        passed=passed,
                        duration_ms=duration_ms,
                        message=message,
                        details={
                            "command": command,
                            "stdout_preview": (cp.stdout or "")[:400],
                            "stderr_preview": (cp.stderr or "")[:400],
                        },
                    )
                )
            except Exception as e:
                duration_ms = int((time.perf_counter() - t0) * 1000)
                results.append(
                    EvalCaseResult(
                        task_id=task.task_id,
                        passed=False,
                        duration_ms=duration_ms,
                        message=f"EXCEPTION: {e}",
                        details={"command": command},
                    )
                )

        run = EvalRunResult(
            run_id=run_id,
            release_tag=release_tag,
            started_at=started_at,
            finished_at=now_iso(),
            results=results,
        )
        self.persistence.append_run(run)
        return run

    def get_pass_rate_trend(self, last_n: int = 10) -> Dict[str, object]:
        runs = self.persistence.load_runs()
        if not runs:
            return {
                "count": 0,
                "rates": [],
                "latest": None,
                "previous": None,
                "delta": None,
            }

        selected = runs[-max(1, int(last_n)):]
        rates = [float(row.get("pass_rate", 0.0)) for row in selected]
        latest = rates[-1] if rates else None
        previous = rates[-2] if len(rates) >= 2 else None
        delta = round(latest - previous, 2) if latest is not None and previous is not None else None
        return {
            "count": len(rates),
            "rates": rates,
            "latest": latest,
            "previous": previous,
            "delta": delta,
        }


def run_eval_cli(argv: Optional[List[str]] = None) -> int:
    args = argv or sys.argv[1:]
    release_tag = args[0] if args else "manual"
    evaluator = RegressionEvaluator(Path(__file__).resolve().parent.parent)
    run = evaluator.run_release_eval(release_tag=release_tag)
    trend = evaluator.get_pass_rate_trend(last_n=10)
    print(f"run_id={run.run_id} release={run.release_tag} pass_rate={run.pass_rate}%")
    print(f"passed={run.passed}/{run.total} failed={run.failed} duration_ms={run.duration_ms}")
    print(f"trend latest={trend.get('latest')} previous={trend.get('previous')} delta={trend.get('delta')}")
    return 0 if run.failed == 0 else 1
