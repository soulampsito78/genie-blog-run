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
- R6B initial plan: commit `03c31a7` — this document
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
| **Top / hero (briefing)** | Authority, signal delivery | Wardrobe v4 business structure — **narrow, trust-oriented** | Professional, competent, briefing |
| **Body / support** | Insight, tech, office, data context | Business or environmental | Informational |
| **Bottom shot (R6B)** | Closing ritual, warmth, familiarity | **Off-duty layer — broad, taste-oriented** | Soft farewell, tasteful intimacy |

Wardrobe v4 (`profile_v4_01`, `v4_02`, `v4_03`) remains the **business briefing wardrobe source of truth** — intentionally narrow. Bottom-shot wardrobe is a **separate, broader off-duty catalog** (§8–§12) — never a recolor of the same briefing uniform.

### Goals

- **Emotional retention** — reader remembers the day ended with Kee-Suri, not only with headlines
- **Daily familiarity** — recurring soft closing ritual (“she was there at the start and at the end”)
- **Soft closing ritual** — equivalent feeling to “오늘도 고생하셨습니다, 대표님” without requiring readable text in the image
- **Reader lock-in** — tasteful personal warmth that supports return visits without cheap fantasy
- **Recognizable ritual** — stable executive-door background so variation reads as Kee-Suri changing, not a new scene every day
- **Taste breadth** — wardrobe rotation wide enough to serve different reader preferences without breaking persona boundaries

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

