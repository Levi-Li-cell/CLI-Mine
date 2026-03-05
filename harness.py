import argparse
import datetime as dt
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Audit logging with trace IDs (M2-004)
from audit import AuditLogger, TraceContext, AuditReplay, create_default_audit_logger
from health import HealthMonitor

_shutdown_requested = False


def _signal_handler(signum, frame):
    global _shutdown_requested
    _shutdown_requested = True
    print("\nShutdown requested, finishing current cycle...")


RUNTIME_DIR = Path(".agent/runtime")
PROMPT_RUN_DIR = Path(".agent/prompts")
LOG_DIR = Path(".agent/logs")
ATTEMPT_STATE_FILE = Path(".agent/runtime/feature_attempt_state.json")
BLOCKED_LOG_FILE = Path(".agent/runtime/blocked_features.jsonl")
REACT_TRACE_FILE = Path(".agent/runtime/react_traces.jsonl")
CYCLE_STATE_FILE = Path(".agent/runtime/cycle_state.json")
AUDIT_LOG_FILE = Path(".agent/runtime/audit.jsonl")  # M2-004: End-to-end audit logging
HEALTH_STATUS_FILE = Path(".agent/runtime/health_status.json")


def extract_react_traces(text: str) -> List[Dict[str, Any]]:
    """Extract Think/Observe/Final Answer blocks from agent output."""
    traces = []

    # Match ## Think blocks
    think_pattern = re.compile(
        r"## Think\s*\n(.*?)(?=\n## |\n```|\Z)", re.DOTALL | re.IGNORECASE
    )
    for match in think_pattern.finditer(text):
        traces.append({
            "type": "think",
            "content": match.group(1).strip()[:500],  # Truncate for logging
        })

    # Match ## Observe blocks
    observe_pattern = re.compile(
        r"## Observe\s*\n(.*?)(?=\n## |\n```|\Z)", re.DOTALL | re.IGNORECASE
    )
    for match in observe_pattern.finditer(text):
        traces.append({
            "type": "observe",
            "content": match.group(1).strip()[:500],
        })

    # Match ## Final Answer blocks
    final_pattern = re.compile(
        r"## Final Answer\s*\n(.*?)(?=\n## |\Z)", re.DOTALL | re.IGNORECASE
    )
    for match in final_pattern.finditer(text):
        traces.append({
            "type": "final_answer",
            "content": match.group(1).strip()[:1000],
        })

    return traces


def log_react_traces(root: Path, cycle_tag: str, traces: List[Dict[str, Any]]) -> None:
    """Log ReAct traces to jsonl file for observability."""
    for i, trace in enumerate(traces):
        entry = {
            "at": now_iso(),
            "cycle": cycle_tag,
            "seq": i,
            **trace,
        }
        append_jsonl(root / REACT_TRACE_FILE, entry)


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(read_text(path))


def save_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, indent=2, ensure_ascii=True) + "\n")


def append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=True) + "\n")


