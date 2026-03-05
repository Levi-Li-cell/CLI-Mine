import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parent
FEATURE_FILE = ROOT / "feature_list.json"
CONFIG_FILE = ROOT / "config.json"
LOG_FILE = ROOT / ".agent" / "runtime" / "autopilot.log"
DEBUG_LOG_FILE = ROOT / ".agent" / "runtime" / "autopilot.debug.log"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{now_iso()}] {msg}\n")


def debug_log(msg: str) -> None:
    DEBUG_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DEBUG_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{now_iso()}] {msg}\n")


def load_config() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def all_features_done() -> bool:
    if not FEATURE_FILE.exists():
        return False
    try:
        data = json.loads(FEATURE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(data, list):
        return False
    return all(bool(item.get("passes", False)) for item in data)


def cleanup_old_claude() -> None:
    if os.name == "nt":
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-CimInstance Win32_Process | "
                "Where-Object { "
                "($_.Name -match '^claude(\\.exe)?$') -or "
                "($_.CommandLine -match '(^|\\s)claude(\\.exe)?(\\s|$)') "
                "} | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
            ),
        ]
    else:
        cmd = ["pkill", "-f", "(^|\\s)claude(\\s|$)"]

    cp = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
    log(f"cleanup claude rc={cp.returncode}")


def cleanup_previous_step_cache(root: Path, cfg: Dict[str, Any]) -> Dict[str, int]:
    patterns = cfg.get(
        "autopilot_cache_cleanup_globs",
        [
            "**/__pycache__",
            "**/*.pyc",
            ".agent/runtime/cycle_state.json",
            ".agent/runtime/health_status.json",
            ".agent/runtime/autopilot_step_cache.json",
        ],
    )
    removed_files = 0
    removed_dirs = 0

    for pattern in patterns:
        for path in root.glob(pattern):
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                    removed_dirs += 1
                elif path.is_file():
                    path.unlink(missing_ok=True)
                    removed_files += 1
            except Exception as e:
                debug_log(f"cache cleanup warning path={path} error={e}")

    log(f"cache cleanup files={removed_files} dirs={removed_dirs}")
    return {"files": removed_files, "dirs": removed_dirs}


def run_debug_tests(root: Path, commands: List[str], timeout_seconds: int = 600) -> bool:
    if not commands:
        log("debug tests skipped: no commands configured")
        return True

    log(f"debug tests start count={len(commands)}")
    all_passed = True

    for command in commands:
        debug_log(f"debug command start: {command}")
        try:
            cp = subprocess.run(
                command,
                cwd=str(root),
                shell=True,
                text=True,
                capture_output=True,
                timeout=max(1, int(timeout_seconds)),
                encoding="utf-8",
                errors="replace",
            )
            debug_log(f"debug command rc={cp.returncode}: {command}")
            if cp.stdout:
                debug_log(cp.stdout.strip())
            if cp.stderr:
                debug_log(cp.stderr.strip())
            if cp.returncode != 0:
                all_passed = False
                log(f"debug test failed rc={cp.returncode}: {command}")
        except Exception as e:
            all_passed = False
            log(f"debug test exception: {command} | {e}")

    log("debug tests passed" if all_passed else "debug tests failed")
    return all_passed


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Autopilot launcher for harness")
    p.add_argument("--once", action="store_true", help="Run one harness launch then exit")
    p.add_argument("--cycles", type=int, default=0, help="When --once, run harness for N cycles")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config()
    sleep_seconds = int(cfg.get("autopilot_sleep_seconds", 10))
    debug_commands = cfg.get(
        "autopilot_debug_test_commands",
        [
            "python verify_m3_002.py",
            "python verify_m4_004.py",
        ],
    )

    log("autopilot start")
    while True:
        if all_features_done():
            log("all features passed, stop")
            return 0

        cleanup_old_claude()
        cleanup_previous_step_cache(ROOT, cfg)

        if not run_debug_tests(ROOT, debug_commands, timeout_seconds=int(cfg.get("autopilot_debug_timeout_seconds", 600))):
            log("skip harness launch because debug tests failed")
            if args.once:
                return 1
            time.sleep(sleep_seconds)
            continue

        cmd = [sys.executable, "harness.py", "--bootstrap"]
        if args.once:
            if args.cycles > 0:
                cmd.extend(["--cycles", str(args.cycles)])
            else:
                cmd.extend(["--cycles", "1"])
        else:
            cmd.append("--run-forever")

        log(f"launch: {' '.join(cmd)}")
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        cp = subprocess.run(cmd, cwd=str(ROOT), text=True, env=env)
        log(f"harness exited rc={cp.returncode}")

        cleanup_old_claude()
        cleanup_previous_step_cache(ROOT, cfg)

        if cp.returncode == 0 and all_features_done():
            log("completed successfully")
            return 0

        if args.once:
            return cp.returncode

        time.sleep(sleep_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
