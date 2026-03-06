"""Persistence for regression benchmark definitions and run history."""

import json
from pathlib import Path
from typing import Any, Dict, List

from .models import BenchmarkTask, EvalRunResult


class EvalPersistence:
    """Store benchmark task catalog and run history on disk."""

    def __init__(self, eval_dir: Path):
        self.eval_dir = Path(eval_dir)
        self.eval_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_file = self.eval_dir / "benchmark_tasks.json"
        self.runs_file = self.eval_dir / "runs.jsonl"

    def save_tasks(self, tasks: List[BenchmarkTask]) -> None:
        payload = [t.to_dict() for t in tasks]
        temp = self.tasks_file.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        temp.replace(self.tasks_file)

    def load_tasks(self) -> List[BenchmarkTask]:
        if not self.tasks_file.exists():
            return []
        try:
            data = json.loads(self.tasks_file.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            return [BenchmarkTask.from_dict(item) for item in data]
        except Exception:
            return []

    def append_run(self, run: EvalRunResult) -> None:
        with self.runs_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(run.to_dict(), ensure_ascii=True) + "\n")

    def load_runs(self) -> List[Dict[str, Any]]:
        if not self.runs_file.exists():
            return []
        rows: List[Dict[str, Any]] = []
        with self.runs_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
        return rows
