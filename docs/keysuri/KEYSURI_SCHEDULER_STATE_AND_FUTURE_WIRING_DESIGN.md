# Key-Suri Scheduler State and Production Wiring

> **⚠️ AUDIT CORRECTION — 2026-06-23**
>
> This document was originally written when Key-Suri scheduler wiring had not yet been connected to GCP.
> A 2026-06-23 operations audit confirmed that **both Key-Suri schedulers are ENABLED and running in production**.
> Section 1 has been fully updated to reflect the confirmed live state.
> Sections marked **[FUTURE]** document architecture that is not yet implemented.
> All other sections describe the current production reality.

## Document purpose

This document records the **current Key-Suri production scheduler state** (as confirmed by 2026-06-23 GCP audit) and defines remaining **future scheduling architecture** not yet implemented.

Clarifications:

- This file does **not** change Cloud Scheduler settings.
- This file does **not** deploy anything.
- This file does **not** change runtime code.
- This file is a **state record** and architecture reference for Key-Suri scheduler operations.

Readers should use this document together with:

- `docs/keysuri/KEYSURI_PRODUCTION_WIRING_DESIGN.md` — image/profile production wiring design
- `docs/keysuri/KEYSURI_IMAGE_PROFILE_LOCK.md` — locked image prompt profiles
- `docs/keysuri/KEYSURI_R6B_BOTTOM_SHOT_EMOTIONAL_LOCKIN_PLAN.md` — bottom-shot slot design
- `docs/keysuri/KEYSURI_R5B_PRODUCTION_PREFLIGHT_AND_MANUAL_CANARY_PROCEDURE.md` — manual canary procedure

---

## 1. Current production scheduler state

> **Source:** 2026-06-23 GCP audit — `gcloud scheduler jobs list/describe`, `gcloud run revisions list`, GCS artifact inspection.

### 1.1 Summary

**Both Key-Suri schedulers are ENABLED and running in production** as of 2026-06-23.

| Finding | Status |
|---------|--------|
| `KeeSuri_Global_Tech` Cloud Scheduler job | **ENABLED** — `30 12 * * 1-5` Asia/Seoul (12:30 KST Mon–Fri) |
| `KeeSuri_Korea_Tech` Cloud Scheduler job | **ENABLED** — `30 18 * * 1-5` Asia/Seoul (18:30 KST Mon–Fri) |
| Production owner-review email pipeline | **OPERATIONAL** — `send_owner_email=true`, artifacts confirmed in GCS |
| `service_full_run` pipeline | **OPERATIONAL** — `service_full_run=true` in GCS metadata |
| Customer delivery | **OPERATIONAL** — `customer_delivery_status=smtp_accepted` confirmed |
| Admin integration | **OPERATIONAL** — `owner_review_url` generated, admin panel deployed |
| Cloud Run service | `genie-blog-run` revision `genie-blog-run-00176-x7r` @ `f08ad53` |

### 1.2 What exists today (confirmed production state)

| Layer | State (2026-06-23) |
|-------|--------------------|
| **GCP Scheduler — Global** | `KeeSuri_Global_Tech` ENABLED, 12:30 KST Mon–Fri, last run 2026-06-23T03:30Z → 200 OK |
| **GCP Scheduler — Korea** | `KeeSuri_Korea_Tech` ENABLED, 18:30 KST Mon–Fri, last run 2026-06-22T09:30Z → 200 OK |
| **Scheduler endpoint** | `POST /internal/jobs/create-keysuri-owner-review` (both programs) |
| **Auth** | `X-Genie-Internal-Job-Token` header (Secret Manager) |
| **Program registry** | `keysuri_global_tech` and `keysuri_korea_tech` in `programs/registry.py` |
| **Production email (owner review)** | Sending via SMTP — `email_sent=true` in GCS artifacts |
| **Production image generation** | `called_image_api=true`, `image_generation_status=generated` in GCS artifacts |
| **Customer delivery** | `smtp_accepted` on approved runs; requires operator approve via admin UI |
| **Admin UI** | `/admin/runs/{run_id}`, `/admin/customer-recipients` — deployed and operational |
| **Artifact storage** | GCS `gen-lang-client-0667098249-genie-artifacts/admin_runs/` |
| **R6B bottom-shot (Korea)** | `generated_v6_multi_ref` path — **production-wired for Korea**, confirmed 2026-06-22 |

