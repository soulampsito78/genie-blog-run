# KEYSURI Image Track R5 Closure Report

Status:
Closure report / documentation only / track ready to close

Scope:
Formal closure of the Kee-Suri **R5 image track** — manual canary infrastructure, visual QA outcomes, and accepted Wardrobe v4 direction.

Non-scope:

- production runtime wiring
- Scheduler changes
- Cloud Run/GCP changes
- default opt-in enablement
- live image generation in this closure step
- Today_Geenee image path changes
- Tomorrow_Geenee revival
- output artifact commits
- static/email asset promotion
- unrelated working tree cleanup

Aligned references:

- Manual opt-in canary runner: commit `2521f7e`
- R5F guarded outfit-structure path: commit `82a0d97`
- Wardrobe v4 rotation design: commit `fa6f592`
- Wardrobe v4 design note: `docs/keysuri/KEYSURI_WARDROBE_V4_STRUCTURE_VARIATION_DESIGN.md`
- R5B procedure: `docs/keysuri/KEYSURI_R5B_PRODUCTION_PREFLIGHT_AND_MANUAL_CANARY_PROCEDURE.md`
- Production wiring design: `docs/keysuri/KEYSURI_PRODUCTION_WIRING_DESIGN.md`

---

## 1. Executive Summary

The Kee-Suri **R5 image track** is **ready to close**.

R5 established guarded manual canary infrastructure, ran a structured sequence of wardrobe experiments, and reached a clear visual conclusion: **color-only variation and small accessory shifts do not produce acceptable wardrobe rotation**. Kee-Suri image variation works when **outfit structure, inner blouse detail, prop, hand pose, and seasonal mood change together** while identity stays fixed.

Three Wardrobe **v4 profiles** passed operator visual QA as **`PASS_DIRECTION`** candidates. Four earlier profiles failed or were not accepted. No Scheduler, GCP, or production wiring was enabled. Generated canary images remain **QA references only** under gitignored `output/`.

**Recommendation:** Close R5 after this report is committed. Any future production asset work belongs in a separate **R6** track focused on asset selection and final prompt packaging—not blind canary retries.

---

## 2. Scope and Non-Scope

### In scope (R5 delivered)

| Area | Outcome |
|------|---------|
| Manual opt-in canary runner with preflight gate | Committed (`2521f7e`) |
| Guarded one-live-call infrastructure | Committed (`82a0d97`) |
| R5D/R5E failure-history modules with regression tests | Committed (`82a0d97`) |
| R5F Wardrobe v4 structure-variation path | Committed (`82a0d97`, extended `fa6f592`) |
| Operator visual QA across v1, R5D, R5E, R5F v4 profiles | Complete |
| Wardrobe v4 design documentation | Committed (`fa6f592`) |
| Locked visual principles and production boundary | Documented here |

### Out of scope (explicitly not done in R5)

- Production resolver promotion of v4 profiles
- Scheduler / Cloud Run / GCP wiring
- Default wardrobe opt-in or automatic image API calls
- Committing generated JPGs to git
- Copying canary images to `static/email/` or production asset paths
- Today_Geenee or Tomorrow_Geenee integration
- Unrelated repository artifact cleanup

---

## 3. Commit Timeline

| Commit | Summary | Significance |
|--------|---------|--------------|
| `2521f7e` | Add Kee-Suri manual opt-in canary runner with preflight gate (R5B-II) | Offline preflight + guarded runner foundation |
| `82a0d97` | Add guarded Kee-Suri outfit-structure canary path (R5F) | One-live-call gate; R5D/R5E failure-history; R5F v4_01 accepted direction infrastructure |
| `fa6f592` | Update Kee-Suri Wardrobe v4 rotation design | v4_02/v4_03 PASS_DIRECTION metadata; seasonal rotation design; three-profile catalog |

Prior R5 design commits (reference only): R5A wardrobe resolver design, R5B preflight procedure, R5 production wiring design, profile lock.

---

## 4. Visual QA Timeline

Manual opt-in canaries were executed under guarded infrastructure: preflight → dry-run (`request_count=0`) → exactly one live call per approved target. Pipeline checks passed for all runs below; **operator visual QA** determined acceptance.

