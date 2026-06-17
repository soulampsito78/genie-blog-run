# KEY-SURI BOTTOM SHOT PROMPT CONTRACT v5

```
status:                  design contract only
generation_allowed:      false
runtime_enabled:         false
customer_delivery_ready: false
owner_approval_required: true
```

---

## Reference Assets

| Asset | Role | Notes |
|-------|------|-------|
| `assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png` | **Primary identity reference** | Face geometry, bob, metal glasses — the ground truth for who Key-Suri is |
| `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg` | **Direction reference only** | Confirms offduty_02C emotional register and PASS_DIRECTION. NOT an image input. NOT a fixed final asset. Do not replicate its silk-knit/satin outfit. |

---

## Section 1 — Master Prompt Contract v5

### Assembly Order (critical — do not reorder)

```
[Scene lock] → [Identity Gene] → [Role/Scene Gene] → [Camera Gene] → [Weather/Outfit Shell] → [Negative]
```

Outfit is always placed last. Putting outfit first causes outfit-first composition and corrupts identity rendering.

---

### A. Fixed Identity Gene (never vary)

```
A Korean woman in her mid-to-late thirties, with a naturally composed face,
slightly angular jaw, almond-shaped eyes with a calm and perceptive gaze,
a clean chin-length bob haircut with subtle volume at the crown,
and thin metal-framed rectangular glasses resting naturally on her face.
Her expression carries quiet authority — emotionally present but never
performative, warm but contained, the look of someone who has already
processed the room.
```

**Invariants:**
- Age: mid-to-late 30s
- Hair: chin-length bob, natural volume, no bangs, no updos, no ponytails
- Glasses: thin metal rectangular frames — always present
- Expression: composed, non-performative, warm gravity
- Ethnicity: Korean woman

---

### B. Fixed Role/Scene Gene (never vary)

```
She is a senior financial technology analyst and trusted briefing host —
the kind of professional whose office exists at the intersection of
precision and warmth. She is between moments: not presenting, not reacting,
simply inhabiting the space with full presence. The environment is upscale
urban professional — a premium office, lobby, or curated interior space
with clean lines, neutral tones, and controlled natural or studio lighting.
No outdoor scenes. No open doors. No full-body framing.
```

**Invariants:**
- Role: senior FinTech analyst / briefing host
- Emotional register: between moments — not performing, not reacting
- Environment: upscale urban interior only
- No outdoor scenes
- No open doors or door frames in background
- No full-body shots

---

### C. Variable Weather/Outfit Shell (changes per weather API call)

```
[WEATHER_OUTFIT_DESCRIPTOR]
```

This slot is filled by the Weather-to-Outfit Mapping Table (Section 3).
The outfit descriptor changes based on live weather data.
**Identity Gene, Role/Scene Gene, and Camera Gene do not change when weather changes.**

---

### D. Camera/Framing Gene (never vary)

```
Framing: upper-body shot, from approximately mid-chest to just above the crown,
centered composition with slight negative space at the top.
Camera angle: eye level or 2–3 degrees above, never below chin level.
Lens: 85mm portrait equivalent, minimal depth of field, subject sharp,
background softly defocused.
No full-body. No waist-down. No wide establishing shots.
```

---

## Section 2 — Negative Prompt v5 (Failure Blocklist)

```
deformed hands, extra fingers, fused fingers, blurry face, asymmetric eyes,
double chin, thick-framed glasses, no glasses, sunglasses, colored glasses,
heavy jewelry, statement necklace, flashy accessories,
casual clothing, streetwear, athletic wear, hoodie, t-shirt, crop top,
low-cut neckline, V-neck wrap dress, open-front dress, satin wrap dress,
silk blouse with plunging neckline,
full body shot, visible legs, visible feet, wide shot, establishing shot,
outdoor scene, open door, door frame visible, window with outdoor view,
overly warm lighting, golden hour, harsh shadows, overexposed face,
performative expression, smile with teeth, surprised expression,
excessive makeup, heavy contouring, dramatic eye makeup,
motion blur, film grain, painterly style, illustration, anime, cartoon
```

**Family A Failure Root (for reference):** V-neck wrap dress + open door + full-body framing were never corrected through v1→v4. These are the top three negative entries and must remain.

---

## Section 3 — Weather-to-Outfit Mapping Table

| Weather Case | Outfit Descriptor |
|---|---|
| **Clear / Sunny (warm, 18°C+)** | A lightweight structured blazer in cream or warm ivory over a fitted silk shell top in champagne or soft nude. The blazer is open, draped with effortless precision. Minimal accessories: small gold stud earrings only. |
| **Clear / Sunny (cool, below 18°C)** | A tailored wool blazer in charcoal or slate over a fine-knit mock-neck sweater in ivory or warm grey. Clean, layered, no visible texture contrast issues. |
| **Partly Cloudy** | A structured jacket in muted camel or stone over a cotton-blend shell top in off-white. Understated, professional, seasonally neutral. |
| **Overcast / Grey** | A collarless structured coat in deep charcoal or navy, worn over a ribbed fine-knit turtleneck in cream. The coat is buttoned at the top third only. No brooch. |
| **Light Rain / Drizzle** | A fitted waterproof shell jacket in deep navy or slate, zipped to mid-chest, over a lightweight knit layer. Clean lines. No hood visible. |
| **Heavy Rain / Storm** | A structured trench coat in classic khaki or dark olive, collar up but not dramatic, over a dark turtleneck. The trench is closed and belted at the waist (waist not visible in frame). |
| **Snow / Cold (below 2°C)** | A premium merino turtleneck in oatmeal or charcoal under a structured wool-cashmere overcoat in camel or deep grey. Coat collar softly framing face. |
| **Humid / Hot (above 28°C)** | A sleeveless structured top in silk-matte finish in warm white or pale champagne, under a very lightweight linen blazer in ecru. Clean and breathable without being casual. |