### 1.3 Latest confirmed run results (GCS artifact audit)

| Run | Artifact status | Validation | Customer delivery |
|-----|-----------------|------------|-------------------|
| `20260623_063058_today_genie_46793a9b` | emailed | pass | smtp_accepted |
| `20260623_123002_keysuri_global_tech_79f98bf4` | emailed | pass | smtp_accepted |
| `20260622_183002_keysuri_korea_tech_6960a026` | emailed | pass | smtp_accepted |

### 1.4 Genie programs are separate

**Today_Geenee** (`today_geenee` / `today_genie`) and **Tomorrow_Geenee** (`tomorrow_genie`) have their own orchestrator paths and Cloud Scheduler jobs.

- `Today_Geenee` scheduler: ENABLED, `30 6 * * 1-5` → `/internal/jobs/create-owner-review`
- `Tomorrow_Geenee` scheduler: **PAUSED**, `0 18 * * *` → `POST /` (root endpoint, no internal token)

Those schedules are **not Key-Suri**. Do not confuse Genie 18:00 (`tomorrow_genie`) with Key-Suri 18:30 (`keysuri_korea_tech`).

### 1.5 R6B bottom-shot current state

R6B bottom-shot for Korea:

- `generated_v6_multi_ref` source path is **production-wired** for `keysuri_korea_tech`
- Confirmed in GCS: `bottom_shot_source=generated_v6_multi_ref` in `20260622_183002_keysuri_korea_tech_6960a026`
- Korea bottom baseline gate (`_KEYSURI_KOREA_BOTTOM_BASELINE_ASSET_ID`) active in `admin_store.py`
- `keysuri_global_tech` remains **top-shot only** — no bottom-shot

---

## 2. Program separation

### 2.1 keysuri_global_tech — 12:30 KST global tech slot

| Attribute | Value |
|-----------|-------|
| `program_id` | `keysuri_global_tech` |
| Schedule identity | **12:30 KST** |
| Content domain | Global AI, big tech, semi, platforms, policy |
| Visual identity | Daytime global briefing (top shot) |
| Image slot rule | **Top-shot only** — no bottom shot, no off-duty wardrobe, no leaving-work mood |

### 2.2 keysuri_korea_tech — 18:30 KST Korea tech slot

| Attribute | Value |
|-----------|-------|
| `program_id` | `keysuri_korea_tech` |
| Schedule identity | **18:30 KST** (not 18:00) |
| Content domain | Korea AI, startups, platforms, policy, support |
| Visual identity | Early-evening Korea briefing |
| Image slot rule | Top shot **+** bottom shot (when R6B production promotion is approved) |

### 2.3 R6B bottom-shot slot binding

| Rule | Detail |
|------|--------|
| Bottom-shot belongs to | **18:30 Korea slot only** (`keysuri_korea_tech`) |
| Global 12:30 slot | **Top-shot only** — bottom-shot prompts/images must not attach |
| Separate approval required | Bottom-shot in a different slot requires **explicit separate approval** — default is Korea 18:30 only |

### 2.4 Forbidden program confusion

Do **not** confuse Key-Suri with:

| Program | Schedule (Genie docs) | Relationship to Key-Suri |
|---------|----------------------|--------------------------|
| `today_geenee` / `today_genie` | 05:30–06:30 KST (Genie) | **Forbidden** in Key-Suri canary gate |
| `tomorrow_geenee` / `tomorrow_genie` | 18:00 KST (Genie override) | **Forbidden** — not Key-Suri Korea 18:30 |

`keysuri_image_api_gate.py` lists Today/Tomorrow_Geenee as `FORBIDDEN_PROGRAMS` for Key-Suri image operations.

---

## 3. Current hard gates

These gates are **active today** and must remain until explicit production wiring approval.

### 3.1 Image provider contract (`keysuri_image_provider_contract.py`)

