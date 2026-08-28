# Market semantic invariant remediation — 2026-08-28

Status: implemented. Contract lives in `market_observation.py`; regressions in
`tests/test_market_semantic_invariants_20260828.py`.

## 1. What actually happened

The 06:30 KST natural run for 2026-08-28 blocked on `market_indices_narrative_thin`
(run `20260828_063053_today_genie_f7496c1b`). The owner approved a recovery run at
08:24 KST (`20260828_082449_today_genie_0ea5c971`), which passed validation and was
delivered.

That recovery run probed Naver's **live quote page** roughly 35 minutes before the
KRX opening auction. Production feed cache
(`runtime_feed_cache/today_genie/korea_japan_indices/latest.json`, fetched
`2026-08-27T23:24:03Z`) recorded:

| instrument | close | change_pts | change_pct | previous_close | as_of |
|---|---|---|---|---|---|
| KOSPI | 6912.37 | 0.0 | 0.0 | 6912.37 | 2026-08-28 |
| KOSDAQ | 837.65 | 0.0 | 0.0 | 837.65 | 2026-08-28 |
| NIKKEI | 66131.98 | 0.0 | 0.0 | — | 2026-08-27 |

Pre-open, the quote page shows the previous session's close still standing with a
**zero change**, because the new session has not traded. The closes were right; the
changes described a session that had not happened.

Actual settled 2026-08-27 tape: KOSPI 6912.37 / +104.16 / **+1.53%**,
KOSDAQ 837.65 / +10.78 / **+1.30%**.

Reader-visible result: `코스피 6912.37 0%`, `코스닥 837.65 0%`, `니케이 66131.98 0%`,
and the sentence `코스피와 코스닥이 전일 대비 변동 없이 …`.

**The delivery reached 12 customer recipients** (`customer_delivery_status:
ACCEPTED_ALL`, `customer_sent_at 2026-08-28T08:26:45+09:00`), not owner review only.

## 2. First corruption stage

`NORMALIZATION`. Not generation, not repair, not rendering — every later stage
carried the source faithfully.

```
SOURCE (correct)  →  NORMALIZATION (✗ binds a pre-open quote as a settled close)
→ FIELD BINDING → PROMPT → MODEL → PARSE → PRODUCER → EMAIL   (all faithful)
```

The pipeline had no notion of **which session** an observation described, so a
not-yet-started session was indistinguishable from a settled one.

Why nothing caught it: the corrupted row was *internally coherent*.
`previous_close == close`, `change_pts == 0`, `change_pct == 0`,
`change_direction == 0` all agree. `_market_index_recomputed_rate` reproduced 0.00,
the sign checks passed, and `abs(pct) < MARKET_INDEX_LARGE_MOVE_PP` skipped the
uncorroborated-large-move gate. Cross-field consistency alone can never catch this.

This was not a one-off. At 11:03 KST the same code path would have published
KOSPI **6838.57 / -1.07%** — today's live intraday tape — under the header
`전일 국내 마감`. The Nikkei row has the same defect: at 11:20 KST CNBC reported
`.N225` with `curmktstatus: REG_MKT` and `last_time: 2026-08-28`.

## 3. Root causes, proved or disproved

| # | Hypothesis | Verdict |
|---|---|---|
| A | `MISSING_IS_TREATED_AS_ZERO` | **Confirmed, contributing.** `_parse_float("")` returned `0.0`. Not the trigger here (the source really did publish 0.00) but the same class. Fixed. |
| B | `FALLBACK_CREATES_FACTS` | **Not the trigger.** `today_genie_feed_fallback_used: false`; the run used a live refresh. Fallback paths audited and unchanged. |
| C | `CROSS_FIELD_SEMANTIC_INCONSISTENCY` | **Disproved as the cause.** The row was fully self-consistent. This is why an observation *identity* invariant was required, not more cross-field arithmetic. |
| D | `SOURCE_IDENTITY_CAN_DRIFT` | **Confirmed, latent.** Feed-level `as_of` is `max()` across instruments, and `_feed_index_row` read that aggregate, letting one index publish another's session date. Fixed. |
| E | `REPAIR_CAN_HIDE_FAILURE` | **Not applicable to Today.** Already addressed for Global by `global_contract_scaffold_fabricated_top5` (commit `4c59e4c`). |
| F | `SHARED_HELPERS_CHANGE_PRODUCT_SEMANTICS` | **No violation found.** Today's market path (`main`/`validators`/`renderers`) and the keysuri Global/Korea scoring modules are disjoint. Now pinned by `ProgramBoundaryTests`. |

