# KEYSURI Image Track — Current State Handoff

Status:
Handoff report / documentation only / no production wiring / no image API in this document

Purpose:
Let a **new chat or new developer** continue the Kee-Suri image track without repeated discovery questions.

Last updated:
After offduty_02 NOT_ACCEPTED visual QA — R6B framing strategy revision (documentation only)

Non-scope:

- live image generation
- production wiring
- working tree cleanup
- unrelated artifact commits

---

## 1. Executive Summary

The Kee-Suri image track has progressed through **R5 (closed)**, **R6 (full-body asset classification)**, and **R6B (bottom-shot emotional lock-in planning)**.

| Track | Status | Outcome |
|-------|--------|---------|
| **R5** | **Closed** | Wardrobe v4 business briefing direction accepted; guarded manual canary infrastructure committed |
| **R6** | **Planning complete** | Asset 02 classified `KEEP_AS_SILHOUETTE_REFERENCE`; full-body generation rules documented |
| **R6B** | **Planning complete** | 18:30-only bottom-shot slot defined; fixed CEO-door background + broad off-duty wardrobe rotation |

**Current state in one sentence:** Business briefing wardrobe (Wardrobe v4) is locked as direction; R6B canaries `offduty_01` and `offduty_02` **NOT_ACCEPTED**; R6B default framing is now **3/4 body or knee-up** with **Asset 01 identity priority** — not full-body-first.

**Next likely step:** **`offduty_02B_elegant_knit_kneeup_farewell`** — knee-up framing, Asset 01 primary reference, same gesture direction as offduty_02 → operator approval → one-live-call → visual QA. **Do not retry offduty_01 or offduty_02 full-body immediately.**

---

## 2. Committed Milestone Chain

| Commit | Summary |
|--------|---------|
| `2521f7e` | Add Kee-Suri manual opt-in canary runner with preflight gate |
| `82a0d97` | Add guarded Kee-Suri outfit-structure canary path (R5F) |
| `fa6f592` | Update Kee-Suri Wardrobe v4 rotation design |
| `844591e` | Add Kee-Suri Image Track R5 closure report |
| `bc78c4f` | Add Kee-Suri Image Track R6 full-body asset plan |
| `0c7a6f0` | Update Kee-Suri R6 full-body asset classification |
| `03c31a7` | Add Kee-Suri R6B bottom-shot emotional lock-in plan |
| `5819c11` | Add Kee-Suri R6B first bottom-shot candidate package |
| `2246c64` | Expand Kee-Suri R6B bottom-shot wardrobe rotation |

**Uncommitted QA:**

- R6B first canary `offduty_01` → `keysuri_global_canary_20260605_101845.jpg` — **NOT_ACCEPTED** (motherly/matronly drift)
- R6B second canary `offduty_02` → `keysuri_global_canary_20260605_103238.jpg` — **NOT_ACCEPTED** (identity/proportion drift; gesture PASS)

### Primary documentation index

| Document | Path |
|----------|------|
| R5 closure | `docs/keysuri/KEYSURI_IMAGE_TRACK_R5_CLOSURE_REPORT.md` |
| Wardrobe v4 design | `docs/keysuri/KEYSURI_WARDROBE_V4_STRUCTURE_VARIATION_DESIGN.md` |
| R6 full-body plan | `docs/keysuri/KEYSURI_IMAGE_TRACK_R6_FULL_BODY_ASSET_PLAN.md` |
| R6B bottom-shot plan | `docs/keysuri/KEYSURI_R6B_BOTTOM_SHOT_EMOTIONAL_LOCKIN_PLAN.md` |
| R5B preflight procedure | `docs/keysuri/KEYSURI_R5B_PRODUCTION_PREFLIGHT_AND_MANUAL_CANARY_PROCEDURE.md` |
| Visual asset guide | `assets/keysuri/README_KeeSuri_Visual_Asset_Guide.md` |

