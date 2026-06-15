# Kee-Suri R6B Production Promotion Checklist

## Document purpose

This document defines the **checklist and decision gate** required before any Kee-Suri R6B bottom-shot image can be promoted from QA/direction reference to production asset or production prompt default.

Clarifications:

- **PASS_DIRECTION is not production approval.**
- **`PROMPT_DIRECTION_ONLY` is creative/prompt direction only** — not a customer production asset, not scheduler-ready, not variation-ready.
- **Owner-review-only fixed asset attachment is a separate narrow allowance** for the watermarked `105936` registry asset in Korea owner-review email only.
- **Production promotion is a separate decision gate** from creative direction validation.
- This checklist **blocks accidental wiring** of QA canary images into email, scheduler, or production content.
- This file does **not** connect Cloud Scheduler, enable image API auto-calls, or send email.
- This file does **not** commit or reference `output/` images as production paths.

Related documents:

- `docs/keysuri/KEYSURI_SCHEDULER_STATE_AND_FUTURE_WIRING_DESIGN.md` — scheduler state (commit `1b23bcf`)
- `docs/keysuri/KEYSURI_R6B_OFFDUTY_02C_PROMPT_DIRECTION_ONLY_DECISION.md` — offduty_02C `PROMPT_DIRECTION_ONLY` decision (commit `07a98ac`)
- `docs/keysuri/KEYSURI_R6B_OFFDUTY_02C_LUXURY_BOTTOM_SHOT_CANDIDATE_PACKAGE.md` — offduty_02C PASS_DIRECTION record
- `docs/keysuri/KEYSURI_R6B_BOTTOM_SHOT_EMOTIONAL_LOCKIN_PLAN.md` — R6B slot and creative rules
- `docs/keysuri/KEYSURI_PRODUCTION_WIRING_DESIGN.md` — image/profile production wiring design

---

## 1. Purpose

### 1.1 Why this checklist exists

Kee-Suri R6B bottom-shot work has produced an accepted **creative direction** (`offduty_02C` PASS_DIRECTION). That result validates *how* bottom-shot generation should be steered — framing, wardrobe tier, expression, gesture, background.

It does **not** automatically authorize:

- Attaching the QA JPG to customer production email
- Scheduling automatic bottom-shot generation
- Copying the canary image into `static/email/` or other committed asset paths
- Flipping `scheduler_allowed` or `ready_for_scheduler`
- Using the canary output as the permanent production image asset
- Generating per-run offduty_02C variations

### 1.2 What this gate protects

| Risk | Gate action |
|------|-------------|
| QA canary JPG wired into customer email | **Block** until customer production promotion decision and asset path approved |
| PASS_DIRECTION treated as final asset | **Block** — direction ≠ production asset |
| Bottom-shot attached to wrong slot (12:30 global) | **Block** — slot binding enforced |
| Scheduler fires before promotion | **Block** — `SKIP_NO_PRODUCTION_PROMOTION` until checklist passes |
| Genie program image confusion | **Block** — Today/Tomorrow_Geenee forbidden |
| Owner-review asset mistaken for variation approval | **Block** — fixed `105936` reuse only |

### 1.3 Current promotion status

**`offduty_02C`: `PROMPT_DIRECTION_ONLY` — recorded**

A **`PROMPT_DIRECTION_ONLY`** decision has been recorded in:

- `docs/keysuri/KEYSURI_R6B_OFFDUTY_02C_PROMPT_DIRECTION_ONLY_DECISION.md`
- Commit: `07a98ac` — Record Kee-Suri R6B offduty_02C prompt-direction decision

`offduty_02C` remains **PASS_DIRECTION** at the canary QA level. That PASS validates creative direction only.

**Higher promotion levels remain blocked:**

| Level | Status |
|-------|--------|
| `PROMOTE_PROMPT_DIRECTION_ONLY` | **APPROVED** — commit `07a98ac` |
| `PROMOTE_OWNER_REVIEW_EMAIL_FIXED_ASSET` | **APPROVED** — fixed watermarked `105936`, Korea owner-review email only |
| `PROMOTE_STATIC_REFERENCE_FOR_DESIGN_ONLY` | Optional / not required |
| `PROMOTE_PRODUCTION_IMAGE_ASSET` | **NOT_APPROVED** |
| `PROMOTE_PRODUCTION_PROMPT_DEFAULT` | **NOT_APPROVED** |
| `PROMOTE_SCHEDULED_SLOT_ATTACHMENT` | **NOT_APPROVED** |