| Gate | Current value |
|------|---------------|
| `scheduler_allowed` | **false** |
| `manual_only` | **true** |
| `production_auto_call_allowed` | **false** |
| `default_no_call` | **true** |
| `max_requests_per_run` | **1** |
| `runtime_wiring` | **none** |

### 3.2 Program registry (`programs/registry.py`)

| Gate | `keysuri_global_tech` | `keysuri_korea_tech` |
|------|----------------------|----------------------|
| `auto_send_after_timeout_enabled` | **false** | **false** |
| `image_attachment_enabled` | **false** | **false** |
| `customer_send_requires_approval` | **true** | **true** |
| `source_gate_enabled` | **true** | **true** |

### 3.3 Canary client (`keysuri_image_api_canary_client.py`)

| Gate | Current value |
|------|---------------|
| `ready_for_scheduler` | **false** (hardcoded; report validation enforces) |
| `changed_scheduler` side effect | Must remain **false** |
| `sent_email` side effect | Must remain **false** |

### 3.4 Generated output policy

| Rule | Detail |
|------|--------|
| Canary images | Under `output/keysuri_preview/image_canary/` |
| Git status | **gitignored** (`.gitignore` → `output/`) |
| Production use | **Forbidden** — QA references only |
| Commit policy | **Must not commit** generated images or canary reports |

### 3.5 PASS_DIRECTION boundary

`offduty_02C_luxury_knit_silk_skirt_farewell` is **PASS_DIRECTION** only:

- Image: `keysuri_global_canary_20260605_105936.jpg` (local, gitignored)
- Status: QA/direction reference — **not** a production asset
- **Cannot be production-wired** without a separate R6B production promotion gate (see §8)

---

## 4. Production scheduler architecture (now live)

### 4.1 Production pipeline (deployed)

> This pipeline was previously described as future/proposed. As of 2026-06-23 audit it is **live in production**.

The deployed architecture:

```
Cloud Scheduler (or equivalent timer)
        │
        ▼
Internal job endpoint
  (orchestrator mode / Cloud Run job / HTTP worker)
        │
        ▼
Key-Suri schedule gate
  (weekday + Korean public holiday + promotion checks)
        │
        ├── SKIP → log reason, exit (no text, no image, no email)
        │
        └── RUN
              │
              ▼
        Program runtime builder
          (keysuri_global_runtime / keysuri_korea_runtime)
              │
              ▼
        Text / content generation
          (source gate → prompt → parse → validate)
              │
              ▼
        Image generation
          ONLY IF production asset gate passes
          (profile lock + wardrobe seed + slot rules)
              │
              ▼
        Owner review OR email send
          (per approved delivery policy)
```

### 4.2 Architecture principles (active)

| Principle | Detail |
|-----------|--------|
| Skip before cost | `today_genie_weekend_skip_payload()` guards weekends for Today; Korean public holiday gate is **[FUTURE]** for Key-Suri |
| Slot separation | Global 12:30 and Korea 18:30 are **separate GCP jobs** with separate triggers |
| Image is gated | `called_image_api=true` confirmed — gate passes in production |
| Delivery is gated | Customer email requires operator approval via admin UI (`approve_run`) |
| Internal token auth | `X-Genie-Internal-Job-Token` secures both Key-Suri scheduler endpoints |

### 4.3 Relationship to existing design docs

| Document | Scope |
|----------|-------|
| This document | Scheduler state + timer/gate architecture |
| `KEYSURI_PRODUCTION_WIRING_DESIGN.md` | Image profile, wardrobe, slot visual identity |
| `KEYSURI_R6B_BOTTOM_SHOT_EMOTIONAL_LOCKIN_PLAN.md` | Bottom-shot creative and QA rules |
| `KEYSURI_R5B_PRODUCTION_PREFLIGHT_AND_MANUAL_CANARY_PROCEDURE.md` | Manual canary preflight before any live call |

---

## 5. Weekday and holiday policy

### 5.1 Schedule times (unchanged)

| Program | Scheduled time | Timezone |
|---------|---------------|----------|
| `keysuri_global_tech` | **12:30 KST** | Asia/Seoul (authoritative) |
| `keysuri_korea_tech` | **18:30 KST** | Asia/Seoul (authoritative) |

