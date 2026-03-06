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
STATE_FILE = ROOT / ".agent" / "runtime" / "autopilot_state.json"
OBSERVABILITY_STATUS_FILE = ROOT / ".agent" / "runtime" / "cost_latency_status.json"


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


def load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {"consecutive_failures": 0, "last_failure": ""}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {
                "consecutive_failures": int(data.get("consecutive_failures", 0)),
                "last_failure": str(data.get("last_failure", "")),
            }
    except Exception:
        pass
    return {"consecutive_failures": 0, "last_failure": ""}


def save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "consecutive_failures": int(state.get("consecutive_failures", 0)),
        "last_failure": str(state.get("last_failure", "")),
        "updated_at": now_iso(),
    }
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    temp.replace(STATE_FILE)


def reset_failure_state(state: Dict[str, Any]) -> None:
    state["consecutive_failures"] = 0
    state["last_failure"] = ""
    save_state(state)


def record_failure(state: Dict[str, Any], reason: str) -> None:
    state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1
    state["last_failure"] = reason
    save_state(state)
    log(f"failure recorded streak={state['consecutive_failures']} reason={reason}")


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


def run_release_gate(root: Path, cfg: Dict[str, Any]) -> bool:
    commands = cfg.get(
        "autopilot_release_gate_commands",
        [
            "python verify_m5_001.py",
            "python verify_m5_002.py",
            "python verify_m5_003.py",
            "python verify_m5_004.py",
        ],
    )
    timeout_seconds = int(cfg.get("autopilot_release_gate_timeout_seconds", 1200))
    if not commands:
        log("release gate skipped: no commands configured")
        return True

    log(f"release gate start count={len(commands)}")
    all_passed = True
    for command in commands:
        debug_log(f"release gate command start: {command}")
        try:
            cp = subprocess.run(
                command,
                cwd=str(root),
                shell=True,
                text=True,
                capture_output=True,
                timeout=max(1, timeout_seconds),
                encoding="utf-8",
                errors="replace",
            )
            debug_log(f"release gate rc={cp.returncode}: {command}")
            if cp.stdout:
                debug_log(cp.stdout.strip())
            if cp.stderr:
                debug_log(cp.stderr.strip())
            if cp.returncode != 0:
                all_passed = False
                log(f"release gate failed rc={cp.returncode}: {command}")
        except Exception as e:
            all_passed = False
            log(f"release gate exception: {command} | {e}")
    log("release gate passed" if all_passed else "release gate failed")
    return all_passed


def check_budget_guard(root: Path, cfg: Dict[str, Any]) -> bool:
    hard_limit = float(cfg.get("autopilot_budget_hard_limit", 0.0))
    if hard_limit <= 0:
        return True

    status_path = root / cfg.get("observability_status_file", str(OBSERVABILITY_STATUS_FILE.relative_to(ROOT)))
    if not status_path.exists():
        log(f"budget guard skipped: status file missing path={status_path}")
        return True

    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"budget guard skipped: invalid status file error={e}")
        return True

    metrics = data.get("metrics", {}) if isinstance(data, dict) else {}
    total_cost = float(metrics.get("total_cost", 0.0)) if isinstance(metrics, dict) else 0.0
    if total_cost > hard_limit:
        log(f"budget guard blocked run total_cost={total_cost} hard_limit={hard_limit}")
        return False
    return True


