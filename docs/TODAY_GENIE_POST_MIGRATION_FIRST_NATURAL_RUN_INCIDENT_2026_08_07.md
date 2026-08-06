# TODAY_GENIE Post-Migration First Natural-Run Incident Closeout

**Incident date:** 2026-08-07 (KST)  
**Final label:** set after deploy + verification (see bottom)  
**Evidence root (immutable, outside repo):**  
`/Volumes/DATA_MirAION/Young SeoK Park/git_Genie_Project/_incident_evidence_20260807_today_natural`

## Summary

The first post-migration 06:30 `Today_Geenee` natural execution did fire, reached
Cloud Run revision `genie-blog-run-00274-j2h` (`50da284`), and returned HTTP 200
in ~4.8s without creating a new artifact or sending a second owner-review mail.
An earlier same-KST-date QA/manual run (`20260807_003207_today_genie_255d3454`)
had already been emailed; the legacy same-calendar-day dedupe treated that QA
artifact as the natural slot completer and silently skipped.

The early QA owner-review mail does **not** constitute natural-run success.

## Timeline (KST / UTC)

| KST | UTC | Event | Source |
|-----|-----|-------|--------|
| 2026-08-07 00:28:48 | 2026-08-06 15:28:48Z | Cloud Run revision `00273-c42` ready (`054b127`) | Cloud Run revisions |
| 2026-08-07 00:31:07 | 2026-08-06 15:31:07Z | QA `POST /internal/jobs/create-owner-review` starts (~80s) | Cloud Run request log |
| 2026-08-07 00:32:28 | 2026-08-06 15:32:28Z | QA completes `run_id=20260807_003207_today_genie_255d3454` email_sent=True | App log + GCS meta |
| 2026-08-07 01:15:34 | 2026-08-06 16:15:34Z | Cloud Run revision `00274-j2h` ready (`50da284`) content-quality harness deploy | Cloud Run revisions |
| 2026-08-07 06:30:02 | 2026-08-06 21:30:02Z | Scheduler `Today_Geenee` AttemptStarted | Cloud Scheduler log |
| 2026-08-07 06:30:02 | 2026-08-06 21:30:02Z | Cloud Run `POST .../create-owner-review` → **200** latency **4.77s** on `00274-j2h` | Cloud Run request log |
| 2026-08-07 06:30:13 | 2026-08-06 21:30:13Z | Scheduler attempt finished status 200 | Cloud Scheduler log |
| 2026-08-07 06:32–06:33 | 2026-08-06 21:32–21:33Z | Owner opens/approves QA run; customer final send | Cloud Run request log + artifact |

**GCS inventory for 20260807 today_genie:** only `20260807_003207_today_genie_255d3454` (no 06:30 natural child).

## Scheduler evidence

- Fired: **yes**
- URI: `/internal/jobs/create-owner-review`
- Body at incident: `{}` (no execution_class / scheduled_slot)
- Revision: `genie-blog-run-00274-j2h`
- HTTP: 200 / ~4.77s
- Scheduler result: success (silent skip looked like OK)
- Classification: **CLOUD_RUN_REQUEST_CONFIRMED**

## Root cause

| Layer | Label | Role |
|-------|-------|------|
| Direct | `SAME_DATE_ARTIFACT_FALSE_MATCH` / `QA_CONSUMED_NATURAL_SLOT` | `find_scheduled_owner_review_for_kst_date` matched any same-KST-date emailed Today run |
| Detection | `SILENT_SUCCESS_RESPONSE_DEFECT` / `FAILURE_EVENT_MISSING` | Duplicate skip returned ordinary HTTP 200 with no failure event and no skip log line |
| Contributing | Early same-day QA via the same endpoint with default `trigger_source=scheduled_owner_review` | Causal for *this* day; gate defect is latent since `d4881b8` |
| Migration relation | Content-quality / sandbox migration lineage on `origin/main` through `50da284` | Did not introduce the gate; first natural day after migration exposed it when QA ran before 06:30 |

**Why tests missed it:** existing suites mocked `find_scheduled_owner_review_for_kst_date` away or never asserted QA vs natural coexistence through the live endpoint gate.

**Blast radius:** Today natural path only (Global/Korea use different endpoints). Any same-KST-date Today QA/manual emailed run could suppress 06:30.

## Correction invariants

1. Execution classes: `natural_scheduled`, `qa_manual`, `admin_reissue`, `preview`, `recovery`, `customer_delivery`
2. Natural identity: `program_id` + KST date + slot `06:30` + `execution_class=natural_scheduled`
3. Only a successful natural terminal (`email_sent=true`, class+slot match) satisfies the slot
4. QA/manual/reissue/preview/failed/safe-fail/no-send/legacy-without-class never satisfy
5. Legitimate duplicate returns diagnostics (`matched_run_id`, class, slot, status) without failure alert
6. Invalid match → HTTP 409 + exactly one structured failure event
7. Missing `execution_class` / `trigger_source` → fail closed (422), never guessed natural
8. Scheduler body must supply identity fields (updated with deploy)

## Harness

`tests/test_today_natural_slot_incident_harness.py` — scenarios 1–25 + adversarial mutations; production entry `/internal/jobs/create-owner-review`.

## Why early QA mail ≠ natural success

QA run was an early validation of migrated content, not the canonical 06:30 natural obligation. No second owner-review mail was sent as “recovery” for this incident.

## Next natural-run monitoring

Monitor Monday 06:30 KST `Today_Geenee` for:

- request admitted (not silent same-date skip)
- new `execution_class=natural_scheduled` / `scheduled_slot=06:30` artifact
- owner-review SMTP once
- no `invalid_natural_slot_duplicate_match` failure event on success
