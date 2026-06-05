# KEYSURI Wardrobe v4 Structure Variation Design

Status:
Design note only / no production wiring / no default opt-in

Scope:
Kee-Suri image wardrobe **structure variation** principles derived from R5F visual QA.

Non-scope:

- production runtime wiring
- Scheduler changes
- Cloud Run/GCP changes
- live image generation
- `.env` or approval enablement
- Today_Geenee image path
- Tomorrow_Geenee revival
- output artifact commits
- static/email asset promotion
- default wardrobe resolver changes

Aligned references:

- R5F guarded canary path: commit `82a0d97`
- R5B manual canary procedure: `docs/keysuri/KEYSURI_R5B_PRODUCTION_PREFLIGHT_AND_MANUAL_CANARY_PROCEDURE.md`
- Wardrobe seed resolver: `docs/keysuri/KEYSURI_WARDROBE_SEED_RESOLVER_DESIGN.md`
- Profile lock: `docs/keysuri/KEYSURI_IMAGE_PROFILE_LOCK.md`

---

## 1. Purpose

This document captures the **accepted R5F outfit-structure direction** for Kee-Suri wardrobe v4 and records why earlier canary attempts failed.

The goal is to prevent future work from repeating the same mistake: treating **small color or accessory shifts** as sufficient visual variation when the rendered image still reads as the same **dark blazer + pale blouse + tablet-at-waist** structure.

Wardrobe v4 is a **design and QA framework**, not a production enablement decision. It defines what “visible wardrobe delta” means for future manual canaries, resolver palette expansion, and operator review.

---

## 2. Visual QA History

Manual opt-in canaries were run under the guarded one-live-call infrastructure (R5B-II/III). Pipeline checks passed for all candidates below; **visual QA** determined acceptance.

| Track | Profile | Visual QA status | Operator outcome |
|-------|---------|------------------|------------------|
| v1 | `profile_01_charcoal_ivory` | FAIL | Pipeline PASS; visible delta insufficient |
| v1 | `profile_03_graphite_champagne` | FAIL | Pipeline PASS; visible wardrobe delta insufficient |
| R5D v2 | `profile_v2_01_deep_navy_cream_silver` | `NOT_ACCEPTED` | Structure delta failed |
| R5E v3 | `profile_v3_01_navy_tie_neck_secretary` | `REVIEW_NOT_ACCEPTED` | Tie-neck worked; overall structure too close |
| **R5F v4** | **`profile_v4_01_cream_short_jacket_black_silk_inner`** | **`PASS_DIRECTION`** | **Accepted direction** — broke dark blazer / pale blouse / tablet structure |
| **R5F v4** | **`profile_v4_02_black_suit_silk_bow_blouse_clutch_folder`** | **`PASS_DIRECTION`** | **Shopping-cart rotation** — black suit + bow blouse + clutch folder; heavier fall/winter mood |
| **R5F v4** | **`profile_v4_03_summer_ivory_jacket_cool_beige_inner_thin_folder`** | **`PASS_DIRECTION`** | **Seasonal variation** — lightweight ivory jacket + cool beige inner + thin light folder |

Reference canary images (local QA only — **not production assets**):

| Profile | QA reference image |
|---------|-------------------|
| v4_01 | `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_090150.jpg` |
| v4_02 | `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_092556.jpg` |
| v4_03 | `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_092930.jpg` |

Baseline comparison reference (pre-v4 uniform):

- `output/keysuri_preview/image_canary/keysuri_global_canary_20260604_221233.jpg`

---

## 3. Accepted R5F Directions (PASS_DIRECTION)

Three v4 profiles have passed operator visual QA under the guarded manual canary path. All remain **canary-only design references** — not production assets, not default opt-in.

### v4_01 — structure break (all-season reference)

**Profile ID:** `profile_v4_01_cream_short_jacket_black_silk_inner`

**Palette version:** `v4`

**Seed format:** `keysuri_daily|<KST-date>|v4|profile_v4_01_cream_short_jacket_black_silk_inner`

**Approved wardrobe clause (summary):**

- Cream structured short jacket as the **dominant upper garment**
- Black silk inner blouse clearly visible under the jacket
- Charcoal pencil skirt
- Slim black leather document folder on desk or held low at side
- Premium Korean executive secretary private AI tech briefing look

