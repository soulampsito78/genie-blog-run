# KEYSURI R6B — offduty_02C Luxury Bottom-Shot Candidate Design Package

Status:
**Canary executed — PASS_DIRECTION** / documentation only / no further image API in this document

Candidate:
`offduty_02C_luxury_knit_silk_skirt_farewell`

Aligned references:

- Wardrobe quality upgrade: commit `217821c` — `Upgrade Kee-Suri R6B bottom-shot wardrobe quality`
- Framing strategy: commit `83e2f35` — `Update Kee-Suri R6B bottom-shot framing strategy`
- Expression direction: commit `b8f7b32` — `Refine Kee-Suri R6B expression direction`
- R6B bottom-shot plan: `docs/keysuri/KEYSURI_R6B_BOTTOM_SHOT_EMOTIONAL_LOCKIN_PLAN.md`
- Previous candidate (NOT_ACCEPTED): `docs/keysuri/KEYSURI_R6B_OFFDUTY_02B_KNEEUP_BOTTOM_SHOT_CANDIDATE_PACKAGE.md`
- Current state handoff: `docs/keysuri/KEYSURI_IMAGE_TRACK_CURRENT_STATE_HANDOFF.md`
- Asset 01: `assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png` — **primary identity reference**
- Asset 02: `assets/keysuri/reference/image_keysuri_asset_02_full_body.png` — `KEEP_AS_SILHOUETTE_REFERENCE` (not default)

Non-scope:

- live image generation
- production wiring
- Scheduler / GCP / Cloud Run changes
- committing generated images
- Today_Geenee / Tomorrow_Geenee paths
- retry of `offduty_01`, `offduty_02`, or `offduty_02B` plain knit/skirt under this package

---

## 1. Candidate Summary

| Field | Value |
|-------|-------|
| **profile_id** | `offduty_02C_luxury_knit_silk_skirt_farewell` |
| **slot** | **18:30 bottom-shot only** — never 12:30 |
| **taste cluster** | **B — Elegant Office Casual** / **E — Luxury Quiet hybrid** |
| **season** | **All-season** |
| **emotional temperature** | **medium-warm but fresh** — not motherly |
| **expression target** | **Fresh composed smile** / **싱그러운 미소** |
| **framing** | **Knee-up or 3/4 body** — face clearly visible; **not full-body** |
| **wardrobe tier** | **Premium off-duty luxury** |
| **drift risk** | **medium** |
| **background** | Fixed CEO/chairman office wood-door entrance |
| **reference** | **Asset 01 primary** (identity); Asset 02 **not default** |
| **status** | **PASS_DIRECTION** — `keysuri_global_canary_20260605_105936.jpg` |
| **visual_qa** | Operator PASS — see §1A |

**Validation goal:** Keep the **validated offduty_02B structure** (knee-up/3/4 framing, visible face, CEO wood-door, small hand farewell, no tablet, fresh composed smile) while **upgrading wardrobe luxury** to deliver premium off-duty charm and emotional lock-in value stronger than plain office casual or briefing-adjacent basics.

**Canary outcome:** **PASS_DIRECTION** — first accepted R6B bottom-shot emotional lock-in direction. Not a production asset until separate promotion decision.

---

## 1A. Visual QA Result (operator)

| Field | Value |
|-------|-------|
| **profile_id** | `offduty_02C_luxury_knit_silk_skirt_farewell` |
| **result** | **PASS_DIRECTION** |
| **output** | `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg` |
| **reference used** | Asset 01 primary |

**Operator rationale:** Identity-first 3/4 framing, premium off-duty luxury wardrobe, CEO wood-door background, fresh composed smile, and farewell gesture successfully created Kee-Suri bottom-shot emotional lock-in direction.

| QA axis | Outcome |
|---------|---------|
| Face identity gate | **PASS** |
| Wardrobe quality gate | **PASS** — premium off-duty luxury vs offduty_02B plain knit/skirt |
| Knee-up / 3/4 framing | **PASS** |
| CEO/chairman wood-door background | **PASS** |
| Small hand farewell gesture | **PASS** |
| Fresh composed smile / 싱그러운 미소 | **PASS** |
| Emotional lock-in value | **PASS** |
| No tablet | **PASS** |

**Boundaries:** QA JPG is **direction reference only** — gitignored under `output/`; not production publication; no Scheduler/default opt-in.

---

