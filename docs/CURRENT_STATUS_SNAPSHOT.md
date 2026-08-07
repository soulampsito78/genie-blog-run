# Current Operational Status Snapshot

**As of: 2026-06-23 (KST) — full GCP audit**
**Cloud Run / commit / health + Kee-Suri recovery: re-verified 2026-06-26 (KST)**
**Kee-Suri Global 재발방지: 재검증 2026-07-31 (KST) — §1, §9**
**Sandbox harness giant step: local-only 2026-08-06 (KST) — §9 / closeout pointer**
**Sandbox repository closeout: local-only 2026-08-07 (KST) — §9 / closeout pointer**
**Today natural-slot incident: 2026-08-07 (KST) — see incident closeout pointer below**
**Korean failure report + human recovery: 2026-08-07 (KST) — production activated**
**Basis: GCP audit — Cloud Scheduler, Cloud Run, GCS artifact inspection**
**Service: `genie-blog-run`, region `asia-northeast3`**

This document is the authoritative operational snapshot. Update it after each audit.

> **Korean natural-run failure report + human-approved recovery (PRODUCTION 2026-08-07):**
> Deployed revision `genie-blog-run-00278-7lj` @ `b6a9fc1`. Scheduler job
> `Natural_Run_Watchdog` (`*/15 * * * *` Asia/Seoul) →
> `POST /internal/jobs/natural-run-watchdog`. Activation watermark prevents
> pre-activation backfill. Admin `/admin/incidents` for exactly-once recovery.
> Synthetic verification mail sent once (`[GENIE WATCHDOG TEST]`); Gmail receipt
> not independently confirmed in agent environment.
> Runbook: [docs/ops/OWNER_REVIEW_FAILURE_ALERTING.md](ops/OWNER_REVIEW_FAILURE_ALERTING.md).

> **Today_Geenee post-migration first natural-run incident (2026-08-07):**
> Scheduler fired at 06:30 KST; Cloud Run returned HTTP 200 in ~4.8s without a
> new natural artifact because same-KST-date QA
> `20260807_003207_today_genie_255d3454` falsely satisfied the legacy dedupe.
> Correction: execution-class + natural-slot identity gate; Scheduler body must
> include `execution_class=natural_scheduled` and `scheduled_slot=06:30`.
> Early QA mail is not natural-run success. Full record:
> [docs/TODAY_GENIE_POST_MIGRATION_FIRST_NATURAL_RUN_INCIDENT_2026_08_07.md](TODAY_GENIE_POST_MIGRATION_FIRST_NATURAL_RUN_INCIDENT_2026_08_07.md).

> Scope of the 2026-06-26 re-verification: Cloud Run revision / commit / traffic /
> health and the Kee-Suri owner-review exposure log runtime (Sections 1, 7, 8 and
> the recovery closeout pointer below) were re-verified read-only on 2026-06-26.
> The Scheduler (§2), Program Run (§3), PASS Criteria (§4), Key Config (§5), and
> Secrets (§6) tables retain their **2026-06-23 audit basis** and were not
> re-audited on 2026-06-26.

> **Sandbox repository closeout (2026-08-07, LOCAL ONLY):**
> `GENIE_KEESURI_SANDBOX_REPOSITORY_CLOSEOUT_COMPLETE` — independent harness
> verification, self-review defect repair (falsifiable assertions), consistency
> audit, full local regression. **No push / no deploy / no live operational QA.**
> Production-proof batch (Gmail receipt required for operational PASS) remains
> pending. Do not start another sandbox coding phase.
> [docs/keysuri/KEYSURI_SANDBOX_REPOSITORY_CLOSEOUT_2026_08_07.md](keysuri/KEYSURI_SANDBOX_REPOSITORY_CLOSEOUT_2026_08_07.md).

> **Sandbox harness giant step (2026-08-06, LOCAL ONLY):**
> `GENIE_KEESURI_SANDBOX_HARNESS_GIANT_STEP_COMPLETE` — baseline-failure
> classification/remediation, Admin reissue + Today/Global/Korea natural-run
> harnesses, failure-event/metrics harness + local inspect script. Full suite
> **2570 passed** locally. **No push / no deploy / no live operational QA.**
> Gmail/SMTP/Scheduler proof is a separate future batch.
> [docs/keysuri/KEYSURI_SANDBOX_HARNESS_GIANT_STEP_CLOSEOUT_2026_08_06.md](keysuri/KEYSURI_SANDBOX_HARNESS_GIANT_STEP_CLOSEOUT_2026_08_06.md).

