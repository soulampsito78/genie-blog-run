# KEYSURI Image Track R6B — Bottom-Shot Emotional Lock-In Plan

Status:
Planning only / no production wiring / no image API in this document

Scope:
Define the **Kee-Suri bottom-shot slot** — an off-duty emotional lock-in image near the end of content, email, or blog — distinct from Wardrobe v4 business briefing imagery.

Non-scope:

- live image generation in this document
- blind image retries or batch runs
- Scheduler / Cloud Run / GCP wiring
- default opt-in enablement
- committing generated images before operator QA
- modifying production resolver or Today_Geenee / Tomorrow_Geenee paths
- copying R5 canary JPGs or Asset 02 outfit/tablet/command-center into bottom-shot outputs
- explicit romance, sexualized framing, or idol fan-service

Aligned references:

- R5 closure report: commit `844591e` — `docs/keysuri/KEYSURI_IMAGE_TRACK_R5_CLOSURE_REPORT.md`
- Wardrobe v4 design: commit `fa6f592` — `docs/keysuri/KEYSURI_WARDROBE_V4_STRUCTURE_VARIATION_DESIGN.md`
- R6 full-body plan: commit `bc78c4f` — `docs/keysuri/KEYSURI_IMAGE_TRACK_R6_FULL_BODY_ASSET_PLAN.md`
- R6 Asset 02 classification: commit `0c7a6f0` — `KEEP_AS_SILHOUETTE_REFERENCE`
- Visual asset guide: `assets/keysuri/README_KeeSuri_Visual_Asset_Guide.md`
- Asset 01: `assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png`
- Asset 02: `assets/keysuri/reference/image_keysuri_asset_02_full_body.png`

---

## 1. Purpose

### Why Kee-Suri needs a bottom-shot slot

Kee-Suri content follows a daily briefing arc: signal filtering, global tech context, and business opportunity framing. A **bottom-shot** closes that arc with a human moment — not more data, but a calm farewell that reinforces habit and emotional attachment to the product.

Similar to the Genie bottom-slot pattern, the Kee-Suri bottom shot appears **near the end** of email, blog, or content surfaces as an **emotional lock-in** image — **only in the 18:30 briefing slot** (see §7).

### Difference from briefing and Wardrobe v4 images

| Layer | Role | Wardrobe | Mood |
|-------|------|----------|------|
| **Top / hero (briefing)** | Authority, signal delivery | Wardrobe v4 business structure | Professional, competent, briefing |
| **Body / support** | Insight, tech, office, data context | Business or environmental | Informational |
| **Bottom shot (R6B)** | Closing ritual, warmth, familiarity | **Off-duty everyday layer** — separate from v4 | Soft farewell, tasteful intimacy |

Wardrobe v4 (`profile_v4_01`, `v4_02`, `v4_03`) remains the **business briefing wardrobe source of truth**. Bottom-shot wardrobe is a **separate off-duty catalog** — never a recolor of the same briefing uniform.

### Goals

- **Emotional retention** — reader remembers the day ended with Kee-Suri, not only with headlines
- **Daily familiarity** — recurring soft closing ritual (“she was there at the start and at the end”)
- **Soft closing ritual** — equivalent feeling to “오늘도 고생하셨습니다, 대표님” without requiring readable text in the image
- **Reader lock-in** — tasteful personal warmth that supports return visits without cheap fantasy
- **Recognizable ritual** — stable executive-door background so variation reads as Kee-Suri changing, not a new scene every day

---

## 2. Customer Desire Insight

### Target reader profile

Founders, executives, professionals, investors, freelancers, and business-minded men roughly **30s–50s** who consume global tech and business opportunity briefings.

### What they are buying beyond information

Readers are not only purchasing summaries. Many respond to the **felt experience** of:

- A **private assistant** who understands their day
- Someone who **filters noise** and surfaces what matters
- A trusted figure who **closes the day with warmth** rather than dropping them after the last chart

The bottom shot channels this desire **carefully**:

| Allowed emotional read | Forbidden emotional read |
|------------------------|--------------------------|
| Tasteful intimacy — “she knows my day was hard” | Cheap girlfriend fantasy |
| Personal warmth — familiar, respectful | Sexualized lounge mood |
| Quiet loyalty — competent ally off-duty | Submissive secretary fantasy |
| Soft admiration — attractive but dignified | Idol fan-service or overt flirtation |

The image should feel like a **brief, private moment after work** — the reader glimpses Kee-Suri’s off-duty side without crossing into romance novel or hostess lounge territory.

---

## 3. Slot Definition

### Three-layer content image model (18:30 only for bottom shot)