### Infrastructure (committed, guarded)

| Component | Path |
|-----------|------|
| Manual opt-in canary runner | `keysuri_manual_opt_in_canary_runner.py` |
| Manual canary preflight | `keysuri_manual_canary_preflight.py` |
| R5D failure history | `keysuri_r5d_manual_canary.py` |
| R5E failure history | `keysuri_r5e_manual_canary.py` |
| R5F v4 catalog | `keysuri_r5f_manual_canary.py` |
| Runner tests | `tests/test_keysuri_manual_opt_in_canary_runner.py` |
| Preflight tests | `tests/test_keysuri_manual_canary_preflight.py` |
| Run script | `scripts/run_keysuri_manual_opt_in_canary.py` |

---

## 3. Current Locked Decisions

These decisions are **not open for re-debate** unless operator explicitly reopens a track.

### Schedule-slot image rules

| Slot | Images | Mood | Wardrobe |
|------|--------|------|----------|
| **12:30 briefing** | **Top shot only** | Business briefing / tech signal / authority | Wardrobe v4 business only |
| **18:30 briefing** | **Top shot + bottom shot** | Top = authority; bottom = end-of-day lock-in | Top = v4; bottom = R6B off-duty |

### Image role split

| Layer | Role |
|-------|------|
| **Top shot** | Business briefing / professional authority |
| **Bottom shot** | Off-duty closing greeting / emotional lock-in — **18:30 only** |

### Bottom-shot scene and variation

| Fixed (do not roulette) | Variable (roulette here) |
|-------------------------|--------------------------|
| CEO/chairman office **wood-door entrance** | Outfit style, silhouette, fabric, color temperature |
| Wood-paneled executive wall | Season |
| Warm evening executive-floor light | Expression, gesture, prop |
| Kee-Suri identity | Emotional temperature (low / medium / warm) |
| Premium private AI secretary mood | Taste cluster (A–H) |
| Tasteful boundary | Posture variation |

### Explicit prohibitions

- **No broad background roulette** for bottom shot
- **No** cafe / home / lounge / street / hotel / nightlife drift
- **No** leaving-work mood or off-duty wardrobe at **12:30**
- **No** color-only wardrobe variation (R5 lesson)

---

## 4. Asset Role Split

### Asset 01 — primary identity / face family (R6B default attached reference)

**Path:** `assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png`

**Role:**

- Identity / face family anchor — short bob, thin glasses, refined Korean Kee-Suri impression
- **Primary attached reference** for R6B 3/4 body or knee-up bottom shots (updated after offduty_02 failure)
- Post-generation identity QA cross-check — **face identity gate must PASS first**

### Asset 02 — silhouette reference (R6 production track; optional R6B support)

**Path:** `assets/keysuri/reference/image_keysuri_asset_02_full_body.png`

**Classification:** `KEEP_AS_SILHOUETTE_REFERENCE` (commit `0c7a6f0`)

**R6 production full-body track:** Asset 02 supports full-length v4 wardrobe validation and production asset candidates — **separate from default R6B bottom-shot framing**.

**R6B optional role:** Silhouette/proportion support when lower-body framing is **explicitly operator-approved** — must not override Asset 01 face identity or force full-body composition.

**Asset 02 may support (when explicitly approved):**

- Standing silhouette hint
- Skirt length / leg line (partial at knee-up)
- Body posture baseline

**Forbidden transfer:**

- Charcoal suit, champagne blouse
- Tablet-at-waist pose
- Command-center / data-wall background
- Stiff briefing mood
- Overriding face identity
- Forcing full-body as default R6B framing

**Reference split:** One image per API call — attach **Asset 01** by default for R6B; Asset 02 only with explicit approval.

**Do not replace Asset 02 in repo.**

### Wardrobe v4 — business briefing

**Role:** Business briefing wardrobe structure **source of truth**

**Profiles:** `profile_v4_01`, `profile_v4_02`, `profile_v4_03` — see §6

