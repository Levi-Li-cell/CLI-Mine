"""Health monitoring utilities for long-running harness loops (M4-004)."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


TIMESTAMP_RE = re.compile(r"^\[(?P<ts>[^\]]+)\]")
RC_RE = re.compile(r"cycle end\s+\S+\s+rc=(?P<rc>-?\d+)")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


class HealthMonitor:
    """Analyzes runtime logs and writes a health status file."""

    def __init__(self, status_file: Path):
        self.status_file = Path(status_file)
        self.status_file.parent.mkdir(parents=True, exist_ok=True)

    def write_status(self, data: Dict[str, Any]) -> None:
        payload = dict(data)
        payload.setdefault("updated_at", _now_iso())
        temp = self.status_file.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=True)
        temp.replace(self.status_file)

    def load_status(self) -> Optional[Dict[str, Any]]:
        if not self.status_file.exists():
            return None
        try:
            return json.loads(self.status_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def update_heartbeat(self, source: str = "harness") -> Dict[str, Any]:
        status = {
            "ok": True,
            "status": "healthy",
            "source": source,
            "heartbeat_at": _now_iso(),
            "alerts": [],
            "metrics": {},
        }
        self.write_status(status)
        return status

    def analyze_harness_log(
        self,
        log_path: Path,
        stalled_after_seconds: int = 600,
        failure_alert_threshold: int = 3,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        now = now or datetime.now()
        lines: List[str] = []
        if Path(log_path).exists():
            lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()

        last_event_at: Optional[datetime] = None
        consecutive_failures = 0
        max_consecutive_failures = 0

        for line in lines:
            tm = TIMESTAMP_RE.search(line)
            if tm:
                parsed = _parse_iso(tm.group("ts"))
                if parsed:
                    last_event_at = parsed

            rc_match = RC_RE.search(line)
            if rc_match:
                rc = int(rc_match.group("rc"))
                if rc == 0:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    if consecutive_failures > max_consecutive_failures:
                        max_consecutive_failures = consecutive_failures

        alerts: List[str] = []
        stalled = False
        stall_seconds: Optional[int] = None

        if last_event_at is not None:
            delta = now - last_event_at
            stall_seconds = int(delta.total_seconds())
            if stall_seconds > max(1, int(stalled_after_seconds)):
                stalled = True
                alerts.append(
                    "loop stalled: no harness log activity "
                    f"for {stall_seconds}s (threshold={stalled_after_seconds}s)"
                )
        else:
            alerts.append("no harness events found")

        failure_alert = consecutive_failures >= max(1, int(failure_alert_threshold))
        if failure_alert:
            alerts.append(
                "repeated failures detected: "
                f"consecutive_failed_cycles={consecutive_failures}"
            )

        ok = not stalled and not failure_alert
        status = {
            "ok": ok,
            "status": "healthy" if ok else "degraded",
            "heartbeat_at": _now_iso(),
            "alerts": alerts,
            "metrics": {
                "stalled": stalled,
                "stall_seconds": stall_seconds,
                "consecutive_failed_cycles": consecutive_failures,
                "max_consecutive_failures": max_consecutive_failures,
                "line_count": len(lines),
            },
        }
        self.write_status(status)
        return status