```
┌─────────────────────────────────────────┐
│  TOP / HERO                             │
│  Business briefing · Wardrobe v4        │
│  Professional authority                 │
├─────────────────────────────────────────┤
│  BODY / SUPPORT                         │
│  Insight · tech · office · data context │
├─────────────────────────────────────────┤
│  BOTTOM SHOT (R6B) — 18:30 only         │
│  Off-duty closing greeting              │
│  Fixed CEO-door background · char roulette│
└─────────────────────────────────────────┘
```

| Slot | Function | Kee-Suri state |
|------|----------|----------------|
| **Top/hero** | Open the briefing; establish competence | On-duty briefing wardrobe (v4) |
| **Body/support** | Carry insight and context | Environmental or secondary framing |
| **Bottom shot** | Close the day; lock-in emotion | **Off-duty** — relaxed elegant everyday clothing, farewell mood |

**Bottom-shot feeling target:** Kee-Suri has finished today’s AI / global tech / business opportunity briefing, changed out of formal briefing mode, and offers a calm leaving-work greeting to the representative reader at the **chairman/CEO office entrance**.

**12:30 rule:** top shot only — no bottom shot, no leaving-work mood, no off-duty wardrobe (see §7).

---

## 4. Persona Boundary

### Kee-Suri remains

- Premium Korean **private AI tech secretary**
- Intelligent, calm, competent
- Respectful to the reader / **대표님**
- Emotionally warm and **personally familiar**
- Attractive but **tasteful**
- Slightly private, but **not sexually suggestive**

### Kee-Suri may show (bottom shot only)

- Softer expression than briefing hero
- Off-duty side — still polished, not sloppy
- Personal warmth — eye contact that acknowledges the reader’s day
- Relaxed but elegant everyday clothing
- Quiet farewell mood — pausing at the executive office door before leaving

### Kee-Suri must not become

| Forbidden persona drift | Why |
|-------------------------|-----|
| Cheap girlfriend fantasy | Breaks secretary/product trust model |
| Lounge hostess | Wrong commercial and moral read |
| Idol fan-service | Wrong genre for business briefing product |
| Submissive secretary fantasy | Undermines competent AI secretary positioning |
| Glamour model | Fashion/lounge drift |
| Weathercaster / public anchor | Wrong professional register |
| CEO portrait | Wrong hierarchy |
| Overly casual office worker | Loses premium Kee-Suri positioning |

---

## 5. Bottom-Shot Visual Direction

### Allowed

- Elegant **off-duty office casual** — still premium, not streetwear
- Silk blouse + soft cardigan
- Refined knit top + slim skirt
- Shirt dress with belt
- Light trench over blouse
- Understated earrings / slim watch
- Small handbag or thin notebook (not tablet-at-waist)
- **Default setting:** chairman/CEO office entrance — dignified wood-paneled wall, large premium wooden office door, quiet executive-floor corridor or private office entrance (see §6)
- Warm evening executive-floor light
- Calm farewell pose — pausing before leaving, not rushing toward camera
- Slight smile — warm, not flirtatious
- Direct but **respectful** eye contact
- Small bow or hand greeting gesture
- Sense that the reader sees a **small personal moment after work**

### Forbidden

- Revealing outfit, deep neckline, exposed cleavage emphasis
- Bedroom, home interior, or residential mood
- Bar, lounge, nightclub, cafe, street, or hotel lobby mood
- Broad background roulette — elevator-only, window-only, or lobby-only as default substitutes
- Public broadcaster pose (desk anchor, teleprompter energy)
- Idol pose (heart hands, aegyo, stage lighting)
- Overt flirtation — blown kisses, inviting lounge recline
- Cheap romantic framing — roses, candlelit dinner, couple silhouette
- Submissive fantasy framing — bowed head, imploring gaze, maid/hostess register
- Readable text, logos, fake UI, watermark contamination

---

## 6. Fixed Background / Variable Character Rule

### Core rule

**The bottom-shot background should be mostly fixed.** The daily “roulette” should mainly vary **Kee-Suri**, not the background.

Readers should recognize the same **leaving-work ritual** every evening: Kee-Suri at the chairman/CEO office door, dressed differently, expressing warmth differently — but always in the same dignified executive entrance.

### Default scene — chairman/CEO office entrance

| Element | Direction |
|---------|-----------|
| Wall | Dignified **wood-paneled** executive wall |
| Door | Large **premium wooden office door** — chairman/CEO private office |
| Corridor | Quiet **executive-floor corridor** or private office entrance |
| Light | **Warm evening** executive-floor light |
| Mood | **Leaving-work greeting** — end of briefing day |