**Scope:** Top/hero briefing images only — **narrow, trust-oriented**

### R6B bottom-shot wardrobe — off-duty lock-in

**Role:** Off-duty emotional lock-in wardrobe — **separate catalog from v4**

**Scope:** 18:30 bottom shot only — **broad, taste-oriented**

**Source:** `docs/keysuri/KEYSURI_R6B_BOTTOM_SHOT_EMOTIONAL_LOCKIN_PLAN.md` §9–§12

---

## 5. R5 Visual QA Outcomes

### Failed / not accepted

| Profile | Status | Lesson |
|---------|--------|--------|
| `profile_01_charcoal_ivory` | **FAIL** — visual delta insufficient | Color-only / minimal change |
| `profile_03_graphite_champagne` | **FAIL** — visual delta insufficient | Color-only / minimal change |
| `profile_v2_01_deep_navy_cream_silver` | **NOT_ACCEPTED** | R5D — structure still too close to failed anchor |
| `profile_v3_01_navy_tie_neck_secretary` | **REVIEW_NOT_ACCEPTED** | R5E — dark blazer + pale blouse + tablet pattern persisted |

Representative QA JPGs (gitignored, not committed):

- v1 fail: `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_082908.jpg` (approx.)
- R5D: `keysuri_global_canary_20260605_084858.jpg`
- R5E: `keysuri_global_canary_20260605_085654.jpg`

### Accepted PASS_DIRECTION (Wardrobe v4)

| Profile | Season | Structure summary | QA JPG (reference only) |
|---------|--------|-------------------|-------------------------|
| `profile_v4_01_cream_short_jacket_black_silk_inner` | All-season | Cream short jacket + black silk inner | `keysuri_global_canary_20260605_090150.jpg` |
| `profile_v4_02_black_suit_silk_bow_blouse_clutch_folder` | Fall/winter | Black suit + bow/tie-neck blouse + clutch folder | `keysuri_global_canary_20260605_092556.jpg` |
| `profile_v4_03_summer_ivory_jacket_cool_beige_inner_thin_folder` | Spring/summer | Ivory light jacket + cool beige inner + thin folder | `keysuri_global_canary_20260605_092930.jpg` |

### Core R5 lesson

**Color-only changes failed.** **Large outfit structure + inner blouse + prop + hand pose + seasonal mood variation works** — while Kee-Suri identity stays fixed.

R5D/R5E modules remain **failure-history only** for regression tests. Do not route new canaries through failed profiles without explicit operator override.

---

## 6. Wardrobe v4 Business Briefing Status

| Profile | Summary | Status |
|---------|---------|--------|
| **v4_01** | Cream jacket + black silk inner | **PASS_DIRECTION** — accepted all-season baseline |
| **v4_02** | Black suit + bow/tie-neck blouse + clutch folder | **PASS_DIRECTION** — heavier fall/winter mood |
| **v4_03** | Summer ivory/light jacket + cool beige inner + thin folder | **PASS_DIRECTION** — lighter spring/summer mood |

**Important boundaries:**

- Canary JPGs are **QA references only** — not production assets
- PASS_DIRECTION profiles are **accepted direction candidates** — not automatic production publication
- Images live under gitignored `output/keysuri_preview/image_canary/` — **do not commit**
- No tablet-at-waist as default prop pattern
- Same identity ≠ same image

---

## 7. R6 Full-Body Status

| Fact | Status |
|------|--------|
| Asset 02 file exists at correct path | Yes |
| Asset 02 is production asset | **No** |
| Asset 02 is wardrobe reference | **No** |
| Asset 02 is silhouette/proportion reference only | **Yes** — `KEEP_AS_SILHOUETTE_REFERENCE` |
| New full-body production images | Must be generated separately after prompt package + operator approval |
| Full-body generation extends v4 direction | Yes — do not invent parallel business wardrobe track |

