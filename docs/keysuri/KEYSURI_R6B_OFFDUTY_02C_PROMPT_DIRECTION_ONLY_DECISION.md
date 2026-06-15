# Kee-Suri R6B — offduty_02C PROMPT_DIRECTION_ONLY Decision Record

Status:
**Decision recorded** / owner-review fixed fallback amendment / no customer or scheduler production wiring

Candidate:
`offduty_02C_luxury_knit_silk_skirt_farewell`

Related documents:

- `docs/keysuri/KEYSURI_R6B_PRODUCTION_PROMOTION_CHECKLIST.md` — promotion gate (commit `8c8b9a8`)
- `docs/keysuri/KEYSURI_SCHEDULER_STATE_AND_FUTURE_WIRING_DESIGN.md` — scheduler state (commit `1b23bcf`)
- `docs/keysuri/KEYSURI_R6B_OFFDUTY_02C_LUXURY_BOTTOM_SHOT_CANDIDATE_PACKAGE.md` — PASS_DIRECTION canary record
- `docs/keysuri/KEYSURI_R6B_BOTTOM_SHOT_EMOTIONAL_LOCKIN_PLAN.md` — R6B slot and creative rules

Non-scope:

- live image generation
- customer production asset approval
- Scheduler / GCP / Cloud Run changes
- customer email attachment
- scheduler variation generation
- production prompt default
- enabling `KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED`
- copying QA JPG to `static/email/` or `assets/keysuri/production/`
- Today_Geenee / Tomorrow_Geenee paths
- Global top-shot or Korea top-shot reuse

---

## 1. Decision summary

| Field | Value |
|-------|-------|
| **decision** | **PROMPT_DIRECTION_ONLY** |
| **profile_id** | `offduty_02C_luxury_knit_silk_skirt_farewell` |
| **source image** | `keysuri_global_canary_20260605_105936.jpg` |
| **source path (local QA)** | `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg` |
| **canary status** | **PASS_DIRECTION** |
| **reference used** | Asset 01 primary — `assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png` |
| **target slot (design intent)** | 18:30 bottom-shot — `keysuri_korea_tech` |
| **production_asset** | **false** |
| **scheduler_ready** | **false** |
| **owner_review_email_attachment_ready** | **true** — fixed watermarked `105936` only |
| **customer_email_attachment_ready** | **false** |
| **scheduler_variation_ready** | **false** |
| **production_prompt_default** | **false** |
| **generated_variation_allowed** | **false** |
| **KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED** | **false** |
| **role** | `korea_bottom only` |
| **fixed asset id** | `keysuri_korea_bottom_20260605_105936` |
| **fixed watermarked GCS object** | `assets/keysuri/korea_bottom/keysuri_global_canary_20260605_105936_mirai_on_watermarked.jpg` |
| **decision date** | 2026-06-05 (KST) |
| **approved_by** | Operator / product owner (prompt-direction lock) |

**One-line summary:** `offduty_02C` is accepted as prompt direction, and `105936` is the reference asset for that direction. The fixed watermarked `105936` file is approved only as a temporary `korea_bottom` fallback CID in KeeSuri Korea owner-review email. It is **not** the permanent fixed bottom image, customer-delivery-ready, variation-ready, scheduler-ready, global-usable, Korea-top-usable, or a production prompt default.

---

## 2. What is approved

The following creative formula is **approved for prompt steering** in future R6B bottom-shot canaries and documentation:

| Element | Approved direction |
|---------|-------------------|
| Identity priority | **Asset 01** — face/identity family anchor |
| Framing | **Knee-up or 3/4 body** — face clearly visible; not full-body default |
| Background | **CEO/chairman wood-door entrance** — fixed emotional continuity |
| Wardrobe tier | **Premium off-duty luxury** |
| Wardrobe cues | Silk-knit top, satin/silk-blend skirt, premium mini handbag, delicate jewelry |
| Expression | **Fresh composed smile** / **싱그러운 미소** |
| Gesture | **Small natural farewell** — emotional lock-in close |
| Props | **No tablet** |
| Slot role | **18:30 bottom-shot emotional closing** — end-of-day farewell after briefing body |