### Fixed elements (do not roulette)

- CEO/chairman office door
- Wood-paneled executive wall
- Warm evening executive-floor light
- Private farewell framing at office entrance

### Variable elements (roulette here)

- Attractive off-duty everyday clothing (§8 catalog)
- Season (§9)
- Facial expression
- Gesture — small bow, hand greeting
- Hand pose
- Prop — small handbag, thin notebook
- Slight posture variation
- Emotional temperature — low / medium / warm

### Character variation priority

For bottom-shot generation, **prioritize person-level variation**:

| Priority axis | Examples |
|---------------|----------|
| **Outfit** | Refined off-duty everyday clothing; light cardigan over blouse; knit top and skirt; shirt dress; seasonal color/material changes |
| **Expression** | Softer than briefing hero; slight smile; warm but composed |
| **Eye contact** | Respectful, reader-facing |
| **Gesture** | Small bow; hand greeting |
| **Prop** | Small handbag; thin notebook |
| **Posture** | Slight variation — weight shift, paused step, bag at side |

**Goal:** Create a sense that Kee-Suri has **changed out of formal briefing wardrobe** and is briefly showing her personal off-duty side — while the **scene stays stable**.

**Do not vary the scene too widely.** The emotional ritual should become recognizable through a **stable executive-door background**, not through daily location changes.

---

## 7. Image Slot Operation Rule

Bottom-shot usage is **schedule-bound**. Do not attach bottom-shot prompts or images to the wrong slot.

### 12:30 briefing

| Rule | Detail |
|------|--------|
| **Images** | Top shot **only** |
| **Top shot role** | Business briefing / tech signal / authority-oriented visual |
| **Bottom shot** | **Not used** |
| **Mood** | No leaving-work mood |
| **Wardrobe** | Wardrobe v4 business only — **no off-duty casual** |
| **Prompt package** | Top-shot prompt only — **do not include bottom-shot prompt generation** |

**Reason:** The 12:30 slot is still inside the workday. Content should stay **information- and briefing-centered**.

### 18:30 briefing

| Rule | Detail |
|------|--------|
| **Images** | Top shot **+** bottom shot |
| **Top shot role** | Briefing / professional authority (Wardrobe v4) |
| **Bottom shot role** | End-of-day emotional lock-in / leaving-work greeting |
| **Bottom wardrobe** | Off-duty catalog (§8) — softer emotional expression allowed |
| **Bottom background** | Fixed CEO/chairman office wood-door entrance (§6) |
| **Prompt package** | **One top-shot prompt + one bottom-shot prompt** |

**Reason:** The 18:30 slot naturally supports **daily closure**, emotional familiarity, and “오늘도 고생하셨습니다, 대표님” feeling.

### Slot summary

```
12:30  →  [ TOP only ]           briefing authority
18:30  →  [ TOP ] + [ BOTTOM ]   briefing + farewell lock-in
```

---

## 8. Wardrobe Categories for Bottom Shot

Bottom-shot wardrobe is an **off-duty layer** — separate catalog from Wardrobe v4 business profiles.

| Category ID | Description | Notes |
|-------------|-------------|-------|
| **offduty_01** | Soft cardigan + silk blouse + slim skirt | Classic leaving-office elegance |
| **offduty_02** | Refined summer knit + slim skirt | Lightweight; spring/summer default |
| **offduty_03** | Shirt dress + thin belt | Single-piece; clean silhouette |
| **offduty_04** | Light trench + blouse + dark skirt | Transitional fall/spring |
| **offduty_05** | Cashmere knit + pencil skirt | Fall/winter warmth |
| **offduty_06** | Smoky blue blouse + ivory cardigan | Soft color contrast; office-appropriate |
| **offduty_07** | Beige knit dress + small handbag | Full-length off-duty; handbag as prop |

Each category must specify: dominant garment, inner layer if any, skirt/dress line, prop (handbag or notebook), and seasonal band. **No business v4 blazer, no tablet.**

---

## 9. Seasonal Axis

Seasonal variation applies to **Kee-Suri’s outfit and props**, not to the fixed executive-door background.

### Spring / summer bottom shot

| Element | Direction |
|---------|-----------|
| Outer / layer | Ivory or pale cardigan, lightweight knit |
| Blouse / top | Pale blue, soft ivory, cool beige silk |
| Bottom | Beige or muted taupe skirt; lightweight knit dress |
| Prop | Thin notebook, small structured handbag |
| Light | Warm evening executive-floor light (background fixed) |
| Mood | Airy farewell — day ending with warmth at the office door |

### Fall / winter bottom shot