R6 planning is **complete**. No production full-body image has been generated yet.

---

## 8. R6B Bottom-Shot System

### Purpose

- Emotional retention
- Daily familiarity
- Soft closing ritual (“오늘도 고생하셨습니다, 대표님” feeling without readable text)
- Reader lock-in through tasteful familiarity — not explicit romance

### Operating rules

| Rule | Value |
|------|-------|
| **Schedule** | **18:30 only** — never 12:30 |
| **Background** | Fixed CEO/chairman office wood-door entrance |
| **Variation axis** | Person-level only — outfit, expression, gesture, prop, season, emotional temperature |
| **Briefing wardrobe** | Wardrobe v4 — unchanged, separate layer |
| **Design pairing** | Background provides **authority**; wardrobe provides **intimacy** |

Customer desire is **intentionally used** but must remain **premium, tasteful, Kee-Suri-consistent** — no cheap girlfriend fantasy, lounge hostess, idol fan-service, or submissive secretary tropes.

### Taste clusters (A–H)

| ID | Name | Character |
|----|------|-----------|
| **A** | Soft Classic | Silk blouse + cardigan; safest lock-in |
| **B** | Elegant Office Casual | Knit + slim skirt; daily repeat-friendly |
| **C** | Cool Executive Off-Duty | Smoky blue + cardigan; composed premium |
| **D** | Feminine Minimal | Shirt dress + belt; clean approachable |
| **E** | Luxury Quiet | Cashmere + pencil skirt; mature restrained |
| **F** | Summer Light | Light cardigan + blouse; extra revealing-drift QA |
| **G** | Fall/Winter Warm | Camel cardigan / trench; cozy executive |
| **H** | Personal but Premium | Knit dress + trench; **higher drift risk — use carefully** |

### Emotional temperature and expression scale

**Expression rule:** Visible face = **fresh composed smile**, not **warm motherly smile**. Tone may carry warmth; expression must read **fresh, modern, attractive off-duty**.

| Level | Read | Use |
|-------|------|-----|
| **low** | Polite but **fresh** farewell; **restrained fresh smile** | Default-safe; high-drift clusters |
| **medium** | **Fresh composed smile**; gentle fresh eye contact; attractive off-duty presence | Standard 18:30 target |
| **warm** | More familiar **lively** farewell — **still fresh, not motherly** | **Sparingly** — never sexualized, submissive, or guardian-like |

### Bottom-shot draft profile catalog

| Profile ID | Cluster | Drift risk |
|------------|---------|------------|
| `offduty_01_soft_classic_cardigan_silk_blouse` | A | low — **NOT_ACCEPTED** (motherly/matronly drift) |
| `offduty_02_elegant_knit_slim_skirt` | B | low — **NOT_ACCEPTED** (identity drift; gesture PASS) |
| `offduty_02B_elegant_knit_kneeup_farewell` | B | low–medium — **next candidate** |
| `offduty_03_smoky_blue_blouse_ivory_cardigan` | C | low |
| `offduty_04_shirt_dress_thin_belt` | D | low–medium |
| `offduty_05_cashmere_knit_pencil_skirt` | E | low |
| `offduty_06_summer_light_cardigan_beige_skirt` | F | medium |
| `offduty_07_camel_cardigan_charcoal_knit` | G | low |
| `offduty_08_knit_dress_light_trench` | H | **high** |

Full spec per profile: `docs/keysuri/KEYSURI_R6B_BOTTOM_SHOT_EMOTIONAL_LOCKIN_PLAN.md` §12.

**R6B status:** Two canaries **NOT_ACCEPTED**. Default framing revised to **3/4 or knee-up**, **Asset 01 identity priority**. Next: **`offduty_02B_elegant_knit_kneeup_farewell`**.

### R6B offduty_01 first canary failure