| Phase | Date (KST target) | Profile | Image (local QA ref) | Outcome |
|-------|-------------------|---------|-------------------|---------|
| v1 baseline | 2026-06-04 area | `profile_01_charcoal_ivory` | `keysuri_global_canary_20260605_082908.jpg` | **FAIL** — visual delta insufficient |
| v1 palette | 2026-06-05 area | `profile_03_graphite_champagne` | `keysuri_global_canary_20260605_084002.jpg` | **FAIL** — visible wardrobe delta insufficient |
| R5D v2 | 2026-06-06 area | `profile_v2_01_deep_navy_cream_silver` | `keysuri_global_canary_20260605_084858.jpg` | **NOT_ACCEPTED** |
| R5E v3 | 2026-06-07 area | `profile_v3_01_navy_tie_neck_secretary` | `keysuri_global_canary_20260605_085654.jpg` | **REVIEW_NOT_ACCEPTED** |
| R5F v4 structure break | 2026-06-08 | `profile_v4_01_cream_short_jacket_black_silk_inner` | `keysuri_global_canary_20260605_090150.jpg` | **PASS_DIRECTION** |
| v4 shopping-cart (fall/winter) | 2026-06-09 | `profile_v4_02_black_suit_silk_bow_blouse_clutch_folder` | `keysuri_global_canary_20260605_092556.jpg` | **PASS_DIRECTION** |
| v4 shopping-cart (spring/summer) | 2026-06-10 | `profile_v4_03_summer_ivory_jacket_cool_beige_inner_thin_folder` | `keysuri_global_canary_20260605_092930.jpg` | **PASS_DIRECTION** |

Pre-v4 baseline comparison reference: `keysuri_global_canary_20260604_221233.jpg`

All images above live under `output/keysuri_preview/image_canary/` and are **gitignored**. They are **not production assets**.

---

## 5. Failure Analysis

### Why v1 color-only profiles failed

**Profiles:** `profile_01_charcoal_ivory`, `profile_03_graphite_champagne`

**Failure mode:** Pipeline and prompt injection succeeded, but rendered images retained the same **dark blazer + pale blouse** executive secretary uniform. Graphite/champagne wording collapsed visually into charcoal/ivory rendering.

**Lesson:** **Color-only wardrobe variation is insufficient** when structure, prop, and pose remain locked.

### Why R5D v2 failed (`NOT_ACCEPTED`)

**Profile:** `profile_v2_01_deep_navy_cream_silver`

**Failure mode:** Deep navy / cream / brooch prompt language still rendered as **dark blazer + pale blouse**. Accessory and hue naming did not change the dominant silhouette.

**Lesson:** Renaming garments within the blazer-blouse template does not guarantee visible structure delta.

### Why R5E v3 was not accepted (`REVIEW_NOT_ACCEPTED`)

**Profile:** `profile_v3_01_navy_tie_neck_secretary`

**Partial success:** Tie-neck detail appeared.

**Failure mode:** Overall image remained too close to **dark blazer + pale blouse + tablet-like prop** pattern. Folder swap alone was insufficient when upper structure stayed in the same family.

**Lesson:** A single neckline or accessory detail cannot carry the full variation burden.

### Cross-cutting failure pattern

| Attempt type | Result |
|--------------|--------|
| Color shift only | Failed |
| Small accessory as sole delta (brooch, watch) | Failed |
| Prompt wording without structural garment change | Failed |
| Tablet-at-waist as default prop anchor | Failed to break repetition |
| Structure + inner blouse + prop + pose together | **Succeeded (v4)** |

---

## 6. Accepted Wardrobe v4 Direction

Wardrobe **v4** is the **accepted visual direction** for Kee-Suri image rotation. Three profiles hold `PASS_DIRECTION` status in the R5F manual canary catalog.

| Profile | Seasonal band | Dominant structure | Key differentiator | QA reference image |
|---------|---------------|-------------------|--------------------|--------------------|
| `profile_v4_01_cream_short_jacket_black_silk_inner` | All-season | Cream structured short jacket + black silk inner | Broke dark blazer / pale blouse / tablet structure | `keysuri_global_canary_20260605_090150.jpg` |
| `profile_v4_02_black_suit_silk_bow_blouse_clutch_folder` | Fall/winter | Black tailored suit + ivory bow/tie-neck blouse | Visible bow blouse + clutch folder; heavier mood | `keysuri_global_canary_20260605_092556.jpg` |
| `profile_v4_03_summer_ivory_jacket_cool_beige_inner_thin_folder` | Spring/summer | Ivory lightweight short/3-4 sleeve jacket + cool beige inner | Lighter seasonal styling + thin light folder | `keysuri_global_canary_20260605_092930.jpg` |

**Color/set roulette rule (from Wardrobe v4 design):** Rotating outfit sets is valid **only when structure, inner blouse, prop, and hand pose vary together**—not when hue shifts within the same blazer-blouse-tablet template.

---

## 7. Locked Principles

These principles are **locked** for any future Kee-Suri image work building on R5 outcomes:

1. **Use reference image for identity only, not outfit cloning.** Face, short bob, thin glasses, and refined Korean private AI tech secretary identity — not reference outfit, pose, or composition.

2. **Avoid color-only wardrobe variation.** Charcoal → graphite → navy → champagne shifts within the same silhouette are insufficient.

3. **Avoid dark blazer + pale blouse + tablet repetition.** This uniform is the failed baseline; explicit anti-repeat blocks are required in prompt design.

4. **Prefer large visible garment structure changes.** Dominant upper garment, inner layer visibility, and silhouette must read differently at a glance.

