# KEYSURI R6B — First Bottom-Shot Candidate Design Package

Status:
Design package only / **not approved for generation** / no image API in this document

Candidate:
`offduty_01_soft_classic_cardigan_silk_blouse`

Aligned references:

- Current state handoff: commit `e7d4e62` — `docs/keysuri/KEYSURI_IMAGE_TRACK_CURRENT_STATE_HANDOFF.md`
- R6B bottom-shot plan: commits `03c31a7`, `2246c64` — `docs/keysuri/KEYSURI_R6B_BOTTOM_SHOT_EMOTIONAL_LOCKIN_PLAN.md`
- R6 full-body / Asset 02: commits `bc78c4f`, `0c7a6f0` — `docs/keysuri/KEYSURI_IMAGE_TRACK_R6_FULL_BODY_ASSET_PLAN.md`
- Asset 01: `assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png`
- Asset 02: `assets/keysuri/reference/image_keysuri_asset_02_full_body.png` — `KEEP_AS_SILHOUETTE_REFERENCE` only

Non-scope:

- live image generation
- production wiring
- Scheduler / GCP / Cloud Run changes
- committing generated images
- Today_Geenee / Tomorrow_Geenee paths

---

## 1. Candidate Summary

| Field | Value |
|-------|-------|
| **profile_id** | `offduty_01_soft_classic_cardigan_silk_blouse` |
| **slot** | **18:30 bottom-shot only** — never 12:30 |
| **taste cluster** | **A — Soft Classic** |
| **season** | All-season; **slightly spring/summer leaning** |
| **emotional temperature** | **medium** |
| **drift risk** | **low** |
| **background** | Fixed CEO/chairman office wood-door entrance |
| **framing (recommended)** | 3/4 body or full-body — **Asset 02 required as attached reference** |
| **status** | **NOT_ACCEPTED** — first canary failed visual QA (see §11) |

**Validation goal:** First live proof of the R6B system — fixed executive-door background + attractive off-duty outfit + warm farewell gesture + medium emotional temperature.

---

## 2. Product Purpose

This candidate validates the **R6B bottom-shot emotional lock-in slot** for the 18:30 briefing.

| Purpose | How this candidate serves it |
|---------|------------------------------|
| **Emotional lock-in** | Reader ends the day with a human farewell, not only headlines |
| **Private closing ritual** | Recurring moment at the same CEO office door — recognizable ritual |
| **Daily familiarity** | Kee-Suri visible at open (top/v4) and close (bottom/off-duty) |
| **Personal greeting to representative** | Warm but respectful eye contact + farewell gesture — “오늘도 고생하셨습니다, 대표님” energy without readable text |
| **System validation** | Proves **fixed background + broad off-duty wardrobe** design contract from R6B plan |

This is the **safest first candidate** (cluster A, low drift risk). Success here unlocks rotation across clusters B–G; cluster H remains deferred.

---

## 3. Visual Direction

### Scene

Kee-Suri stands in front of a **large premium wooden CEO/chairman office door** with **dignified wood-paneled walls** and **warm evening executive-floor lighting**. She has changed out of formal briefing wardrobe and offers a **calm leaving-work greeting** to the representative reader.

### Subject

| Element | Direction |
|---------|-----------|
| **Identity** | Same Kee-Suri — refined Korean woman, sleek short bob, thin glasses; **same identity, not same image** |
| **Persona** | Premium private AI tech secretary — intelligent, calm, competent |
| **Wardrobe register** | Off-duty office casual — attractive but tasteful |
| **Outer layer** | Soft **ivory or light beige** cardigan |
| **Inner** | **Silk blouse** — elegant, office-appropriate, modest neckline |
| **Bottom** | **Slim skirt** — beige or muted charcoal |
| **Prop** | **Small elegant structured handbag** OR **thin notebook** — operator chooses one at approval |
| **Expression** | **Warm but composed** — softer than briefing hero; restrained smile |
| **Gesture** | **Slight bow** OR **small hand farewell** — respectful, not submissive |
| **Eye contact** | Direct but respectful — acknowledges reader / 대표님 |
| **Mood** | Warm, personal, premium — **not** romance, lounge, or glamour |

### Hard mood limits

- Not cheap girlfriend fantasy
- Not sexualized lounge mood
- Not idol fan-service
- Not submissive secretary fantasy
- Not weathercaster / public anchor pose
- Not fashion editorial / catalog showroom

---

## 4. Fixed vs Variable Elements

### Fixed (do not vary in prompt or QA)