| QA axis | Result |
|---------|--------|
| Background lock | PASS |
| Off-duty wardrobe concept | PARTIAL |
| No tablet | PASS |
| Identity / age / charm | FAIL — motherly/older guardian; **“warm smile”** phrasing contributed |
| Reference strategy | FAIL — Asset 01 only; insufficient proportion anchor |

**Lesson:** **“Warm smile”** + cardigan/beige/hands-clasped drifted motherly. Target **fresh composed smile**, not warm motherly smile.

### R6B offduty_02 second canary failure

| Field | Value |
|-------|-------|
| **Output** | `keysuri_global_canary_20260605_103238.jpg` |
| **Reference** | Asset 02 attached (full-body default — superseded) |

| QA axis | Result |
|---------|--------|
| Background lock | PASS |
| Wardrobe direction (knit + slim skirt) | PASS |
| No tablet | PASS |
| Gesture / pose | PASS — operator: “제스처나 포즈는 참 좋아” |
| Face identity consistency | FAIL — Kee-Suri not same character |
| Full-body proportion | FAIL — did not preserve Asset 02 reference quality |
| Expression + face | FAIL — identity drift; face too small/unstable at full-body |

**Lesson:** Gesture works; **full-body-first + Asset 02 default caused identity drift** when expression applied. For R6B emotional lock-in, **identity and expression matter more than full-body proportion**. Do not continue R6B as full-body-first.

---

## 9. Hard Boundaries

Do **not** do these without explicit operator approval and a documented decision gate:

| Boundary | Rule |
|----------|------|
| Scheduler / GCP / Cloud Run | No wiring changes |
| Default opt-in | No enablement |
| Image API | No blind calls; no batch; no retry loops |
| Global+Korea pair | No unless separately approved |
| `output/**` images | QA references only — **never commit** |
| Live image call | Requires explicit **one-live-call approval** |
| Production asset promotion | Requires visual QA + separate decision |
| `README.md` | Modified and **out of scope** — do not commit with Kee-Suri work |
| Unrelated artifacts | PDFs, HTML previews, `ops/`, `static/email/`, unrelated scripts — **out of scope** |
| Today_Geenee / Tomorrow_Geenee | Do not modify unless explicitly scoped |
| Asset 02 cloning | No outfit / tablet / command-center copy |
| Bottom shot at 12:30 | Forbidden |

---

## 10. Recommended Next Step

### R6B third bottom-shot candidate — offduty_02B

**Do not retry offduty_01 or offduty_02 full-body.** Next package: **`offduty_02B_elegant_knit_kneeup_farewell`**.

| Field | Value |
|-------|-------|
| **Profile** | `offduty_02B_elegant_knit_kneeup_farewell` |
| **Taste cluster** | B — Elegant Office Casual |
| **Reason** | Carry offduty_02 gesture PASS; fix identity drift with knee-up framing |
| **Framing** | **3/4 body or knee-up** — face clearly visible; **no full-body requirement** |
| **Expression** | **Fresh composed smile / 싱그러운 미소** |
| **Gesture** | Small hand farewell — same direction as offduty_02 PASS |
| **Reference** | **Asset 01 primary** — Asset 02 optional silhouette support only if approved |
| **Wardrobe** | Modern fitted knit top; slim skirt partially visible |
| **Slot** | 18:30 bottom-shot only |
| **Background** | Fixed CEO/chairman office wood-door entrance |

**Prompt implication:**

> 3/4 body or knee-up composition, face clearly visible, Kee-Suri identity priority, fresh composed smile, small hand farewell, CEO wood-door background.

### Retired: immediate retries

| Profile | Output | Status |
|---------|--------|--------|
| `offduty_01` | `keysuri_global_canary_20260605_101845.jpg` | NOT_ACCEPTED — motherly/matronly |
| `offduty_02` | `keysuri_global_canary_20260605_103238.jpg` | NOT_ACCEPTED — identity/proportion drift |

### Pre-generation checklist (summary)

