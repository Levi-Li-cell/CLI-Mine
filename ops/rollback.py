"""Rollback planning helpers for deployment operations (M5-004)."""

import subprocess
from pathlib import Path
from typing import Dict, List, Optional


RUNTIME_CLEANUP_TARGETS = [
    ".agent/runtime/cycle_state.json",
    ".agent/runtime/health_status.json",
    ".agent/runtime/cost_latency_status.json",
]


def _run_git(root: Path, args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=str(root),
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def get_recent_commits(root: Path, limit: int = 20) -> List[Dict[str, str]]:
    cp = _run_git(root, ["log", f"-{max(1, int(limit))}", "--oneline"])
    if cp.returncode != 0:
        return []
    rows: List[Dict[str, str]] = []
    for line in (cp.stdout or "").splitlines():
        parts = line.strip().split(" ", 1)
        if len(parts) == 2:
            rows.append({"sha": parts[0], "message": parts[1]})
    return rows


def choose_known_good_commit(root: Path, prefer_prefix: str = "feat(") -> Optional[str]:
    commits = get_recent_commits(root, limit=50)
    for row in commits:
        if row["message"].startswith(prefer_prefix):
            return row["sha"]
    return commits[0]["sha"] if commits else None


def build_rollback_plan(root: Path, known_good_commit: Optional[str] = None) -> Dict[str, object]:
    root = Path(root)
    target = known_good_commit or choose_known_good_commit(root)
    commands = [
        "python harness.py --bootstrap",
        "python harness.py --cycles 1",
        "python autopilot.py --once --cycles 1",
    ]
    return {
        "root": str(root),
        "known_good_commit": target,
        "checkout_command": f"git checkout {target}" if target else "",
        "cleanup_targets": list(RUNTIME_CLEANUP_TARGETS),
        "post_rollback_commands": commands,
    }