| Element | Lock |
|---------|------|
| Setting | CEO/chairman **office entrance** |
| Wall | Dignified **wood-paneled** executive wall |
| Door | **Large premium wooden** office door — visible, door-like |
| Light | **Warm evening** executive-floor lighting |
| Slot use | **18:30 bottom-shot only** |
| Identity | Kee-Suri face, bob, glasses — Asset 01 policy |
| Persona register | Premium private AI tech secretary |

### Variable for this candidate (approved ranges)

| Element | Allowed variation |
|---------|-------------------|
| Cardigan color | Ivory, light beige, soft cream |
| Blouse | Silk; soft ivory, pale blue, or smoky neutral |
| Skirt tone | Beige, muted taupe, or soft charcoal |
| Prop | Small structured handbag **or** thin notebook — **one only** |
| Gesture | Slight bow **or** small hand farewell |
| Smile intensity | Medium temperature — soft visible smile, not wide/grinning |
| Emotional warmth | Medium — gently personal, not flirtatious |

**Do not vary:** background location, scene type, lighting mood (daytime cafe, nightclub, home), or briefing Wardrobe v4 outfit structure.

---

## 5. Reference Strategy

### Reference split

| Source | Role |
|--------|------|
| **Asset 01** | Identity / face family — short bob, thin glasses, refined Korean Kee-Suri impression (prompt policy + post-gen QA) |
| **Asset 02** | **Default attached reference** — full-body framing, silhouette, posture/proportion, full-length composition |
| **Prompt** | Off-duty outfit, expression, gesture, fixed CEO wood-door background, emotional temperature, anti-copy constraints, age/charm guardrails |

| Asset | Path | Role |
|-------|------|------|
| **Asset 01** | `assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png` | Identity / face family — **not attached in one-call policy when Asset 02 is used** |
| **Asset 02** | `assets/keysuri/reference/image_keysuri_asset_02_full_body.png` | **Default attached reference** for 3/4 and full-body bottom shots |

### Asset 02 must anchor

- Full-body proportion
- Standing silhouette
- Skirt length / leg line
- Shoe visibility
- Full-length framing
- Body posture baseline

### Asset 02 must not transfer

- Charcoal suit, champagne blouse
- Tablet-at-waist pose, tablet in hands
- Command-center / data-wall background
- Stiff briefing mood

### Reference call rule

- **One reference image per live call** — attach **Asset 02** for R6B 3/4 and full-body bottom shots
- Asset 01 identity enforced through prompt text aligned with Asset 01 + post-generation QA cross-check
- **Do not rely on prompt-only full-body interpretation** — first canary failure demonstrated this risk

---

## 6. Prompt Package Draft

Prompt order: **background lock → identity → wardrobe/person variation → negatives → slot operation.**

### 6.1 Background lock block

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

### 6.2 Reference-use block

```
REFERENCE POLICY — ASSET 02 DEFAULT:
Attach full-body reference for body proportion, full-length framing, standing silhouette,
skirt/leg/shoe balance, and posture baseline ONLY.
Use Asset 01 identity policy in prompt: same refined Korean woman, sleek short bob, thin glasses,
mid-to-late 30s, calm intelligent secretary face — NOT older, NOT motherly.
Generate a NEW image — same identity family, not the same photograph, not the same pose,
not the same outfit as the full-body reference.
DO NOT copy reference outfit (no charcoal suit, no champagne blouse).
DO NOT copy tablet-at-waist pose or tablet in hands.
DO NOT copy command-center or data-wall background from any reference.
Cross-check output face against Asset 01 identity reference after generation.
Avoid motherly, matronly, older guardian, conservative family-meeting mood.
Avoid hands-clasped conservative greeting pose.
```

### 6.3 Wardrobe / person-variation block

```
CHARACTER — OFF-DUTY SOFT CLASSIC (offduty_01):
Kee-Suri has changed out of formal briefing wardrobe into attractive tasteful off-duty office casual.
Soft ivory or light beige fine-knit cardigan worn open or loosely over a refined silk blouse — elegant, modest neckline, office-appropriate.
Slim skirt in beige, muted taupe, or soft charcoal — knee-length, premium tailoring.
Small elegant structured handbag at her side OR a thin closed notebook held naturally — NO tablet.
Slight respectful bow OR small hand farewell gesture toward the viewer — calm leaving-work greeting.
Warm but composed expression — soft restrained smile, emotionally warmer than a briefing hero image.
Direct but respectful eye contact — acknowledges the representative reader with personal warmth, not flirtation.
Emotional temperature: MEDIUM — gently personal farewell, not romantic, not submissive.
3/4 body framing recommended — respectful distance, not bust-only close-up.
Premium Korean private AI tech secretary — intelligent, calm, competent, tasteful.
```

### 6.4 Primary positive prompt (consolidated)

