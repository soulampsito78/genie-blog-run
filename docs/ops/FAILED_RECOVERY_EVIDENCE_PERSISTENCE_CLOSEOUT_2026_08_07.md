# Failed Recovery Evidence Persistence + Test-Count Closeout

**Date (KST):** 2026-08-07  
**Scope:** admin_run evidence on terminal post-generation failures; 2651 vs 2656 suite-count ambiguity.

## 2651 vs 2656 — forensic classification

**Classification: A. FIRST_RUN_BEFORE_5_NEW_TESTS**

Prior ellipsis closeout reported:

| Run | Collected | Log |
|---|---|---|
| #1 | **2651** | `/tmp/suite_e1.txt` → `Ran 2651 tests` |
| #2 | **2656** | `/tmp/suite_e2.txt` → `Ran 2656 tests` |

**Exact reason:** Δ = 5 = number of tests in
`tests/test_keysuri_global_20260807_131133_recovery1_ellipsis_harness.py`.

That harness file was written in the **same agent turn** as full-suite run #1
(tool calls launched in parallel). Suite #1 often started before the new file
was discoverable on disk; suite #2 saw all five new tests.

The two runs were **not** on identical HEAD + identical discoverable tree at
start of collection, even though the intended command was identical:

```bash
python3 -u -m unittest discover -s tests -p 'test_*.py'
```

This is **not** conditional collection, nondeterministic collection, different
commands, or a reporting error.

## Evidence persistence contract

On every terminal failure after generation has begun,
`attach_bounded_post_generation_failure_evidence` (called from
`_save_failed_run_artifact` in `keysuri_service_full_run.py`) persists a
bounded contract onto admin_run, including:

- `program_id`, `run_id`, `trigger_source`, `created_at` / `failed_at`
- `deployed_revision` / `deployed_commit_sha` (from `K_REVISION` / `COMMIT_SHA`)
- `generation_diagnostics` (allowlisted keys only)
- `generation_contract` (sanitized) + `model_identifier` / fingerprint when present
- `selected_news_ids` / `selected_headlines` (bounded)
- `prompt_input_diagnostic_snapshot` (bounded)
- `issue_codes`, `first_failed_stage` (deepest proven stage wins)
- `scaffold_status` (`eligible` / `applied` / `rejection_reason`)
- `visible_text_quality_samples` (bounded)
- `smtp_attempted`, `customer_send=0`, `customer_delivery_status`

Never persisted: raw prompt, unrestricted model body, secrets, SMTP credentials,
recipient lists, full article bodies.

Recovery identity (`execution_class=recovery`, `incident_id`) continues to be
stamped by `natural_run_recovery` via `update_run_artifact` after the run.

## Recovery #1 regression

Fixture:
`ops/feeds/incident_fixtures/20260807_131133_keysuri_global_recovery1_ellipsis.json`

Harness:
`tests/test_failed_recovery_evidence_persistence.py`

## Final deterministic full suite (this closeout)

Command (identical both runs):

```bash
python3 -u -m unittest discover -s tests -p 'test_*.py' -q
```

| Run | HEAD (pre-commit working tree) | Collected | Result |
|---|---|---|---|
| #1 | `39ff1df` + evidence patch | **2661** | OK (`/tmp/evidence_full_suite_1.txt`) |
| #2 | same | **2661** | OK (`/tmp/evidence_full_suite_2.txt`) |

Counts identical. 0 failed. 0 skipped. 0 xfail.
