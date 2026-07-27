# Owner-review failure alerting (design only — not applied)

Status: **designed / not applied**. This document describes the structured
log event and the Cloud Monitoring log-based alert that operators may create
later. No notification channel or alert policy is created by this change.

## Scope

| Item | Value |
|---|---|
| Service | Cloud Run KeeSuri owner-review service (`genie-blog-run`) |
| Programs | `keysuri_global_tech`, `keysuri_korea_tech` |
| Trigger | `scheduled_service_full_run` only |
| Excluded | `manual_*`, admin reissue, dry_run, unit/integration tests |
| Emit timing | Final safe-fail of a scheduled service full run only |
| Dedup | At most one ERROR event per `run_id` (in-process) |

Runtime emitter: `owner_review_failure_events.py`  
Hook: `keysuri_service_full_run.run_keysuri_service_full_run` failure finalizer

## Structured log schema

Severity: `ERROR`

```json
{
  "event": "owner_review_run_failed",
  "severity": "ERROR",
  "program_id": "keysuri_global_tech",
  "run_id": "...",
  "trigger_source": "scheduled_service_full_run",
  "first_failed_stage": "generation_validation",
  "error_code": "validation_blocked",
  "issue_codes": ["gemini_json_missing_required_keys"],
  "revision": "...",
  "email_sent": false,
  "artifact_url": "..."
}
```

Forbidden fields (never emit):

- Secret values / env dumps
- SMTP credentials
- Recipient email addresses
- Raw Gemini prompt or response bodies

## Cloud Logging filter (proposed)

```text
resource.type="cloud_run_revision"
jsonPayload.event="owner_review_run_failed"
jsonPayload.trigger_source="scheduled_service_full_run"
severity>=ERROR
```

If the logging agent stores the JSON line as `textPayload` instead of
`jsonPayload`, use:

```text
resource.type="cloud_run_revision"
textPayload:"\"event\": \"owner_review_run_failed\""
severity>=ERROR
```

Prefer confirming `jsonPayload` on a staging revision before attaching an
alert. The emitter writes a single-line JSON message specifically so Cloud
Logging can promote it into `jsonPayload`.

## Alert condition (proposed — do not create yet)

- Metric: log-based metric counting `owner_review_run_failed`
- Condition: count > 0 for alignment period 5–15 minutes
- Auto-close / absence: optional
- Notification channel: existing on-call channel (not created here)

## Deduplication / suppression

1. Runtime: in-process set keyed by `run_id` (covers duplicate finalizer calls).
2. Monitoring: optional alert policy auto-close and notification rate limits.
3. Intermediate recovery failures never emit this event — only the scheduled
   run's final safe-fail path does.

## Verification

1. Scheduled dry staging run forced to validation failure → exactly one ERROR.
2. Same run finalizer invoked twice → still one event.
3. Manual / dry_run failure → zero events.
4. Recovery that later succeeds → zero events.
5. Payload inspection: no secrets, no raw model text, no email addresses.

## Rollback

- Remove or no-op `emit_owner_review_failure_from_artifact_meta` in the
  service failure finalizer.
- Delete any later-created log-based metric / alert policy (none are applied
  by this commit).

## Cost impact

- One additional ERROR log line per failed scheduled run.
- Negligible Cloud Logging ingest cost at current schedule volume.
- No extra Gemini / image / SMTP calls.

## Explicit non-goals

- Creating notification channels
- Creating alert policies in Cloud Monitoring
- Paging on manual canary or dry-run failures
- Changing Scheduler jobs