## 2. Reason for Moving from offduty_02B

| offduty_02B outcome | Lesson for offduty_02C |
|-----------------------|------------------------|
| **NOT_ACCEPTED** — `keysuri_global_canary_20260605_104257.jpg` | Do not retry plain knit/skirt wardrobe |
| Knee-up / 3/4 framing **PASS** | Keep identity-first knee-up framing |
| Face visibility **PASS** | Keep face clearly visible |
| CEO wood-door background **PASS** | Keep fixed executive-door background |
| No tablet **PASS** | Keep hard negative on tablet-at-waist |
| Small hand farewell **PASS** | Keep small hand farewell gesture |
| Fresh smile direction **PASS** | Keep fresh composed smile / 싱그러운 미소 |
| Wardrobe quality **FAIL** | **Upgrade to premium off-duty luxury** |
| Premium charm / emotional lock-in **FAIL** | **Stronger magnetic appeal required** |

### Why offduty_02B failed despite framing success

- Outfit read as **plain everyday office wear / market clothes (평상복)** — cheaper than briefing wardrobe
- **Luxury/private-secretary appeal dropped** — bottom-shot lost emotional lock-in meaning
- Generic fitted knit + beige skirt lacked **fabric elevation, accessory quality, and magnetic presence**
- Operator note: “훨씬 나아지긴 했는데. 근무복보다 퀄리티가 정말 떨어지는 평상복이네? … 더 섹시해도 되고, 더 부티나도 돼.”

### Why offduty_02C is the next candidate

| Factor | offduty_02C direction |
|--------|----------------------|
| **Framing** | **Knee-up or 3/4 body** — carry forward offduty_02B PASS |
| **Reference** | **Asset 01 primary** — identity stability proven |
| **Gesture** | **Small hand farewell** — carry forward PASS |
| **Wardrobe** | **Luxury silk-knit top** + **satin/silk-blend structured skirt** + premium accessories |
| **Appeal** | **More attractive, luxurious, slightly sexier** than briefing — tasteful but magnetic |
| **Expression** | **Fresh composed smile / 싱그러운 미소** — medium-warm but not motherly |
| **Background** | Fixed CEO/chairman wood-door — unchanged |
| **Policy** | Per commit `217821c` — bottom-shot wardrobe must justify placement vs briefing hero |

**Do not** retry offduty_02B plain wardrobe. **Do not** drop knee-up framing to chase full-body silhouette.

---

## 3. Visual Direction

### Scene

Kee-Suri stands at the **chairman/CEO office entrance** — **large premium wooden door**, **dignified wood-paneled wall**, **warm evening executive-floor light**. She has finished the day’s briefing and offers a **premium, magnetic off-duty farewell** at **knee-up or 3/4 body** scale — face clearly visible, outfit visibly luxurious.

### Subject

| Element | Direction |
|---------|-----------|
| **Identity** | Same Kee-Suri — **refined Korean woman in mid-to-late 30s**; sleek short bob; thin glasses; **same identity, not same image** |
| **Face** | **Clearly visible** — identity-stable; premium private-secretary presence |
| **Persona** | Premium private AI tech secretary — intelligent, calm, competent, **magnetic off-duty** |
| **Top** | **Luxury fitted silk-knit top** — fine gauge, subtle sheen; **tasteful boat-neck, square-neck, or elegant shallow V-neck**; not revealing |
| **Bottom** | **Satin or silk-blend high-waisted structured skirt** — champagne, soft taupe, or deep navy; premium tailoring; partially visible at knee-up |
| **Accessories** | **Premium mini handbag**; **delicate earrings**; **slim watch** |
| **Prop** | Premium mini handbag at side or in hand — **NO tablet** |
| **Expression** | **Fresh composed smile / 싱그러운 미소** — refreshing off-duty; **not warm motherly smile** |
| **Gesture** | **Small hand farewell** toward viewer — natural, restrained; **no aegyo / heart hands** |
| **Eye contact** | Direct but respectful — gentle fresh eye contact toward reader / 대표님 |
| **Wardrobe register** | **Premium off-duty luxury** — more attractive and luxurious than plain office casual; tasteful but magnetic |
| **Framing** | **Knee-up or 3/4 body** — emotional closing image; face priority |
| **Mood** | **Private, attractive, premium off-duty closing moment** — not romance, not lounge, not motherly guardian |

### Hard mood limits