> **Kee-Suri Global 재발방지 클로즈아웃 (2026-07-31):**
> `KEESURI_GLOBAL_RECURRENCE_PREVENTION_COMPLETE` — 2026-07-30 Global 장애 2건
> (visible-text truncation 오탐, `program_id == ""` schema block)이 닫혔고
> 재발방지 컨트롤 A~D가 배포되었다. 전체 기록:
> [docs/keysuri/KEYSURI_GLOBAL_RECURRENCE_PREVENTION_CLOSEOUT_2026_07_31.md](keysuri/KEYSURI_GLOBAL_RECURRENCE_PREVENTION_CLOSEOUT_2026_07_31.md).
> 식별된 재발 경로는 통제되었으나 이후 자연실행은 통상 운영 모니터링 대상으로 남는다.

> **Kee-Suri recovery closeout (2026-06-26):**
> `CLOSED_FOR_VERIFIED_SCOPES` — verified scopes closed; remaining conditions held
> as labels (not "전체 완료"). Full record:
> [docs/keysuri/KEYSURI_RECOVERY_CLOSEOUT_2026_06_26.md](keysuri/KEYSURI_RECOVERY_CLOSEOUT_2026_06_26.md).

---

## 1. Cloud Run Service

| Item | Value |
|------|-------|
| Service name | `genie-blog-run` |
| Region | `asia-northeast3` |
| Active revision | `genie-blog-run-00275-nhv` (100% traffic, `latestRevision: true`) — 2026-08-07 natural-slot fix |
| Commit SHA | `c32486a` (`c32486a3ee693023f06e76c3001a2c849b57fa97`) — revision `commit-sha` label match |
| Commit message | `docs(today): close 2026-08-07 first natural-run incident record` (stack includes gate fix + harness) |
| Cloud Build | `ed444e9b-b2a4-4a5e-947d-edc5eac49c0d` (SUCCESS) |
| Image digest | `sha256:9b97c6296ab054522cc77752f125738a576e51b07122d36eb8f7a370979e11ac` (build = deployed) |
| Ready condition | `True` — re-verified 2026-08-07 |
| Health | `/health` → HTTP 200 ✅ (re-verified 2026-08-07; HTTP 200 alone is **not** deployment success — see §9) |
| Prior revision (2026-06-26) | `genie-blog-run-00201-447`, commit `0ef8fb9` |
| Public URL | `https://genie-blog-run-2sftivmzga-du.a.run.app` |
| Scheduler URL | `https://genie-blog-run-1055014091206.asia-northeast3.run.app` |
| Architecture | **Single Cloud Run Service** (not API+Worker split) |
| Deploy trigger | Cloud Build auto-deploys on `origin/main` push — **push is a deploy trigger** |
| Prior revision (2026-06-23 audit) | `genie-blog-run-00176-x7r`, commit `f08ad53` |

---

## 2. Scheduler State

| GCP Job | Program | Schedule (KST) | State | Last run result |
|---------|---------|---------------|-------|-----------------|
| `Today_Geenee` | `today_genie` | 06:30 Mon–Fri | **ENABLED** | Body requires `execution_class`+`scheduled_slot`; lastAttempt 2026-08-07 06:30 → 200 (incident silent skip; fixed in `c32486a`) |
| `KeeSuri_Global_Tech` | `keysuri_global_tech` | 12:30 Mon–Fri | **ENABLED** | 2026-06-23 12:30 → 200 OK |
| `KeeSuri_Korea_Tech` | `keysuri_korea_tech` | 18:30 Mon–Fri | **ENABLED** | 2026-06-22 18:30 → 200 OK |
| `Tomorrow_Geenee` | `tomorrow_genie` | 18:00 daily | **PAUSED** | No successful run on record |
| `approval_timeout_processor` | internal | Every 10 min | **ENABLED** | 2026-06-23 06:00 → 200 OK |
| `Natural_Run_Watchdog` | SLA report-only | Every 15 min | **ENABLED** | First poll 2026-08-07 10:15 KST → 200; watermark active; no content retry |

---

## 3. Program Full Run Status

| Program | Last successful run | Artifact status | Customer delivery |
|---------|---------------------|-----------------|-------------------|
| `today_genie` | `20260623_063058_today_genie_46793a9b` | emailed | **smtp_accepted** |
| `keysuri_global_tech` | `20260623_123002_keysuri_global_tech_79f98bf4` | emailed | **smtp_accepted** |
| `keysuri_korea_tech` | `20260622_183002_keysuri_korea_tech_6960a026` | emailed | **smtp_accepted** |
| `tomorrow_genie` | none | — | — |

---

## 4. Full Run PASS Criteria

