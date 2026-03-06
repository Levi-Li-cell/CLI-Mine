"""Verification script for M5-003: 72-hour soak test support/report."""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from soak import SoakAnalyzer


def pass_line(msg: str) -> None:
    print(f"   [PASS] {msg}")


def fail_line(msg: str, reason: str = "") -> None:
    print(f"   [FAIL] {msg}")
    if reason:
        print(f"          Reason: {reason}")
    raise SystemExit(1)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    print("=== M5-003 VERIFICATION: Soak Test Report ===\n")
    tmp = Path(tempfile.mkdtemp(prefix="m5_003_test_"))

    try:
        runtime = tmp / ".agent" / "runtime"
        harness_log = runtime / "harness.log"
        cycle_state = runtime / "cycle_state.json"
        report_file = runtime / "soak_report.json"

        print("1. Testing: soak duration and cycle parsing...")
        log_content = "\n".join(
            [
                "[2026-03-01T00:00:00] cycle start cycle_000001 feature_id=F1",
                "[2026-03-01T00:10:00] cycle end cycle_000001 rc=0",
                "[2026-03-04T00:00:01] cycle start cycle_001000 feature_id=F2",
                "[2026-03-04T00:05:00] cycle end cycle_001000 rc=1",
            ]
        )
        write(harness_log, log_content + "\n")
        write(cycle_state, json.dumps({"status": "completed"}))

        analyzer = SoakAnalyzer(tmp)
        report = analyzer.build_report(
            harness_log_path=harness_log,
            cycle_state_path=cycle_state,
            output_path=report_file,
            target_hours=72.0,
        )
        if report.get("observed_hours", 0) < 72.0:
            fail_line("Observed duration", f"observed_hours={report.get('observed_hours')}")
        metrics = report.get("metrics", {})
        if metrics.get("cycle_count") != 2:
            fail_line("Cycle count", f"count={metrics.get('cycle_count')}")
        if metrics.get("failed_cycles") != 1:
            fail_line("Failed cycle count", f"failed={metrics.get('failed_cycles')}")
        pass_line("Duration and cycle metrics parsed correctly")

        print("\n2. Testing: unrecovered crash detection from cycle state...")
        write(cycle_state, json.dumps({"status": "in_progress", "cycle_index": 9}))
        report2 = analyzer.build_report(
            harness_log_path=harness_log,
            cycle_state_path=cycle_state,
            output_path=report_file,
            target_hours=72.0,
            max_allowed_unrecovered_crashes=0,
        )
        metrics2 = report2.get("metrics", {})
        if metrics2.get("unrecovered_crashes") != 1:
            fail_line("Unrecovered crash metric", f"value={metrics2.get('unrecovered_crashes')}")
        if report2.get("passed") is not False:
            fail_line("Pass flag when unrecovered crash present", f"passed={report2.get('passed')}")
        pass_line("Unrecovered crash is detected and fails criteria")

        print("\n3. Testing: report file persistence...")
        if not report_file.exists():
            fail_line("Report file exists", "soak_report.json not written")
        loaded = json.loads(report_file.read_text(encoding="utf-8"))
        if "criteria" not in loaded or "metrics" not in loaded:
            fail_line("Report shape", "missing criteria/metrics")
        pass_line("Soak report is persisted with expected fields")

        print("\n=== M5-003 VERIFICATION PASSED ===")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