# Global audit logger instance (M2-004)
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger(root: Optional[Path] = None) -> AuditLogger:
    """Get or create the global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        log_path = (root or Path(".")) / AUDIT_LOG_FILE if root else AUDIT_LOG_FILE
        _audit_logger = create_default_audit_logger(log_path=log_path)
    return _audit_logger


def set_audit_logger(logger: AuditLogger) -> None:
    """Set the global audit logger instance."""
    global _audit_logger
    _audit_logger = logger


def run_command(
    command: str,
    cwd: Path,
    timeout: Optional[int] = None,
    unset_env: Optional[List[str]] = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    for key in (unset_env or []):
        env.pop(key, None)
    return subprocess.run(
        command,
        cwd=str(cwd),
        shell=True,
        text=True,
        capture_output=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def has_initializer_artifacts(root: Path, cfg: Dict[str, Any]) -> bool:
    required = [
        cfg.get("init_script", "init.sh"),
        cfg["feature_file"],
        cfg["progress_file"],
    ]
    for rel in required:
        if not (root / rel).exists():
            return False
    return True


def ensure_runtime_dirs(root: Path) -> None:
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    (root / PROMPT_RUN_DIR).mkdir(parents=True, exist_ok=True)
    (root / LOG_DIR).mkdir(parents=True, exist_ok=True)


def load_attempt_state(root: Path) -> Dict[str, Any]:
    path = root / ATTEMPT_STATE_FILE
    if not path.exists():
        return {"attempts": {}, "skipped": {}}
    try:
        data = load_json(path)
    except Exception:
        return {"attempts": {}, "skipped": {}}
    if not isinstance(data, dict):
        return {"attempts": {}, "skipped": {}}
    attempts = data.get("attempts", {})
    skipped = data.get("skipped", {})
    if not isinstance(attempts, dict):
        attempts = {}
    if not isinstance(skipped, dict):
        skipped = {}
    return {"attempts": attempts, "skipped": skipped}


def save_attempt_state(root: Path, state: Dict[str, Any]) -> None:
    save_json(root / ATTEMPT_STATE_FILE, state)


# Cycle state for crash recovery (M4-001)

def load_cycle_state(root: Path) -> Dict[str, Any]:
    """Load cycle state from disk. Returns empty state if not found."""
    path = root / CYCLE_STATE_FILE
    if not path.exists():
        return {}
    try:
        data = load_json(path)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def save_cycle_state(root: Path, state: Dict[str, Any]) -> None:
    """Persist cycle state to disk for crash recovery."""
    save_json(root / CYCLE_STATE_FILE, state)


def mark_cycle_start(root: Path, cycle_index: int, feature_id: str, agent_pid: Optional[int] = None) -> None:
    """Mark a cycle as in-progress before starting agent execution."""
    state = {
        "cycle_index": cycle_index,
        "feature_id": feature_id,
        "status": "in_progress",
        "started_at": now_iso(),
        "completed_at": None,
        "agent_pid": agent_pid,
    }
    save_cycle_state(root, state)
    append_harness_log(root, f"cycle state saved: cycle={cycle_index} feature={feature_id} status=in_progress")


def mark_cycle_complete(root: Path, cycle_index: int, feature_id: str, success: bool) -> None:
    """Mark a cycle as completed (success or failed)."""
    state = load_cycle_state(root)
    state["status"] = "completed" if success else "failed"
    state["completed_at"] = now_iso()
    save_cycle_state(root, state)
    append_harness_log(root, f"cycle state updated: cycle={cycle_index} feature={feature_id} status={state['status']}")


def check_crash_recovery(root: Path) -> Optional[Dict[str, Any]]:
    """
    Check if there was a crash during a previous cycle.
    Returns recovery info if crash detected, None otherwise.
    """
    state = load_cycle_state(root)
    if not state:
        return None

    status = state.get("status", "")
    if status != "in_progress":
        return None

    # Check if agent process is still running
    agent_pid = state.get("agent_pid")
    if agent_pid:
        try:
            # Check if process exists (POSIX)
            os.kill(agent_pid, 0)
            # Process still running - not a crash
            return None
        except (OSError, ProcessLookupError):
            # Process not found - confirmed crash
            pass
        except AttributeError:
            # Windows doesn't support os.kill with signal 0
            # Fall through to assume crash
            pass

    # Return recovery info
    return {
        "cycle_index": state.get("cycle_index", 1),
        "feature_id": state.get("feature_id"),
        "started_at": state.get("started_at"),
        "recovered_at": now_iso(),
    }


def get_next_cycle_index(root: Path) -> int:
    """
    Determine the next cycle index based on existing logs.
    Used for crash recovery to resume from the correct cycle.
    """
    log_dir = root / LOG_DIR
    if not log_dir.exists():
        return 1

    # Find highest cycle number from existing log files
    max_cycle = 0
    for f in log_dir.iterdir():
        if f.is_file() and f.name.startswith("agent_output_cycle_"):
            try:
                # Extract cycle number from filename like agent_output_cycle_000001.log
                parts = f.stem.split("_")
                if len(parts) >= 3:
                    cycle_num = int(parts[-1])
                    max_cycle = max(max_cycle, cycle_num)
            except (ValueError, IndexError):
                continue

    # Also check cycle state for recovery
    state = load_cycle_state(root)
    if state and state.get("status") == "in_progress":
        # Resume from the crashed cycle (it needs to be re-run)
        return state.get("cycle_index", max_cycle + 1)

    return max_cycle + 1


def load_config(root: Path) -> Dict[str, Any]:
    cfg_path = root / "config.json"
    if not cfg_path.exists():
        raise FileNotFoundError(
            "config.json not found. Copy config.example.json to config.json and edit it."
        )
    data = load_json(cfg_path)
    required = [
        "agent_command_template",
        "working_directory",
        "feature_file",
        "progress_file",
        "project_goal_file",
    ]
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"config.json missing required keys: {missing}")
    return data


def git_check(root: Path, required: bool) -> None:
    cp = run_command("git rev-parse --is-inside-work-tree", root)
    ok = cp.returncode == 0 and "true" in (cp.stdout or "")
    if required and not ok:
        raise RuntimeError("git_required=true but this directory is not a git repository.")


def read_feature_list(path: Path) -> List[Dict[str, Any]]:
    data = load_json(path)
    if not isinstance(data, list):
        raise ValueError("feature_list.json must be a JSON array")
    return data


def pick_next_feature(
    features: List[Dict[str, Any]],
    priority_order: List[str],
    skipped_ids: Optional[set] = None,
) -> Optional[Dict[str, Any]]:
    rank = {p: i for i, p in enumerate(priority_order)}
    skipped_ids = skipped_ids or set()
    pending = [
        f
        for f in features
        if not bool(f.get("passes", False)) and str(f.get("id", "")) not in skipped_ids
    ]
    if not pending:
        return None
    pending.sort(key=lambda f: (rank.get(str(f.get("priority", "P9")), 99), str(f.get("id", ""))))
    return pending[0]


def render_session_prompt(
    base_prompt: str,
    goal_text: str,
    feature: Optional[Dict[str, Any]],
    feature_file: str,
    progress_file: str,
) -> str:
    chosen = "None"
    if feature:
        chosen = json.dumps(feature, ensure_ascii=True, indent=2)
    return (
        f"{base_prompt.strip()}\n\n"
        f"## Harness context\n"
        f"- Goal file content:\n\n{goal_text.strip()}\n\n"
        f"- Feature file: {feature_file}\n"
        f"- Progress file: {progress_file}\n"
        f"- Selected feature for this session:\n{chosen}\n"
    )


def invoke_agent(
    root: Path,
    command_template: str,
    prompt_content: str,
    cycle_tag: str,
    timeout_seconds: Optional[int] = None,
) -> int:
    prompt_file = root / PROMPT_RUN_DIR / f"session_prompt_{cycle_tag}.md"
    out_file = root / LOG_DIR / f"agent_output_{cycle_tag}.log"
    err_file = root / LOG_DIR / f"agent_error_{cycle_tag}.log"

    write_text(prompt_file, prompt_content)
    cmd = command_template.format(prompt_file=str(prompt_file))
    timeout = None if timeout_seconds is None else max(1, int(timeout_seconds))
    cp = run_command(cmd, root, timeout=timeout, unset_env=["CLAUDECODE"])

    write_text(out_file, cp.stdout or "")
    write_text(err_file, cp.stderr or "")
    return cp.returncode


def append_harness_log(root: Path, message: str) -> None:
    log_file = root / RUNTIME_DIR / "harness.log"
    line = f"[{now_iso()}] {message}\n"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line)


def run_post_checks(root: Path, checks: List[str]) -> None:
    for cmd in checks:
        cp = run_command(cmd, root)
        append_harness_log(
            root,
            f"post-check: {cmd} | rc={cp.returncode} | out={(cp.stdout or '').strip()} | err={(cp.stderr or '').strip()}",
        )


def run_initializer(root: Path, cfg: Dict[str, Any]) -> int:
    prompt_path = root / "prompts" / "initializer_prompt.md"
    goal_path = root / cfg["project_goal_file"]
    if not prompt_path.exists():
        raise FileNotFoundError(f"Missing {prompt_path}")
    if not goal_path.exists():
        raise FileNotFoundError(f"Missing {goal_path}")

    if bool(cfg.get("bootstrap_allow_existing_artifacts", True)) and has_initializer_artifacts(root, cfg):
        append_harness_log(root, "initializer skipped: artifacts already exist")
        return 0

    base_prompt = read_text(prompt_path)
    prompt = render_session_prompt(
        base_prompt=base_prompt,
        goal_text=read_text(goal_path),
        feature=None,
        feature_file=cfg["feature_file"],
        progress_file=cfg["progress_file"],
    )
    append_harness_log(root, "initializer start")
    rc = invoke_agent(
        root,
        cfg["agent_command_template"],
        prompt,
        cycle_tag="init",
        timeout_seconds=cfg.get("agent_timeout_seconds", 1800),
    )
    append_harness_log(root, f"initializer end rc={rc}")
    return rc


def should_run_initializer(root: Path, cfg: Dict[str, Any]) -> bool:
    marker = root / RUNTIME_DIR / "initializer.done"
    return bool(cfg.get("run_init_once", True)) and not marker.exists()


def mark_initializer_done(root: Path) -> None:
    marker = root / RUNTIME_DIR / "initializer.done"
    write_text(marker, f"done {now_iso()}\n")


def run_cycle(root: Path, cfg: Dict[str, Any], cycle_index: int) -> bool:
    prompt_path = root / "prompts" / "coding_prompt.md"
    goal_path = root / cfg["project_goal_file"]
    feature_path = root / cfg["feature_file"]

    if not prompt_path.exists() or not goal_path.exists() or not feature_path.exists():
        append_harness_log(root, "missing required files for cycle")
        return False

    features = read_feature_list(feature_path)
    attempt_state = load_attempt_state(root)
    skipped_ids = set(attempt_state.get("skipped", {}).keys())
    next_feature = pick_next_feature(
        features,
        cfg.get("default_priority_order", ["P0", "P1", "P2", "P3"]),
        skipped_ids=skipped_ids,
    )
    if next_feature is None:
        remaining = [f for f in features if not bool(f.get("passes", False))]
        if remaining:
            append_harness_log(root, "all remaining features are skipped/blocked; stopping")
        else:
            append_harness_log(root, "all features passing; stopping")
        return False

    goal_text = read_text(goal_path)
    base_prompt = read_text(prompt_path)
    prompt = render_session_prompt(
        base_prompt=base_prompt,
        goal_text=goal_text,
        feature=next_feature,
        feature_file=cfg["feature_file"],
        progress_file=cfg["progress_file"],
    )

    cycle_tag = f"cycle_{cycle_index:06d}"
    feature_id = str(next_feature.get("id", ""))

    # Start audit trace for this cycle (M2-004)
    audit_logger = get_audit_logger(root)
    trace = audit_logger.start_trace(
        task_id=cycle_tag,
        feature_id=feature_id,
        metadata={"cycle_index": cycle_index},
    )

    # Log model call with trace_id (M2-004)
    audit_logger.log_model_call(
        trace_id=trace.trace_id,
        model=cfg.get("model_name", "unknown"),
        provider=cfg.get("model_provider", "unknown"),
        prompt=prompt[:5000],  # Truncate for storage
    )

    # Persist cycle state for crash recovery (M4-001)
    mark_cycle_start(root, cycle_index, feature_id)

    append_harness_log(root, f"cycle start {cycle_tag} feature_id={feature_id} trace_id={trace.trace_id}")
    use_multi_agent = bool(cfg.get("multi_agent_enabled", False))
    if use_multi_agent:
        from agents import create_orchestrator

        orchestrator = create_orchestrator(
            command_template=cfg["agent_command_template"],
            root_dir=root,
            timeout_seconds=cfg.get("agent_timeout_seconds", 1800),
            max_iterations=int(cfg.get("multi_agent_max_iterations", 2)),
        )
        workflow = orchestrator.run_workflow(
            feature_id=feature_id,
            goal_text=goal_text,
            feature=next_feature,
            context={"cycle": cycle_tag},
            cycle_tag=cycle_tag,
        )
        workflow_path = root / LOG_DIR / f"workflow_{cycle_tag}.json"
        save_json(workflow_path, workflow.to_dict())

        output_lines = [
            "## Final Answer",
            "- Role: Orchestrator",
            f"- Status: {'COMPLETE' if workflow.decision and workflow.decision.is_approved else 'BLOCKED'}",
            f"- Summary: {workflow.decision.summary if workflow.decision else 'No decision'}",
            f"- Files Modified: {workflow.decision.approved_files if workflow.decision else []}",
            "- Files Created: []",
            f"- Issues Found: {workflow.decision.required_actions if workflow.decision else []}",
            f"- Suggestions: {workflow.decision.review_notes if workflow.decision else ''}",
            f"- Confidence: {workflow.decision.confidence if workflow.decision else 0.0}",
        ]
        write_text(root / LOG_DIR / f"agent_output_{cycle_tag}.log", "\n".join(output_lines) + "\n")
        write_text(root / LOG_DIR / f"agent_error_{cycle_tag}.log", "")

        rc = 0 if workflow.decision and workflow.decision.is_approved else 1
        if workflow.decision:
            append_harness_log(
                root,
                (
                    "multi-agent decision "
                    f"feature_id={feature_id} "
                    f"decision={workflow.decision.decision.value} "
                    f"conflicts={len(workflow.conflicts)}"
                ),
            )
    else:
        rc = invoke_agent(
            root,
            cfg["agent_command_template"],
            prompt,
            cycle_tag=cycle_tag,
            timeout_seconds=cfg.get("agent_timeout_seconds", 1800),
        )
    append_harness_log(root, f"cycle end {cycle_tag} rc={rc}")

    # Mark cycle as complete for crash recovery (M4-001)
    mark_cycle_complete(root, cycle_index, feature_id, success=(rc == 0))

    # Extract and log ReAct traces for observability (M1-001)
    out_file = root / LOG_DIR / f"agent_output_{cycle_tag}.log"
    if out_file.exists():
        output_text = read_text(out_file)
        traces = extract_react_traces(output_text)
        if traces:
            log_react_traces(root, cycle_tag, traces)
            append_harness_log(root, f"react traces logged count={len(traces)}")

        # Log model response with trace_id (M2-004)
        audit_logger.log_model_response(
            trace_id=trace.trace_id,
            response=output_text[:5000],  # Truncate
            finish_reason="stop" if rc == 0 else "error",
            error=None if rc == 0 else f"Agent returned rc={rc}",
        )

    attempts = attempt_state.get("attempts", {})
    attempts[feature_id] = int(attempts.get(feature_id, 0)) + 1
    attempt_state["attempts"] = attempts

    max_attempts = int(cfg.get("max_attempts_per_feature", 8))
    allow_skip = bool(cfg.get("allow_skip_on_stuck", True))
    if rc != 0 and allow_skip and attempts[feature_id] >= max_attempts:
        skipped = attempt_state.get("skipped", {})
        reason = (
            f"Auto-skipped after {attempts[feature_id]} failed attempts; "
            "requires human review"
        )
        skipped[feature_id] = {
            "reason": reason,
            "at": now_iso(),
            "last_cycle": cycle_tag,
            "last_rc": rc,
        }
        attempt_state["skipped"] = skipped
        append_harness_log(root, f"feature skipped {feature_id}: {reason}")
        append_jsonl(
            root / BLOCKED_LOG_FILE,
            {
                "at": now_iso(),
                "feature_id": feature_id,
                "reason": reason,
                "last_cycle": cycle_tag,
                "last_rc": rc,
            },
        )

    save_attempt_state(root, attempt_state)

    run_post_checks(root, cfg.get("post_cycle_checks", []))

    # End audit trace (M2-004)
    trace_status = "success" if rc == 0 else "failed"
    audit_logger.end_trace(
        trace_id=trace.trace_id,
        status=trace_status,
        summary=f"Cycle completed with rc={rc}",
    )

    return True


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Long-running AI coding harness")
    p.add_argument("--root", default=".", help="Project root directory")
    p.add_argument("--bootstrap", action="store_true", help="Run initializer if needed")
    p.add_argument("--run-forever", action="store_true", help="Run coding cycles continuously")
    p.add_argument("--cycles", type=int, default=0, help="Number of coding cycles when not using --run-forever")
    return p.parse_args()


def main() -> int:
    global _shutdown_requested
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    args = parse_args()
    root = Path(args.root).resolve()
    os.chdir(root)

    ensure_runtime_dirs(root)
    cfg = load_config(root)
    git_check(root, bool(cfg.get("git_required", True)))

    health_monitor = HealthMonitor(root / cfg.get("health_status_file", str(HEALTH_STATUS_FILE)))
    health_monitor.update_heartbeat(source="harness_start")

    if args.bootstrap and should_run_initializer(root, cfg):
        rc = run_initializer(root, cfg)
        if rc == 0:
            mark_initializer_done(root)
        else:
            append_harness_log(root, "initializer failed")
            return rc

    if not args.run_forever and args.cycles <= 0:
        return 0

    sleep_seconds = int(cfg.get("sleep_seconds_between_cycles", 10))
    max_cycles = int(cfg.get("max_cycles", 0))
    limit = max_cycles if args.run_forever and max_cycles > 0 else (sys.maxsize if args.run_forever else args.cycles)

    # Check for crash recovery (M4-001)
    recovery_info = check_crash_recovery(root)
    if recovery_info:
        append_harness_log(
            root,
            f"crash recovery detected: cycle={recovery_info['cycle_index']} "
            f"feature={recovery_info['feature_id']} "
            f"original_start={recovery_info['started_at']}"
        )
        print(f"Recovering from crash at cycle {recovery_info['cycle_index']} (feature: {recovery_info['feature_id']})")

    # Determine starting cycle (resume from crash or use next available)
    cycle = get_next_cycle_index(root)
    append_harness_log(root, f"harness starting from cycle {cycle}")

    while cycle <= limit:
        if _shutdown_requested:
            append_harness_log(root, "harness stopped by signal")
            print("Graceful shutdown complete.")
            return 0

        health_monitor.update_heartbeat(source="cycle_start")
        did_work = run_cycle(root, cfg, cycle)
        health_status = health_monitor.analyze_harness_log(
            log_path=root / RUNTIME_DIR / "harness.log",
            stalled_after_seconds=int(cfg.get("health_stalled_after_seconds", 600)),
            failure_alert_threshold=int(cfg.get("health_failure_alert_threshold", 3)),
        )
        if health_status.get("alerts"):
            append_harness_log(
                root,
                "health alerts: " + " | ".join(health_status.get("alerts", [])),
            )
        if not did_work:
            break
        cycle += 1
        if cycle <= limit:
            time.sleep(sleep_seconds)

    append_harness_log(root, "harness stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
