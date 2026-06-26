# Current Operational Status Snapshot

**As of: 2026-06-23 (KST) — full GCP audit**
**Cloud Run / commit / health + Kee-Suri recovery: re-verified 2026-06-26 (KST)**
**Basis: GCP audit — Cloud Scheduler, Cloud Run, GCS artifact inspection**
**Service: `genie-blog-run`, region `asia-northeast3`**

This document is the authoritative operational snapshot. Update it after each audit.

> Scope of the 2026-06-26 re-verification: Cloud Run revision / commit / traffic /
> health and the Kee-Suri owner-review exposure log runtime (Sections 1, 7, 8 and
> the recovery closeout pointer below) were re-verified read-only on 2026-06-26.
> The Scheduler (§2), Program Run (§3), PASS Criteria (§4), Key Config (§5), and
> Secrets (§6) tables retain their **2026-06-23 audit basis** and were not
> re-audited on 2026-06-26.

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
| Active revision | `genie-blog-run-00201-447` (100% traffic) — re-verified 2026-06-26 |
| Commit SHA | `0ef8fb9` (`0ef8fb9cf873b1057cdc87f4eedb42298dc0f4ae`) — revision `commit-sha` label match |
| Commit message | `fix(keysuri): track owner review exposures for cross-day dedup` |
| Health | `/health` → HTTP 200 ✅ (re-verified 2026-06-26) |
| Public URL | `https://genie-blog-run-2sftivmzga-du.a.run.app` |
| Scheduler URL | `https://genie-blog-run-1055014091206.asia-northeast3.run.app` |
| Architecture | **Single Cloud Run Service** (not API+Worker split) |
| Deploy trigger | Cloud Build auto-deploys on `origin/main` push — **push is a deploy trigger** |
| Prior revision (2026-06-23 audit) | `genie-blog-run-00176-x7r`, commit `f08ad53` |

---

## 2. Scheduler State

| GCP Job | Program | Schedule (KST) | State | Last run result |
|---------|---------|---------------|-------|-----------------|
| `Today_Geenee` | `today_genie` | 06:30 Mon–Fri | **ENABLED** | 2026-06-22 06:30 → 200 OK |
| `KeeSuri_Global_Tech` | `keysuri_global_tech` | 12:30 Mon–Fri | **ENABLED** | 2026-06-23 12:30 → 200 OK |
| `KeeSuri_Korea_Tech` | `keysuri_korea_tech` | 18:30 Mon–Fri | **ENABLED** | 2026-06-22 18:30 → 200 OK |
| `Tomorrow_Geenee` | `tomorrow_genie` | 18:00 daily | **PAUSED** | No successful run on record |
| `approval_timeout_processor` | internal | Every 10 min | **ENABLED** | 2026-06-23 06:00 → 200 OK |

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

*Next audit recommended: after any Scheduler change, new program launch, or monthly at minimum.*