1. R6B plan §19 decision gate fields completed
2. Written prompt package (background locked first, then character variables)
3. Operator approval recorded
4. Preflight PASS; dry-run `request_count=0`, `called_image_api=false`
5. One-live-call approval
6. Output remains QA reference until §18 QA checklist PASS

---

## 11. Next Prompt Template

Use this template when creating the **R6B bottom-shot candidate prompt package**.

```markdown
# R6B Bottom-Shot Prompt Package — [profile_id]

## Approval fields (required before any API call)

| Field | Value |
|-------|-------|
| Date | YYYY-MM-DD |
| Operator ref | |
| Slot time | 18:30 |
| Profile ID | offduty_01_soft_classic_cardigan_silk_blouse |
| Taste cluster | A — Soft Classic |
| Season | spring/summer OR fall/winter |
| Emotional temperature | low / medium / warm |
| Drift risk | low / medium / high |
| Framing | 3/4 body OR knee-up preferred; full-body only if explicitly approved |
| Reference strategy | Asset 01 primary; Asset 02 optional silhouette support |
| Previous accepted bottom shot | none / [profile_id] — confirm not too close |
| One-live-call approval | PENDING / APPROVED |

## 1. Fixed background (lock first)

- Dignified wood-paneled CEO/chairman office wall
- Large premium wooden office door — private executive entrance
- Quiet executive-floor corridor or office entrance framing
- Warm evening executive-floor light
- Leaving-work greeting mood
- NO cafe / home / lounge / street / hotel / command-center
- NO broad background roulette

## 2. Kee-Suri identity

- Same Kee-Suri identity as Asset 01 — not same image
- Premium Korean private AI tech secretary
- Intelligent, calm, competent, respectful to 대표님
- Off-duty closing image — end of briefing day

## 3. Variable character (from profile)

- Top: [e.g. ivory soft cardigan over silk blouse]
- Bottom: [e.g. beige slim skirt]
- Fabric hints: [silk, fine knit, etc.]
- Prop: [small handbag OR thin notebook — no tablet]
- Gesture: [slight bow OR small hand farewell]
- Expression: **fresh composed smile**; refreshing off-duty expression; per emotional temperature (§11 R6B plan)
- Posture: [paused at door; natural hands]

## 4. Emotional register

- Temperature: [low / medium / warm]
- Warm farewell to representative/reader in **tone**
- **Fresh composed smile** on face — NOT warm motherly smile
- Subtle personal warmth — NOT romance
- NO cheap girlfriend fantasy
- NO sexualized lounge mood
- NO idol fan-service
- NO submissive secretary fantasy

## 5. Hard negatives

- No warm motherly smile, guardian-like smile, conservative family-meeting expression
- No hands-clasped polite-matron pose
- Prefer fresh composed smile, refreshing off-duty expression, modern attractive presence over warm smile alone
- No tablet-at-waist; no tablet in hands
- No Asset 02 outfit clone (charcoal suit, champagne blouse)
- No command-center / data-wall
- No revealing outfit, deep neckline, bedroom, bar, nightclub
- No readable text, logos, fake UI
- No color-only variation without structure change
- No v4 business briefing blazer uniform

## 6. One-live-call constraints

- Single API call only
- No retry on failure
- No batch
- No production wiring
- Output path: output/keysuri_preview/ — QA reference only
- Do not commit generated JPG

## 7. QA criteria (post-generation)

- [ ] **Face identity PASS first** — FAIL = NOT_ACCEPTED even if gesture/background pass
- [ ] **3/4 body or knee-up valid** — full-body not required for R6B
- [ ] Expression reads **fresh** rather than motherly
- [ ] Smile keeps Kee-Suri in **mid-to-late 30s modern attractive** range
- [ ] Image avoids **guardian / family-meeting** mood
- [ ] Gesture avoids **hands-clasped conservative politeness**
- [ ] Face reads as same Kee-Suri vs Asset 01 — identity gate before wardrobe/gesture acceptance
- [ ] Kee-Suri reads mid-to-late 30s, not older/motherly
- [ ] Outfit modern and attractive, not motherly cardigan mood
- [ ] Pose avoids hands-clasped conservative greeting
- [ ] Scene remains CEO/chairman wood-door background
- [ ] Identity stable vs Asset 01
- [ ] CEO wood-door background fixed and recognizable
- [ ] Off-duty outfit from profile — not v4 briefing uniform
- [ ] Emotional temperature matches approval
- [ ] End-of-day greeting mood present
- [ ] No cafe/lounge/glamour/home drift
- [ ] Person-centered variation — not scene-random
- [ ] Useful as 18:30 email/blog bottom image
- [ ] No text/logo/UI contamination
```