This approval covers **how to prompt** future generations. It also records one fixed owner-review-only fallback allowance:

| Allowance | Boundary |
|-----------|----------|
| Direction reference | `105936` anchors offduty_02C identity, wardrobe, mood, and wooden-door farewell direction |
| Fixed owner-review bottom CID | Watermarked `keysuri_korea_bottom_20260605_105936` may attach only as temporary fallback to `keysuri_korea_tech` owner-review email |
| Variation gate | `KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED=false` by default |
| Customer delivery | **Not approved** |
| Scheduler generation | **Not approved** |
| Per-run variation | **Not approved** |
| Production prompt default | **Not approved** |
| Role reuse | **Blocked** outside `korea_bottom only` |

---

## 3. What is not approved

The following remain **explicitly not approved**:

| Item | Status |
|------|--------|
| Generated QA JPG as production asset | **NOT approved** |
| Commit `output/` JPG to git | **NOT approved** |
| Copy QA JPG to `static/email/` | **NOT approved** |
| Attach QA JPG to customer production email | **NOT approved** |
| Use fixed `105936` in customer email | **NOT approved** |
| Schedule automatic bottom-shot image generation | **NOT approved** |
| Generate offduty_02C variations per run | **NOT approved** |
| Set `KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED=true` | **NOT approved** |
| Flip `scheduler_allowed` in image provider contract | **NOT approved** |
| Flip `ready_for_scheduler` in canary client | **NOT approved** |
| Mark `SCHEDULED_SLOT_READY` | **NOT approved** |
| Use for 12:30 global top-shot (`keysuri_global_tech`) | **NOT approved** |
| Use for Today_Geenee (`today_geenee` / `today_genie`) | **NOT approved** |
| Use for Tomorrow_Geenee (`tomorrow_geenee` / `tomorrow_genie`) | **NOT approved** |
| Use as generic Genie persona image | **NOT approved** |
| `PROMOTE_PRODUCTION_IMAGE_ASSET` | **NOT approved** |
| `PROMOTE_PRODUCTION_PROMPT_DEFAULT` | **NOT approved** |
| `PROMOTE_SCHEDULED_SLOT_ATTACHMENT` | **NOT approved** |

---

## 4. Why not production asset yet

`offduty_02C` achieved **PASS_DIRECTION** — the first accepted R6B bottom-shot creative direction. It has **not** met the bar for production asset promotion.

| Reason | Detail |
|--------|--------|
| First accepted direction only | Single canary PASS — repeatability across runs not yet proven |
| Static asset behavior not customer-validated | Owner-review placement is allowed, but customer email/mobile/blog production behavior is not approved |
| Production asset path not selected | No approved path under `assets/keysuri/production/` |
| Scheduler pipeline not wired | Kee-Suri has no active production scheduler (commit `1b23bcf`) |
| Customer email pipeline blocked | Korea customer delivery remains blocked; owner-review email is the only attachment allowance |
| Promotion checklist gate | `KEYSURI_R6B_PRODUCTION_PROMOTION_CHECKLIST.md` exists (`8c8b9a8`) but has **not** approved asset-level promotion |
| Correct next level | **PROMPT_DIRECTION_ONLY** — not `PRODUCTION_ASSET` |

Production asset promotion requires a **separate future decision** with full §5–§7 checks from the promotion checklist.

---

## 5. Prompt direction lock

### 5.1 Canonical direction string

Use this as the reusable prompt direction anchor for future R6B bottom-shot candidates:

```
premium off-duty luxury Kee-Suri bottom-shot, identity-first knee-up/3/4 composition,
CEO wood-door background, silk-knit and satin skirt styling, premium mini handbag,
delicate jewelry, fresh composed smile, small natural farewell gesture.
```

### 5.2 Prompt composition notes