**Why this passed visual QA:**

The rendered look broke the repeated uniform. The upper silhouette changed from “dark blazer over pale blouse” to “cream structured jacket over black inner.” The hand prop changed from tablet-at-waist to folder-at-side or on-desk.

### v4_02 — fall/winter shopping-cart rotation

**Profile ID:** `profile_v4_02_black_suit_silk_bow_blouse_clutch_folder`

**Seed format:** `keysuri_daily|<KST-date>|v4|profile_v4_02_black_suit_silk_bow_blouse_clutch_folder`

**Approved wardrobe clause (summary):**

- Elegant black tailored suit
- Visible ivory silk bow blouse or tie-neck blouse at neck/chest
- Slim black pencil skirt; small silver earrings and slim watch
- Clutch-style black leather document folder held low at side
- No tablet in hands

**Why this passed visual QA:**

Confirmed Kee-Suri can rotate into a different executive secretary outfit — black suit with visible bow/tie-neck blouse detail and clutch folder — without collapsing to the old dark blazer + plain pale blouse + tablet structure. Mood reads heavier fall/winter than v4_01/v4_03.

### v4_03 — spring/summer seasonal variation

**Profile ID:** `profile_v4_03_summer_ivory_jacket_cool_beige_inner_thin_folder`

**Seed format:** `keysuri_daily|<KST-date>|v4|profile_v4_03_summer_ivory_jacket_cool_beige_inner_thin_folder`

**Approved wardrobe clause (summary):**

- Summer-appropriate ivory lightweight structured short-sleeve or three-quarter sleeve jacket
- Cool beige or pale champagne silk blouse
- Charcoal or muted taupe pencil skirt; slim silver watch and small earrings
- Thin light beige executive document folder or notebook held low at side
- Brighter summer daylight in premium private office briefing setting

**Why this passed visual QA:**

Confirmed seasonal wardrobe range: lighter, cleaner, and more summer-appropriate than the black suit v4_02, without reverting to the failed uniform or heavy winter styling.

### Shared prompt guard blocks (all PASS_DIRECTION v4 profiles)

- Same Kee-Suri identity, not same image
- Use reference for face/bob/glasses identity only — do not copy reference outfit
- Do not repeat dark blazer + plain pale blouse + tablet-at-waist structure
- Do not place a tablet in her hands
- Natural hand pose; premium private office briefing; not anchor/CEO/editorial/glamour

---

## 4. Failed Approaches and Why They Failed

### v1 color-only profiles (`profile_01`, `profile_03`)

**Attempt:** Charcoal/ivory and graphite/champagne palette shifts within the same blazer-and-blouse structure.

**Failure mode:** Pipeline and prompt injection worked, but rendered images still read as the same outfit family. **Color-only variation is insufficient** when structure, prop, and pose remain locked.

### R5D v2 — `profile_v2_01_deep_navy_cream_silver` (`NOT_ACCEPTED`)

**Attempt:** Deep navy tailored suit, warm cream silk blouse, small silver brooch.

**Failure mode:** Prompt described a different garment set, but output still rendered as **dark blazer + pale blouse**. Brooch and navy/cream wording did not produce a visible structure delta.

**Lesson:** Naming a “suit” or shifting hue within the blazer-blouse template does not guarantee a new silhouette.

### R5E v3 — `profile_v3_01_navy_tie_neck_secretary` (`REVIEW_NOT_ACCEPTED`)

**Attempt:** Deep navy fitted blazer, ivory tie-neck blouse with visible neck detail, document folder instead of tablet.

**Partial success:** Tie-neck detail appeared in output.

**Failure mode:** Overall image still too close to dark blazer + pale blouse + tablet-like prop pattern. Replacing tablet with folder alone was not enough when the upper structure stayed in the same family.

**Lesson:** A single neckline or accessory detail cannot carry the full variation burden.

---

## 5. Wardrobe v4 Principles