| Criterion | today_genie | keysuri_global_tech | keysuri_korea_tech | tomorrow_genie |
|-----------|:-----------:|:-------------------:|:-----------------:|:--------------:|
| Gemini call | ✅ | ✅ | ✅ | ❌ PAUSED |
| Image generation | ✅ generated | ✅ generated | ✅ generated | — |
| GCS artifact | ✅ | ✅ | ✅ | — |
| Email HTML | ✅ | ✅ | ✅ | — |
| Owner review | ✅ | ✅ | ✅ | — |
| Admin accessible | ✅ | ✅ | ✅ | — |
| SMTP accepted | ✅ | ✅ | ✅ | — |
| Customer sent | ✅ | ✅ | ✅ | — |
| **Overall** | **PASS** | **PASS** | **PASS** | **FAIL** |

---

## 5. Key Configuration

| Env var / config | Value (summary) |
|-----------------|-----------------|
| `GENIE_CUSTOMER_EMAIL_TO` | 5 baseline recipients |
| `GENIE_ARTIFACT_BUCKET` | `gen-lang-client-0667098249-genie-artifacts` |
| `GENIE_ARTIFACT_STORE_BACKEND` | `gcs` |
| `GENIE_OPS_TOMORROW_SCHEDULER_STATE` | `PAUSED` |
| `TODAY_GENIE_*_JSON` env market data | `as_of: 2026-06-08` — **stale** (P1 tech debt) |
| Beta admin recipient config | `admin_config/customer_recipients.json` in GCS — 1 admin-managed recipient (`supergp@hanmail.net`) |

---

## 6. Secrets (version status)

| Secret | Latest version | Created |
|--------|---------------|---------|
| `genie-admin-password` | v1 | 2026-05-30 |
| `genie-internal-job-token` | v1 | 2026-05-30 |
| `genie-smtp-password` | v4 | 2026-03-31 |

---

## 7. Known Issues / Tech Debt

| Priority | Issue |
|----------|-------|
| P1 | `TODAY_GENIE_*_JSON` env market data `as_of=2026-06-08` — stale |
| P1 | `approval_timeout_processor` scheduler ENABLED but send is retired in code |
| P1 | `Tomorrow_Geenee` scheduler has no `X-Genie-Internal-Job-Token` (unlike other jobs) |
| P1 | `tomorrow_genie` resume/retire decision pending |
| P2 | Korean public holiday skip gate not implemented for Key-Suri |
| P2 | `owner_review_url` not persisted in Today run metadata |
| P2 | Pending `pending_review` artifacts in GCS from 6/16–6/19 (not reviewed/expired) |
| P2 | Two Cloud Run URL aliases in use (status.url vs legacy scheduler URL) |

### Kee-Suri recovery — remaining items (2026-06-26, labels only)

| Item | Status |
|------|--------|
| Admin notice auth smoke (needs auth/cookie/session; do not call `POST /admin/notices/send` without authorization) | `KNOWN_ISSUE_REMAINS` |
| cross-day entity/editorial_cluster matching (exposure log is a minimal foundation feeding the existing dedup gate only) | `OUT_OF_SCOPE_DEFERRED` |
| `sent_news_log_store.py` read fail-open improvement (existing store untouched this patch) | `OUT_OF_SCOPE_DEFERRED` |
| internal job token rotation (recorded as status only; no Secret query/change) | `SECURITY_DECISION_REQUIRED` |

---

## 8. Recent Commits (production)

| Commit | Message |
|--------|---------|
| `0ef8fb9` | fix(keysuri): track owner review exposures for cross-day dedup → rev `genie-blog-run-00201-447` (DEPLOYED_SMOKE_PASS) |
| `8bb93a9` | fix(keysuri): preserve replacement pool for diversity selection → rev `genie-blog-run-00200-jbg` (DEPLOYED_SMOKE_PASS) |
| `68cc152` | fix(keysuri): generalize diversity entity and cluster detection (DEPLOYED_SMOKE_PASS) |
| `3fe4bc2` | fix(keysuri): apply diversity caps before top five selection (DEPLOYED_SMOKE_PASS) |
| `2375d5f` | fix(keysuri): prefix owner reissue subjects for text regenerations (DEPLOYED_SMOKE_PASS) |
| `e821095` | fix(keysuri): rebuild image-only reissue emails to avoid Gmail trimming (OPERATOR_QA_PASS) |
| `f08ad53` | admin: link beta customer recipient manager |
| `4237c5a` | admin: manage beta customer recipients |
| `37c8b46` | admin: show customer email delivery status |
| `980f400` | keysuri: clean korea preview numbering punctuation |
| `9657498` | today: block scheduled weekend owner reviews |

Recovery scope detail and runtime verification:
[docs/keysuri/KEYSURI_RECOVERY_CLOSEOUT_2026_06_26.md](keysuri/KEYSURI_RECOVERY_CLOSEOUT_2026_06_26.md).

---

## 9. Kee-Suri Global 재발방지 컨트롤 (2026-07-31)