**Rule:** Weather API changes only the `[WEATHER_OUTFIT_DESCRIPTOR]` slot. Identity Gene, Role/Scene Gene, and Camera Gene are not modified by weather.

---

## Section 4 — Family A v5 Prompt (Example: Autumn Evening, Cluster G)

> This example deliberately uses a structured blazer + fine-knit shell, NOT 105936's silk-knit/satin.
> The purpose is to prove the contract generalizes beyond any single reference image.

### Full assembled prompt:

```
Upper-body portrait, eye-level, 85mm lens, shallow depth of field,
upscale interior office environment with neutral tones and controlled lighting.

A Korean woman in her mid-to-late thirties, with a naturally composed face,
slightly angular jaw, almond-shaped eyes with a calm and perceptive gaze,
a clean chin-length bob haircut with subtle volume at the crown,
and thin metal-framed rectangular glasses resting naturally on her face.
Her expression carries quiet authority — emotionally present but never
performative, warm but contained, the look of someone who has already
processed the room.

She is a senior financial technology analyst and trusted briefing host —
the kind of professional whose office exists at the intersection of
precision and warmth. She is between moments: not presenting, not reacting,
simply inhabiting the space with full presence. The environment is upscale
urban professional — a premium office interior with clean lines, neutral tones,
and warm studio lighting. No outdoor scene. No open doors. No full-body framing.

She wears a tailored charcoal blazer over a fine-knit ivory mock-neck sweater.
The blazer sits cleanly on her shoulders. Small gold stud earrings, nothing else.
The autumn evening light falls evenly on her face from slightly above frame left.

Framing: upper-body shot, from approximately mid-chest to just above the crown,
centered composition with slight negative space at the top.
Camera angle: eye level, lens at 85mm portrait equivalent, subject sharp,
background softly defocused.
```

### Negative prompt:

```
deformed hands, extra fingers, fused fingers, blurry face, asymmetric eyes,
double chin, thick-framed glasses, no glasses, sunglasses, colored glasses,
heavy jewelry, statement necklace, flashy accessories,
casual clothing, streetwear, athletic wear, hoodie, t-shirt, crop top,
low-cut neckline, V-neck wrap dress, open-front dress, satin wrap dress,
silk blouse with plunging neckline,
full body shot, visible legs, visible feet, wide shot, establishing shot,
outdoor scene, open door, door frame visible, window with outdoor view,
overly warm lighting, golden hour, harsh shadows, overexposed face,
performative expression, smile with teeth, surprised expression,
excessive makeup, heavy contouring, dramatic eye makeup,
motion blur, film grain, painterly style, illustration, anime, cartoon
```

---

## Section 5 — Pilot Generation Instruction

```
generation_allowed:   false  (until owner explicitly approves below gate)
images_per_pilot_run: 2
gate:                 R6B §19 — owner must review and sign off before pilot run
reference_for_run:    Asset01 (face/identity anchor), NOT 105936
```

### Gate requirements before any pilot generation:

1. Owner reviews this contract document and confirms all 6 sections
2. Owner explicitly approves pilot run in writing (not implied)
3. Maximum 2 images in pilot run
4. No customer delivery after pilot run — owner review only
5. Korea bottom delivery remains blocked until separate gate

### Do not use:

- 105936 as image input (it is direction reference only)
- Any full-body framing
- Any outdoor environment
- Any V-neck wrap / open-front / satin dress outfit

---

## Section 6 — Review Checklist v5

After each generated image, verify all 5 gates before any approval:

### Gate 1 — Identity

- [ ] Face: angular jaw, almond eyes, calm perceptive gaze — matches Asset01
- [ ] Hair: chin-length bob, natural volume, no bangs, no updo
- [ ] Glasses: thin metal rectangular frames, present and visible
- [ ] Expression: composed, non-performative, warm gravity (not smiling with teeth, not surprised)
- [ ] Age reads: mid-to-late 30s (not younger, not older)

### Gate 2 — Role/Scene

- [ ] Environment: upscale urban interior — premium office, lobby, or curated space
- [ ] No outdoor scene visible
- [ ] No open door or door frame in background
- [ ] Emotional register: between moments, not presenting, not reacting
- [ ] No full-body framing (no visible waist, legs, feet)

### Gate 3 — Camera

- [ ] Framing: upper-body, mid-chest to just above crown
- [ ] Camera angle: eye level or 2–3 degrees above (not below chin)
- [ ] Background: softly defocused (not sharp, not flat)
- [ ] No wide shot, no establishing shot

### Gate 4 — Weather Shell

- [ ] Outfit matches the active weather case from the mapping table
- [ ] Outfit is professional — no casual, streetwear, or athletic wear
- [ ] No V-neck wrap dress, no open-front dress, no satin wrap
- [ ] Identity Gene not distorted by outfit choice

### Gate 5 — Failure Blocklist

- [ ] None of the negative prompt terms are visible in the image
- [ ] No deformed hands (check if hands are in frame)
- [ ] No thick-framed or missing glasses
- [ ] No heavy jewelry or statement accessories
- [ ] No performative expression

---

*Contract authored: 2026-06-17*
*Based on: Key-Suri Visual DNA v1, R6B direction analysis, offduty_02C PASS_DIRECTION (105936)*
*Next gate: R6B §19 owner approval before any pilot generation*
