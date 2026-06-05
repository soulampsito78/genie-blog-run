# KEYSURI R6B — offduty_02 Bottom-Shot Candidate Design Package

Status:
Design package only / **not approved for generation** / no image API in this document

Candidate:
`offduty_02_elegant_knit_slim_skirt`

Aligned references:

- Expression direction: commit `b8f7b32` — `Refine Kee-Suri R6B expression direction`
- Full-body reference strategy: commit `76727e5` — Asset 02 default for R6B framing
- R6B bottom-shot plan: `docs/keysuri/KEYSURI_R6B_BOTTOM_SHOT_EMOTIONAL_LOCKIN_PLAN.md`
- Previous candidate (NOT_ACCEPTED): `docs/keysuri/KEYSURI_R6B_FIRST_BOTTOM_SHOT_CANDIDATE_PACKAGE.md`
- Current state handoff: `docs/keysuri/KEYSURI_IMAGE_TRACK_CURRENT_STATE_HANDOFF.md`
- Asset 01: `assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png`
- Asset 02: `assets/keysuri/reference/image_keysuri_asset_02_full_body.png` — `KEEP_AS_SILHOUETTE_REFERENCE`

Non-scope:

- live image generation
- production wiring
- Scheduler / GCP / Cloud Run changes
- committing generated images
- Today_Geenee / Tomorrow_Geenee paths
- retry of `offduty_01` under this package

---

## 1. Candidate Summary

| Field | Value |
|-------|-------|
| **profile_id** | `offduty_02_elegant_knit_slim_skirt` |
| **slot** | **18:30 bottom-shot only** — never 12:30 |
| **taste cluster** | **B — Elegant Office Casual** |
| **season** | All-season; **spring/summer compatible** |
| **emotional temperature** | **medium** |
| **expression target** | **Fresh composed smile** / **싱그러운 미소** |
| **drift risk** | **low** |
| **background** | Fixed CEO/chairman office wood-door entrance |
| **framing** | 3/4 body or full-body — **Asset 02 default attached reference** |
| **status** | **Design package only — not approved for generation yet** |

**Validation goal:** Prove a **more modern, attractive, fresh** R6B bottom-shot direction after `offduty_01` failure — while preserving fixed CEO-door background, Asset 02 full-body framing, fresh composed smile expression, and no motherly/guardian drift.

---

## 2. Reason for Moving from offduty_01

| offduty_01 outcome | Lesson for offduty_02 |
|--------------------|----------------------|
| **NOT_ACCEPTED** — `keysuri_global_canary_20260605_101845.jpg` | Do not retry `offduty_01` immediately |
| Background lock **PASS** | Keep fixed CEO wood-door background |
| No tablet **PASS** | Keep hard negative on tablet-at-waist |
| Off-duty wardrobe **PARTIAL** | Move from cardigan/blouse to **sleeker knit + slim skirt** |
| Identity / age / charm **FAIL** | Avoid motherly / matronly / older guardian read |

### Why offduty_01 failed on expression and silhouette

- **Soft cardigan + beige tones + “warm smile” language** drifted toward motherly / family-meeting mood
- **Hands-clasped conservative greeting** reinforced matronly politeness
- **Asset 01-only reference** — insufficient full-body proportion anchor (policy corrected in `76727e5`)

### Why offduty_02 is the next candidate

| Factor | offduty_02 direction |
|--------|---------------------|
| Silhouette | **Modern fitted knit + slim skirt** — sleeker than cardigan stack |
| Expression | **Fresh composed smile / 싱그러운 미소** — not warm motherly smile |
| Gesture | **Small hand farewell** or **slight over-the-shoulder farewell glance** — active, not clasped |
| Reference | **Asset 02 default** — proportion, leg line, full-length framing |
| Cluster | **B — Elegant Office Casual** — daily repeat-friendly, intelligent everyday elegance |

---

## 3. Visual Direction

### Scene

Kee-Suri stands at the **chairman/CEO office entrance** — **large premium wooden door**, **dignified wood-paneled wall**, **warm evening executive-floor light**. She has finished the day’s briefing and offers a **fresh, modern off-duty farewell** to the representative reader.