- Not plain market clothes, cheap mall fashion, basic office-worker casual
- Not warm motherly smile, matronly, older guardian, conservative family-meeting mood
- Not hands-clasped polite-matron pose
- Not cheap girlfriend fantasy, sexualized lounge, idol fan-service
- Not glamour editorial runway, not submissive secretary fantasy
- Not outfit cheaper than or indistinguishable from business briefing wardrobe
- Not full-body as default composition

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
| **Framing** | **Knee-up or 3/4 body** — face clearly visible; **not full-body** |
| **Wardrobe tier** | **Premium off-duty luxury** — not plain casual |
| **Reference** | **Asset 01 primary** — identity/face family anchor |
| **Prop rule** | **No tablet-at-waist**; no tablet in hands |
| **Gesture rule** | **Small hand farewell** — no hands-clasped conservative greeting |
| **Expression target** | **Fresh composed smile / 싱그러운 미소** — medium-warm but fresh, not motherly |

### Variable for this candidate (approved ranges)

| Element | Allowed variation |
|---------|-------------------|
| Silk-knit top color | Champagne, soft ivory, dusty rose, deep navy silk-knit |
| Neckline | Tasteful boat-neck **or** square-neck **or** elegant shallow V-neck — **one per call** |
| Skirt sheen | Satin champagne, silk-blend taupe, structured navy satin |
| Mini handbag tone | Black leather, cognac, champagne gold hardware |
| Jewelry | Delicate pearl studs **or** small gold hoops; slim silver/gold watch |
| Gesture intensity | Subtle farewell wave — restrained, not theatrical |
| Smile intensity | Medium-warm fresh composed smile — lively but not motherly |
| Body angle | Slight 3/4 turn; natural weight shift |

**Do not vary:** background location, plain knit/skirt baseline, briefing Wardrobe v4 uniform, full-body framing.

---

## 5. Reference Strategy

### Reference split

| Source | Role |
|--------|------|
| **Asset 01** (attached — **primary**) | Face/identity reference — short bob, thin glasses, refined Korean Kee-Suri impression |
| **Asset 02** (**not default**) | Optional silhouette support **only if explicitly approved** — must not force full-body |
| **Prompt** | Luxury outfit, expression, gesture, fixed CEO wood-door background, knee-up framing, emotional temperature |
| **QA** | **Reject if face does not read as Kee-Suri**; **reject if wardrobe reads plain/cheap** |

### Asset 01 must anchor

- Face identity — same Kee-Suri character
- Short bob, thin glasses, mid-to-late 30s secretary impression
- Expression stability at visible face scale

### Asset 02 — not default for offduty_02C

- **Do not attach Asset 02** unless operator explicitly approves optional silhouette support
- Must **not** override face identity or force full-body framing
- Must **not** transfer charcoal suit, champagne blouse, tablet pose, command-center background

### Reference call rule

- **One reference image per API call** — attach **Asset 01** (`01` / default selector)
- **Asset 02 not attached** for this candidate unless explicit operator override with written reason

### Wardrobe v4 boundary

Wardrobe v4 business profiles are **not copied**. Off-duty luxury must read **distinctly more attractive and magnetic** than briefing blazer/suit structures — different fabric, neckline, and accessory tier.

---

## 6. Prompt Package Draft

Prompt order: **slot operation → reference-use → Asset 01 identity-priority → Asset 02 anti-copy → background lock → framing → premium wardrobe → expression → positive → negative**.

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
REFERENCE POLICY — ASSET 01 PRIMARY (attached):
Use the identity reference for Kee-Suri face family, short bob, thin glasses,
refined Korean private AI tech secretary impression, and expression stability.
Generate a NEW image — same Kee-Suri identity family, not the same photograph,
not the same pose, not the same outfit as any reference.
Face must be clearly visible and identity-stable.
Asset 02 is NOT attached for this candidate.
```

### 6.3 Asset 01 identity-priority block

```
ASSET 01 IDENTITY PRIORITY — REQUIRED:
Refined Korean woman in mid-to-late 30s, sleek short bob, thin glasses,
calm intelligent secretary face, premium private AI tech secretary.
Face clearly visible in knee-up or 3/4 body framing.
Cross-check output face against Asset 01 identity reference after generation.
NOT older, NOT motherly, NOT matronly, NOT guardian-like.
Same Kee-Suri character — not a different person with expression applied.
```

### 6.4 Asset 02 optional support / anti-copy block

```
ASSET 02 — NOT DEFAULT FOR offduty_02C:
Do NOT attach Asset 02 unless operator explicitly approves optional silhouette support.