**Do not change** these slot times when adding weekday/holiday skip logic.

### 5.2 Trigger rules

| Condition | Action |
|-----------|--------|
| Monday–Friday (KST) | Eligible to run (subject to other gates) |
| Saturday (KST) | **SKIP** — no generation |
| Sunday (KST) | **SKIP** — no generation |
| Korean public holiday (KST) | **SKIP** — no generation |

### 5.3 Implementation split

| Skip type | Recommended implementation layer |
|-----------|-------------------------------|
| Weekend (Sat/Sun) | **Cloud Scheduler cron** — `1-5` weekday field (see §6) |
| Korean public holiday | **Internal Key-Suri schedule gate** — runtime calendar lookup |

Rationale: Cloud Scheduler cron handles simple weekday exclusion. Korean public holidays require a maintained holiday calendar and belong in application logic where skip reasons can be logged and tested.

### 5.4 Skip behavior (mandatory)

When a weekday/holiday skip occurs:

- **Do not** generate text/content
- **Do not** call image API
- **Do not** render owner-review HTML for delivery
- **Do not** send email or in_app notification
- **Do** log skip reason with program_id and KST date
- **Do** exit cleanly with zero side effects

---

## 6. Active cron configuration (confirmed GCP)

> These are **deployed and active** as of 2026-06-23 audit. They are NOT examples.

### 6.1 keysuri_global_tech (ENABLED)

```
GCP Job:  KeeSuri_Global_Tech
Cron:     30 12 * * 1-5
Timezone: Asia/Seoul
Meaning:  12:30 KST, Monday through Friday only
Endpoint: POST /internal/jobs/create-keysuri-owner-review
Auth:     X-Genie-Internal-Job-Token
```

### 6.2 keysuri_korea_tech (ENABLED)

```
GCP Job:  KeeSuri_Korea_Tech
Cron:     30 18 * * 1-5
Timezone: Asia/Seoul
Meaning:  18:30 KST, Monday through Friday only
Endpoint: POST /internal/jobs/create-keysuri-owner-review
Auth:     X-Genie-Internal-Job-Token
```

### 6.3 What cron does not handle

Cron `1-5` excludes weekends but **does not** exclude Korean public holidays that fall on weekdays. The internal schedule gate (§7) must handle those.

### 6.4 GCP authority note

Per `SCHEDULE_OVERRIDE.md`, **live GCP Cloud Scheduler settings** are authoritative for deployed Genie jobs. Any future Key-Suri scheduler must be verified against live GCP config after deployment — repo docs alone do not create schedules.

---

## 7. Korean public holiday gate [FUTURE — not yet implemented]

### 7.1 Module status

**File:** `keysuri_schedule_gate.py` — **not implemented**. Weekday cron (`1-5`) runs Mon–Fri but does **not** skip Korean public holidays that fall on weekdays. This is a known gap.

Current behavior: scheduler fires on public holidays falling on weekdays (no skip). Holiday gate remains on the backlog.

**File:** `keysuri_schedule_gate.py` (future — do not create until approved)

### 7.2 Responsibilities

| Responsibility | Detail |
|----------------|--------|
| Determine current KST date | Use `Asia/Seoul` as authoritative timezone |
| Check weekend | Saturday/Sunday → skip |
| Check Korean public holiday | National/public holiday calendar → skip |
| Return decision | `RUN` or `SKIP` with reason |
| Log skip | Structured log entry — no image/email side effects |
| Zero cost on skip | Exit before text generation, image API, render, email |

### 7.3 Possible gate statuses

| Status | Meaning |
|--------|---------|
| `RUN` | All schedule checks passed — proceed to runtime builder (subject to other gates) |
| `SKIP_WEEKEND` | Saturday or Sunday in KST |
| `SKIP_PUBLIC_HOLIDAY` | Korean public holiday in KST |
| `SKIP_DISABLED` | Production scheduler not enabled (default state today) |
| `SKIP_NO_PRODUCTION_PROMOTION` | Required asset (e.g. R6B bottom-shot) not promoted to production |