### Subject

| Element | Direction |
|---------|-----------|
| **Identity** | Same Kee-Suri — **refined Korean woman in mid-to-late 30s**; sleek short bob; thin glasses; **same identity, not same image** |
| **Persona** | Premium private AI tech secretary — intelligent, calm, competent |
| **Top** | **Modern fitted refined knit top** — lightweight, office-appropriate, attractive not revealing |
| **Bottom** | **Slim skirt** — beige, muted taupe, or soft charcoal; knee-length premium tailoring |
| **Footwear** | Low heels or elegant office pumps (if visible) |
| **Prop** | **Small elegant structured handbag** OR **thin notebook** — operator chooses one at approval |
| **Expression** | **Fresh composed smile / 싱그러운 미소** — refreshing off-duty expression; **not warm motherly smile** |
| **Gesture** | **Small hand farewell** OR **slight over-the-shoulder farewell glance** — **no hands-clasped conservative greeting** |
| **Eye contact** | Direct but respectful — gentle fresh eye contact toward reader / 대표님 |
| **Wardrobe register** | Attractive but **office-appropriate off-duty** — modern, elegant, not business v4 briefing uniform |
| **Mood** | Personally warm in **tone**; **fresh and modern in visible expression** — premium; not romance, lounge, glamour, motherly guardian |

### Hard mood limits

- Not cheap girlfriend fantasy
- Not sexualized lounge mood
- Not idol fan-service
- Not submissive secretary fantasy
- Not motherly / matronly / older guardian / conservative family-meeting mood
- Not weathercaster / public anchor / fashion editorial

---

## 4. Fixed vs Variable Elements

### Fixed (do not vary in prompt or QA)

| Element | Lock |
|---------|------|
| **Slot** | **18:30 bottom-shot only** |
| **Setting** | CEO/chairman **office entrance** |
| **Wall** | Dignified **wood-paneled** executive wall |
| **Door** | **Large premium wooden** office door — visible, door-like |
| **Light** | **Warm evening** executive-floor lighting |
| **Reference** | **Asset 02** attached — full-body/silhouette default |
| **Anti-copy** | No Asset 02 outfit, tablet pose, command-center background |
| **Prop rule** | **No tablet-at-waist**; no tablet in hands |
| **Identity** | Kee-Suri face family — Asset 01 prompt/QA policy |
| **Expression target** | **Fresh composed smile / 싱그러운 미소** — not warm motherly smile |

### Variable for this candidate (approved ranges)

| Element | Allowed variation |
|---------|-------------------|
| Knit top color | Soft ivory, pale blue, cool beige, light charcoal knit |
| Skirt tone | Beige, muted taupe, soft charcoal |
| Prop | Small structured handbag **or** thin notebook — **one only** |
| Gesture | Small hand farewell **or** slight over-the-shoulder farewell glance |
| Smile intensity | Medium — **fresh composed smile**; lively but restrained |
| Posture angle | Slight turn toward door; natural weight shift; 3/4 or full-body framing |

**Do not vary:** background location, scene type, briefing Wardrobe v4 uniform, Asset 02 embedded outfit.

---

## 5. Reference Strategy

### Reference split

| Source | Role |
|--------|------|
| **Asset 02** (attached) | **Default** full-body/silhouette reference for 3/4 or full-body bottom shot |
| **Asset 01** (prompt + QA) | Identity / face family — short bob, thin glasses, refined Kee-Suri impression |
| **Prompt** | Off-duty outfit, expression, gesture, fixed CEO wood-door background, emotional temperature, anti-copy blocks |

### Asset 02 must anchor

- Full-body proportion
- Standing silhouette
- Body line and posture baseline
- Skirt length / leg line
- Shoe visibility (if in frame)
- Full-length framing

### Asset 02 must not transfer

- Charcoal suit
- Champagne blouse
- Tablet-at-waist pose
- Tablet in hands
- Command-center / data-wall background
- Stiff briefing mood
- Embedded reference outfit or composition copy

### Reference call rule