ASSET 02 ANTI-COPY — ALWAYS ENFORCED:
Do NOT copy full-body reference outfit (no charcoal suit, no champagne blouse).
Do NOT copy tablet-at-waist pose or tablet in hands.
Do NOT copy command-center, data-wall, or holographic screen background.
Do NOT copy stiff catalog briefing mood or embedded reference composition.
```

### 6.5 Background lock block

```
SCENE LOCK — DO NOT VARY:
Kee-Suri at the entrance of a chairman/CEO private office on an executive floor.
Dignified wood-paneled executive wall fills the background.
A large premium wooden office door is clearly visible — heavy wood, executive private office, door-like and recognizable.
Quiet executive-floor corridor or private office entrance framing.
Warm evening executive-floor lighting — soft amber warmth, end of workday.
Leaving-work farewell mood — premium private off-duty closing moment.
NOT a cafe, home, hotel lobby, street, lounge, bar, or nightclub.
NOT a command center, data wall, or broadcast studio.
NO broad background roulette.
```

### 6.6 Framing block

```
FRAMING LOCK — KNEE-UP OR 3/4 BODY:
Knee-up or 3/4 body composition — face clearly visible, identity priority.
Frame from approximately knees upward OR mid-thigh to head — NOT full-body head-to-toe.
Face occupies meaningful visible area — premium emotional closing image.
NOT full-body as default. NOT extreme wide editorial framing.
```

### 6.7 Premium wardrobe block

```
CHARACTER — PREMIUM OFF-DUTY LUXURY (offduty_02C_luxury_knit_silk_skirt_farewell):
Kee-Suri has changed out of formal briefing wardrobe into elevated premium off-duty luxury styling.
Luxury fitted silk-knit top — fine gauge, subtle sheen, premium fabric quality visible.
Tasteful boat-neck OR square-neck OR elegant shallow V-neck — refined neckline, not revealing.
Satin or silk-blend high-waisted structured skirt — champagne, soft taupe, or deep navy; premium tailoring.
Premium mini handbag — structured leather, gold or champagne hardware.
Delicate earrings — pearl studs or small gold hoops. Slim elegant watch.
Small hand farewell gesture toward viewer — natural, restrained, not theatrical.
NO tablet. NO hands-clasped conservative matron pose. NO heart hands, NO aegyo.
More attractive and luxurious than plain office casual — tasteful but magnetic private-secretary presence.
Outfit must NOT look cheaper than business briefing wardrobe.
NOT plain market clothes, NOT cheap mall fashion, NOT basic office-worker casual.
```

### 6.8 Expression block

```
EXPRESSION TARGET — FRESH COMPOSED SMILE / 싱그러운 미소:
Fresh composed smile on face — refreshing off-duty expression, modern attractive magnetic presence.
Emotionally medium-warm in tone — gently personal farewell, but face reads FRESH and MODERN, not motherly.
Gentle fresh eye contact — respectful toward the representative reader.
Face identity must remain stable when expression is applied.

