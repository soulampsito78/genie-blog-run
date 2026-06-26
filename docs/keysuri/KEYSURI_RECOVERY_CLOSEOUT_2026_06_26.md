# Kee-Suri Recovery Closeout — 2026-06-26

**Status: `CLOSED_FOR_VERIFIED_SCOPES`** — verified scopes are closed; remaining
conditions are recorded as status labels, not as completion.

This document is the canonical record of the GENIE / Kee-Suri recovery work
landed on 2026-06-26. It is not a "전체 완료" (fully complete) declaration.
검증된 범위는 닫고, 남은 조건은 라벨로 남긴다 — verified scopes are closed, and
remaining conditions are left as labels.

Status labels used here (only these): `OPERATOR_QA_PASS`,
`DEPLOYED_SMOKE_PASS`, `KNOWN_ISSUE_REMAINS`, `OUT_OF_SCOPE_DEFERRED`,
`SECURITY_DECISION_REQUIRED`, `CLOSED_FOR_VERIFIED_SCOPES`.

---

## Production baseline (verified 2026-06-26)

| Item | Value |
|------|-------|
| repo / branch | `genie-blog-run` / `main` |
| latest commit | `0ef8fb9cf873b1057cdc87f4eedb42298dc0f4ae` (`0ef8fb9`) |
| commit message | `fix(keysuri): track owner review exposures for cross-day dedup` |
| service | `genie-blog-run` |
| region | `asia-northeast3` |
| latest revision | `genie-blog-run-00201-447` |
| revision `commit-sha` label | `0ef8fb9cf873b1057cdc87f4eedb42298dc0f4ae` (match) |
| traffic | 100% on latest revision |
| health | `/health` → HTTP 200 |
| artifact bucket | `gen-lang-client-0667098249-genie-artifacts` |
| artifact prefix | `admin_runs/` |

Verified read-only via `git`, `gcloud run services describe`, `curl /health`,
and `gcloud storage` listing/read. Note: this repo auto-deploys via Cloud Build
on `origin/main` push — **push is a production deploy trigger**.

---

## Recovery scope status table

| # | Scope | Commit | Revision | Status |
|---|-------|--------|----------|--------|
| 1 | image_only Gmail mobile trimming | `e821095` | — | `OPERATOR_QA_PASS` |
| 2 | reissue subject prefix | `2375d5f` | — | `DEPLOYED_SMOKE_PASS` |
| 3 | same-run TOP5 diversity gate | `3fe4bc2` | — | `DEPLOYED_SMOKE_PASS` |
| 4 | diversity generalization | `68cc152` | — | `DEPLOYED_SMOKE_PASS` |
| 5 | replacement pool preservation | `8bb93a9` | `genie-blog-run-00200-jbg` | `DEPLOYED_SMOKE_PASS` |
| 6 | owner-review exposure log foundation | `0ef8fb9` | `genie-blog-run-00201-447` | `DEPLOYED_SMOKE_PASS` |

---

### 1. image_only Gmail mobile trimming — `OPERATOR_QA_PASS`

- Commit: `e821095`
- Basis: owner Gmail mobile QA success.
- **Caution: do not touch the image_only reissue path again.**

### 2. reissue subject prefix — `DEPLOYED_SMOKE_PASS`

- Commit: `2375d5f`
- Policy:
  - `body_only`: `[본문 재발행]`
  - `body_and_image`: `[본문·이미지 재발행]`
  - `image_only`: no subject prefix change
  - customer subject: prefix stripped

### 3. same-run TOP5 diversity gate — `DEPLOYED_SMOKE_PASS`

- Commit: `3fe4bc2`
- Reflected:
  - same-source / entity / editorial_cluster diversity cap
  - `diversity_summary` / `diversity_rejected_items`
  - relax-to-fill retained
- **Caution: cross-day repetition prevention is NOT solved by this patch alone.**
  Same-run diversity and cross-day dedup are distinct layers.

### 4. diversity generalization — `DEPLOYED_SMOKE_PASS`

- Commit: `68cc152`
- Reflected:
  - removed NVIDIA-only overfitting
  - aliases: OpenAI/Open AI, Microsoft/MS, Google/Alphabet, AWS/Amazon, etc.
  - expanded entities: Anthropic, Perplexity, Databricks, Oracle, Salesforce,
    Adobe, Broadcom, AMD, Intel, etc.
  - expanded clusters: platform_policy, enterprise_saas, cloud_infrastructure, etc.
- **Caution: the category classifier was NOT modified.**

### 5. replacement pool preservation — `DEPLOYED_SMOKE_PASS`

- Commit: `8bb93a9` (`8bb93a92a875b214704c6a09dbf8a19452247df6`)
- Revision: `genie-blog-run-00200-jbg`
- Reflected:
  - preserve selected TOP5 + watchlist + safe rejected candidates
  - `downstream_candidate_source_ids`
  - `selection_pool` metadata
  - `pre_diversity_candidate_count` may be > 5
  - duplicate-reject followed by replacement promotion
  - `selected_count = 5` retained
  - sufficient replacement → `relaxed = false`
  - insufficient replacement → `diversity_relaxed = true`
  - `source_pack_funnel_summary` / `candidate_funnel_summary`

