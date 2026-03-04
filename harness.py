import argparse
import datetime as dt
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


RUNTIME_DIR = Path(".agent/runtime")
PROMPT_RUN_DIR = Path(".agent/prompts")
LOG_DIR = Path(".agent/logs")


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


def run_command(command: str, cwd: Path, timeout: Optional[int] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=str(cwd),
        shell=True,
        text=True,
        capture_output=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def ensure_runtime_dirs(root: Path) -> None:
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    (root / PROMPT_RUN_DIR).mkdir(parents=True, exist_ok=True)
    (root / LOG_DIR).mkdir(parents=True, exist_ok=True)


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


def pick_next_feature(features: List[Dict[str, Any]], priority_order: List[str]) -> Optional[Dict[str, Any]]:
    rank = {p: i for i, p in enumerate(priority_order)}
    pending = [f for f in features if not bool(f.get("passes", False))]
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


def invoke_agent(root: Path, command_template: str, prompt_content: str, cycle_tag: str) -> int:
    prompt_file = root / PROMPT_RUN_DIR / f"session_prompt_{cycle_tag}.md"
    out_file = root / LOG_DIR / f"agent_output_{cycle_tag}.log"
    err_file = root / LOG_DIR / f"agent_error_{cycle_tag}.log"

    write_text(prompt_file, prompt_content)
    cmd = command_template.format(prompt_file=str(prompt_file))
    cp = run_command(cmd, root)

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

    base_prompt = read_text(prompt_path)
    prompt = render_session_prompt(
        base_prompt=base_prompt,
        goal_text=read_text(goal_path),
        feature=None,
        feature_file=cfg["feature_file"],
        progress_file=cfg["progress_file"],
    )
    append_harness_log(root, "initializer start")
    rc = invoke_agent(root, cfg["agent_command_template"], prompt, cycle_tag="init")
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
    next_feature = pick_next_feature(features, cfg.get("default_priority_order", ["P0", "P1", "P2", "P3"]))
    if next_feature is None:
        append_harness_log(root, "all features passing; stopping")
        return False

    base_prompt = read_text(prompt_path)
    prompt = render_session_prompt(
        base_prompt=base_prompt,
        goal_text=read_text(goal_path),
        feature=next_feature,
        feature_file=cfg["feature_file"],
        progress_file=cfg["progress_file"],
    )

    cycle_tag = f"cycle_{cycle_index:06d}"
    append_harness_log(root, f"cycle start {cycle_tag} feature_id={next_feature.get('id')}")
    rc = invoke_agent(root, cfg["agent_command_template"], prompt, cycle_tag=cycle_tag)
    append_harness_log(root, f"cycle end {cycle_tag} rc={rc}")

    run_post_checks(root, cfg.get("post_cycle_checks", []))
    return True


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Long-running AI coding harness")
    p.add_argument("--root", default=".", help="Project root directory")
    p.add_argument("--bootstrap", action="store_true", help="Run initializer if needed")
    p.add_argument("--run-forever", action="store_true", help="Run coding cycles continuously")
    p.add_argument("--cycles", type=int, default=1, help="Number of coding cycles when not using --run-forever")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    os.chdir(root)

    ensure_runtime_dirs(root)
    cfg = load_config(root)
    git_check(root, bool(cfg.get("git_required", True)))

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

    cycle = 1
    while cycle <= limit:
        did_work = run_cycle(root, cfg, cycle)
        if not did_work:
            break
        cycle += 1
        if cycle <= limit:
            time.sleep(sleep_seconds)

    append_harness_log(root, "harness stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