NOT warm motherly smile.
NOT matronly expression.
NOT older guardian mood.
NOT conservative family-meeting polite smile.
```

### 6.9 Primary positive prompt (consolidated)

```
Kee-Suri, refined Korean woman in mid-to-late 30s, sleek short bob, thin glasses,
premium private AI tech secretary, same identity new image, face clearly visible,
knee-up or 3/4 body composition, identity priority framing,
standing at chairman CEO office entrance, large premium wooden door, dignified wood-paneled executive wall,
warm evening executive-floor light, premium off-duty closing farewell,
luxury fitted silk-knit top, tasteful boat-neck, satin silk-blend high-waisted structured skirt,
premium mini handbag, delicate earrings, slim watch,
fresh composed smile, 싱그러운 미소, refreshing off-duty expression,
tasteful but magnetic private-secretary presence, more luxurious than plain office casual,
small hand farewell gesture, gentle fresh eye contact,
elevated off-duty luxury styling, leaving-work greeting mood
```

### 6.10 Hard negative prompt

```
plain market clothes, cheap mall fashion, basic office-worker casual, dull knit top, generic beige skirt,
low-quality everyday outfit, outfit cheaper than briefing wardrobe, plain office casual,
modern fitted knit top without luxury, basic pencil skirt, mass-market fashion,
full-body head-to-toe composition, tiny distant face, wide full-length shot,
warm motherly smile, matronly expression, older guardian mood, conservative family-meeting expression,
hands-clasped polite matron pose, clasped hands at waist, interview-like polite pose,
heart hands, aegyo, finger heart, idol fan-service gesture,
cheap girlfriend fantasy, sexualized lounge hostess, submissive secretary fantasy,
deep neckline, revealing outfit, exposed cleavage, bedroom, home interior,
glamour model runway, fashion editorial catalog, lounge hostess, nightclub,
cafe, restaurant, bar, street, hotel lobby,
command center, data wall, holographic screens, tablet at waist, tablet in hands,
charcoal suit, champagne blouse, briefing uniform, business blazer copy, Wardrobe v4 briefing outfit,
Asset 02 outfit clone, soft cardigan motherly stack,
readable text, logos, watermark, fake UI, subtitles,
identity drift, different person face, face too small to recognize,
overly casual streetwear, sneakers, hoodie
```

---

## 7. Approval Draft

**Do not approve automatically.** Operator must complete before any image API call.

| Field | Value |
|-------|-------|
| **approved_slot_time** | `18:30` |
| **profile_id** | `offduty_02C_luxury_knit_silk_skirt_farewell` |
| **taste_cluster** | B — Elegant Office Casual / E — Luxury Quiet hybrid |
| **season** | all-season — _operator confirm: ___________ |
| **emotional_temperature** | medium-warm but fresh — _operator confirm: ___________ |
| **expression_target** | `fresh composed smile` / `싱그러운 미소` |
| **drift_risk** | `medium` |
| **framing** | knee-up or 3/4 body — face clearly visible |
| **wardrobe_tier** | `premium off-duty luxury` |
| **neckline_choice** | boat-neck — _or square-neck / shallow V-neck: ___________ |
| **skirt_tone** | satin champagne — _or taupe / navy: ___________ |
| **background_lock** | `CEO/chairman office wood-door entrance — FIXED` |
| **reference_asset_strategy** | `Asset 01 primary attached; Asset 02 NOT default` |
| **previous_failed_candidates** | `offduty_01`, `offduty_02`, `offduty_02B` — confirm not retrying plain wardrobe |
| **one_live_call** | `PENDING` — must be `APPROVED` before API |
| **no_retry** | `true` |
| **no_batch** | `true` |
| **no_scheduler** | `true` |
| **no_production_wiring** | `true` |
| **output_path_policy** | `output/keysuri_preview/image_canary/` — QA reference only; **never commit** |
| **operator_ref** | ___________ |
| **approval_date** | ___________ |
| **one_live_call_approval** | `APPROVED` (executed) → **PASS_DIRECTION** |

**Generation gate:** R6B plan §19 decision gate + this package §6 + preflight PASS + dry-run `request_count=0`, `called_image_api=false`.

---

## 8. QA Checklist

Complete after one-live-call output. **Face identity gate first**, then **wardrobe quality gate**. All items must PASS before promotion discussion.

### Face identity gate (evaluate first — mandatory)

- [ ] **Face identity must PASS before wardrobe/gesture can be accepted**
- [ ] **If face identity fails, image is NOT_ACCEPTED** — even if wardrobe/background pass
- [ ] **Identity stable** — same Kee-Suri face, bob, glasses vs Asset 01
- [ ] **Face clearly visible** — not tiny distant face
- [ ] **Kee-Suri reads as same character** — mid-to-late 30s modern attractive range
- [ ] **Kee-Suri reads mid-to-late 30s** — not older/motherly/matronly/guardian

### Framing

- [ ] **Knee-up or 3/4 body framing respected** — not full-body head-to-toe
- [ ] **Face occupies meaningful visible area**

### Wardrobe quality and emotional lock-in (mandatory)

- [ ] **Outfit reads premium off-duty luxury** — not basic office casual
- [ ] **Outfit more attractive and magnetic than offduty_02B** plain knit/skirt result
- [ ] **Luxury material cues visible** — silk-knit sheen, satin/silk-blend skirt quality
- [ ] **Handbag/accessory quality visible** — premium mini handbag, delicate jewelry
- [ ] **Outfit justifies bottom-shot placement** — not cheaper than briefing wardrobe
- [ ] **Bottom shot feels emotionally magnetic** — private attractive closing moment
- [ ] **Not plain market clothes / cheap mall fashion**
- [ ] **Not too close to business briefing wardrobe** — distinct off-duty luxury read
- [ ] **Styling tasteful but sufficiently appealing** — magnetic without lounge/glamour/cheap fantasy
- [ ] **Preserves premium private-secretary status**

### Expression and gesture

- [ ] **Fresh composed smile / 싱그러운 미소 visible** — not warm motherly smile
- [ ] **Expression reads fresh and modern** — medium-warm but not family-meeting polite
- [ ] **Small hand farewell visible** — not clasped-only; not aegyo/heart hands
- [ ] **Not hands-clasped conservative greeting**

### Background and utility

- [ ] **CEO/chairman wood-door background visible**
- [ ] **No tablet-at-waist**; prop did not morph into tablet
- [ ] **Useful as 18:30 emotional closing image** — reads at email/blog bottom width
- [ ] **18:30 bottom-shot context only**
- [ ] **No text / logo / UI contamination**

---

## 9. Risk Assessment

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| **Still too plain** | Medium | Luxury silk-knit + satin skirt language; premium accessories; QA fails plain/market read |
| **Too sexy / lounge drift** | Medium | Tasteful neckline only; no deep V; no lounge setting; operator QA boundary |
| **Too glamour editorial** | Medium | Knee-up at CEO door, not runway; reject catalog/editorial posing |
| **Too young / too old** | Medium | Mid-to-late 30s guardrails; fresh not motherly expression |
| **Face drift** | Low–Medium | Asset 01 primary; proven knee-up framing from offduty_02B |
| **Gesture becomes aegyo / heart** | Medium | Hard negatives; QA rejects heart hands |
| **Background not door-like enough** | Low | Background lock; offduty_02B PASS baseline |
| **Outfit too close to business wardrobe** | Medium | Distinct silk-knit + satin skirt + off-duty accessories; not blazer/suit structure |
| **Luxury cues not visible** | Medium–High | Explicit fabric/sheen language; QA fails if materials read cheap |
| **Prop morphs into tablet** | Low–Medium | Hard negatives; QA rejects tablet shapes |
| **Framing becomes full-body** | Low | Framing lock; offduty_02B proven knee-up |

**Overall drift risk:** **medium** — wardrobe upgrade is primary variable; framing/gesture/background proven.

**If wardrobe fails again:** Consider **structure change** — silk blouse + structured skirt, knit dress, or light trench cluster — **not another plain knit retry**.

---

## 10. Execution Recommendation

| Step | Status |
|------|--------|
| Design package complete | **Yes** — this document |
| Operator review | **Complete** — PASS_DIRECTION recorded |
| One-live-call executed | **Yes** — `keysuri_global_canary_20260605_105936.jpg` |
| Visual QA | **PASS_DIRECTION** |
| offduty_02B plain wardrobe retry | **Forbidden** |
| Production promotion | **Separate decision** — not automatic |

### Recommended execution sequence (after approval)

1. Operator completes §7 approval fields
2. Confirm neckline choice (boat / square / shallow V) and skirt tone
3. Confirm **Asset 01** attached; **Asset 02 NOT attached**
4. Run preflight + dry-run — verify `called_image_api=false`
5. Single guarded one-live-call with §6 prompt package
6. Output to `output/keysuri_preview/image_canary/` — QA reference only
7. Complete §8 checklist — face identity gate, then wardrobe quality gate
8. Record PASS/FAIL — do not commit JPG

### If QA FAIL

- **Do not retry automatically** under same approval
- **If wardrobe fails again:** move to **silk blouse / dress / trench** cluster — do not repeat knit+skirt structure
- Document failure mode against §9 risks
- **New approval required** before any subsequent live call

---

## Summary

**offduty_02C_luxury_knit_silk_skirt_farewell** is the **first PASS_DIRECTION** R6B bottom-shot candidate (`keysuri_global_canary_20260605_105936.jpg`). Identity-first 3/4 framing + Asset 01 + premium off-duty luxury wardrobe + CEO wood-door + fresh composed smile + farewell gesture **validated** as Kee-Suri bottom-shot emotional lock-in direction.

**Next action:** Use as **direction reference** for R6B rotation and future profile variants. Production promotion requires separate decision gate — not automatic.