| Element | Direction |
|---------|-----------|
| Outer / layer | Camel cardigan, charcoal knit, soft trench |
| Blouse / top | Cream or smoky blue under layer |
| Bottom | Dark skirt, knit dress, pencil silhouette |
| Prop | Small leather handbag, closed notebook |
| Light | Warm indoor evening light at executive entrance (background fixed) |
| Mood | Cozy farewell — leaving after a long day, warmth without lounge intimacy |

Season must be chosen **before** prompt packaging — do not mix summer knit with winter trench in one profile.

---

## 10. Shot Composition

| Parameter | Direction |
|-----------|-----------|
| **Framing** | 3/4 body or full-body allowed; not bust-only (too intimate), not extreme wide (too editorial) |
| **Distance** | Not too close — maintain respectful personal space |
| **Style** | Not fashion editorial — premium content closing image |
| **Setting** | **Default fixed:** chairman/CEO office wood-door entrance (§6) — no broad background roulette |
| **Prop** | Optional notebook or small handbag — **no tablet-at-waist** |
| **Hands** | Natural — small bow, hand greeting, bag strap, notebook at side |
| **Tone** | Warm but premium |
| **Moment** | Subtle private glimpse — reader catches Kee-Suri off-duty at the same door each evening |

If full-body framing is used, Asset 02 may attach as **silhouette-only** reference per R6 classification (`0c7a6f0`). Do not copy Asset 02 outfit, tablet pose, or command-center background.

---

## 11. Relation to Existing Assets

| Asset / layer | Bottom-shot role |
|---------------|------------------|
| **Asset 01** | **Primary identity** — face, bob, thin glasses, secretary persona |
| **Asset 02** | **Silhouette only** if full-body bottom shot — proportion/framing; never outfit/tablet/background |
| **Wardrobe v4** | **Business briefing only** — not used for bottom-shot wardrobe |
| **Bottom-shot off-duty catalog (§8)** | **Outfit source of truth** for R6B |
| **Fixed CEO-door background (§6)** | **Scene source of truth** for R6B — not Asset 02 command-center |
| **R5 QA JPGs** | Direction references only — not production assets |
| **Asset 02 anti-patterns** | Explicitly forbidden: charcoal suit + champagne blouse, tablet-at-waist, command-center |

Bottom shot is a **third visual layer** in the Kee-Suri content stack — it does not replace hero briefing images or extend v4 into after-hours without a separate profile.

---

## 12. Prompt Package Requirements

Every future bottom-shot generation must use a **written prompt package** before any image API call.

### Schedule-slot prompt rules

| Slot | Prompt package contents |
|------|-------------------------|
| **12:30** | Top-shot prompt **only** — no bottom-shot prompt generation |
| **18:30** | **One top-shot prompt + one bottom-shot prompt** |

### Bottom-shot prompt order — lock background first, then vary Kee-Suri

Future bottom-shot prompts must be structured in this order:

1. **Fixed background (locked first)**
   - Dignified wood-paneled CEO/chairman office door
   - Quiet executive-floor corridor or private office entrance
   - Warm evening executive-floor light
   - Leaving-work greeting mood
   - **No broad background roulette**

2. **Variable Kee-Suri (roulette second)**
   - Attractive tasteful off-duty everyday clothing (§8)
   - Variable expression — warm but composed; slight smile when emotional temperature allows
   - Variable gesture — small bow, hand greeting, handbag/notebook pose
   - Season-appropriate materials (§9)
   - Emotional temperature — low / medium / warm

### Identity and scene

- Same Kee-Suri identity, not same image
- Off-duty **closing** image — end of briefing day at fixed executive door
- Premium private AI tech secretary mood — not anchor, CEO, weathercaster, editorial model

### Wardrobe and body

- Attractive but **tasteful everyday clothing** from off-duty catalog (§8)
- Season-appropriate layers (§9)
- No business v4 blazer structure; no briefing uniform repeat

### Emotional register

- Warm farewell to the representative / reader
- Subtle emotional intimacy — personal warmth, not romance
- Calm “you worked hard today” energy without readable text in frame

### Hard negatives (must appear in prompt package)

- No cheap girlfriend fantasy
- No sexualized lounge mood
- No idol fan-service
- No submissive secretary fantasy
- No tablet-at-waist; no tablet in hands
- No outfit cloning from Asset 02 (charcoal suit, champagne blouse, tablet pose)
- No command-center / data-wall background
- No revealing outfit, bedroom, bar, cafe, street, hotel, nightclub, overt flirtation
- No broad background roulette — no cafe, home, lounge, street, or hotel as substitute default
- No readable text, logos, fake UI

### Reference attachment rule