**Operational flags (current):** `owner_review_email_attachment_ready=true`, `customer_email_attachment_ready=false`, `scheduler_variation_ready=false`, `production_prompt_default=false`, `generated_variation_allowed=false`, `production_asset=false`, `scheduler_ready=false`, `role=korea_bottom only`.

The approved owner-review path uses the fixed watermarked registry/GCS asset only:

- Asset ID: `keysuri_korea_bottom_20260605_105936`
- Role: `korea_bottom only`
- Watermarked file: `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936_mirai_on_watermarked.jpg`
- GCS object: `assets/keysuri/korea_bottom/keysuri_global_canary_20260605_105936_mirai_on_watermarked.jpg`

The raw QA JPG under `output/` remains non-production and must not be committed or copied to `static/email/`.

---

## 2. Current accepted direction

### 2.1 Candidate record

| Field | Value |
|-------|-------|
| **profile_id** | `offduty_02C_luxury_knit_silk_skirt_farewell` |
| **result** | **PASS_DIRECTION** |
| **canary image (local QA)** | `keysuri_global_canary_20260605_105936.jpg` |
| **full local path** | `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg` |
| **reference used** | Asset 01 primary — `assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png` |
| **intended slot** | 18:30 bottom-shot (`keysuri_korea_tech`) — validated via global canary for direction only |
| **promotion level** | **`PROMPT_DIRECTION_ONLY`** — commit `07a98ac` |
| **production asset** | **false** |
| **owner-review email attachment** | **true** — fixed watermarked `105936` only |
| **customer email attachment** | **false** |
| **scheduler variation** | **false** |
| **production prompt default** | **false** |
| **generated variation allowed** | **false** |

### 2.2 Accepted direction formula

The following creative formula is **approved for prompt steering** (`PROMPT_DIRECTION_ONLY`) — **not** promoted as production asset:

| Element | Accepted direction |
|---------|-------------------|
| Identity priority | **Asset 01** — face/identity family anchor |
| Framing | **Knee-up or 3/4 body** — face clearly visible; not full-body default |
| Background | **CEO/chairman wood-door entrance** — fixed emotional continuity |
| Wardrobe | **Premium off-duty luxury** — silk-knit, satin/silk-blend skirt, premium mini handbag, delicate jewelry; tasteful but magnetic |
| Expression | **Fresh composed smile** / **싱그러운 미소** — not motherly |
| Gesture | **Small natural farewell** — emotional lock-in close; no finger heart / aegyo |
| Props | **No tablet** |
| QA gates passed | Face identity first; wardrobe quality second; framing/gesture PASS |

### 2.3 Operator rationale (summary)

Identity-first 3/4 framing, premium off-duty luxury wardrobe, CEO wood-door background, fresh composed smile, and farewell gesture successfully created Kee-Suri bottom-shot emotional lock-in direction.

**First accepted R6B bottom-shot direction** after three NOT_ACCEPTED canaries (`offduty_01`, `offduty_02`, `offduty_02B`).

---

## 3. Non-production boundary

The following rules are **mandatory today** and remain until a **higher** promotion level is explicitly approved in §9. The only exception is the explicitly approved fixed watermarked `105936` Korea owner-review email attachment.

| Rule | Detail |
|------|--------|
| `output/` image is QA reference only | Local gitignored path — not a production asset |
| Do not commit generated JPG | `.gitignore` → `output/` |
| Do not copy to `static/email/` | Owner-review uses registry/GCS/local watermarked resolver only; no static/email copy |
| Do not attach to customer production email | `customer_email_attachment_ready=false`; Korea customer delivery remains blocked |
| Owner-review fixed attachment is Korea-only | `owner_review_email_attachment_ready=true` only for `keysuri_korea_tech` bottom CID from fixed watermarked `105936` |
| Do not schedule automatic generation | No Cloud Scheduler / orchestrator bottom-shot job |
| Do not flip `scheduler_allowed` | `keysuri_image_provider_contract.py` remains `false` |
| Do not flip `ready_for_scheduler` | Canary client remains `false` |
| Do not use PASS_DIRECTION as final production asset approval | `PROMPT_DIRECTION_ONLY` recorded — production asset still requires separate approval |
| No scheduler/customer/static asset wiring approved | `scheduler_variation_ready=false`, `customer_email_attachment_ready=false`; no `static/email/` copy |
| Do not generate variations | `generated_variation_allowed=false`; offduty_02C is not a production prompt default |
| Do not wire Today/Tomorrow_Geenee | Forbidden program paths for Kee-Suri image ops |