### 6. owner-review exposure log foundation — `DEPLOYED_SMOKE_PASS`

- Commit: `0ef8fb9` (`0ef8fb9cf873b1057cdc87f4eedb42298dc0f4ae`)
- Revision: `genie-blog-run-00201-447`
- Reflected:
  - new `owner_review_exposure_log_store.py`
  - new operational log `owner_review_exposure_log.json`
  - **completely separated from `sent_news_log.json`**
  - records only when an owner-review email is actually sent
    (`email_sent=True` / `artifact_status="emailed"`)
  - does NOT record: stored / no-send / smoke / local dry-run
  - does NOT record: image_only reissue
  - body_only / body_and_image reissue: records only when `selected_items`
    differ from parent
  - merges `recent_sent_news_log` + `recent_owner_review_exposure_log`
  - feeds combined recent log to the existing `run_sent_news_dedup_gate`
    (the dedup gate itself is unmodified)
  - fail-open read
  - write failure does not fail the run; it leaves only a meta warning
- Changed files:
  - `owner_review_exposure_log_store.py`
  - `tests/test_owner_review_exposure_log_store.py`
  - `keysuri_service_full_run.py`
  - `keysuri_prompt_input.py`
  - `tests/test_keysuri_prompt_input.py`
  - `tests/test_service_full_run.py`
- Verification: 224 passed, `py_compile` OK, `git diff --check` clean.

---

## owner-review exposure log — purpose, record conditions, separation principle

**Purpose:** supply owner-review exposure rows to the existing cross-day dedup
gate so that items already shown to the owner via owner-review email are not
re-surfaced on later days. This is a **minimal foundation**, not full cross-day
matching.

**Records (write) only when:**
- owner-review email actually sent: `email_sent=True` / `artifact_status="emailed"`
- body_only / body_and_image reissue where `selected_items` differ from parent

**Does NOT record:**
- stored / no-send / smoke / local dry-run
- image_only reissue
- body_only / body_and_image reissue where selection is unchanged

**Separation principle (must not be conflated):**
- `sent_news_log.json` = customer final-send log
- `owner_review_exposure_log.json` = owner-review exposure log
- An owner-review-only event must never pollute the customer final-send log.
- customer final send and owner-review exposure are different events.

---

## owner-review exposure log — runtime verification — `DEPLOYED_SMOKE_PASS`

A previous check reported runtime row verification as `BLOCKED` because no
qualifying post-deploy owner-review run existed at that time. That condition was
later resolved: a qualifying run occurred and was verified read-only.

- verified run: `20260626_183002_keysuri_korea_tech_b79bab96`
- created_at: `2026-06-26T18:31:25+09:00` (after revision creation)
- artifact: `artifact_status=emailed`, `email_sent=True`,
  `exposure_log_updated=True`, `exposure_log_written_count=5`,
  `exposure_log_update_error=None`
- exposure log: `owner_review_exposure_log.json` present,
  `schema=owner_review_exposure_log_v1`, 5 rows, all rows reference run_id
  `20260626_183002_keysuri_korea_tech_b79bab96`, all 15 schema fields populated,
  `exposure_kind=owner_review_email`, `program_id=keysuri_korea_tech`,
  no cross-program leakage
- separation confirmed: `sent_news_log.json` remained 2 rows; no row added for
  `20260626_183002_keysuri_korea_tech_b79bab96`; `customer_delivery_status=not_sent`;
  owner-review-only event did not pollute the customer final-send log

Scope note: only the exposure-log runtime verification is updated to
`DEPLOYED_SMOKE_PASS`. This is not a full-completion declaration.

---

## Remaining issues (labels only — no new work proposed here)

| Item | Status | Note |
|------|--------|------|
| Admin notice auth smoke | `KNOWN_ISSUE_REMAINS` | Admin notice deployed, but real Admin auth smoke not yet completed (needs auth / cookie / session). Do not call `POST /admin/notices/send` without authorization. |
| cross-day entity/editorial_cluster matching | `OUT_OF_SCOPE_DEFERRED` | The 1st-pass exposure log only supplies exposure rows to the existing URL/title/source-title dedup gate. Full entity/cluster cross-day matching is not implemented. |
| `sent_news_log_store.py` read fail-open improvement | `OUT_OF_SCOPE_DEFERRED` | The existing store was not touched in this patch. |
| internal job token rotation | `SECURITY_DECISION_REQUIRED` | Recorded as status only; no Secret query/change performed. |

---

## Scope guard / forbidden actions

This recovery and its documentation reflect read-only verification plus
docs-only edits. Confirmed NOT done:

- code / test / runtime-logic modification (recovery code already committed under the commits above; this doc work changed no code)
- Scheduler / Secret / Cloud Run config change or Secret query
- real customer send / approve / customer final send
- owner-review send trigger / `POST /admin/notices/send`
- modification of `sent_news_log.json` / `owner_review_exposure_log.json` / run artifacts
- push / deploy (push auto-triggers Cloud Build deploy and is forbidden here)