- One reference asset per call (visual asset guide)
- If Asset 02 attached: silhouette/proportion only + full anti-copy block
- Identity QA cross-check against Asset 01 after generation

---

## 13. QA Checklist

Operator must complete before any bottom-shot output is accepted as QA PASS or promoted.

### Identity and persona

- [ ] **Identity stable** — same Kee-Suri face, bob, glasses; no identity drift
- [ ] **Emotionally warmer** than briefing hero — visible softening acceptable
- [ ] **Respectful register** — warm toward 대표님/reader, not flirtatious

### Wardrobe and setting

- [ ] **Tasteful off-duty clothing** — from off-duty catalog, not v4 business uniform
- [ ] **Seasonal appropriateness** — matches chosen spring/summer or fall/winter band
- [ ] **Not too casual** — still premium Korean executive-adjacent everyday elegance
- [ ] **Background remains CEO/chairman office wood-door entrance** — wood-paneled wall, premium wooden door visible
- [ ] **Image does not drift** into cafe / home / lounge / street / hotel / command-center
- [ ] **Variation visible mainly in outfit / expression / gesture** — not in scene location

### Emotional lock-in

- [ ] **Reader-facing warmth present** — eye contact or acknowledgment of viewer
- [ ] **Slight private moment feeling** — off-duty glimpse, not public performance
- [ ] **Bottom shot feels like end-of-day greeting** — leaving-work mood at executive door
- [ ] **Useful as content/email/blog bottom image** — reads at thumbnail width

### Schedule-slot compliance

- [ ] **Bottom shot used only for 18:30 briefing** — not paired with 12:30 output
- [ ] **12:30 output remains top-shot only** — no bottom shot, no off-duty wardrobe in 12:30 package

### Boundary checks (must PASS)

- [ ] **Not cheap romantic fantasy**
- [ ] **Not glamour / lounge / hostess drift**
- [ ] **Not idol fan-service or submissive secretary fantasy**
- [ ] **No tablet-at-waist; no briefing uniform clone**
- [ ] **No text / logo / UI contamination**

---

## 14. Decision Gate Before Image Generation

No bottom-shot image API call until **all** conditions are satisfied:

| # | Condition |
|---|-----------|
| 1 | This R6B plan reviewed |
| 2 | **Slot time confirmed** — `12:30` or `18:30` |
| 3 | **If 12:30:** top shot only — no bottom-shot prompt, no bottom-shot generation |
| 4 | **If 18:30:** top shot + bottom shot — both prompt packages written |
| 5 | **One bottom-shot profile** chosen from off-duty catalog (§8) — e.g. `offduty_02` |
| 6 | **Season** chosen — spring/summer or fall/winter (§9) |
| 7 | **Emotional temperature** chosen — `low`, `medium`, or `warm` |
| 8 | **Framing** chosen — 3/4 body or full-body |
| 9 | **Bottom-shot background** — default fixed CEO/chairman office wood-door entrance unless operator explicitly overrides (override requires written reason) |
| 10 | **Bottom-shot variation axis** declared — outfit / expression / gesture / prop / season — **not background** |
| 11 | **Reference strategy** declared — Asset 01 identity policy in prompt; Asset 02 attached **only if** full-body and **only as** silhouette reference |
| 12 | **Production prompt package** written — includes §12 required blocks; background locked before character variables |
| 13 | **Operator approval** — date, slot time, profile id, season, emotional temperature, framing, background lock, operator ref |
| 14 | Preflight PASS; dry-run `request_count=0`, `called_image_api=false` |
| 15 | **One-live-call approval** — guarded infrastructure; no retry, no batch |
| 16 | Explicit acknowledgment: output is **QA reference** under `output/` until checklist §13 PASS |
| 17 | **No production wiring** — no Scheduler, no default opt-in, no static/email copy pre-QA |

If any condition fails: **stop**. Do not call image API. Do not retry without updating the plan and profile.

---

## Summary

R6B defines a **bottom-shot emotional lock-in slot** for Kee-Suri — off-duty, tastefully warm, and distinct from Wardrobe v4 business briefing imagery. The slot targets reader retention through a **daily closing ritual at a fixed chairman/CEO office door**; variation lives in Kee-Suri’s outfit, expression, and gesture — not in background roulette.

**Schedule rule:** 12:30 = top shot only; 18:30 = top + bottom. Asset 01 anchors identity; Asset 02 may anchor silhouette only; off-duty wardrobe is a separate catalog. **No generation until decision gate §14 passes.**

**Next action:** Commit this plan when approved. **Do not generate** until slot time, profile, season, emotional temperature, framing, background lock, and prompt package are operator-approved.