**Default operational mode:** Fixed watermarked `105936` may attach only to Korea owner-review email. It is not customer delivery, not scheduler generation, not a global asset, and not a Korea top-shot.

---

## 4. Promotion types

### 4.1 Defined promotion levels

| Level | Code | Meaning | Typical use |
|-------|------|---------|-------------|
| Prompt direction only | `PROMOTE_PROMPT_DIRECTION_ONLY` | Lock creative formula in prompt/docs; **no** committed image asset; **no** email attachment | **Recorded for offduty_02C** — commit `07a98ac` |
| Owner-review fixed asset attachment | `PROMOTE_OWNER_REVIEW_EMAIL_FIXED_ASSET` | Reuse fixed watermarked registry/GCS asset in Korea owner-review email only; **no customer delivery**, **no scheduler**, **no variation generation** | **Approved for `105936` korea_bottom only** |
| Static reference for design | `PROMOTE_STATIC_REFERENCE_FOR_DESIGN_ONLY` | Committed design reference under `assets/keysuri/` for human/design review — **not** email attachment | Future design lock |
| Production image asset | `PROMOTE_PRODUCTION_IMAGE_ASSET` | Approved image copied to committed production asset path; may attach to email when policy allows | Requires full §5–§7 checks |
| Production prompt default | `PROMOTE_PRODUCTION_PROMPT_DEFAULT` | Profile becomes default bottom-shot prompt template for scheduled generation | Requires asset or stable prompt lock |
| Scheduled slot attachment | `PROMOTE_SCHEDULED_SLOT_ATTACHMENT` | Bottom-shot auto-generated or auto-attached at 18:30 Korea slot | Requires scheduler + asset + gate approval |

### 4.2 Promotion level hierarchy

Higher levels imply all lower-level creative checks pass, plus additional technical and delivery gates:

```
PROMOTE_PROMPT_DIRECTION_ONLY
  → PROMOTE_OWNER_REVIEW_EMAIL_FIXED_ASSET
    → PROMOTE_STATIC_REFERENCE_FOR_DESIGN_ONLY
    → PROMOTE_PRODUCTION_IMAGE_ASSET
      → PROMOTE_PRODUCTION_PROMPT_DEFAULT
        → PROMOTE_SCHEDULED_SLOT_ATTACHMENT
```

### 4.3 Current recorded level

**`PROMOTE_PROMPT_DIRECTION_ONLY`** — **APPROVED** for `offduty_02C` (commit `07a98ac`)

Decision record: `docs/keysuri/KEYSURI_R6B_OFFDUTY_02C_PROMPT_DIRECTION_ONLY_DECISION.md`

Rationale at time of decision:

- Creative direction is validated (PASS_DIRECTION)
- QA image remains local and gitignored — **not** a production asset
- No production asset path exists
- Scheduler is not connected (`scheduler_ready=false`)
- Customer email sender remains blocked for Kee-Suri Korea (`customer_email_attachment_ready=false`)
- Owner-review email may attach the fixed watermarked `105936` bottom CID only (`owner_review_email_attachment_ready=true`)
- Bottom-shot rotation variants may still be explored before locking a single production asset

**Higher levels remain NOT_APPROVED:** `PRODUCTION_IMAGE_ASSET`, `PRODUCTION_PROMPT_DEFAULT`, `SCHEDULED_SLOT_READY`.

**Do not skip to `PROMOTE_SCHEDULED_SLOT_ATTACHMENT` without completing intermediate gates.**

---

## 5. Required production asset checks

All checks below must **PASS** before `PROMOTE_PRODUCTION_IMAGE_ASSET` or higher. For `PROMOTE_PROMPT_DIRECTION_ONLY`, creative checks inform prompt docs; asset-specific checks may be marked N/A until a production asset candidate exists.

### 5.1 Identity and tone

