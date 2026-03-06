# Long-Running AI Dev Harness

This project implements a practical harness pattern from Anthropic's article
"Effective harnesses for long-running agents":

- Separate **initializer session** (one-time environment scaffolding)
- Repeating **coding sessions** (one feature per cycle)
- Persistent handoff artifacts (`claude-progress.txt`, `feature_list.json`, git history)
- Continuous loop mode so the system can run for days

## What this gives you

- A repeatable way to run an autonomous coding agent across many context windows.
- Guardrails against common failure modes:
  - trying to one-shot the whole app,
  - declaring completion too early,
  - losing context between sessions,
  - marking features done without verification.

## Quick start

1. Create a project directory and put your app source code there.
2. Copy this harness into that directory.
3. Configure `config.json` (copy from `config.example.json`).
4. Add your app goal/spec into `project_goal.md` (copy from `project_goal.example.md`).
5. Run:

```bash
python harness.py --bootstrap
python harness.py --run-forever
```

On first bootstrap, if initialization artifacts already exist (`init.sh`,
`feature_list.json`, `claude-progress.txt`), the harness will skip re-running
initializer and directly mark bootstrap complete.

## How it works

Each cycle does:

1. Read state from `.agent/runtime/` + git history.
2. Pick the highest-priority unfinished feature from `feature_list.json`.
3. Build a session prompt and call your configured agent command.
4. Ask the coding agent to:
   - complete exactly one feature,
   - run end-to-end verification,
   - update `feature_list.json` (`passes` only),
   - append `claude-progress.txt`,
   - commit cleanly.
5. Run post-session sanity checks and continue.

## Files

- `harness.py` - main runtime loop
- `config.example.json` - harness settings template
- `project_goal.example.md` - product goal/spec template
- `prompts/initializer_prompt.md` - one-time initializer instructions
- `prompts/coding_prompt.md` - repeating coding-session instructions
- `.agent/runtime/*` - generated state and logs

## Agent command integration

The harness is model/provider-agnostic by using an external command.

Set `agent_command_template` in `config.json`, for example:

- Claude Code CLI style:
  - `claude --print --dangerously-skip-permissions -f "{prompt_file}"`
- Any script wrapper you control:
  - `python tools/run_agent.py --prompt-file "{prompt_file}"`

The template must include `{prompt_file}`.

Important settings:

- `agent_timeout_seconds`: max seconds per agent run (default `1800`)
- `bootstrap_allow_existing_artifacts`: if `true`, bootstrap succeeds when
  core artifacts already exist
- `allow_skip_on_stuck`: if `true`, repeatedly failing features are auto-skipped
- `max_attempts_per_feature`: failed-attempt threshold before auto-skip

When a feature is auto-skipped, harness writes records to:

- `.agent/runtime/feature_attempt_state.json`
- `.agent/runtime/blocked_features.jsonl`

## Suggested production setup

- Run this inside a git repository.
- Keep CI checks available via a stable command.
- Provide browser E2E tooling (Playwright/Puppeteer MCP).
- Use a process manager (`systemd`, `pm2`, `supervisord`, Windows Task Scheduler).
- Send heartbeat logs to your monitoring system.

## Important behavior assumptions

- The coding agent modifies code directly in your project.
- The coding agent is responsible for making commits.
- `feature_list.json` entries must not be rewritten except for `passes` updates and evidence fields.

## Safety

- Keep secrets outside repo.
- Start in a non-production environment.
- Restrict dangerous shell capabilities in your selected agent runtime.
