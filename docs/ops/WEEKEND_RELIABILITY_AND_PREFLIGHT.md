# Weekend Reliability + Weekday Pre-Natural Preflight

## Operating model

**Weekend:** incident corpus → offline adversarial → live-model no-send burn-in → patch → repeat.

**Weekdays:** `preflight_canary` at 05:45 / 11:45 / 17:45 KST → PASS silent → natural run unchanged.
FAIL → Korean early warning only. Natural Scheduler stays enabled.

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

## Frozen packs

- `ops/feeds/reliability_packs/20260807_global_frozen_source_pack.json`
- `ops/feeds/reliability_packs/20260807_korea_frozen_source_pack.json`

## Corpus

`ops/feeds/incident_fixtures/CORPUS_INDEX.json`
