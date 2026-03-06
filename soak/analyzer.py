"""Soak test analysis and report generation for M5-003."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


TIMESTAMP_RE = re.compile(r"^\[(?P<ts>[^\]]+)\]")
RC_RE = re.compile(r"cycle end\s+\S+\s+rc=(?P<rc>-?\d+)")


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


class SoakAnalyzer:
    """Build soak reports from runtime logs and state files."""

    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir)

    def _read_lines(self, path: Path) -> List[str]:
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8", errors="replace").splitlines()

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            return {}
        except Exception:
            return {}

    def build_report(
        self,
        harness_log_path: Optional[Path] = None,
        cycle_state_path: Optional[Path] = None,
        output_path: Optional[Path] = None,
        target_hours: float = 72.0,
        max_allowed_unrecovered_crashes: int = 0,
    ) -> Dict[str, Any]:
        harness_log = Path(harness_log_path or (self.root_dir / ".agent" / "runtime" / "harness.log"))
        cycle_state = Path(cycle_state_path or (self.root_dir / ".agent" / "runtime" / "cycle_state.json"))

        lines = self._read_lines(harness_log)
        first_at: Optional[datetime] = None
        last_at: Optional[datetime] = None
        cycle_count = 0
        failed_cycles = 0
        recovery_events = 0

        for line in lines:
            match = TIMESTAMP_RE.search(line)
            if match:
                ts = _parse_iso(match.group("ts"))
                if ts:
                    if first_at is None:
                        first_at = ts
                    last_at = ts

            rc = RC_RE.search(line)
            if rc:
                cycle_count += 1
                if int(rc.group("rc")) != 0:
                    failed_cycles += 1

            if "crash recovery detected:" in line:
                recovery_events += 1

        observed_hours = 0.0
        if first_at and last_at and last_at >= first_at:
            observed_hours = round((last_at - first_at).total_seconds() / 3600.0, 3)

        cycle_state_data = self._load_json(cycle_state)
        unrecovered_crashes = 0
        if cycle_state_data.get("status") == "in_progress":
            unrecovered_crashes = 1

        criteria = {
            "duration_met": observed_hours >= float(target_hours),
            "no_unrecovered_crash": unrecovered_crashes <= int(max_allowed_unrecovered_crashes),
        }
        passed = all(criteria.values())

        report = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "target_hours": float(target_hours),
            "observed_hours": observed_hours,
            "harness_log": str(harness_log),
            "cycle_state_file": str(cycle_state),
            "metrics": {
                "cycle_count": cycle_count,
                "failed_cycles": failed_cycles,
                "recovery_events": recovery_events,
                "unrecovered_crashes": unrecovered_crashes,
            },
            "criteria": criteria,
            "passed": passed,
            "summary": (
                "Soak criteria met"
                if passed
                else "Soak criteria not met (inspect metrics/criteria)"
            ),
        }

        target = Path(output_path or (self.root_dir / ".agent" / "runtime" / "soak_report.json"))
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        temp.replace(target)

        return report