---

## 12. Current Repo Caution

### Working tree (typical — verify with `git status --short`)

| Item | State | Action |
|------|-------|--------|
| `README.md` | Modified, unstaged | **Out of scope** — do not stage or commit with Kee-Suri work |
| `docs/keysuri/*.md` | Tracked; handoff doc may be new/uncommitted | Commit **narrowly** — one doc per commit when asked |
| `output/**` | Gitignored | Never commit canary/QA JPGs |
| PDFs, HTML previews | Untracked | Out of scope |
| `ops/` | Untracked | Out of scope |
| `static/email/` | Untracked generated images | Out of scope — not production Kee-Suri assets |
| Unrelated scripts | Untracked | Out of scope |

### Git hygiene

- **Do not use `git add -A`**
- **Do not clean working tree** unless explicitly asked
- **Keep Kee-Suri commits narrow** — typically one `docs/keysuri/` file per commit
- Confirm `git show --stat` shows only intended files before pushing

### Test note

Canary runner + preflight tests exist (`tests/test_keysuri_manual_opt_in_canary_runner.py`, `tests/test_keysuri_manual_canary_preflight.py`). Run when modifying infrastructure — not required for documentation-only handoff commits unless CI expects it.

---

## Quick Reference Card

```
TRACK STATUS
  R5   CLOSED     → Wardrobe v4 PASS_DIRECTION (v4_01, v4_02, v4_03)
  R6   PLANNED     → Asset 02 = SILHOUETTE ONLY
  R6B  PLANNED     → 18:30 bottom shot; fixed CEO door; 8 off-duty profiles

SCHEDULE
  12:30  TOP only        Wardrobe v4
  18:30  TOP + BOTTOM    v4 top + R6B off-duty bottom

CANARY RESULTS
  offduty_01 NOT_ACCEPTED → motherly/matronly drift (101845.jpg)
  offduty_02 NOT_ACCEPTED → identity/proportion drift; gesture PASS (103238.jpg)

NEXT ACTION
  R6B  framing = 3/4 or knee-up preferred, NOT full-body-first
  R6B  reference = Asset 01 identity priority; Asset 02 optional only
  R6B  expression = fresh composed smile, NOT warm motherly smile
  NEXT offduty_02B knee-up identity-priority → approve → one live call → QA
  DO NOT retry offduty_01 or offduty_02 full-body immediately

NEVER
  commit output/**  |  git add -A  |  wire Scheduler  |  bottom at 12:30
  clone Asset 02 outfit/tablet/bg  |  color-only wardrobe roulette
  R6B full-body as default framing  |  prompt "warm smile" without fresh composed smile guard
  accept gesture/background PASS when face identity FAILs
```

---

## Summary

Kee-Suri image track handoff: **R5 closed with Wardrobe v4 direction**, **R6 classified Asset 02 as silhouette-only**, **R6B canaries offduty_01 and offduty_02 NOT_ACCEPTED**. Strategy revised: **3/4 or knee-up framing**, **Asset 01 identity priority**, gesture direction from offduty_02 preserved. **Next:** `offduty_02B_elegant_knit_kneeup_farewell` — not full-body retry.
