# Deployment Runbook and Rollback Procedure (M5-004)

## Scope

This runbook covers deployment and rollback for the harness-driven automation system in this repository.

## Prerequisites

- Clean git state (no uncommitted production changes)
- Valid `config.json` in deployment target
- Python runtime available
- Required CLI/runtime dependencies installed
- Access to runtime directories under `.agent/`

## Deployment Steps

1. Validate repository state
   - `git status --short`
   - Ensure target commit is known and tagged/referenced

2. Run verification suite on target commit
   - `python verify_m3_001.py`
   - `python verify_m3_002.py`
   - `python verify_m3_003.py`
   - `python verify_m3_004.py`
   - `python verify_m4_002.py`
   - `python verify_m4_003.py`
   - `python verify_m4_004.py`
   - `python verify_m5_001.py`
   - `python verify_m5_002.py`
   - `python verify_m5_003.py`

3. Bootstrap and smoke run
   - `python harness.py --bootstrap`
   - `python harness.py --cycles 1`

4. Start managed run mode
   - One-shot dry run: `python autopilot.py --once --cycles 1`
   - Continuous mode (operations): `python autopilot.py`

5. Post-deploy checks
   - Review `.agent/runtime/harness.log` for clean cycle start/end
   - Review `.agent/runtime/health_status.json`
   - Review `.agent/runtime/cost_latency_status.json`
   - Confirm no repeated-failure or budget alerts unless expected

## Rollback Criteria

Rollback should be triggered when any condition is met:

- Critical regression in verification suite
- Repeated cycle failures beyond configured threshold
- Unrecovered crash state persists (`cycle_state.json` stuck `in_progress`)
- Safety/policy checks malfunction or are bypassed
- Production-impacting latency/cost alerts sustained beyond tolerance

## Rollback Procedure

1. Stop running automation process
   - Stop active `autopilot.py`/`harness.py` process safely

2. Identify last known-good commit
   - Use release tag or prior successful deployment commit

3. Switch to known-good version
   - `git checkout <known_good_commit>`

4. Reset runtime transient state (non-destructive)
   - Remove stale temp/ephemeral runtime files if needed:
     - `.agent/runtime/cycle_state.json`
     - `.agent/runtime/health_status.json`
     - `.agent/runtime/cost_latency_status.json`

5. Re-bootstrap and smoke test
   - `python harness.py --bootstrap`
   - `python harness.py --cycles 1`

6. Resume managed run and monitor
   - `python autopilot.py --once --cycles 1`
   - Verify logs/status files are healthy

## Rollback Validation (Tested Once)

Validation can be executed with:

- `python verify_m5_004.py`

The test simulates:

- selecting a known-good commit from local history,
- generating a rollback plan,
- validating required runtime cleanup targets,
- generating reproducible command checklist for operators.
