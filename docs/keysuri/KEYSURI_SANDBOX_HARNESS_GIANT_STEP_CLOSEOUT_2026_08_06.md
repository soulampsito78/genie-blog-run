# GENIE / KeeSuri Sandbox Harness Giant Step — Closeout

**Date:** 2026-08-06 (KST)
**Scope:** SANDBOX / LOCAL ONLY
**Label:** `GENIE_KEESURI_SANDBOX_HARNESS_GIANT_STEP_COMPLETE`

## What this batch did

- Classified and remediated clean-HEAD baseline failures (environment-dependent hero data-URI fixtures).
- Completed parent-eligibility gate for Admin reissue (`reissue_parent_block_reason`).
- Added production-faithful harnesses:
  - `tests/test_admin_reissue_sandbox_harness.py` (Today body_only / image_only / full; Global body_only / full; negatives)
  - `tests/test_natural_run_sandbox_harness.py` (Today 12 / Global 20 / Korea 18 scenario IDs; Tomorrow inactive guard)
  - `tests/test_failure_events_metrics_sandbox_harness.py` + `scripts/inspect_owner_review_ops_local.py`
- Converted pre-existing skip/xfail stubs into real assertions where already in the dirty tree.

## Baseline-failure status

See `docs/keysuri/KEYSURI_SANDBOX_BASELINE_FAILURE_CLASSIFICATION_2026_08_06.md`.

Clean HEAD (`7d19869`) had **2 failed** nodes caused by missing local `output/keysuri_preview/image_canary` assets. Remedied by deterministic tiny PNG data-URI fixtures (no production validation weakening).

Historical “21 baseline failures” from the 2026-07-31 closeout are **ALREADY_FIXED_BUT_STALE_BASELINE** at this HEAD.

## Failure-event payload reality

Runtime emits a **bare single-line JSON object** via logger `genie.owner_review_failure_event` (`%(message)s`, `propagate=False`). Cloud Logging may parse that line into `jsonPayload`. Dedup is **in-process only**. Documented filters in `docs/ops/OWNER_REVIEW_FAILURE_ALERTING.md` match this reality.

## Recurrence-counter inspection

```bash
python3 scripts/inspect_owner_review_ops_local.py \
  --failure-log tests/fixtures/owner_review_ops/sample_failure_events.jsonl \
  --artifacts-dir tests/fixtures/owner_review_ops/artifacts \
  --group-by program_id,first_failed_stage,issue_code \
  --json
```

Read-only. No secrets. No network. Non-zero on malformed input.

## Final local test results (this batch)

- Targeted harnesses: Admin + Natural + Failure/Metrics green
- Generation-recovery + recurrence: 88 passed
- Full suite: **2570 passed**, 0 failed, 0 new xfail
- No live operational QA in this batch
- Gmail / SMTP / Scheduler proof remains a **separate future batch**
- **No push. No deploy.**

## Explicit non-claims

- No production Admin reissue POST
- No Scheduler run/modification
- No live Gemini / image API / SMTP / Gmail
- No customer approve / final-send
- No Secret Manager access
