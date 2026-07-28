# Owner-review failure alerting (design only — not applied)

Status: **designed / not applied**. This document describes the structured
log event and the Cloud Monitoring log-based alert that operators may create
later. No notification channel or alert policy is created by this change.

## Scope

| Item | Value |
|---|---|
| Service | Cloud Run KeeSuri owner-review service (`genie-blog-run`) |
| Programs | `keysuri_global_tech`, `keysuri_korea_tech` |
| Trigger | Any trigger accepted by `genie_schedule_policy.is_scheduled_trigger_source` |
| Excluded | `manual_*`, admin reissue, `dry_run=True`, unit/integration tests |
| Emit timing | Final safe-fail of a scheduled service full run only |
| Dedup | At most one ERROR event per `(program_id, run_id)` — **in-process only** |

Runtime emitter: `owner_review_failure_events.py`
Hook: `keysuri_service_full_run.run_keysuri_service_full_run` failure finalizers
plus the terminal-path and exception-boundary emitters in the same function.

## Trigger eligibility

The gate does **not** keep its own allow-list. It delegates to the repo's
canonical policy, `genie_schedule_policy.is_scheduled_trigger_source`, so this
document and the code cannot drift apart. As of this commit that accepts:

| Accepted (event emitted) | Rejected (no event) |
|---|---|
| `scheduled_owner_review` (the `internal_jobs` default) | `manual_service_full_run` |
| `scheduled_service_full_run` | `manual`, `manual_*` |
| any `scheduled_*` prefix | `admin_image_only_reissue`, `admin_text_only_reissue` |
| `cloud_scheduler` | `dry_run`, `test`, `local`, `preview` |
| `scheduler` | unknown / empty / `None` |
| `internal_job` | any run with `dry_run=True` |

`tests/test_owner_review_failure_events.py::ScheduledTriggerPolicyTests::test_gate_matches_central_policy_exactly`
asserts the gate equals the central policy for every sampled value.

## Structured log schema

`severity` is carried **inside the JSON payload**. The emitter writes one bare
JSON object per line through a dedicated logger
(`genie.owner_review_failure_event`) whose formatter is exactly `%(message)s`
and which does **not** propagate into the prefixed application formatter
configured by `main.configure_application_logging`.

```json
{
  "event": "owner_review_run_failed",
  "severity": "ERROR",
  "program_id": "keysuri_global_tech",
  "run_id": "...",
  "trigger_source": "scheduled_owner_review",
  "first_failed_stage": "email_delivery",
  "error_code": "smtp_send_failed",
  "issue_codes": ["gemini_json_missing_required_keys"],
  "revision": "...",
  "email_sent": false,
  "artifact_saved": true,
  "artifact_url": "..."
}
```

`artifact_saved: false` means the run artifact could not be persisted. The
`first_failed_stage` still reports the **primary** failure; the storage fault is
a secondary signal and `artifact_url` is blanked so no stale link is published.

Forbidden fields (never emit):

- Secret values / env dumps
- SMTP credentials
- Recipient email addresses
- Raw Gemini prompt or response bodies
- Exception tracebacks or exception messages

## `first_failed_stage` values

| Stage | Representative `error_code` |
|---|---|
| `generation_validation` | `validation_blocked`, `gemini_or_smoke_failed`, `generated_briefing_reload_failed`, `keysuri_korean_connector_ellipsis_blocked` |
| `validation_hold` | `validation_blocked` with a non-empty `hold_reason` (source shortage). The service reports holds as `validation_result="block"`, so `hold_reason` — not `validation_result` — is the signal that separates a hold from a model-contract failure. |
| `image_generation` | `IMAGE_GENERATION_FAILED`, `keysuri_top_shot_watermark_failed` |
| `email_rendering` | `keysuri_global_post_render_qa_blocked`, `keysuri_korea_post_render_qa_blocked` |
| `email_delivery` | `smtp_send_failed`, `owner_review_send_gate_off` |
| `artifact_persistence` | `artifact_persistence_failed` |
| `service_exception` | `service_unexpected_exception` |

