"""Data models for regression evaluation suite (M5-001)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class BenchmarkTask:
    """A benchmark task representing a core user journey."""

    task_id: str
    name: str
    description: str
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "metadata": self.metadata,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchmarkTask":
        return cls(
            task_id=str(data["task_id"]),
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            tags=list(data.get("tags", [])),
            metadata=dict(data.get("metadata", {})),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class EvalCaseResult:
    """Result of a single benchmark task execution."""

    task_id: str
    passed: bool
    duration_ms: int
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "passed": self.passed,
            "duration_ms": self.duration_ms,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class EvalRunResult:
    """Aggregated result for one regression run (typically one release)."""

    run_id: str
    release_tag: str
    started_at: str
    finished_at: str
    results: List[EvalCaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return round((self.passed / self.total) * 100.0, 2)

    @property
    def duration_ms(self) -> int:
        return sum(r.duration_ms for r in self.results)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "release_tag": self.release_tag,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "duration_ms": self.duration_ms,
            "results": [r.to_dict() for r in self.results],
        }