| # | Check | PASS criteria |
|---|-------|---------------|
| 1 | Face identity stable against Asset 01 | Same Kee-Suri character family — not a different person |
| 2 | Age impression | Mid-to-late 30s modern attractive — not teen, not 50+ matron |
| 3 | Hair and glasses | Short bob and thin glasses preserved |
| 4 | Motherly / matronly drift | **FAIL if present** — no older guardian / caring-mother tone |
| 5 | Lounge / sexualized / cheap fantasy | **FAIL if present** — no hostess, idol fan-service, submissive secretary tropes |

### 5.2 Wardrobe

| # | Check | PASS criteria |
|---|-------|---------------|
| 6 | Premium off-duty luxury visible | Silk-knit, quality skirt, premium accessories — magnetic but tasteful |
| 7 | Not plain office casual | **FAIL** if reads as 시장 옷 / 평상복 / mall basics |
| 8 | Not market clothes / cheap mall fashion | **FAIL** if outfit cheaper/weaker than business briefing wardrobe |
| 9 | Wardrobe justifies bottom-shot placement | Emotional lock-in value clear — not "leftover briefing frame" |

### 5.3 Pose, expression, gesture

| # | Check | PASS criteria |
|---|-------|---------------|
| 10 | Natural small farewell gesture | Calm hand farewell — emotional close |
| 11 | No finger heart / aegyo | **FAIL** if cute-idol gesture present |
| 12 | Fresh composed smile / 싱그러운 미소 | Present — not stern, not motherly smile |

### 5.4 Scene and artifacts

| # | Check | PASS criteria |
|---|-------|---------------|
| 13 | CEO wood-door background visible | Fixed entrance continuity |
| 14 | No tablet | **FAIL** if tablet or command-center prop present |
| 15 | No text/logo/UI artifacts | **FAIL** if legible signage, watermarks, UI chrome |

### 5.5 Delivery surface fit

| # | Check | PASS criteria |
|---|-------|---------------|
| 16 | Works at email thumbnail size | Face and gesture readable at small crop |
| 17 | Works in blog/mobile preview crop | Knee-up/3/4 framing survives common aspect crops |
| 18 | Does not conflict with business briefing identity | Bottom-shot complements — does not contradict — Wardrobe v4 top-shot Kee-Suri |

---

## 6. Required technical checks

Required before `PROMOTE_PRODUCTION_IMAGE_ASSET` or higher. Record evidence in §8 decision table.

| # | Check | Requirement |
|---|-------|-------------|
| T1 | Exact source path | Document full path at promotion time — today: `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg` (QA only) |
| T2 | Image dimensions | Record width × height px |
| T3 | File size | Record bytes / KB — within email/CDN budget if attaching |
| T4 | Format | JPEG or approved WebP — document color profile if relevant |
| T5 | Crop safety | Verify safe crop regions for email top/bottom slots |
| T6 | Compression behavior | Verify no visible artifacting at delivery compression level |
| T7 | Static asset destination | **Must not** be `output/` — propose path under `assets/keysuri/` only after approval |
| T8 | Naming convention | e.g. `image_keysuri_r6b_bottom_offduty_02C_production_v1.jpg` — document in promotion record |
| T9 | No `output/` path in production | Production code/config must not reference gitignored canary path |
| T10 | No scheduler/email wiring | Until explicit promotion decision — `scheduler_allowed` and send paths remain off |

### 6.1 Proposed production asset path (not created until approved)

```
assets/keysuri/production/r6b_bottom/
```

Exact filename and version suffix to be recorded in §9 promotion decision template. **Do not create or commit until promotion approved.**

---

## 7. Required content checks

| # | Check | Requirement |
|---|-------|-------------|
| C1 | Correct slot | **18:30 bottom-shot only** — `keysuri_korea_tech` |
| C2 | Not 12:30 global top-shot | **FAIL** if attached to `keysuri_global_tech` 12:30 slot |
| C3 | Not Today_Geenee | **FAIL** if used in `today_geenee` / `today_genie` content or email |
| C4 | Not Tomorrow_Geenee | **FAIL** if used in `tomorrow_geenee` / `tomorrow_genie` content or email |
| C5 | Not generic Genie image | **FAIL** if reused as Genie persona image |
| C6 | Emotional close function clear | Image reads as end-of-day farewell — not primary news hero |
| C7 | Placement after briefing body | Bottom-shot appears **after** briefing content — not as primary news image or headline visual |
| C8 | Top shot still present at 18:30 | When bottom-shot attaches, Korea slot retains separate top-shot per R6B plan |