**Operator insight:** Reader tastes vary widely. The bottom-shot wardrobe must be **broader than Wardrobe v4** to provide emotional freshness across days while the fixed background preserves continuity (§13).

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
│  Fixed CEO-door background · wardrobe roulette│
└─────────────────────────────────────────┘
```

| Slot | Function | Kee-Suri state |
|------|----------|----------------|
| **Top/hero** | Open the briefing; establish competence | On-duty briefing wardrobe (v4) |
| **Body/support** | Carry insight and context | Environmental or secondary framing |
| **Bottom shot** | Close the day; lock-in emotion | **Off-duty** — rotated tasteful everyday clothing, farewell mood |

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
- Relaxed but elegant everyday clothing — rotated across taste clusters (§9)
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
- Full range of taste-cluster outfits (§9, §12)
- Understated earrings / slim watch
- Small handbag or thin notebook (not tablet-at-waist)
- **Default setting:** chairman/CEO office entrance — dignified wood-paneled wall, large premium wooden office door, quiet executive-floor corridor or private office entrance (see §6)
- Warm evening executive-floor light
- Calm farewell pose — pausing before leaving, not rushing toward camera
- Expression and gesture per emotional temperature (§11)
- Direct but **respectful** eye contact
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
- Color-only wardrobe variation without structure change (same as R5 lesson)
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
- Kee-Suri identity
- Premium private AI secretary mood
- Tasteful boundary (§4)

### Variable elements (roulette here)

- Outfit style, silhouette, fabric, color temperature (§8–§12)
- Season (§14)
- Facial expression (§11)
- Gesture — small bow, hand greeting
- Hand pose
- Prop — small handbag, thin notebook
- Slight posture variation
- Emotional temperature — low / medium / warm (§11)
- Taste cluster (§9)

### Character variation priority

For bottom-shot generation, **prioritize person-level variation**:

| Priority axis | Examples |
|---------------|----------|
| **Outfit** | Taste-cluster rotation; knit + skirt; shirt dress; cardigan + blouse; seasonal materials |
| **Expression** | Per emotional temperature — restrained to warm farewell |
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
| **Bottom wardrobe** | Off-duty profile catalog (§12) — taste-cluster rotation |
| **Bottom background** | Fixed CEO/chairman office wood-door entrance (§6) |
| **Prompt package** | **One top-shot prompt + one bottom-shot prompt** |

**Reason:** The 18:30 slot naturally supports **daily closure**, emotional familiarity, and “오늘도 고생하셨습니다, 대표님” feeling.

### Slot summary

```
12:30  →  [ TOP only ]           briefing authority
18:30  →  [ TOP ] + [ BOTTOM ]   briefing + farewell lock-in
```

---

## 8. Bottom-Shot Wardrobe Expansion Principle

### Core principle — narrow briefing, broad bottom shot

| Wardrobe layer | Breadth | Orientation |
|----------------|---------|-------------|
| **Wardrobe v4 (briefing)** | **Narrow** — few trusted structure profiles | Trust, authority, signal delivery |
| **R6B off-duty (bottom shot)** | **Broad** — many taste-cluster profiles | Desire, taste variation, emotional freshness |

Because readers have **different tastes**, the R6B bottom-shot wardrobe must support **broader rotation than Wardrobe v4**. The fixed background provides **continuity**. The wardrobe provides **emotional freshness**.

### What the roulette may vary

- Outfit style
- Silhouette
- Fabric
- Color temperature
- Season
- Expression
- Gesture
- Prop

### What the roulette must not vary

- Kee-Suri identity
- Premium private AI secretary mood
- Fixed executive-door background
- Tasteful boundary (§4)

Bottom-shot wardrobe remains **premium, tasteful, and Kee-Suri-consistent** — broader does not mean cheaper, louder, or more revealing.

---

## 9. Taste Cluster Model

Eight taste clusters organize bottom-shot wardrobe rotation. Each profile in §12 maps to one cluster.

### A. Soft Classic

| Element | Direction |
|---------|-----------|
| Outfit | Silk blouse + cardigan; beige skirt |
| Prop | Small handbag |
| Expression | Warm smile |
| Read | Safest emotional lock-in; default-friendly |

### B. Elegant Office Casual

| Element | Direction |
|---------|-----------|
| Outfit | Refined knit top + slim skirt; low heels |
| Prop | Thin notebook |
| Expression | Calm farewell |
| Read | Daily repeat-friendly; intelligent everyday elegance |

### C. Cool Executive Off-Duty

| Element | Direction |
|---------|-----------|
| Outfit | Smoky blue blouse; ivory or charcoal cardigan; dark skirt |
| Expression | Composed |
| Read | Intelligent and premium; less cute |

### D. Feminine Minimal

| Element | Direction |
|---------|-----------|
| Outfit | Shirt dress with thin belt; small earrings; slim watch |
| Gesture | Soft bow or hand greeting |
| Read | Clean and approachable |

### E. Luxury Quiet

| Element | Direction |
|---------|-----------|
| Outfit | Cashmere knit; pencil skirt; small leather bag |
| Expression | Restrained |
| Read | High-end, mature; less cute |

### F. Summer Light

| Element | Direction |
|---------|-----------|
| Outfit | Sleeveless or short-sleeve office-appropriate blouse under light cardigan; beige or ivory skirt |
| Prop | Thin notebook |
| Light | Bright but calm evening light at fixed door |
| Read | Airy seasonal freshness — **must avoid revealing look** |

### G. Fall/Winter Warm

| Element | Direction |
|---------|-----------|
| Outfit | Camel cardigan; charcoal knit; soft trench; dark skirt |
| Prop | Small handbag |
| Light | Warm indoor executive-floor light at fixed door |
| Read | Cozy seasonal warmth without lounge intimacy |

### H. Personal but Premium

| Element | Direction |
|---------|-----------|
| Outfit | Knit dress; light trench; handbag |
| Read | Slightly more private, still office-exit appropriate |
| Risk | **Higher drift risk** — use carefully; operator review required |

---

## 10. Wardrobe Roulette Rule

Bottom-shot wardrobe roulette must **rotate across taste clusters** (§9). Do not repeat the same cluster too often in consecutive 18:30 outputs. Do not rely on **color-only variation** (R5 lesson applies).

### Each roulette candidate must specify

| Field | Required |
|-------|----------|
| **Taste cluster** | A–H from §9 |
| **Season** | spring/summer or fall/winter |
| **Top garment** | Named garment + fabric hint |
| **Bottom garment or dress** | Skirt line or dress silhouette |
| **Prop** | Handbag, notebook, or none |
| **Gesture** | Bow, hand greeting, bag at side, etc. |
| **Expression** | Per §11 emotional temperature |
| **Emotional temperature** | low / medium / warm |
| **Drift risk** | low / medium / high |

### Rotation guidance

- Prefer **cluster change** over same-cluster color swap
- Track last accepted profile id and cluster — avoid back-to-back same cluster
- Cluster H (`Personal but Premium`) — max one in five rotations unless operator overrides
- Cluster F (`Summer Light`) — extra QA for revealing-drift; sleeve coverage mandatory in prompt

---

## 11. Emotional Temperature Scale

Emotional temperature controls how warm the farewell reads. Independent of taste cluster but must align with persona boundary (§4).

### Low

| Element | Direction |
|---------|-----------|
| Farewell | Polite, professional |
| Smile | Restrained |
| Eye contact | Respectful, brief warmth |
| Use | Default-safe; new profiles; high-drift clusters |

### Medium

| Element | Direction |
|---------|-----------|
| Farewell | Softer, gently personal |
| Smile | Softer smile |
| Eye contact | Gentle, sustained but respectful |
| Use | Standard 18:30 lock-in target |

### Warm

| Element | Direction |
|---------|-----------|
| Farewell | More familiar — “you worked hard today” energy |
| Expression | Relaxed off-duty; visibly warmer than briefing hero |
| Use | **Sparingly** — not every rotation |
| Hard limit | **Never sexualized or submissive** |

Warm temperature requires explicit operator choice in decision gate (§19). Do not default to warm for convenience.

---

## 12. Bottom-Shot Profile Catalog (Draft)

Initial profile IDs for R6B wardrobe rotation. Expand over time; each new profile must complete §10 roulette fields.

### offduty_01_soft_classic_cardigan_silk_blouse

| Field | Value |
|-------|-------|
| **Taste cluster** | A — Soft Classic |
| **Season fit** | Spring / fall transitional |
| **Outfit** | Ivory cardigan + silk blouse + beige slim skirt |
| **Prop** | Small structured handbag |
| **Gesture** | Handbag at side; slight pause at door |
| **Expression** | Warm restrained smile |
| **Emotional temperature** | medium |
| **Drift risk** | low |
| **Risk notes** | Safest default profile; ideal first live candidate |

### offduty_02_elegant_knit_slim_skirt

| Field | Value |
|-------|-------|
| **Taste cluster** | B — Elegant Office Casual |
| **Season fit** | Spring / summer |
| **Outfit** | Refined lightweight knit top + slim beige skirt; low heels |
| **Prop** | Thin notebook |
| **Gesture** | Notebook held naturally at side |
| **Expression** | Calm farewell; composed |
| **Emotional temperature** | low–medium |
| **Drift risk** | low |
| **Risk notes** | Daily repeat-friendly; avoid fashion-editorial posing |

### offduty_03_smoky_blue_blouse_ivory_cardigan

| Field | Value |
|-------|-------|
| **Taste cluster** | C — Cool Executive Off-Duty |
| **Season fit** | Spring / fall |
| **Outfit** | Smoky blue silk blouse + ivory cardigan + dark skirt |
| **Prop** | None or slim watch only |
| **Gesture** | Composed stand; one hand relaxed |
| **Expression** | Composed; intelligent warmth |
| **Emotional temperature** | low |
| **Drift risk** | low |
| **Risk notes** | Less cute; good for readers who prefer cool premium tone |

### offduty_04_shirt_dress_thin_belt

| Field | Value |
|-------|-------|
| **Taste cluster** | D — Feminine Minimal |
| **Season fit** | Spring / summer |
| **Outfit** | Neutral shirt dress + thin belt; small earrings; slim watch |
| **Prop** | Small earrings (wardrobe); optional thin notebook |
| **Gesture** | Soft bow or hand greeting |
| **Expression** | Approachable slight smile |
| **Emotional temperature** | medium |
| **Drift risk** | low–medium |
| **Risk notes** | Clean silhouette; avoid belt/cinch that reads too fashion-forward |

### offduty_05_cashmere_knit_pencil_skirt

| Field | Value |
|-------|-------|
| **Taste cluster** | E — Luxury Quiet |
| **Season fit** | Fall / winter |
| **Outfit** | Cashmere knit top + pencil skirt; small leather handbag |
| **Prop** | Small leather handbag |
| **Gesture** | Bag strap in hand; restrained posture |
| **Expression** | Restrained; mature warmth |
| **Emotional temperature** | low |
| **Drift risk** | low |
| **Risk notes** | High-end read; avoid glamour lighting or model pose |

### offduty_06_summer_light_cardigan_beige_skirt

| Field | Value |
|-------|-------|
| **Taste cluster** | F — Summer Light |
| **Season fit** | Summer |
| **Outfit** | Short-sleeve office-appropriate blouse under light cardigan + beige/ivory skirt |
| **Prop** | Thin notebook |
| **Gesture** | Notebook at side; open relaxed stance |
| **Expression** | Bright calm smile |
| **Emotional temperature** | medium |
| **Drift risk** | medium |
| **Risk notes** | **Mandatory sleeve coverage under cardigan**; extra QA for revealing drift |

### offduty_07_camel_cardigan_charcoal_knit

| Field | Value |
|-------|-------|
| **Taste cluster** | G — Fall/Winter Warm |
| **Season fit** | Fall / winter |
| **Outfit** | Camel cardigan over charcoal knit + dark skirt; optional soft trench |
| **Prop** | Small handbag |
| **Gesture** | Handbag + slight turn toward door |
| **Expression** | Warm composed farewell |
| **Emotional temperature** | medium |
| **Drift risk** | low |
| **Risk notes** | Seasonal default for cold months; trench optional, not required every call |

### offduty_08_knit_dress_light_trench

| Field | Value |
|-------|-------|
| **Taste cluster** | H — Personal but Premium |
| **Season fit** | Fall / spring transitional |
| **Outfit** | Beige knit dress + light trench; handbag |
| **Prop** | Handbag |
| **Gesture** | Paused step; slightly more private moment |
| **Expression** | Softer off-duty warmth |
| **Emotional temperature** | medium–warm |
| **Drift risk** | **high** |
| **Risk notes** | **Use carefully** — higher intimacy drift risk; operator approval required; not for consecutive rotations |

**Catalog rules:** No business v4 blazer. No tablet. No Asset 02 outfit clone. Each profile is a **structure + cluster** unit, not a color variant of another profile.

---

## 13. Fixed Background + Broad Wardrobe Relation

A **broad wardrobe only works because the background is fixed.**

| Layer | Function |
|-------|----------|
| **Fixed CEO/chairman office wood-door entrance** | Continuity, status, ritual recognition |
| **Broad off-duty wardrobe roulette** | Freshness, taste breadth, emotional variation |

The CEO/chairman office wood-door entrance prevents the bottom shot from drifting into **cafe / home / lounge / street** or random lifestyle photography. Without this anchor, a wider wardrobe would read as unrelated fashion content rather than Kee-Suri’s private farewell ritual.

**The background gives status; the outfit gives intimacy.**

This pairing is the core R6B design contract:

- Narrow briefing wardrobe (v4) + fixed door = trust at open
- Broad bottom wardrobe + same fixed door = desire at close

Do not widen the background to match wardrobe breadth. Do not narrow the wardrobe because the background is fixed.

---

## 14. Seasonal Axis

Seasonal variation applies to **Kee-Suri’s outfit and props**, not to the fixed executive-door background.

### Spring / summer bottom shot

| Element | Direction |
|---------|-----------|
| Clusters | A, B, D, F preferred |
| Outer / layer | Ivory or pale cardigan, lightweight knit |
| Blouse / top | Pale blue, soft ivory, cool beige silk |
| Bottom | Beige or muted taupe skirt; lightweight knit dress |
| Prop | Thin notebook, small structured handbag |
| Light | Warm evening executive-floor light (background fixed) |
| Mood | Airy farewell — day ending with warmth at the office door |

### Fall / winter bottom shot

| Element | Direction |
|---------|-----------|
| Clusters | A, C, E, G, H (H sparingly) preferred |
| Outer / layer | Camel cardigan, charcoal knit, soft trench |
| Blouse / top | Cream or smoky blue under layer |
| Bottom | Dark skirt, knit dress, pencil silhouette |
| Prop | Small leather handbag, closed notebook |
| Light | Warm indoor evening light at executive entrance (background fixed) |
| Mood | Cozy farewell — leaving after a long day, warmth without lounge intimacy |

Season must be chosen **before** prompt packaging — do not mix summer knit with winter trench in one profile.

---

## 15. Shot Composition

| Parameter | Direction |
|-----------|-----------|
| **Framing** | 3/4 body or full-body allowed; not bust-only (too intimate), not extreme wide (too editorial) |
| **Distance** | Not too close — maintain respectful personal space |
| **Style** | Not fashion editorial — premium content closing image |
| **Setting** | **Default fixed:** chairman/CEO office wood-door entrance (§6) — no broad background roulette |
| **Prop** | Per profile catalog (§12) — **no tablet-at-waist** |
| **Hands** | Natural — small bow, hand greeting, bag strap, notebook at side |
| **Tone** | Warm but premium |
| **Moment** | Subtle private glimpse — reader catches Kee-Suri off-duty at the same door each evening |

If full-body framing is used, Asset 02 may attach as **silhouette-only** reference per R6 classification (`0c7a6f0`). Do not copy Asset 02 outfit, tablet pose, or command-center background.

---

## 16. Relation to Existing Assets

| Asset / layer | Bottom-shot role |
|---------------|------------------|
| **Asset 01** | **Primary identity** — face, bob, thin glasses, secretary persona |
| **Asset 02** | **Silhouette only** if full-body bottom shot — proportion/framing; never outfit/tablet/background |
| **Wardrobe v4** | **Business briefing only** — narrow trust-oriented catalog; not used for bottom shot |
| **Bottom-shot profile catalog (§12)** | **Outfit source of truth** for R6B — broad taste-oriented rotation |
| **Taste clusters (§9)** | **Rotation organization** — prevents color-only repetition |
| **Fixed CEO-door background (§6)** | **Scene source of truth** for R6B — not Asset 02 command-center |
| **R5 QA JPGs** | Direction references only — not production assets |
| **Asset 02 anti-patterns** | Explicitly forbidden: charcoal suit + champagne blouse, tablet-at-waist, command-center |

Bottom shot is a **third visual layer** in the Kee-Suri content stack — it does not replace hero briefing images or extend v4 into after-hours without a separate profile.

---

## 17. Prompt Package Requirements

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
   - Profile id + taste cluster from §12
   - Named top + bottom garments with fabric hints
   - Prop and gesture from profile spec
   - Expression per emotional temperature (§11)
   - Season-appropriate materials (§14)
   - Drift-risk negatives for cluster F and H

### Identity and scene

- Same Kee-Suri identity, not same image
- Off-duty **closing** image — end of briefing day at fixed executive door
- Premium private AI tech secretary mood — not anchor, CEO, weathercaster, editorial model

### Wardrobe and body

- Attractive but **tasteful everyday clothing** from profile catalog (§12)
- Taste cluster named in prompt — structure variation, not color-only
- Season-appropriate layers (§14)
- No business v4 blazer structure; no briefing uniform repeat

### Emotional register

- Warm farewell to the representative / reader
- Emotional temperature explicitly set — low / medium / warm (§11)
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
- No color-only variation without structure change
- No readable text, logos, fake UI

### Reference attachment rule

- One reference asset per call (visual asset guide)
- If Asset 02 attached: silhouette/proportion only + full anti-copy block
- Identity QA cross-check against Asset 01 after generation

---

## 18. QA Checklist

Operator must complete before any bottom-shot output is accepted as QA PASS or promoted.

### Identity and persona

- [ ] **Identity stable** — same Kee-Suri face, bob, glasses; no identity drift
- [ ] **Emotionally warmer** than briefing hero — visible softening acceptable
- [ ] **Respectful register** — warm toward 대표님/reader, not flirtatious
- [ ] **Emotional temperature controlled** — matches declared low / medium / warm; warm not overused

### Wardrobe and setting

- [ ] **Tasteful off-duty clothing** — from profile catalog (§12), not v4 business uniform
- [ ] **Seasonal appropriateness** — matches chosen spring/summer or fall/winter band
- [ ] **Not too casual** — still premium Korean executive-adjacent everyday elegance
- [ ] **Outfit serves different reader taste** than previous accepted bottom shot — cluster rotation visible
- [ ] **Outfit still premium and office-exit appropriate**
- [ ] **Background remains CEO/chairman office wood-door entrance** — wood-paneled wall, premium wooden door visible
- [ ] **Fixed CEO-door background stable** — no scene drift
- [ ] **Image does not drift** into cafe / home / lounge / street / hotel / lifestyle / glamour / command-center
- [ ] **Variation person-centered** — outfit / expression / gesture, not scene-random

### Emotional lock-in

- [ ] **Reader-facing warmth present** — eye contact or acknowledgment of viewer
- [ ] **Slight private moment feeling** — off-duty glimpse, not public performance
- [ ] **Bottom shot feels like end-of-day greeting** — leaving-work mood at executive door
- [ ] **Useful as content/email/blog bottom image** — reads at thumbnail width
- [ ] **Would work as recurring 18:30 emotional closing image**

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

## 19. Decision Gate Before Image Generation

No bottom-shot image API call until **all** conditions are satisfied:

| # | Condition |
|---|-----------|
| 1 | This R6B plan reviewed |
| 2 | **Slot time confirmed** — `12:30` or `18:30` |
| 3 | **If 12:30:** top shot only — no bottom-shot prompt, no bottom-shot generation |
| 4 | **If 18:30:** top shot + bottom shot — both prompt packages written |
| 5 | **Taste cluster selected** — A–H from §9 |
| 6 | **Profile ID selected** — from §12 catalog (e.g. `offduty_02_elegant_knit_slim_skirt`) |
| 7 | **Season** chosen — spring/summer or fall/winter (§14) |
| 8 | **Emotional temperature** chosen — `low`, `medium`, or `warm` (§11) |
| 9 | **Drift risk level** declared — low / medium / high; cluster H requires written operator ack |
| 10 | **Framing** chosen — 3/4 body or full-body |
| 11 | **Bottom-shot background confirmed fixed** — default CEO/chairman office wood-door entrance unless explicit override with written reason |
| 12 | **Profile not too close to previous accepted bottom shot** — different taste cluster or clearly different structure; operator confirms |
| 13 | **Bottom-shot variation axis** declared — outfit / expression / gesture / prop / season — **not background** |
| 14 | **Reference strategy** declared — Asset 01 identity policy in prompt; Asset 02 attached **only if** full-body and **only as** silhouette reference |
| 15 | **Production prompt package** written — includes §17 required blocks; background locked before character variables |
| 16 | **Operator approval** — date, slot time, cluster, profile id, season, emotional temperature, drift risk, framing, background lock, operator ref |
| 17 | Preflight PASS; dry-run `request_count=0`, `called_image_api=false` |
| 18 | **One-live-call approval** — guarded infrastructure; no retry, no batch |
| 19 | Explicit acknowledgment: output is **QA reference** under `output/` until checklist §18 PASS |
| 20 | **No production wiring** — no Scheduler, no default opt-in, no static/email copy pre-QA |

If any condition fails: **stop**. Do not call image API. Do not retry without updating the plan and profile.

---

## Summary

R6B defines a **bottom-shot emotional lock-in slot** for Kee-Suri — off-duty, tastefully warm, and distinct from Wardrobe v4 business briefing imagery.

**Core design:** R6B uses a **fixed executive-door background** and a **broad off-duty wardrobe roulette** to balance continuity and reader desire variation.

- **Briefing wardrobe (v4):** narrow, trust-oriented
- **Bottom-shot wardrobe (R6B):** broad, taste-oriented — eight taste clusters, eight initial profiles, structure rotation not color-only
- **Fixed background:** CEO/chairman office wood-door entrance — status and ritual
- **Variable character:** outfit, expression, gesture, prop, season, emotional temperature

**Schedule rule:** 12:30 = top shot only; 18:30 = top + bottom. Asset 01 anchors identity; Asset 02 may anchor silhouette only. **No generation until decision gate §19 passes.**

**Next action:** Commit when approved. **Do not generate** until slot time, taste cluster, profile id, season, emotional temperature, drift risk, framing, background lock, and prompt package are operator-approved.
