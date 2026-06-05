# Kee-Suri Scheduler State and Future Wiring Design

## Document purpose

This document records the **current Kee-Suri scheduler state** (as confirmed by repository inspection) and defines the **future scheduling architecture** before any implementation.

Clarifications:

- This file does **not** connect Cloud Scheduler.
- This file does **not** deploy anything.
- This file does **not** change runtime code.
- This file does **not** enable production auto-calls, image API calls, or email sends.
- This file is a **design guard** and state map for future wiring decisions.

Readers should use this document together with:

- `docs/keysuri/KEYSURI_PRODUCTION_WIRING_DESIGN.md` — image/profile production wiring design
- `docs/keysuri/KEYSURI_IMAGE_PROFILE_LOCK.md` — locked image prompt profiles
- `docs/keysuri/KEYSURI_R6B_BOTTOM_SHOT_EMOTIONAL_LOCKIN_PLAN.md` — bottom-shot slot design
- `docs/keysuri/KEYSURI_R5B_PRODUCTION_PREFLIGHT_AND_MANUAL_CANARY_PROCEDURE.md` — manual canary procedure

---

## 1. Current scheduler state

### 1.1 Summary

**No active Kee-Suri scheduler exists** in this repository or in any wired orchestrator path inspected.

Scheduler inspection confirmed:

| Finding | Status |
|---------|--------|
| Cloud Scheduler job for Kee-Suri | **Not found** in repo |
| Cron definition for Kee-Suri | **Not found** in repo |
| Terraform schedule for Kee-Suri | **Not found** in repo |
| Orchestrator job for Kee-Suri | **Not found** — `orchestrator.py` and `run_orchestrator.py` have no `keysuri` references |
| Cloud Run scheduled job for Kee-Suri | **Not found** in repo |

### 1.2 What exists today

| Layer | Current state |
|-------|---------------|
| **Program registry** | `keysuri_global_tech` and `keysuri_korea_tech` are declared in `programs/registry.py` with `schedule_kst` metadata only |
| **Runtime builders** | `keysuri_global_runtime` and `keysuri_korea_runtime` are named in registry but **not implemented** elsewhere in the repo |
| **Production email** | **Not connected** — no orchestrator path sends Kee-Suri email |
| **Production image generation** | **Not scheduled** — image canary is manual-only |
| **Image canary** | Manual runners only: `keysuri_image_api_canary_client.py`, `keysuri_manual_opt_in_canary_runner.py`, `scripts/run_keysuri_image_api_canary.py`, `scripts/run_keysuri_manual_opt_in_canary.py` |
| **Offline dry-run** | Manual only: `keysuri_offline_dry_run.py`, `scripts/run_keysuri_offline_dry_run.py` |
| **R6B bottom-shot** | Design and manual canary only — no scheduler binding |

### 1.3 Manual canary is the only generation path

Image generation for Kee-Suri today requires **explicit human invocation**:

- Set `GENIE_KEYSURI_IMAGE_MANUAL_APPROVAL` (or CLI `--manual-approval`)
- Select program (`keysuri_global_tech` or `keysuri_korea_tech`)
- Run manual canary script or call `run_keysuri_image_api_canary()` directly

Nothing in-repo auto-fires at 12:30 KST or 18:30 KST.

### 1.4 Genie programs are separate

**Today_Geenee** (`today_geenee` / `today_genie`) and **Tomorrow_Geenee** (`tomorrow_genie`) have their own orchestrator paths, Cloud Scheduler references in `ROLLOUT.md` / `SCHEDULE_OVERRIDE.md`, and deployment docs.

Those schedules are **not Kee-Suri**. Do not assume Genie scheduler configuration applies to Kee-Suri.

### 1.5 R6B bottom-shot current state

R6B bottom-shot emotional lock-in is:

- Documented in `docs/keysuri/KEYSURI_R6B_BOTTOM_SHOT_EMOTIONAL_LOCKIN_PLAN.md`
- Validated via manual canaries only (e.g. `offduty_02C` PASS_DIRECTION)
- **Not scheduled**, **not production-wired**, **not email-attached**

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

Do **not** confuse Kee-Suri with:

| Program | Schedule (Genie docs) | Relationship to Kee-Suri |
|---------|----------------------|--------------------------|
| `today_geenee` / `today_genie` | 05:30–06:30 KST (Genie) | **Forbidden** in Kee-Suri canary gate |
| `tomorrow_geenee` / `tomorrow_genie` | 18:00 KST (Genie override) | **Forbidden** — not Kee-Suri Korea 18:30 |

`keysuri_image_api_gate.py` lists Today/Tomorrow_Geenee as `FORBIDDEN_PROGRAMS` for Kee-Suri image operations.

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

## 4. Future scheduler design

### 4.1 Proposed production architecture

Future Kee-Suri production wiring should follow this pipeline. **None of this is implemented or connected today.**