1. **Change outfit structure, not only color.** The dominant upper garment, inner layer visibility, and silhouette must read differently at a glance.
2. **Vary prop, hands, and composition together.** Folder vs tablet, desk vs waist grip, and natural hand pose are part of the wardrobe story—not optional extras.
3. **Identity continuity without image repetition.** Kee-Suri face, bob, glasses, and executive secretary role stay fixed; outfit and staging must not clone prior hero frames.
4. **Large visible garment changes over micro-accessories.** Jackets, blouse structure, skirt line, and dominant color blocks matter more than brooch or watch alone.
5. **Anti-repeat explicit in prompt.** Negative and positive blocks must forbid the failed uniform: dark blazer dominance, pale blouse template, tablet-at-waist.
6. **Canary-only until separate production decision.** PASS_DIRECTION means accepted creative direction for future design and QA—not automatic resolver or Scheduler promotion.
7. **Seasonal wardrobe is a first-class axis.** Lightweight ivory/cool-beige jackets (spring/summer) and heavier black-suit setups (fall/winter) are valid when structure, inner blouse, prop, and pose vary together—not color alone.

---

## 6. Approved Wardrobe Shopping-Cart Categories

Future v4 candidates should be composed from **structure-changing** combinations drawn from these categories. A valid profile should pick at least one dominant-structure change plus coordinated prop/pose variation—not a lone accessory swap.

| Category | Examples |
|----------|----------|
| Navy suit + white/cream blouse | Full suit reads; blouse contrast visible at collar—must not collapse to generic dark blazer template |
| Black suit + silk blouse | Black dominant suit with contrasting silk inner; inner layer must remain visibly distinct |
| Gray/charcoal dress setup | One-piece or dress-led silhouette instead of blazer + blouse stack |
| Ivory/cream jacket + dark skirt | **R5F pattern:** light structured jacket as dominant upper, dark lower block |
| Bow blouse / tie-neck blouse | Allowed only when paired with non-blazer dominant upper or clearly different silhouette |
| Small brooch / slim watch / small earrings | Secondary accents only—never the sole delta |
| Clutch-style document folder / tablet / thin notebook | Folder preferred when avoiding tablet repetition; prop must support hand pose change |

**R5F reference combinations (PASS_DIRECTION):**

| Profile | Dominant upper | Inner blouse | Skirt | Prop | Seasonal mood |
|---------|----------------|--------------|-------|------|---------------|
| v4_01 | Cream structured short jacket | Black silk inner | Charcoal pencil | Slim black leather folder | All-season structure break |
| v4_02 | Black tailored suit | Ivory bow / tie-neck silk | Black pencil | Clutch-style black folder | Fall/winter |
| v4_03 | Ivory lightweight short/3-4 sleeve jacket | Cool beige / pale champagne silk | Charcoal or muted taupe | Thin light beige folder/notebook | Spring/summer |

### Shopping-cart rotation table

| Season band | Example profile | Key structure | QA reference (local only) |
|-------------|-----------------|---------------|---------------------------|
| **Spring / summer** | v4_03 | Lightweight ivory jacket + cool beige inner + thin light folder | `keysuri_global_canary_20260605_092930.jpg` |
| **Fall / winter** | v4_02 | Black suit + visible bow/tie-neck blouse + clutch folder | `keysuri_global_canary_20260605_092556.jpg` |
| **All-season** | v4_01 | Cream jacket + black inner + no tablet | `keysuri_global_canary_20260605_090150.jpg` |

### Color/set roulette rule

**Color or set rotation is allowed only when outfit structure, inner blouse detail, prop, and hand pose vary together.**

Rotating charcoal → graphite → navy while keeping dark-blazer-over-pale-blouse with tablet-at-waist is **not** valid variation. Rotating cream jacket → black suit → summer ivory jacket **is** valid when each combination changes visible structure and prop/pose as a unit—as demonstrated by v4_01, v4_02, and v4_03.

---

## 7. Strong Rule — Same Identity Must Not Mean Same Image

| Rule | Requirement |
|------|-------------|
| Identity | Same Kee-Suri: face, short bob, thin glasses, mature professional secretary impression |
| Not same image | Outfit structure, prop, hand pose, and composition must vary together |
| Color-only variation | **Insufficient** as the primary strategy |
| Accessory-only variation | **Insufficient** as the primary strategy |
| Minimum bar | Operator must see a **large visible garment structure change** without identity drift |

**Operational phrasing (from R5F canary):**

> Same Kee-Suri identity, not same image.

---

## 8. R5F Production Boundary

The R5F canary path committed in `82a0d97` is **guarded manual infrastructure only**.