### 7.4 Proposed interface (design only)

```python
# Design sketch only — not implemented
def evaluate_keysuri_schedule_gate(
    program_id: str,
    *,
    now_kst: datetime | None = None,
    production_enabled: bool = False,
) -> ScheduleGateResult:
    """
    Returns RUN or SKIP with reason.
    Must not call image API, render email, or mutate scheduler.
    """
```

### 7.5 Holiday calendar source (TBD at implementation)

Implementation must choose and document:

- Static holiday table (yearly maintenance)
- External Korean holiday API
- Government-published ICS/JSON feed

Decision deferred until implementation patch plan is approved.

---

## 8. Production promotion dependency

### 8.1 PASS_DIRECTION is not production approval

`offduty_02C_luxury_knit_silk_skirt_farewell` achieved **PASS_DIRECTION** status:

- Validates R6B creative direction (identity-first 3/4 framing, premium off-duty luxury wardrobe, farewell gesture)
- Image remains local QA reference under `output/`
- **Does not** authorize scheduled bottom-shot generation or email attachment

### 8.2 R6B production promotion gate (required before bottom-shot scheduling)

Before scheduled bottom-shot generation or attachment:

| Requirement | Detail |
|-------------|--------|
| Separate promotion gate | R6B production promotion checklist must exist and pass |
| Asset approval | Approved production bottom-shot profile(s) must be locked — not PASS_DIRECTION canary JPGs |
| Slot binding | Bottom-shot attaches to `keysuri_korea_tech` 18:30 only (unless separately approved) |
| Scheduler behavior | Scheduler must **not** use PASS_DIRECTION canary images directly |

### 8.3 Bottom-shot wiring block

Bottom-shot production wiring remains **blocked** until:

1. R6B production promotion gate is explicitly approved
2. Production asset profile is locked (separate from QA canary output)
3. Schedule gate includes `SKIP_NO_PRODUCTION_PROMOTION` when promotion is incomplete
4. Image provider contract `scheduler_allowed` flip is explicitly approved

---

## 9. Cost control principle

### 9.1 Current production cost profile (2026-06-23)

Both Key-Suri schedulers run Mon–Fri and incur recurring cost:

- **Text generation**: Gemini call per scheduled run (confirmed `response_status` in artifacts)
- **Image API**: Called per run (`called_image_api=true` in artifacts)
- **Email delivery**: Owner review + customer SMTP per approved run

Cost is bounded to weekdays only (cron `1-5`). Korean public holiday skip is **not yet implemented**.

### 9.2 Skip-before-cost ordering (active)

Weekday and holiday skip reduces future:

- LLM text generation cost
- Image API generation cost
- Rendering and email delivery cost

**Mandatory ordering:**

```
Schedule gate (cheapest)
  → source gate / text generation
    → image API (expensive)
      → render + email send (expensive + customer-facing)
```

The skip gate **must run first**. Holiday/weekend skip must **never** occur after image generation has started.

### 9.3 Manual canary cost remains operator-controlled

Manual canaries remain one-call-per-approval regardless of future scheduler state. Scheduler wiring does not remove manual canary gates until explicitly redesigned and approved.

---

## 10. Required future implementation files

**Do not create these files now.** Listed for future patch planning only.

| File / artifact | Purpose |
|-----------------|---------|
| `keysuri_schedule_gate.py` | Weekday/holiday/promotion schedule gate |
| `tests/test_keysuri_schedule_gate.py` | Business-day, weekend, holiday, disabled, promotion skip tests |
| `keysuri_global_runtime.py` (or equivalent) | Program runtime builder for 12:30 global slot |
| `keysuri_korea_runtime.py` (or equivalent) | Program runtime builder for 18:30 Korea slot |
| Orchestrator or internal job route update | New Key-Suri mode(s) — separate from Today/Tomorrow_Geenee |
| Cloud Scheduler config or deployment notes | GCP job definitions (external to or documented in deploy docs) |
| R6B production promotion checklist doc | Asset promotion gate before bottom-shot scheduling |
| `keysuri_image_provider_contract.py` update | Only if `scheduler_allowed` flip is explicitly approved |
| Holiday calendar data or adapter | Korean public holiday lookup for schedule gate |