---

## 8. Decision table

Use this table during promotion review. Mark each row **PASS**, **FAIL**, or **N/A** (for prompt-direction-only level).

### 8.1 Promotion level status (offduty_02C)

| Promotion level | Status |
|-----------------|--------|
| `PROMPT_DIRECTION_ONLY` | **APPROVED** — commit `07a98ac` |
| `STATIC_REFERENCE_FOR_DESIGN_ONLY` | Optional / not required |
| `PRODUCTION_IMAGE_ASSET` | **NOT_APPROVED** |
| `PRODUCTION_PROMPT_DEFAULT` | **NOT_APPROVED** |
| `SCHEDULED_SLOT_READY` | **NOT_APPROVED** |

### 8.2 Checklist rows

| Check | PASS/FAIL | Evidence | Required action if FAIL | Blocking level |
|-------|-----------|----------|-------------------------|----------------|
| PASS_DIRECTION recorded | PASS | `KEYSURI_R6B_OFFDUTY_02C_LUXURY_BOTTOM_SHOT_CANDIDATE_PACKAGE.md` §1A | Complete canary QA first | **BLOCK** all promotion |
| Promotion level selected | PASS | `PROMPT_DIRECTION_ONLY` — commit `07a98ac` | Record decision in decision doc / §9 | **BLOCK** asset/scheduler |
| Face identity vs Asset 01 | PASS | Operator QA §1A | Re-run canary or reject promotion | **BLOCK** asset |
| Age impression mid-to-late 30s | PASS | Operator QA | Adjust expression/wardrobe prompt | **BLOCK** asset |
| Short bob + thin glasses | PASS | Operator QA | Re-run with Asset 01 lock | **BLOCK** asset |
| Premium off-duty luxury wardrobe | PASS | Operator QA vs offduty_02B lesson | Upgrade wardrobe prompt | **BLOCK** asset |
| Not plain office casual | PASS | Operator QA | Reject — wardrobe too weak | **BLOCK** asset |
| Not motherly/matronly | PASS | Operator QA vs offduty_01 lesson | Reject — expression drift | **BLOCK** asset |
| Not lounge/sexualized/cheap fantasy | PASS | R6B plan §boundaries | Reject — tone violation | **BLOCK** asset |
| Natural farewell gesture | PASS | Operator QA | Re-run gesture prompt | **BLOCK** asset |
| No finger heart / aegyo | PASS | Operator QA | Reject gesture | **BLOCK** asset |
| CEO wood-door background | PASS | Operator QA | Fix background lock | **BLOCK** asset |
| No tablet | PASS | Operator QA | Re-run without tablet prop | **BLOCK** asset |
| No text/logo/UI artifacts | PASS | Visual inspection | Re-run or retouch | **BLOCK** asset |
| Email thumbnail readable | N/A | Not tested for QA JPG | Test before asset promotion | **BLOCK** `PRODUCTION_IMAGE_ASSET` |
| Mobile/blog crop safe | N/A | Not tested for QA JPG | Test before asset promotion | **BLOCK** `PRODUCTION_IMAGE_ASSET` |
| No conflict with briefing identity | PASS | Operator rationale | Resolve identity tension | **BLOCK** asset |
| Slot = 18:30 Korea only | PASS | R6B plan §7; candidate §1 | Reject wrong-slot wiring | **BLOCK** all delivery |
| Not used for 12:30 global | PASS | Design rule | Remove from global pipeline | **BLOCK** |
| Not Today/Tomorrow_Geenee | PASS | `keysuri_image_api_gate.py` | Remove cross-program wiring | **BLOCK** |
| Emotional close function | PASS | Operator QA | Clarify prompt intent | **BLOCK** delivery |
| After briefing body placement | N/A | Not wired yet | Confirm in email template design | **BLOCK** `SCHEDULED_SLOT` |
| Source path documented | PASS | §2.1 above | Record path | **BLOCK** asset |
| Production path not `output/` | PASS | No production path yet | Copy to `assets/keysuri/production/` only after approval | **BLOCK** asset |
| `scheduler_allowed` unchanged | PASS | Contract = false | Do not flip without approval | **BLOCK** scheduler |
| `ready_for_scheduler` unchanged | PASS | Canary client = false | Do not flip without approval | **BLOCK** scheduler |
| No email send wired | PASS | No Kee-Suri orchestrator path | Do not connect SMTP | **BLOCK** delivery |
| Scheduler design doc committed | PASS | Commit `1b23bcf` | Commit scheduler doc first | **BLOCK** scheduler |
| Promotion decision recorded | PASS | `KEYSURI_R6B_OFFDUTY_02C_PROMPT_DIRECTION_ONLY_DECISION.md` — commit `07a98ac` | Complete §9 for higher levels only | **BLOCK** asset/scheduler above prompt-direction |
| `PRODUCTION_IMAGE_ASSET` approved | FAIL | Not approved | Complete §5–§7; separate decision | **BLOCK** asset |
| `PRODUCTION_PROMPT_DEFAULT` approved | FAIL | Not approved | Asset or stable prompt lock required | **BLOCK** default prompt |
| `SCHEDULED_SLOT_READY` approved | FAIL | Not approved | Scheduler + asset + gate required | **BLOCK** scheduler attachment |