- **One reference image per API call** — attach **Asset 02** (`02` / `full_body` selector)
- Asset 01 identity enforced through **prompt text aligned with Asset 01** + **post-generation QA cross-check**
- **Do not** use Asset 01-only reference for R6B 3/4 or full-body bottom shots

### Wardrobe v4 boundary

Wardrobe v4 business profiles are **not copied**. No cream jacket, black suit, clutch folder briefing patterns.

---

## 6. Prompt Package Draft

Prompt order: **slot operation → reference-use → Asset 02 anti-copy → background lock → wardrobe/person → expression → positive → negative**.

### 6.1 Slot operation block

```
SLOT OPERATION:
This image is for 18:30 BOTTOM-SHOT ONLY — end-of-day emotional lock-in.
NOT for 12:30 briefing top shot.
NOT business Wardrobe v4 briefing authority image.
Companion top shot for same send uses separate v4 business prompt — not this package.
Output is QA reference only until operator checklist PASS.
Single one-live-call only — no retry under same approval.
```

### 6.2 Reference-use block

```
REFERENCE POLICY — ASSET 02 DEFAULT (attached):
Use the full-body reference ONLY for body proportion, full-length framing, standing silhouette,
skirt/leg/shoe balance, and posture baseline.
Generate a NEW image — same Kee-Suri identity family, not the same photograph, not the same pose,
not the same outfit as the full-body reference.

ASSET 01 IDENTITY POLICY (prompt + post-gen QA):
Refined Korean woman in mid-to-late 30s, sleek short bob, thin glasses, calm intelligent secretary face.
Cross-check output face against Asset 01 identity reference after generation.
NOT older, NOT motherly, NOT matronly, NOT guardian-like.
```

### 6.3 Asset 02 anti-copy block

```
ASSET 02 ANTI-COPY — REQUIRED:
Do NOT copy the full-body reference outfit (no charcoal suit, no champagne blouse).
Do NOT copy tablet-at-waist pose or tablet in hands.
Do NOT copy command-center, data-wall, or holographic screen background.
Do NOT copy stiff catalog briefing mood or embedded reference composition.
Apply R6B off-duty wardrobe from prompt — refined knit top and slim skirt, not reference clothes.
```

### 6.4 Background lock block

```
SCENE LOCK — DO NOT VARY:
Kee-Suri at the entrance of a chairman/CEO private office on an executive floor.
Dignified wood-paneled executive wall fills the background.
A large premium wooden office door is clearly visible — heavy wood, executive private office, door-like and recognizable.
Quiet executive-floor corridor or private office entrance framing.
Warm evening executive-floor lighting — soft amber warmth, end of workday.
Leaving-work farewell mood — she has finished today's briefing and is saying goodbye before leaving.
NOT a cafe, home, hotel lobby, street, lounge, bar, or nightclub.
NOT a command center, data wall, or broadcast studio.
NOT a generic office lobby without a visible wooden executive door.
NO broad background roulette.
```

### 6.5 Wardrobe / person-variation block

```
CHARACTER — OFF-DUTY ELEGANT OFFICE CASUAL (offduty_02_elegant_knit_slim_skirt):
Kee-Suri has changed out of formal briefing wardrobe into modern attractive tasteful off-duty office casual.
Refined fitted lightweight knit top — elegant, office-appropriate, modern silhouette, not revealing.
Slim skirt in beige, muted taupe, or soft charcoal — knee-length, premium tailoring.
Small elegant structured handbag at her side OR thin closed notebook held naturally — NO tablet.
Low heels or elegant office pumps if feet visible.
Small hand farewell gesture OR slight over-the-shoulder farewell glance toward the viewer.
NO hands-clasped conservative matron pose. NO polite family-meeting clasped hands.
3/4 body or full-body framing — respectful distance, premium content closing image.
Premium Korean private AI tech secretary — intelligent, calm, competent, tasteful, modern.
```

### 6.6 Expression block