| Layer | Lock |
|-------|------|
| Identity | Asset 01 reference — short bob, thin glasses, refined Korean Kee-Suri |
| Framing | Knee-up or 3/4 — face clearly visible; avoid full-body default |
| Background | Fixed CEO/chairman wood-door entrance — do not roulette background |
| Wardrobe | Premium off-duty luxury — above plain office casual floor |
| Expression | Fresh composed smile — not motherly, not stern |
| Gesture | Small natural hand farewell — no finger heart, no aegyo |
| Slot | 18:30 emotional close — not primary news hero |

### 5.3 What this lock does not do

- Does **not** freeze a single wardrobe outfit for all future days
- Does **not** prevent rotation across taste clusters (per R6B plan §9)
- Does **not** authorize copying the QA JPG into prompts as a production reference image path

---

## 6. Required future use

### 6.1 Use offduty_02C as

| Role | Detail |
|------|--------|
| Direction reference | Baseline creative formula for new R6B canaries |
| Wardrobe quality floor | Outfits must meet or exceed offduty_02C luxury tier — not plain knit/skirt |
| Anti-plain-clothes benchmark | Reject candidates that read as 시장 옷 / 평상복 (offduty_02B lesson) |
| Emotional lock-in benchmark | Farewell gesture + fresh smile + premium off-duty tone |

### 6.2 Do not use offduty_02C as

| Forbidden role | Detail |
|----------------|--------|
| Production JPG | QA image under `output/` — gitignored |
| Fixed static asset | No committed file in `assets/keysuri/production/` |
| Scheduler default | No auto-generation profile binding |
| Email attachment | No SMTP/in_app image from this path |
| 12:30 global top-shot | Wrong slot |
| Genie program image | Today/Tomorrow_Geenee forbidden |

---

## 7. QA cautions carried forward

Lessons from NOT_ACCEPTED canaries and PASS_DIRECTION validation — apply to all future R6B candidates:

| Caution | Source lesson |
|---------|---------------|
| Avoid market clothes / cheap mall fashion | offduty_02B NOT_ACCEPTED — plain wardrobe |
| Avoid plain office casual | offduty_02B — charm dropped vs briefing |
| Avoid motherly / matronly tone | offduty_01 NOT_ACCEPTED |
| Avoid full-body identity drift | offduty_02 NOT_ACCEPTED — Asset 02 default risk |
| Avoid finger-heart / aegyo gesture | R6B plan boundaries |
| Avoid lounge / glamour / cheap fantasy | R6B plan §boundaries — tasteful premium only |
| Avoid using PASS_DIRECTION image directly | QA JPG is local reference — not production input path |
| Identity gate before wardrobe gate | Face must read as Kee-Suri before accepting outfit |
| Asset 01 primary — not Asset 02 default | Identity anchor for knee-up/3/4 framing |

---

## 8. Future promotion path

To promote beyond **PROMPT_DIRECTION_ONLY** and the fixed owner-review-only `105936` fallback allowance, a **separate decision** must explicitly approve:

| Requirement | Detail |
|-------------|--------|
| Source image or regenerated candidate | May require new canary — not necessarily this QA JPG |
| Exact production asset path | Under `assets/keysuri/production/r6b_bottom/` — not `output/` |
| Crop and thumbnail behavior | Validated at email and mobile preview sizes |
| Static/email placement | After briefing body — bottom slot only |
| Customer delivery policy | Separate approval required before any customer email attachment |
| Variation policy | Separate approval required before generated offduty_02C variations |
| Runtime gate | `KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED=true` only after explicit approval |
| 18:30 slot use | `keysuri_korea_tech` only — unless separately approved |
| Rollback rule | Per `KEYSURI_R6B_PRODUCTION_PROMOTION_CHECKLIST.md` §10 |
| Scheduler dependency | Schedule gate implemented and tested (`keysuri_schedule_gate.py`) |
| Holiday/weekend skip | Tested before any scheduled attachment |
| Promotion checklist sign-off | §8 decision table all blocking checks PASS |
| Explicit operator approval | Record in promotion checklist §9 template |