```
Kee-Suri, refined Korean woman, sleek short bob, thin glasses, premium private AI tech secretary,
standing at chairman CEO office entrance, large premium wooden door, dignified wood-paneled executive wall,
warm evening executive-floor light, off-duty closing farewell,
soft ivory cardigan over silk blouse, slim beige skirt, small elegant handbag,
warm composed smile, slight respectful bow, direct respectful eye contact,
attractive tasteful off-duty office casual, leaving-work greeting mood,
same identity new image, premium calm personal warmth, 3/4 body
```

### 6.5 Hard negative prompt

```
cheap girlfriend fantasy, sexualized lounge hostess, idol fan-service, submissive secretary fantasy,
romantic couple framing, flirtatious pose, blown kiss, inviting recline,
glamour model, fashion editorial, catalog showroom, weathercaster, news anchor desk,
deep neckline, revealing outfit, exposed cleavage, bedroom, home interior,
cafe, restaurant, bar, lounge, nightclub, street, hotel lobby,
command center, data wall, holographic screens, tablet at waist, tablet in hands,
charcoal suit, champagne blouse, briefing uniform, business blazer copy,
Asset 02 outfit clone, dark blazer pale blouse tablet pattern,
readable text, logos, watermark, fake UI, subtitles,
color-only outfit change, same pose as reference photo,
overly casual streetwear, sneakers, hoodie, maid costume,
bowed submissive head, imploring gaze, heart hands, aegyo,
harsh flash photography, cold fluorescent only, no visible wooden door
```

### 6.6 Slot-operation block

```
SLOT OPERATION:
This image is for 18:30 BOTTOM-SHOT ONLY — end-of-day emotional lock-in.
NOT for 12:30 briefing top shot.
NOT business Wardrobe v4 briefing authority image.
Companion top shot for same send uses separate v4 business prompt — not this package.
Output is QA reference only until operator checklist PASS.
```

---

## 7. Approval Draft

**Do not approve automatically.** Operator must fill and sign before any image API call.

| Field | Value |
|-------|-------|
| **approved_slot_time** | `18:30` |
| **profile_id** | `offduty_01_soft_classic_cardigan_silk_blouse` |
| **taste_cluster** | A — Soft Classic |
| **season** | all-season (spring/summer lean) — _operator confirm: ___________ |
| **emotional_temperature** | `medium` |
| **drift_risk** | `low` |
| **framing** | 3/4 body — _or full-body: ___________ |
| **prop_choice** | handbag — _or notebook: ___________ |
| **gesture_choice** | slight bow — _or hand farewell: ___________ |
| **background_lock** | `CEO/chairman office wood-door entrance — FIXED` |
| **reference_strategy** | Asset 02 default attached — Asset 01 identity in prompt |
| **one_live_call** | `PENDING` — must be `APPROVED` before API |
| **no_retry** | `true` |
| **no_batch** | `true` |
| **no_scheduler** | `true` |
| **no_production_wiring** | `true` |
| **output_path policy** | `output/keysuri_preview/` — QA reference only; **never commit** |
| **operator_ref** | ___________ |
| **approval_date** | ___________ |
| **one_live_call_approval** | `PENDING` / `APPROVED` |

**Generation gate:** All fields above complete + R6B plan §19 decision gate + preflight PASS + dry-run `request_count=0`, `called_image_api=false`.

---

## 8. QA Checklist

Complete after one-live-call output. All items must PASS before any promotion discussion.

### Identity and persona

- [ ] **Identity stable** — same Kee-Suri face, bob, thin glasses vs Asset 01
- [ ] **Asset 02-like full-body proportion** — without copying Asset 02 outfit
- [ ] **Kee-Suri reads mid-to-late 30s** — not older/motherly/matronly
- [ ] **Outfit modern and attractive** — not motherly conservative mood
- [ ] **Pose avoids hands-clasped conservative greeting**
- [ ] **Scene remains CEO/chairman wood-door background**
- [ ] **Expression warmer than briefing image** — visible softening, not identical to hero
- [ ] **Not cheap girlfriend fantasy**
- [ ] **Not sexualized**
- [ ] **Not submissive** — bow/gesture reads respectful farewell, not servile

### Background

- [ ] **Background fixed to CEO/chairman office wood-door entrance**
- [ ] **Wood-paneled wall visible**
- [ ] **Large wooden door recognizable** — door-like, executive, not generic wall
- [ ] **Warm evening executive-floor light**
- [ ] **No cafe / home / lounge / street / hotel drift**

### Wardrobe