## Cloud Logging filter (proposed)

Locally confirmed (see `StructuredEventLoggingTests`): the emitted line is a
single bare JSON object with no prefix, so Cloud Logging can parse it into
`jsonPayload`.

```text
resource.type="cloud_run_revision"
resource.labels.service_name="genie-blog-run"
jsonPayload.event="owner_review_run_failed"
jsonPayload.severity="ERROR"
```

Deliberately **not** included: `severity>=ERROR`. Native `severity` promotion is
a Cloud Logging-side behaviour that this repo cannot verify locally — production
log samples for this service show application lines with `severity` unset. Use
the `jsonPayload.severity` field above, and only add a native-severity clause
after confirming promotion on a staging revision (see Verification step 4).

### Fallback filter (emergency only)

Use only if step 3 of Verification shows the entry landed as `textPayload`:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="genie-blog-run"
textPayload:"\"event\": \"owner_review_run_failed\""
```

The substring includes the space after the colon because the emitter uses
`json.dumps` default separators. `test_documented_textpayload_fallback_substring_matches_output`
pins this string against the real serializer output.

## Alert condition (proposed — do not create yet)

- Metric: log-based metric counting `owner_review_run_failed`
- Condition: count > 0 for alignment period 5–15 minutes
- Auto-close / absence: optional
- Notification channel: existing on-call channel (not created here)

## Deduplication / suppression

Scope, stated precisely:

| Layer | Guaranteed? |
|---|---|
| In-process, same `(program_id, run_id)` | **Yes** — covers duplicate finalizers, terminal-path and exception-boundary emitters in one run |
| Cross-process / multiple Cloud Run instances | **No** |
| Cloud Scheduler retry (new `run_id`) | **No** — each retry is a separate run and emits its own event |

This is **not** global exactly-once delivery. Collapse repeats at the alert
policy (auto-close, notification rate limits), not in the runtime.

Intermediate recovery failures never emit this event — only a scheduled run's
final safe-fail does. A run that fails initially and then recovers emits zero
events.

## Covered final failures

| Final failure | Event emitted |
|---|---|
| Generation / parse / validation block | Yes (`generation_validation`) |
| Source shortage hold | Yes (`validation_hold`) |
| Image generation failure | Yes |
| Top-shot watermark failure | Yes |
| Post-render QA (email rendering) block | Yes |
| SMTP send failure / owner-review send gate off | Yes |
| Run artifact save failure | Yes (`artifact_saved: false`) |
| Unexpected service exception | Yes (`service_exception`, then the original exception is re-raised) |

Not covered (by design): failures raised before `run_keysuri_service_full_run`
is entered (for example internal-job auth rejection or program-id validation),
and any failure of a non-scheduled trigger.

## Verification (required before creating any alert policy)

1. Staging scheduled-like request, or a forced mock failure, on a deployed
   revision.
2. Find the Cloud Logging entry for that `run_id`.
3. Confirm the entry has `jsonPayload.event="owner_review_run_failed"` — not
   `textPayload`. If it is `textPayload`, stop and use the fallback filter.
4. Confirm whether `jsonPayload.severity` was promoted to the entry's native
   `severity`. Record the answer; only then may a `severity>=ERROR` clause be
   added.
5. Confirm `trigger_source` matches the live Scheduler job body and is accepted
   by `is_scheduled_trigger_source`.
6. Confirm `first_failed_stage` matches the actual failure.
7. Invoke the same run's finalizer twice → still exactly one entry.
8. Filter preview returns ≥ 1 match.
9. Only then create the log-based metric / alert policy.

## Rollback

- Remove or no-op `emit_owner_review_failure_from_artifact_meta` in the
  service failure finalizers, the terminal-path emitter, and the exception
  boundary of `run_keysuri_service_full_run`.
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