5. **Prop and hand pose must vary with outfit.** Folder vs tablet, desk vs side grip, and natural hand pose are part of the wardrobe story—not optional extras.

6. **Seasonal wardrobe is a first-class axis.** Lightweight ivory/cool-beige jackets (spring/summer) and heavier black-suit setups (fall/winter) are valid when coordinated with structure and prop changes.

7. **Same identity must not mean same image.** Kee-Suri identity is fixed; outfit structure, prop, hand pose, and composition must not clone prior hero frames.

8. **PASS_DIRECTION images are QA references, not production assets.** Canary JPGs under `output/` must not be committed, staged, or copied to production paths without a separate R6 decision and QA cycle.

9. **Tablet-at-waist pose should not be the default visual anchor.** Document folder, clutch-style folder, or thin notebook are preferred props when breaking the old uniform.

---

## 8. Production Boundary

R5 **does not enable production**. The following boundaries remain in force after track closure:

| Boundary | State |
|----------|-------|
| Scheduler / GCP / Cloud Run / production wiring | **Unchanged** — not authorized by R5 |
| Default opt-in / automatic image API | **Disabled** — manual approval + one-live-call gate required |
| Generated images in git | **Gitignored** under `output/` — never committed in R5 |
| R5F / Wardrobe v4 path | **Guarded manual one-call only** — `GENIE_KEYSURI_R5F_STRUCTURE_VARIATION=1` + full approval env |
| v4 profiles in catalog | **Accepted direction candidates** — not automatic production publication |
| v1 production resolver / default prompt builder | **Unchanged** by R5 commits |
| R5D / R5E modules | **Failure-history only** — `NOT_ACCEPTED` / `REVIEW_NOT_ACCEPTED` for regression |

Promoting Wardrobe v4 to daily seed rotation, email/static assets, or Scheduler-bound generation requires a **separate track** with its own design review and QA—not R5 closure alone.

---

## 9. Remaining Risks

Even with accepted v4 directions, the following risks remain if work proceeds toward production assets without additional QA:

| Risk | Description |
|------|-------------|
| **Identity drift** | Outfit variation becomes so broad that Kee-Suri reads as a different woman with similar clothes only |
| **Dark suit collapse** | v4_02-style black suit variants revert to baseline dark blazer + plain pale blouse unless bow blouse and clutch prop stay visually strong |
| **Summer showroom drift** | v4_03-style lightweight jackets drift into department-store or fashion-editorial styling instead of premium private secretary briefing |
| **Prop disappearance** | Folder/notebook prop weakens or morphs into tablet-like shapes if not strongly prompted and visually verified |
| **Tablet reintroduction** | Tablet-at-waist pose re-enters as default hand anchor under ambiguous prompts |
| **Premature production use** | PASS_DIRECTION QA JPGs copied to `static/email/` or production paths without R6 asset selection and final QA |

These risks are manageable with continued operator visual QA and explicit prompt guard blocks—they are not resolved by R5 infrastructure alone.

---

## 10. Next-Step Recommendation

### A. Close R5 image track

**Recommended now.** R5 objectives are met:

- Guarded manual canary infrastructure exists and is tested
- Visual QA produced clear pass/fail outcomes
- Wardrobe v4 direction is documented and cataloged
- Production boundary is explicit and unchanged

Commit this closure report, then mark the R5 image track **closed**.

### B. R6 (later, if needed) — production asset selection only

If production Kee-Suri images are needed, start **R6** as a separate track focused on:

- Final prompt packaging from accepted v4 profiles
- Operator-selected production asset candidates (not blind canary retries)
- Explicit QA before any `static/email/` or publication path
- Resolver or wiring changes only after separate design approval

R6 must **not** repeat open-ended canary experimentation already completed in R5.

### C. Unrelated working tree cleanup

PDFs, HTML previews, unrelated untracked scripts, and modified `README.md` in the working tree are **out of R5 scope**. Handle cleanup in a separate maintenance pass—do not bundle with R5 closure.

---

## Closure Checklist

- [x] Manual canary infrastructure committed and tested
- [x] Visual QA complete with documented pass/fail outcomes
- [x] Wardrobe v4 PASS_DIRECTION catalog (v4_01, v4_02, v4_03)
- [x] Failure-history preserved (v1, R5D, R5E)
- [x] Production boundary unchanged
- [x] QA images remain gitignored references only
- [ ] **This closure report committed** (pending operator approval)
- [ ] **R5 track formally marked closed** (after report commit)

---

## Summary

R5 proved that Kee-Suri wardrobe rotation requires **structure-level change**, not palette roulette. Three Wardrobe v4 profiles are accepted **`PASS_DIRECTION`** references. Four earlier approaches failed because they preserved the **dark blazer + pale blouse + tablet** visual anchor. The track delivered guarded infrastructure and design documentation without enabling production. **Close R5; defer production asset work to R6 if needed.**