**운영 판정: `KEESURI_GLOBAL_RECURRENCE_PREVENTION_COMPLETE`**
정본 기록: [KEYSURI_GLOBAL_RECURRENCE_PREVENTION_CLOSEOUT_2026_07_31.md](keysuri/KEYSURI_GLOBAL_RECURRENCE_PREVENTION_CLOSEOUT_2026_07_31.md)

### 불변 조건 (production invariants)

| 조건 | 값 |
|------|-----|
| Global 최대 모델 호출 | **2회** (`GLOBAL_GENERATION_CALL_BUDGET = 2`) — initial + 최대 1회 corrective |
| 재시도 자격 | `_GLOBAL_CONTRACT_REPAIR_CODES` 명시 코드에 한정. 통상 validation 실패는 자동 재시도 대상 아님 |
| missing / empty `program_id` | 신뢰된 run context 로 결정적 보정 |
| conflicting non-empty `program_id` | **hard block — 보정 안 함, 재시도 자격 없음** |
| sanitized snapshot 상한 | 2000자, truncation 여부 기록. hidden prompt·secret 미저장 |
| recovery 소진 | image / email side effect **이전에** safe-fail, 진단 보존 |
| recovery 성공 | image 및 owner-review email 정확히 **1회** |
| cross-mode | Today / Korea / Tomorrow 로 유출 금지. contamination 은 hard block |

### 실패 우선순위 (Control C)

`no_extractable_json` → `contentless_or_missing_structure` →
`conflicting_mode_or_identifier` → `missing_identifier_after_repair` →
`section_schema_defect` → ordinary-content fall-through →
`post_render_visible_text_defect`

후행 defect 가 선행 구조적 실패를 가리지 않는다. secondary issue code 는 보존된다.

### 재발 카운터 (Control D)

`keysuri_recurrence_metrics.py` — `recurrence_counters_for_run()`,
`aggregate_recurrence_counters()`, `log_recurrence_counters()`.
카운터: `generation_attempts`, `bounded_retry_count`, `retry_success`,
`retry_exhausted`, `json_extraction_failure`, `contentless_response_failure`,
`program_id_repair_count`, `conflicting_program_id_block_count`,
`schema_validation_failure`, `post_render_truncation_block`,
`global_run_success`, `global_run_safe_fail`.
이미 저장된 진단에서 파생되는 read-only 집계이며 side effect 가 없다.

### 프로덕션 성공 판정 기준 (불변 조건)

owner-review 성공은 **endpoint HTTP 200 / `email_sent=true` / SMTP accepted
단독으로 판정하지 않는다.** Gmail 실제 수신까지 확인되어야 한다
(참조 실행 `20260731_022412_keysuri_global_tech_36012cbb`,
`KEESURI_GLOBAL_PRODUCTION_OWNER_REVIEW_PASS`).

### 테스트 기준선

**Sandbox repository closeout (2026-08-07, local only):** full suite re-proven
green after harness self-review repairs; 0 failed, 0 new xfail. Closeout:
[KEYSURI_SANDBOX_REPOSITORY_CLOSEOUT_2026_08_07.md](keysuri/KEYSURI_SANDBOX_REPOSITORY_CLOSEOUT_2026_08_07.md).

**Sandbox giant step (2026-08-06, local only):** full suite **2570 passed**,
0 failed, 0 new xfail. Baseline classification:
[KEYSURI_SANDBOX_BASELINE_FAILURE_CLASSIFICATION_2026_08_06.md](keysuri/KEYSURI_SANDBOX_BASELINE_FAILURE_CLASSIFICATION_2026_08_06.md).
Closeout:
[KEYSURI_SANDBOX_HARNESS_GIANT_STEP_CLOSEOUT_2026_08_06.md](keysuri/KEYSURI_SANDBOX_HARNESS_GIANT_STEP_CLOSEOUT_2026_08_06.md).
Local inspect: `scripts/inspect_owner_review_ops_local.py`.

**Prior closeout baseline (2026-07-31, historical):** recovery+recurrence
harness `88 passed` · targeted `136 passed` · full suite
`2436 passed, 21 failed, 1 skipped, 1 xfailed`. Those 21 failures are now
classified as already-fixed / environment-dependent at HEAD `7d19869`+sandbox
commits; they are not an active failure list.

### 향후 자연실행 관찰 사항

식별된 재발 경로는 통제되었다. 이후 자연실행은 통상적인 운영 모니터링 대상으로
남으며, 위 카운터 추세를 관찰한다. **Gmail/SMTP/Scheduler 실증명 배치는
별도 배치**이며 본 sandbox 작업에 포함되지 않는다.

---

*Next audit recommended: after any Scheduler change, new program launch, or monthly at minimum.*