**Current summary:** **`PROMPT_DIRECTION_ONLY` APPROVED** for `offduty_02C` (commit `07a98ac`). Creative direction checks **PASS**. Asset, delivery, and scheduler promotion levels remain **NOT_APPROVED** — **no production asset, no scheduler wiring, no email attachment approved.**

---

## 9. Promotion decision template

### 9.0 Recorded decision (offduty_02C)

**`PROMPT_DIRECTION_ONLY` is recorded** — see authoritative decision doc:

- `docs/keysuri/KEYSURI_R6B_OFFDUTY_02C_PROMPT_DIRECTION_ONLY_DECISION.md`
- Commit: `07a98ac`

| Field | Value |
|-------|-------|
| Decision | **PROMPT_DIRECTION_ONLY** |
| profile_id | `offduty_02C_luxury_knit_silk_skirt_farewell` |
| canary status | PASS_DIRECTION |
| production_asset | **false** |
| scheduler_ready | **false** |
| email_attachment_ready | **false** |
| asset path | **none** |
| scheduler impact | **none** |
| email impact | **none** |

Use the template below only when recording a **new or higher** promotion decision.

### 9.1 Template for future promotion decisions

```markdown
## R6B Promotion Decision Record

### Decision
- [ ] NOT_PROMOTED
- [x] PROMPT_DIRECTION_ONLY              ← offduty_02C recorded in 07a98ac
- [ ] PRODUCTION_ASSET
- [ ] PRODUCTION_PROMPT_DEFAULT
- [ ] SCHEDULED_SLOT_READY

### Fields
| Field | Value |
|-------|-------|
| approved_by | _[operator name]_ |
| date | _[YYYY-MM-DD KST]_ |
| profile_id | offduty_02C_luxury_knit_silk_skirt_farewell |
| source image | output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg |
| promotion level | _[from §4]_ |
| target slot | 18:30 bottom-shot |
| target program | keysuri_korea_tech |
| asset path | _[none until PRODUCTION_ASSET approved]_ |
| scheduler impact | _[none / describe]_ |
| email impact | _[none / describe]_ |
| rollback rule | See §10 |

### Checklist sign-off
- [ ] §5 production asset checks reviewed
- [ ] §6 technical checks recorded
- [ ] §7 content checks confirmed
- [ ] §8 decision table updated
- [ ] No output/ path in production config
```

### 9.2 Decision definitions

| Decision | Meaning |
|----------|---------|
| `NOT_PROMOTED` | PASS_DIRECTION only; no promotion decision recorded |
| `PROMPT_DIRECTION_ONLY` | Creative formula locked in docs/prompts; no committed asset — **offduty_02C recorded (`07a98ac`)** |
| `PRODUCTION_ASSET` | Image copied to committed `assets/keysuri/production/` path |
| `PRODUCTION_PROMPT_DEFAULT` | Profile becomes default generation template for 18:30 bottom-shot |
| `SCHEDULED_SLOT_READY` | Approved for scheduled generation/attachment when scheduler gate passes |

---

## 10. Rollback rule

If a promoted production bottom-shot asset later causes:

- **Identity drift** — face no longer reads as Kee-Suri vs Asset 01
- **Wardrobe degradation** — outfit reads plain, cheap, or weaker than briefing
- **Inappropriate tone** — motherly, sexualized, lounge, or Genie-confused framing