```
Cloud Scheduler (or equivalent timer)
        │
        ▼
Internal job endpoint
  (orchestrator mode / Cloud Run job / HTTP worker)
        │
        ▼
Kee-Suri schedule gate
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

### 4.2 Design principles

| Principle | Detail |
|-----------|--------|
| Skip before cost | Schedule gate runs **before** text generation, image API, rendering, and email |
| Slot separation | Global 12:30 and Korea 18:30 remain **separate programs** with separate triggers |
| Image is gated | Image API call requires production asset gate — not automatic on schedule fire |
| Delivery is gated | Email/in_app send requires explicit approved policy — registry metadata alone is insufficient |
| No registry-only wiring | `schedule_kst` in registry is **metadata**, not permission to schedule |

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
| Korean public holiday | **Internal Kee-Suri schedule gate** — runtime calendar lookup |

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

## 6. Proposed future cron examples

> **FUTURE EXAMPLES ONLY — DO NOT APPLY UNTIL EXPLICIT PRODUCTION WIRING APPROVAL**

These illustrate how Cloud Scheduler **might** be configured. They are **not** deployed, **not** in any ops config in this repo, and **must not** be applied without explicit approval.

### 6.1 keysuri_global_tech

```
Cron:     30 12 * * 1-5
Timezone: Asia/Seoul
Meaning:  12:30 KST, Monday through Friday only
```

### 6.2 keysuri_korea_tech

```
Cron:     30 18 * * 1-5
Timezone: Asia/Seoul
Meaning:  18:30 KST, Monday through Friday only
```

### 6.3 What cron does not handle

Cron `1-5` excludes weekends but **does not** exclude Korean public holidays that fall on weekdays. The internal schedule gate (§7) must handle those.

### 6.4 GCP authority note

Per `SCHEDULE_OVERRIDE.md`, **live GCP Cloud Scheduler settings** are authoritative for deployed Genie jobs. Any future Kee-Suri scheduler must be verified against live GCP config after deployment — repo docs alone do not create schedules.

---

## 7. Korean public holiday gate

### 7.1 Proposed module (not implemented)

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

### 9.1 Current state (zero recurring scheduler cost)

Manual-only canary state has **no recurring scheduler cost**:

- No Cloud Scheduler jobs for Kee-Suri
- No automatic text generation
- No automatic image API calls
- No automatic email sends

### 9.2 Future state (skip before expensive calls)

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
| Orchestrator or internal job route update | New Kee-Suri mode(s) — separate from Today/Tomorrow_Geenee |
| Cloud Scheduler config or deployment notes | GCP job definitions (external to or documented in deploy docs) |
| R6B production promotion checklist doc | Asset promotion gate before bottom-shot scheduling |
| `keysuri_image_provider_contract.py` update | Only if `scheduler_allowed` flip is explicitly approved |
| Holiday calendar data or adapter | Korean public holiday lookup for schedule gate |

---

## 11. Risk notes

| Risk | Mitigation |
|------|------------|
| Modify Today_Geenee / Tomorrow_Geenee schedules | **Do not.** Kee-Suri wiring is a separate program path. |
| Wire Scheduler based on registry metadata alone | **Do not.** Registry `schedule_kst` is declarative only; runtime builders are not implemented. |
| Flip `scheduler_allowed` without explicit approval | **Do not.** Requires contract update, tests, and operator sign-off. |
| Attach `output/` QA canary images to production email | **Do not.** Gitignored local QA only. |
| Schedule bottom-shot before production promotion gate | **Do not.** R6B PASS_DIRECTION is direction only. |
| Holiday skip after image generation started | **Do not.** Skip gate must precede all costly calls. |
| Use PASS_DIRECTION image as production asset | **Do not.** Separate promotion and asset lock required. |
| Change Cloud Scheduler without explicit approval | **Do not.** Multiple existing docs enforce this boundary. |
| Confuse Genie 18:00 tomorrow_genie with Kee-Suri 18:30 | **Do not.** Different programs, different schedules. |

---

## 12. Recommended next steps

Execute in this order. **Do not skip steps.**

| Step | Action | Status |
|------|--------|--------|
| **A** | Commit this scheduler design doc | Pending operator request |
| **B** | Create Kee-Suri production promotion checklist (R6B asset gate) | Not started |
| **C** | Only after promotion policy exists — draft implementation patch plan | Not started |
| **D** | Only after explicit approval — implement `keysuri_schedule_gate.py` | Not started |
| **E** | Only after tests pass — consider Cloud Scheduler / orchestrator wiring | Not started |

**Do not implement schedule gate, runtime builders, or Cloud Scheduler until steps A–C are complete and step D is explicitly approved.**

---

## Appendix A — Inspection source references

Repository inspection (2026-06) confirmed:

| Checked location | Kee-Suri scheduler finding |
|------------------|---------------------------|
| `programs/registry.py` | Metadata only — 12:30 / 18:30 KST |
| `orchestrator.py`, `run_orchestrator.py` | No keysuri references |
| `cloudbuild-worker.yaml` | Worker image build only |
| `SCHEDULE_OVERRIDE.md`, `ROLLOUT.md`, `OPERATIONS.md` | Today/Tomorrow_Geenee only |
| `keysuri_image_provider_contract.py` | `scheduler_allowed: false` |
| `keysuri_image_api_canary_client.py` | `ready_for_scheduler: false` |
| Terraform / Cloud Scheduler YAML | Not found for Kee-Suri |

---

## Appendix B — Related committed docs (do not duplicate)

| Document | Role |
|----------|------|
| `KEYSURI_PRODUCTION_WIRING_DESIGN.md` | Image/profile wiring — complements this scheduler doc |
| `KEYSURI_IMAGE_TRACK_CURRENT_STATE_HANDOFF.md` | Track handoff including R6B PASS_DIRECTION state |
| `KEYSURI_R6B_OFFDUTY_02C_LUXURY_BOTTOM_SHOT_CANDIDATE_PACKAGE.md` | offduty_02C PASS_DIRECTION record |

This document does not replace those files. It adds the **scheduler state map** and **future timer/gate architecture** layer.