The 2026-08-24 → 08-27 Global incidents (cross-item contamination, English
template leakage, robot→ESS misclassification, dead owner-review memory) were
already remediated in `4c59e4c`, `e7d579e`, `f2f5874` and are covered by
`tests/test_keysuri_global_systemic_remediation_20260827.py`. This work adds
cross-program boundary regressions only.

## 4. The contract

`market_observation.py`. Every index row reduces to one observation identity —
`instrument, market_date, close, previous_close, point_change, pct_change,
session_state` — with a status. Only `settled` may reach a reader.

- **Observation identity.** A row's session date is its own; the feed-level date is
  a fallback that is recorded as such.
- **Settlement.** A `전일 마감` / `밤사이 마감` row must carry a session that closed
  *before* the target date, and a source that reports the session as still trading
  (`curmktstatus: REG_MKT`, `PRE_MKT`) is never settled.
- **Unknown stays unknown.** A missing rate is `None`, never `0`.
- **Zero needs evidence.** `pct_change == 0` publishes only when the source
  supplied an independent previous close equal to the close, or explicit
  `settlement_evidence`. A quote snapshot reading 0.00 is exactly what an
  untraded market looks like.
- **Coherence and repair.** With a sourced `previous_close`, the point and rate are
  derived from it; a disagreeing supplied rate is repaired, and a
  direction contradiction or an absurd move is refused.
- **Refusal is visible.** Refused rows keep identity and provenance, lose their
  numbers, and are reported in `today_genie_market_observation_report`.

### Source change

Domestic rows now come from Naver's settled daily table
(`sise_index_day.nhn`), selected **by explicit date**, not from the live quote page.
The quote page answers "what is this index doing now"; a pre-open briefing asks
"how did the last completed session end". This also makes the domestic rows
independent of what time of day the probe runs — the exact failure mode of the
08:24 recovery run.

`parse_naver_index_html` is retained as the live-tape parser and keeps its
direction-adjudication regressions.

### Post-generation

`_today_market_fact_consistency_issues` blocks prose that restates a canonical
number as a different fact (`market_fact_narrative_conflict`) — a flat claim
against a real move, or a direction the number rules out.

### History repair

`market_observation_store.py` persists settled observations per instrument. A late
or recovery run restores a previously *established* fact rather than publishing a
live tape or failing outright. Refused when the stored session is not older than the
target date, or older than 5 days.

## 5. Zero-default audit (repository-wide)

`SAFE_ZERO` — counters, sizes, indexes, token tallies, attempt counts. All
`or 0` / `.get(..., 0)` sites in `admin_store.py`, `natural_run_*.py`,
`keysuri_*_signal_scoring.py`, `orchestrator.py`, `internal_jobs.py`,
`service_full_run_contract.py`, `admin_view_models.py`. No change.

`DANGEROUS_FACTUAL_ZERO` — fixed:
- `ops/probe_today_genie_feeds.py::_parse_float` — `""` → `0.0`, now `None`.
- `main.py::_fmt_signed_pct` and `renderers.py::_fmt_snapshot_change_pct` —
  rendered `0` as `0%`, indistinguishable from a placeholder; now `0.00%`, and only
  an evidenced zero can reach them.
- `validators.py::market_index_validation_report` — accepted a zero rate with no
  corroboration; now refuses any non-`settled` observation.

`NOT_RELEVANT` — `validators.py::_MARKET_INDEX_DIRECTION_SIGNS` (a token→sign
lookup, not a default), keysuri category tie-break ranks, image dimensions.

## 6. Residual gap (owner decision)

Nikkei has **no settled daily-history source** among the providers in use. CNBC's
quote endpoint is the only path, so between the Tokyo pre-open and the following
session's close a Today run cannot obtain a settled Nikkei observation and will
block (fail closed) unless the settled-observation store already holds one from
that morning's scheduled run.

The 06:30 KST scheduled slot is inside the window where all six rows are settled,
so scheduled runs are unaffected. Adding a settled daily-history source for Nikkei
would close this; introducing a new market-data provider is an owner decision.