def _run_git(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def get_git_status_map() -> Dict[str, str]:
    cp = _run_git(["status", "--porcelain"])
    if cp.returncode != 0:
        debug_log(f"git status failed: {cp.stderr.strip()}")
        return {}

    status_map: Dict[str, str] = {}
    for line in (cp.stdout or "").splitlines():
        if len(line) < 4:
            continue
        status = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        status_map[path] = status
    return status_map


def select_new_changed_paths(before: Dict[str, str], after: Dict[str, str]) -> List[str]:
    selected: List[str] = []
    for path, status in after.items():
        if path not in before:
            selected.append(path)
    selected.sort()
    return selected


def auto_commit_and_push(
    cfg: Dict[str, Any],
    cycle_hint: str,
    before_status: Dict[str, str],
    after_status: Dict[str, str],
) -> bool:
    if not bool(cfg.get("autopilot_git_auto_commit", True)):
        log("auto-commit disabled by config")
        return True

    selected_paths = select_new_changed_paths(before_status, after_status)
    if not selected_paths:
        log("auto-commit skipped: no newly changed paths")
        return True

    add_cmd = ["add"] + selected_paths
    cp_add = _run_git(add_cmd)
    if cp_add.returncode != 0:
        log(f"auto-commit failed at git add rc={cp_add.returncode}")
        debug_log(cp_add.stderr.strip())
        return False

    prefix = str(cfg.get("autopilot_git_commit_prefix", "chore(autopilot)"))
    message = f"{prefix}: checkpoint {cycle_hint}"
    cp_commit = _run_git(["commit", "-m", message])
    if cp_commit.returncode != 0:
        log(f"auto-commit failed at git commit rc={cp_commit.returncode}")
        debug_log(cp_commit.stdout.strip())
        debug_log(cp_commit.stderr.strip())
        return False

    log(f"auto-commit success paths={len(selected_paths)}")
    debug_log(cp_commit.stdout.strip())

    if bool(cfg.get("autopilot_git_auto_push", True)):
        cp_push = _run_git(["push"])
        if cp_push.returncode != 0:
            log(f"auto-push failed rc={cp_push.returncode}")
            debug_log(cp_push.stdout.strip())
            debug_log(cp_push.stderr.strip())
            return False
        log("auto-push success")

    return True


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Autopilot launcher for harness")
    p.add_argument("--once", action="store_true", help="Run one harness launch then exit")
    p.add_argument("--cycles", type=int, default=0, help="When --once, run harness for N cycles")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config()
    state = load_state()
    sleep_seconds = int(cfg.get("autopilot_sleep_seconds", 10))
    pause_seconds = int(cfg.get("autopilot_pause_seconds", 180))
    max_consecutive_failures = int(cfg.get("autopilot_max_consecutive_failures", 3))
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

        status_before = get_git_status_map()

        if not run_debug_tests(ROOT, debug_commands, timeout_seconds=int(cfg.get("autopilot_debug_timeout_seconds", 600))):
            record_failure(state, "pre_run_debug_failed")
            log("skip harness launch because debug tests failed")
            if args.once:
                return 1
            if state["consecutive_failures"] >= max_consecutive_failures:
                log(f"circuit breaker engaged pause={pause_seconds}s")
                time.sleep(max(1, pause_seconds))
            else:
                time.sleep(sleep_seconds)
            continue

        if not run_release_gate(ROOT, cfg):
            record_failure(state, "release_gate_failed")
            log("skip harness launch because release gate failed")
            if args.once:
                return 1
            if state["consecutive_failures"] >= max_consecutive_failures:
                log(f"circuit breaker engaged pause={pause_seconds}s")
                time.sleep(max(1, pause_seconds))
            else:
                time.sleep(sleep_seconds)
            continue

        if not check_budget_guard(ROOT, cfg):
            record_failure(state, "budget_guard_blocked")
            log("skip harness launch because budget guard blocked run")
            if args.once:
                return 1
            if state["consecutive_failures"] >= max_consecutive_failures:
                log(f"circuit breaker engaged pause={pause_seconds}s")
                time.sleep(max(1, pause_seconds))
            else:
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
        if cp.returncode != 0:
            record_failure(state, f"harness_rc_{cp.returncode}")

        if not run_debug_tests(ROOT, debug_commands, timeout_seconds=int(cfg.get("autopilot_debug_timeout_seconds", 600))):
            record_failure(state, "post_run_debug_failed")
            log("post-run debug tests failed")
            if args.once:
                return 1

        if not check_budget_guard(ROOT, cfg):
            record_failure(state, "post_run_budget_guard_blocked")
            log("post-run budget guard blocked run")
            if args.once:
                return 1

        status_after = get_git_status_map()
        cycle_hint = "once" if args.once else "loop"
        auto_git_ok = auto_commit_and_push(cfg, cycle_hint=cycle_hint, before_status=status_before, after_status=status_after)
        if not auto_git_ok:
            record_failure(state, "auto_git_failed")

        cleanup_old_claude()
        cleanup_previous_step_cache(ROOT, cfg)

        if cp.returncode == 0 and all_features_done():
            log("completed successfully")
            reset_failure_state(state)
            return 0

        if cp.returncode == 0 and auto_git_ok:
            reset_failure_state(state)

        if args.once:
            return cp.returncode

        if state["consecutive_failures"] >= max_consecutive_failures:
            log(f"circuit breaker engaged pause={pause_seconds}s")
            time.sleep(max(1, pause_seconds))
            continue

        time.sleep(sleep_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