```
EXPRESSION TARGET — FRESH COMPOSED SMILE / 싱그러운 미소:
Fresh composed smile on face — refreshing off-duty expression, modern attractive presence.
Emotionally warmer than briefing hero in tone, but face reads FRESH and MODERN, not motherly.
Gentle fresh eye contact — respectful toward the representative reader.
Emotional temperature: MEDIUM — gently personal farewell, not romantic, not submissive.

NOT warm motherly smile.
NOT matronly expression.
NOT older guardian mood.
NOT conservative family-meeting polite smile.
```

### 6.7 Primary positive prompt (consolidated)

```
Kee-Suri, refined Korean woman in mid-to-late 30s, sleek short bob, thin glasses,
premium private AI tech secretary, same identity new image,
standing at chairman CEO office entrance, large premium wooden door, dignified wood-paneled executive wall,
warm evening executive-floor light, off-duty closing farewell,
modern fitted refined knit top, slim beige skirt, small elegant handbag,
fresh composed smile, 싱그러운 미소, refreshing off-duty expression, modern attractive off-duty presence,
small hand farewell or slight over-the-shoulder farewell glance, gentle fresh eye contact,
elegant office casual off-duty look, leaving-work greeting mood, 3/4 body
```

### 6.8 Hard negative prompt

```
warm motherly smile, matronly expression, older guardian mood, conservative family-meeting expression,
hands-clasped polite matron pose, clasped hands at waist conservative greeting,
cheap girlfriend fantasy, sexualized lounge hostess, idol fan-service, submissive secretary fantasy,
romantic couple framing, flirtatious pose, blown kiss, inviting recline,
glamour model, fashion editorial, catalog showroom, weathercaster, news anchor desk,
deep neckline, revealing outfit, exposed cleavage, bedroom, home interior,
cafe, restaurant, bar, lounge, nightclub, street, hotel lobby,
command center, data wall, holographic screens, tablet at waist, tablet in hands,
charcoal suit, champagne blouse, briefing uniform, business blazer copy, Wardrobe v4 briefing outfit,
Asset 02 outfit clone, dark blazer pale blouse tablet pattern,
soft cardigan motherly stack, ivory cardigan beige family-meeting look,
readable text, logos, watermark, fake UI, subtitles,
color-only outfit change, same pose as reference photo,
overly casual streetwear, sneakers, hoodie, maid costume,
bowed submissive head, imploring gaze, heart hands, aegyo,
harsh flash photography, cold fluorescent only, no visible wooden door
```

---

## 7. Approval Draft

**Do not approve automatically.** Operator must complete before any image API call.

| Field | Value |
|-------|-------|
| **approved_slot_time** | `18:30` |
| **profile_id** | `offduty_02_elegant_knit_slim_skirt` |
| **taste_cluster** | B — Elegant Office Casual |
| **season** | all-season (spring/summer compatible) — _operator confirm: ___________ |
| **emotional_temperature** | `medium` |
| **expression_target** | `fresh composed smile` / `싱그러운 미소` |
| **drift_risk** | `low` |
| **framing** | 3/4 body — _or full-body: ___________ |
| **prop_choice** | handbag — _or notebook: ___________ |
| **gesture_choice** | small hand farewell — _or over-shoulder glance: ___________ |
| **background_lock** | `CEO/chairman office wood-door entrance — FIXED` |
| **reference_asset_strategy** | `Asset 02 attached (default); Asset 01 identity in prompt + post-gen QA` |
| **previous_failed_candidate** | `offduty_01` — confirm not retrying |
| **one_live_call** | `PENDING` — must be `APPROVED` before API |
| **no_retry** | `true` |
| **no_batch** | `true` |
| **no_scheduler** | `true` |
| **no_production_wiring** | `true` |
| **output_path_policy** | `output/keysuri_preview/image_canary/` — QA reference only; **never commit** |
| **operator_ref** | ___________ |
| **approval_date** | ___________ |
| **one_live_call_approval** | `PENDING` / `APPROVED` |

**Generation gate:** R6B plan §19 decision gate + this package §6 + preflight PASS + dry-run `request_count=0`, `called_image_api=false`.

---

## 8. QA Checklist

Complete after one-live-call output. All items must PASS before any promotion discussion.

### Identity and expression