**Then:**

1. **Revert** to no bottom-shot attachment in email and in_app delivery
2. **Keep** text-only or top-shot-only operation for `keysuri_korea_tech` 18:30 slot
3. **Record** rollback in promotion decision template with date and reason
4. **Do not** auto-retry image generation on rollback — require new manual canary and promotion review
5. **Reset** promotion decision to `NOT_PROMOTED` or `PROMPT_DIRECTION_ONLY` until re-approved

Rollback does **not** require scheduler deletion if scheduler was never wired. If scheduler was wired, disable bottom-shot attachment flag before re-enabling slot.

---

## 11. Scheduler dependency

Scheduler wiring for Kee-Suri **cannot proceed** until all of the following are true:

| # | Prerequisite | Current status |
|---|--------------|----------------|
| 1 | Production promotion checklist exists | **This document** |
| 2 | Promotion decision at required level | **`PROMPT_DIRECTION_ONLY` only** — higher levels **NOT_APPROVED** |
| 3 | Schedule gate design documented | **Done** — `KEYSURI_SCHEDULER_STATE_AND_FUTURE_WIRING_DESIGN.md` (`1b23bcf`) |
| 4 | `keysuri_schedule_gate.py` implemented and tested | **Not started** |
| 5 | Weekend skip behavior tested | **Not started** |
| 6 | Korean public holiday skip behavior tested | **Not started** |
| 7 | Production asset path is not `output/` | **Not applicable** — no production asset yet |
| 8 | Explicit operator approval for scheduler wiring | **Not given** |
| 9 | `scheduler_allowed` flip explicitly approved | **Not given** |
| 10 | Bottom-shot `SKIP_NO_PRODUCTION_PROMOTION` gate active | **Design only** — not implemented |

**Minimum promotion for scheduler with bottom-shot:** `SCHEDULED_SLOT_READY` plus §8 all blocking checks PASS.

**Scheduler without bottom-shot** (text-only or top-shot-only) is a separate decision — not covered by this R6B checklist but still requires `KEYSURI_SCHEDULER_STATE_AND_FUTURE_WIRING_DESIGN.md` gates.

---

## 12. Recommended next steps

Execute in this order:

| Step | Action | Status |
|------|--------|--------|
| 1 | Commit this checklist | **Done** — `8c8b9a8` |
| 2 | Record `PROMPT_DIRECTION_ONLY` for `offduty_02C` | **Done** — `07a98ac` |
| 3 | Update this checklist to reflect prompt-direction decision | Pending operator request |
| 4 | Decide second PASS_DIRECTION candidate (other taste cluster) or `PRODUCTION_ASSET` review | Not started |
| 5 | If `PRODUCTION_ASSET` candidate — complete §6 technical checks on a **new** approved render (not necessarily the QA JPG) | Not started |
| 6 | If `SCHEDULED_SLOT_READY` — implement schedule gate first | Not started |
| 7 | Only after explicit approval — scheduler wiring | **Blocked** — `SCHEDULED_SLOT_READY` not approved |

**Do not implement scheduler or email attachment while only `PROMPT_DIRECTION_ONLY` is approved.**

---

## Appendix A — FAIL history context

Prior NOT_ACCEPTED canaries inform promotion checks:

| Profile | Failure lesson | Promotion implication |
|---------|----------------|----------------------|
| `offduty_01` | Motherly/matronly drift | Enforce checks #4, #12 |
| `offduty_02` | Identity/proportion drift (Asset 02 default) | Enforce Asset 01 priority, knee-up framing |
| `offduty_02B` | Plain wardrobe / 시장 옷 | Enforce checks #6–#8 |

`offduty_02C` resolved wardrobe and identity gates — sufficient for **PASS_DIRECTION**, not automatic **production asset** approval.

---

## Appendix B — Related commits

| Commit | Message |
|--------|---------|
| `07a98ac` | Record Kee-Suri R6B offduty_02C prompt-direction decision |
| `8c8b9a8` | Add Kee-Suri R6B production promotion checklist |
| `1b23bcf` | Document Kee-Suri scheduler state and future wiring design |
| `e9a54da` | Record Kee-Suri R6B offduty_02C PASS_DIRECTION |
| `02a68a8` | Add Kee-Suri R6B offduty_02C luxury candidate package |