**Minimum level for scheduled bottom-shot attachment:** `SCHEDULED_SLOT_READY` — **not approved today**.

---

## 9. Decision table

Promotion levels from `KEYSURI_R6B_PRODUCTION_PROMOTION_CHECKLIST.md` §4:

| Promotion level | Status | Notes |
|-----------------|--------|-------|
| **PROMPT_DIRECTION_ONLY** | **APPROVED** | This document — creative formula locked |
| **OWNER_REVIEW_EMAIL_FIXED_ASSET** | **APPROVED** | Temporary fixed watermarked `105936` fallback for `keysuri_korea_tech` owner-review bottom CID only |
| **GENERATED_BOTTOM_VARIATION_GATE** | **NOT_APPROVED** | Future per-run offduty_02C variation mode; default false |
| **STATIC_REFERENCE_FOR_DESIGN_ONLY** | Optional / not required | May commit design reference later — not needed now |
| **PRODUCTION_IMAGE_ASSET** | **NOT_APPROVED** | No committed asset path; QA JPG not promoted |
| **PRODUCTION_PROMPT_DEFAULT** | **NOT_APPROVED** | No default generation profile binding |
| **SCHEDULED_SLOT_READY** | **NOT_APPROVED** | No scheduler; no email attachment |

### 9.1 Operational flags (unchanged)

| Flag | Value |
|------|-------|
| `scheduler_allowed` | **false** |
| `ready_for_scheduler` | **false** |
| `production_auto_call_allowed` | **false** |
| `auto_send_after_timeout_enabled` | **false** (registry) |
| `image_attachment_enabled` | **false** (registry) |
| `owner_review_email_attachment_ready` | **true** — fixed `105936` Korea bottom only |
| `customer_email_attachment_ready` | **false** |
| `scheduler_variation_ready` | **false** |
| `production_prompt_default` | **false** |
| `generated_variation_allowed` | **false** |
| `KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED` | **false** |
| `role` | `korea_bottom only` |

---

## 10. Recommended next steps

| Step | Action | Status |
|------|--------|--------|
| **A** | Commit this decision record | Pending operator request |
| **B** | Decide whether to create a second PASS_DIRECTION candidate from another wardrobe taste cluster | Optional — broadens rotation before asset lock |
| **C** | Do not implement scheduler, generated variation, or customer email attachment | **Hold** until higher promotion level approved |

**Do not proceed to scheduler wiring, variation generation, or customer email attachment before explicit asset-promotion and delivery decisions.**

---

## Appendix A — Decision lineage

| Commit | Document / action |
|--------|-------------------|
| `e9a54da` | Record Kee-Suri R6B offduty_02C PASS_DIRECTION |
| `02a68a8` | Add Kee-Suri R6B offduty_02C luxury candidate package |
| `1b23bcf` | Document Kee-Suri scheduler state and future wiring design |
| `8c8b9a8` | Add Kee-Suri R6B production promotion checklist |
| _(pending)_ | Record Kee-Suri R6B offduty_02C prompt-direction decision — **this document** |

---

## Appendix B — Cross-reference to promotion checklist §9

This document fulfills the **PROMPT_DIRECTION_ONLY** branch of the promotion decision template in `KEYSURI_R6B_PRODUCTION_PROMOTION_CHECKLIST.md` §9.

| Template field | Value |
|----------------|-------|
| Decision | **PROMPT_DIRECTION_ONLY** |
| profile_id | `offduty_02C_luxury_knit_silk_skirt_farewell` |
| source image | `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg` |
| promotion level | `PROMOTE_PROMPT_DIRECTION_ONLY` |
| target slot | 18:30 bottom-shot |
| target program | `keysuri_korea_tech` |
| asset path | `assets/keysuri/korea_bottom/keysuri_global_canary_20260605_105936_mirai_on_watermarked.jpg` for temporary owner-review fallback only; **none** for customer production |
| scheduler impact | **none** |
| email impact | Owner-review bottom CID only; customer email **none** |
| rollback rule | Per promotion checklist §10 |
