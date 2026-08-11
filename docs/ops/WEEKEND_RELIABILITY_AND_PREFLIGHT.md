# Weekend Reliability + Weekday Pre-Natural Preflight

## Operating model

**Weekend:** incident corpus → offline adversarial → live-model no-send burn-in → patch → repeat.

**Weekdays:** `preflight_canary` at 05:45 / 11:45 / 17:45 KST → current live feed,
eligibility, ranking, dedup/backfill, model, parser, repair, and validator → PASS silent →
natural run unchanged.
FAIL → Korean early warning only. Natural Scheduler stays enabled.

The preflight persists source, selection, contract, revision, and model fingerprints.
The natural run compares its independently refreshed input with those fingerprints and
records `PREFLIGHT_INPUT_DRIFT` when they differ. Drift is diagnostic and does not by
itself cancel the natural run.

## Endpoint

`POST /internal/jobs/natural-run-preflight`

Body:

```json
{
  "program_id": "today_genie|keysuri_global_tech|keysuri_korea_tech",
  "scheduled_service_date": "YYYY-MM-DD",
  "scheduled_slot": "06:30|12:30|18:30",
  "execution_class": "preflight_canary",
  "alert_on_fail": true
}
```

## Hard bans

- no paid image
- no owner-review SMTP from canary/preflight success path
- no customer send
- no natural-slot completion
- no auto-recovery
- no natural incident creation from preflight

## Frozen reliability packs

Frozen packs are used only by `reliability_canary` burn-in. They are not representative
of the next natural input and must not be used by weekday `preflight_canary`.

- `ops/feeds/reliability_packs/20260807_global_frozen_source_pack.json`
- `ops/feeds/reliability_packs/20260807_korea_frozen_source_pack.json`

## Corpus

`ops/feeds/incident_fixtures/CORPUS_INDEX.json`

## Evidence scope

A repeated frozen-pack burn-in proves `MODEL_PIPELINE_STABILITY` for a fixed input,
production model, and production prompt. It does not prove
`NATURAL_INPUT_DISTRIBUTION_RELIABILITY`. Weekday live-input preflight and natural-run
fingerprint comparison provide the separate distribution-coverage evidence.