- [ ] **Outfit reads off-duty but premium** — not briefing v4 uniform
- [ ] **Cardigan / blouse / skirt visible** — soft classic structure clear
- [ ] **Not too similar to business Wardrobe v4** — no blazer, no briefing folder prop pattern
- [ ] **Not too casual** — still executive-adjacent elegance

### Gesture and utility

- [ ] **Greeting gesture visible** — slight bow or hand farewell present
- [ ] **No tablet-at-waist**; no tablet morph from notebook/handbag
- [ ] **Useful as 18:30 emotional closing image** — reads at email/blog bottom width

### Slot compliance

- [ ] **18:30 bottom-shot context only** — not paired with 12:30 off-duty use
- [ ] **No text / logo / UI contamination**

---

## 9. Risk Assessment

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| **Too casual** | Medium | Prompt emphasizes premium off-duty office casual; QA rejects streetwear/sneakers |
| **Too romantic** | Medium | Hard negatives on girlfriend fantasy, flirtation; medium not warm temperature |
| **Too showroom / catalog** | Medium | Avoid fashion editorial framing; 3/4 body not full editorial wide |
| **Too stiff** | Medium | Require visible soft smile + greeting gesture; medium emotional temperature |
| **Background not door-like enough** | Medium–High | Background lock block stresses visible wooden executive door; QA fails if door absent |
| **Outfit too similar to business wardrobe** | Medium | Explicit anti-v4 blocks; off-duty cardigan+blouse+skirt distinct from v4 jacket/suit |
| **Face drift** | Low–Medium | Asset 01 identity reference; post-gen cross-check vs Asset 01 |
| **Prop morphs into tablet** | Medium | Hard negative tablet-at-waist; QA rejects any tablet shape from notebook/handbag |

**Overall drift risk for this candidate:** **low** — appropriate first live candidate.

---

---

## 11. R6B offduty_01 First Canary Failure Note

First live R6B bottom-shot canary — **NOT_ACCEPTED**.

| Field | Value |
|-------|-------|
| **Profile** | `offduty_01_soft_classic_cardigan_silk_blouse` |
| **Output** | `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_101845.jpg` |
| **Reference used** | Asset 01 only — **Asset 02 not attached** |
| **Result** | **NOT_ACCEPTED** |

| QA axis | Outcome |
|---------|---------|
| Background lock | **PASS** |
| Off-duty wardrobe concept | **PARTIAL** |
| No tablet | **PASS** |
| Identity / age / charm | **FAIL** — motherly/older guardian read |
| Full-body proportion anchor | **FAIL** — prompt-only interpretation |

**Reason:** Prompt-only full-body interpretation produced older/motherly impression. Future R6B full-body bottom shots **must use Asset 02 as default silhouette reference**.

**Do not retry offduty_01 immediately.**

---

## 12. Next Candidate Direction

**Next profile:** `offduty_02_elegant_knit_slim_skirt`

| Reason | Detail |
|--------|--------|
| Avoids cardigan motherly risk | Knit + slim skirt reads more modern |
| Better personal charm | Office-appropriate but attractive off-duty silhouette |
| Asset 02 required | Must attach Asset 02 for full-body/3/4 framing — do not use Asset 01-only |

Create new candidate package for `offduty_02` before next one-live-call.

---

## 13. Execution Recommendation

| Step | Status |
|------|--------|
| Design package complete | **Yes** — this document |
| First canary executed | **Yes** — NOT_ACCEPTED |
| Operator review | **Complete** — failure recorded |
| Next candidate | **`offduty_02_elegant_knit_slim_skirt`** — new package required |
| Image generation | **Do not retry offduty_01** |
| Live call policy | **One-live-call only if approved** — Asset 02 default reference |

### Recommended execution sequence (after approval)

1. Operator completes §7 approval fields
2. Confirm prop (handbag vs notebook) and gesture (bow vs hand farewell)
3. Run preflight + dry-run — verify `called_image_api=false`
4. Single guarded one-live-call
5. Output to `output/keysuri_preview/` — QA reference only
6. Complete §8 checklist
7. Record PASS/FAIL in operator log — do not commit JPG

### If QA FAIL

- **Do not retry automatically**
- Document failure mode against §9 risks
- Update this package or select alternate prop/gesture
- New approval required before any subsequent live call

---

## Summary

First R6B candidate **`offduty_01_soft_classic_cardigan_silk_blouse`** first canary **NOT_ACCEPTED** (`keysuri_global_canary_20260605_101845.jpg`). Background lock worked; identity/age/charm failed with Asset 01-only reference. **Policy update:** Asset 02 is default for R6B 3/4 and full-body framing. **Next candidate:** `offduty_02_elegant_knit_slim_skirt` — do not retry offduty_01 immediately.