---

## 11. Risk notes

| Risk | Mitigation |
|------|------------|
| Modify Today_Geenee / Tomorrow_Geenee schedules | **Do not.** Key-Suri wiring is a separate program path. |
| Wire Scheduler based on registry metadata alone | **Do not.** Registry `schedule_kst` is declarative only; runtime builders are not implemented. |
| Flip `scheduler_allowed` without explicit approval | **Do not.** Requires contract update, tests, and operator sign-off. |
| Attach `output/` QA canary images to production email | **Do not.** Gitignored local QA only. |
| Schedule bottom-shot before production promotion gate | **Do not.** R6B PASS_DIRECTION is direction only. |
| Holiday skip after image generation started | **Do not.** Skip gate must precede all costly calls. |
| Use PASS_DIRECTION image as production asset | **Do not.** Separate promotion and asset lock required. |
| Change Cloud Scheduler without explicit approval | **Do not.** Multiple existing docs enforce this boundary. |
| Confuse Genie 18:00 tomorrow_genie with Key-Suri 18:30 | **Do not.** Different programs, different schedules. |

---

## 12. Current operational status and remaining actions

| Item | Status |
|------|--------|
| Cloud Scheduler wired (both programs) | ✅ **DONE** (confirmed 2026-06-23 audit) |
| Production owner-review pipeline | ✅ **DONE** |
| Customer delivery pipeline | ✅ **DONE** (requires operator approval) |
| Admin UI integration | ✅ **DONE** (commit `f08ad53`) |
| Beta recipient management | ✅ **DONE** (commit `4237c5a`) |
| R6B bottom-shot Korea production wiring | ✅ **DONE** (`generated_v6_multi_ref` confirmed) |
| Korean public holiday skip gate | ❌ **NOT IMPLEMENTED** — weekday cron only |
| `keysuri_schedule_gate.py` | ❌ **NOT IMPLEMENTED** |
| Document this scheduler doc update | ✅ **DONE** (2026-06-23 audit remediation) |

---

## Appendix A — Audit source references

### Original repo inspection (2026-06, pre-production)

At original writing, repo inspection showed no Key-Suri scheduler wiring. That finding is now superseded.

### 2026-06-23 GCP production audit

| Checked location | Finding |
|-----------------|---------|
| `gcloud scheduler jobs list --location=asia-northeast3` | `KeeSuri_Global_Tech` ENABLED, `KeeSuri_Korea_Tech` ENABLED |
| GCS `admin_runs/20260623_123002_keysuri_global_tech_79f98bf4.json` | `service_full_run=true`, `email_sent=true`, `smtp_accepted` |
| GCS `admin_runs/20260622_183002_keysuri_korea_tech_6960a026.json` | `service_full_run=true`, `bottom_shot_source=generated_v6_multi_ref`, `smtp_accepted` |
| Cloud Run `gcloud run revisions list` | `genie-blog-run-00176-x7r` @ `f08ad53` |
| Cloud Build history | All recent builds SUCCESS, SHA-tagged |
| `/health` endpoint | `{"status":"ok","supported_modes":["today_genie","tomorrow_genie"]}` |
| `gcloud run services describe` env | `GENIE_CUSTOMER_EMAIL_TO` 5 baseline recipients; `GENIE_ARTIFACT_BUCKET` GCS configured |

---

## Appendix B — Related committed docs (do not duplicate)

| Document | Role |
|----------|------|
| `KEYSURI_PRODUCTION_WIRING_DESIGN.md` | Image/profile wiring — complements this scheduler doc |
| `KEYSURI_IMAGE_TRACK_CURRENT_STATE_HANDOFF.md` | Track handoff including R6B PASS_DIRECTION state |
| `KEYSURI_R6B_OFFDUTY_02C_LUXURY_BOTTOM_SHOT_CANDIDATE_PACKAGE.md` | offduty_02C PASS_DIRECTION record |

This document does not replace those files. It adds the **scheduler state map** and **future timer/gate architecture** layer.