- [ ] **Identity stable** — same Kee-Suri face, bob, glasses vs Asset 01
- [ ] **Kee-Suri reads mid-to-late 30s** — not older/motherly/matronly/guardian
- [ ] **Fresh composed smile / 싱그러운 미소 visible** — not warm motherly smile
- [ ] **Expression reads fresh and modern** — refreshing off-duty, not family-meeting polite
- [ ] **Not cheap girlfriend fantasy**; **not sexualized**; **not submissive**

### Reference and proportion

- [ ] **Asset 02-like full-body proportion preserved** — without copying Asset 02 outfit
- [ ] **No Asset 02 outfit clone** — no charcoal suit, champagne blouse
- [ ] **No command-center / data-wall background** from reference

### Background and wardrobe

- [ ] **CEO/chairman wood-door background visible** — wood-paneled wall, premium wooden door
- [ ] **Outfit reads modern/elegant off-duty** — knit + slim skirt; **not** Wardrobe v4 briefing uniform
- [ ] **Not too casual** — still premium executive-adjacent elegance
- [ ] **Not too glamour / editorial / lounge**

### Gesture and utility

- [ ] **Small hand farewell OR over-the-shoulder farewell glance visible**
- [ ] **Not hands-clasped conservative greeting**
- [ ] **No tablet-at-waist**; prop did not morph into tablet
- [ ] **Useful as 18:30 emotional closing image** — reads at email/blog bottom width

### Slot compliance

- [ ] **18:30 bottom-shot context only**
- [ ] **No text / logo / UI contamination**

---

## 9. Risk Assessment

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| **Too mature / motherly** | Medium | Fresh composed smile language; no cardigan stack; no hands-clasped; Asset 02 + age guardrails |
| **Too casual** | Low–Medium | Fitted knit + slim skirt + low heels; reject streetwear/sneakers |
| **Too glamour** | Medium | No editorial posing; 3/4 body at CEO door, not runway |
| **Too office-worker plain** | Medium | Modern attractive knit silhouette; fresh expression; handbag/notebook prop |
| **Background not door-like enough** | Medium | Background lock block; QA fails if wooden executive door absent |
| **Full-body reference outfit copied** | Medium–High | Asset 02 anti-copy block; QA rejects charcoal/champagne/tablet |
| **Prop morphs into tablet** | Medium | Hard negatives; QA rejects tablet shapes |
| **Face drift** | Low–Medium | Asset 01 identity in prompt; post-gen cross-check vs Asset 01 |
| **Gesture missing** | Medium | Require hand farewell or over-shoulder glance in prompt; QA fails if clasped-only |

**Overall drift risk:** **low** — improved vs offduty_01 if Asset 02 attached and expression/gesture rules followed.

---

## 10. Execution Recommendation

| Step | Status |
|------|--------|
| Design package complete | **Yes** — this document |
| Operator review | **Ready** — awaiting approval |
| offduty_01 retry | **Forbidden** — use this package only |
| Image generation | **Do not generate until approved** |
| Live call policy | **One-live-call only if approved** — **no retry under same approval** |

### Recommended execution sequence (after approval)

1. Operator completes §7 approval fields
2. Confirm prop (handbag vs notebook) and gesture (hand farewell vs over-shoulder glance)
3. Confirm **Asset 02** attached (`reference_asset=02`)
4. Run preflight + dry-run — verify `called_image_api=false`
5. Single guarded one-live-call with §6 prompt package
6. Output to `output/keysuri_preview/image_canary/` — QA reference only
7. Complete §8 checklist
8. Record PASS/FAIL — do not commit JPG

### If QA FAIL

- **Do not retry automatically** under same approval
- Document failure mode against §9 risks
- Update package or select alternate gesture/prop
- **New approval required** before any subsequent live call

---

## Summary

**offduty_02_elegant_knit_slim_skirt** is the second R6B bottom-shot candidate — **Elegant Office Casual** with **modern fitted knit + slim skirt**, **fresh composed smile / 싱그러운 미소**, **Asset 02 default framing**, and **fixed CEO wood-door background**. Designed to correct `offduty_01` motherly/guardian failure. **Status: not approved for generation.**

**Next action:** Operator review → complete §7 approval → one-live-call (only if approved).