| Boundary | State |
|----------|-------|
| Accepted directions | v4_01, v4_02, v4_03 — all `PASS_DIRECTION` |
| Production asset | **No** — all generated JPGs under `output/` are **QA references only** |
| Default opt-in | **No** — v1 resolver and default prompt builder unchanged |
| Scheduler / GCP / production wiring | **No** — not authorized by R5F commit or shopping-cart canaries |
| Live call | Requires explicit approval env + `GENIE_KEYSURI_R5F_STRUCTURE_VARIATION=1` + one-live-call gate |
| R5D / R5E modules | Retained as `NOT_ACCEPTED` / `REVIEW_NOT_ACCEPTED` failure-history for regression only |

Promoting v4 to production resolver, daily seed rotation, or email/static assets requires a **separate** design decision and visual QA cycle—not this document alone.

---

## 9. Future Candidate Rules

When proposing `profile_v4_*` successors or expanding the v4 palette:

**Avoid:**

- Dark blazer + pale blouse repetition (even with renamed fabrics or “navy/charcoal/graphite” wording)
- Tablet-at-waist repetition
- Tiny accessory (brooch, watch, earrings) as the **sole** visual delta
- Prompt-only “variation” language without structural garment change
- Copying reference outfit, pose, or composition from prior hero images

**Prefer:**

- Large visible garment structure changes (jacket type, dominant upper color block, dress vs separates)
- Clearly visible inner layer under a different outer silhouette
- Prop changes that force natural hand pose updates (folder on desk, folder low at side)
- Explicit anti-uniform blocks in positive and negative prompt
- One manual call per approved candidate; no batch, no retry, no Scheduler

**Profile metadata convention (from R5F implementation):**

Each catalog entry should carry:

- `visual_qa_status`: `PASS_DIRECTION`, `NOT_ACCEPTED`, or `REVIEW_NOT_ACCEPTED`
- `visual_qa_reason`: operator-facing explanation of QA outcome

---

## 10. QA Checklist for Future Canaries

Use this checklist after a guarded manual one-live-call canary. Pipeline PASS alone is not sufficient.

### Preflight (offline)

- [ ] Correct profile id and seed format for palette version (`v4`)
- [ ] R5F override flag set only for v4 profiles; R5D/R5E not used as accepted paths
- [ ] Default production prompt unchanged while override runs
- [ ] Opt-in prompt differs from default prompt
- [ ] Production flags remain false; no Scheduler wiring implied
- [ ] Approval env matches date, program, profile, seed, operator ref

### Visual QA (operator)

- [ ] **Dominant upper garment** reads differently from baseline (not dark blazer template)
- [ ] **Inner blouse** visible and structurally distinct (e.g. black under cream jacket)
- [ ] **Skirt/lower block** coherent with executive secretary look
- [ ] **No tablet in hands** when anti-tablet rule applies
- [ ] **Prop** supports pose change (folder/clutch/notebook—not tablet-at-waist clone)
- [ ] **Hands** natural, not distorted
- [ ] **Identity** preserved: same Kee-Suri, not a different woman
- [ ] **Composition** not a near-duplicate of baseline hero frame
- [ ] **Overall:** structure delta visible at thumbnail glance—not only on close inspect

### Disposition

| Outcome | Action |
|---------|--------|
| `PASS_DIRECTION` | Record in design docs; may inform future palette design—not production auto-promote |
| `REVIEW_NOT_ACCEPTED` | Keep as failure-history; do not treat partial wins as accepted |
| `NOT_ACCEPTED` | Do not retry without new structure strategy; update catalog metadata |

### Post-QA hygiene

- [ ] Do not commit generated images under `output/`
- [ ] Do not copy canary JPGs to `static/email/` or production asset paths
- [ ] Do not enable default opt-in or Scheduler without separate approval

---

## Summary

Wardrobe v4 succeeds when **outfit structure, prop, hand pose, and composition vary together** while Kee-Suri identity stays constant. Three profiles — v4_01 (all-season structure break), v4_02 (fall/winter black suit rotation), and v4_03 (spring/summer lightweight rotation) — are **PASS_DIRECTION** references. All canary JPGs under `output/` remain QA references only, not production assets. Earlier v1 color shifts, R5D navy/cream/brooch, and R5E tie-neck attempts failed because the rendered uniform did not change enough. Future work should treat this document as the visual bar for structure and seasonal variation—not as production enablement.
