# GENIE — today_genie email image character lock

**Purpose:** One visual identity across `GENIE_EMAIL_today_genie_top_v{1,2,3}.jpg` and `GENIE_EMAIL_today_genie_bottom_v{1,2,3}.jpg`. All image prompts and regenerations must paste the **LOCK BLOCK** verbatim before the shot-specific line.

## Identity-only principle (2026-04 contract — server-enforced suffix)

- **Fixed (continuity only):** same premium Korean woman; same recognizable **face family**; same **hair identity** (long dark-brown soft waves); same late-20s age read; same trustworthy Genie brand tier.
- **Explicitly NOT fixed:** outfit, blazer, inner blouse, pose, hands, camera distance, background, lighting recipe, body angle, expression template, silhouette recipe.
- **Hard rule:** identity consistency must **never** read as mannequin repetition, catalogue “outfit swap only,” or the same shot reused with a new filename.
- **Intent:** the inbox pair must feel like **the same person in two different lived moments** — not the same doll redressed in one anchor pose. Runtime Vertex appendices live in `image_exec_suffixes.py` (`today_genie_suffix_studio_hero`, `today_genie_suffix_outdoor_daily`) and log per-run wardrobe / pose / scene / camera picks into TPO JSON as `image_prompt_contract`.

## LOCK BLOCK (paste first in every prompt)

```
CHARACTER LOCK — identical woman in all 6 images, zero substitution:
Korean woman, apparent age 28–30, same face every shot. Oval face, defined cheekbones, dark almond eyes, refined nose, full lips with natural rose tint. Hair: dark espresso brown, glossy, side part on subject’s left, polished waves past shoulders — same length and volume in every variant. Slim athletic consistent build (not thin-frail, not heavy), upright posture. Skin: luminous even tone; makeup: defined brows, subtle liner, soft cheek highlight — premium broadcast / editorial standard.

TWO-ZONE WARDROBE FAMILY LOCK — same premium Genie brand world, same woman; split by shot type:

ZONE A — TOP / studio commercial greeting (top_v1–v3 only):
TOP shots are camera-facing commercial greeting images — NOT sterile public-service neutrality, NOT “lecturer” energy. Mandatory: direct eye contact with the lens (viewer connection); camera-facing greeting presence; premium, warm, alive, commercially magnetic, refined (never vulgar). Forbidden for TOP: off-camera gaze; lecturer / presenter hand gestures; explainer poses; frozen polite mask smile as the only emotional read.
Composition (TOP): Allowed — tight portrait, waist-up, 3/4, standing full-body in studio, standing key visual in a premium studio set. NOT required — seated desk-only, upper-body-only crop. Vary framing across top_v1–v3 so the three do not read as one repeated crop.
Wardrobe (TOP): Stay Genie premium anchor brand, but widen the studio closet — ivory, soft white, warm cream, soft beige-white tailoring; inners in powder blue, gray-blue, refined navy, muted beige-blue; premium skirts allowed; premium studio dresses or dress-like formal silhouettes allowed; elegant set styling variation allowed. Do NOT trap TOP into only stiff suit jacket + rigid trousers as the only look. Do NOT drift into cheap officewear or random influencer fashion. Small elegant accessories only.
Accessories: thin chain, pearl or micro studs, optional slim watch — no logo chaos.

ZONE B — BOTTOM / outside-going / lifestyle / human / premium-relatable (bottom_v1–v3 only):
- Richer outdoor closet — NOT “studio blazer pasted outdoors.” Allowed categories include: bright elegant dresses; premium one-piece looks; refined weekend city / terrace / boulevard / rooftop lifestyle outfits; polished activewear or runningwear for rest, pause, or cool-down moments; other premium human-relatable styling that feels closer to real life while staying camera-ready.
- Every outside look must remain: premium, elegant, slim silhouette where appropriate, camera-friendly, clearly the same woman and same brand taste tier as Zone A.
- Forbidden for bottoms: generic commuter-office suit clone; low-end loud athleisure; random influencer or teenager styling; a different persona; outfit variation that breaks brand identity (cheap casual drift, logo chaos, sloppy layers).

Cross-zone: Same identity lock always. TOP = Zone A studio commercial greeting; BOTTOM = Zone B outdoor human closet.

QUALITY BAR: TOP = high-end commercial studio still — click-supporting, warm, camera-magnetic. BOTTOM = premium lifestyle editorial. Cinematic color, strong presence, no text, logo, watermark, UI, collage, split screen.
```

## Shot + wardrobe assignment (paste after LOCK BLOCK; one row per file)

| Asset | Mood / scene rhythm | Wardrobe & composition pick |
|-------|---------------------|----------------------------|
| top_v1 | Strongest **camera-facing greeting hero** — first impression, inbox magnet | Zone A: portrait **or** waist-up; **direct lens eye contact** mandatory; e.g. warm cream tailoring or dress-like studio column + powder-blue inner, or refined skirt suit — premium greeting energy, not frozen neutral |
| top_v2 | **Warm premium studio standing key visual** — commercial breadth | Zone A: **standing 3/4 or full-body** in premium studio set allowed; same direct camera gaze; richer rotation e.g. ivory jacket + fluid skirt, or soft separates — **not** same crop as v1 |
| top_v3 | **Stronger commercial charm** — third studio beat, still greeting | Zone A: distinct from v1–v2 — may be **standing desk-side**, elegant lean, or premium studio pose with **camera-facing** connection; dress / skirt / tailored variation; **no** off-camera stare; **not** identical suit clone of v1 or v2 |
| bottom_v1 | City calm / architecture / release | Zone B: **elegant city-release dress or premium one-piece** — not a studio blazer repeat; refined footwear if visible |
| bottom_v2 | Motion / boulevard / terrace energy | Zone B: **premium terrace or boulevard lifestyle look** (refined separates or elevated day-dress energy) — human-relatable, still expensive and camera-ready |
| bottom_v3 | Terrace / lounge / golden hour OR rest beat | Zone B: **polished runningwear / activewear rest or pause scene**, **or** another premium human-relatable outside look (e.g. elevated lounge co-ord) — never low-end gym cliché |

**Rules:** Tops = Zone A with **mandatory lens eye contact** and **varied crops** (not three identical bust shots). Bottoms = Zone B. No bottom reuses the same Zone B outfit formula as another bottom.

## Wardrobe system (summary)

- **Zone A (tops):** Premium Genie **studio commercial greeting** closet — tailoring plus **skirts**, **studio dresses**, dress-like silhouettes; compositions from tight hero to **standing full-body**; camera-magnetic, not stiff suit-only.
- **Zone B (bottoms):** Outside-going / lifestyle / human — dresses, one-pieces, refined city looks, polished activewear for rest — never cheap casual, never six blazer clones outdoors.

## Regeneration

When replacing assets, regenerate **all six** in one session with the same LOCK BLOCK to minimize drift; apply assignment rows so **TOP** shots differ in **role, crop, and wardrobe rotation** (not three clones), and **BOTTOM** shots stay Zone B-rich.

## Briefing-reactive image mood (no extra slots)

Visual diversity must come from **that day’s briefing meaning**, not from adding more fixed filename slots (which causes roulette repetition).

- The text model JSON includes `image_briefing_mood_state` and `image_mood_basis`, derived from runtime briefing tone (see `prompts.py` / validators).
- Allowed mood states: `risk_heavy_tense`, `optimistic_energetic`, `mixed_cautious`, `soft_lifestyle_human`.
- `image_prompt_studio` / `image_prompt_outdoor` must **encode** the chosen mood in expression temperature, lighting, set/background type, wardrobe category, and pose rhythm.
- The `/images/today_genie` pipeline prepends the mood block to both Vertex image prompts so generation stays aligned with the classified day.

## Hard reset (2026-04) — production rules

- **Hair:** Long, dark, glossy **waves** (same curl family) in every frame — no straight bob in one variant and waves in another.
- **Screens / street:** No legible words, logos, or UI on monitors or signage; blur signage to abstraction.
- **TOP (Zone A):** **Direct camera eye contact** on every top asset; **no** off-camera gaze; allow standing full-body / 3/4 / key visual; allow skirts and studio dresses; forbid lecturer/explainer gestures; aim for **commercial warmth**, not dead PS neutrality.
- **BOTTOM (Zone B):** Outside shots must not all read as the same repeated suit; outdoor closet must not feel empty or blazer-only.

## Proportion and feminine appeal lock (2026-04 patch)

- **Proportion hard lock (top + bottom):** For full-body or strong 3/4 framing, enforce **8.5 to 9-head-tall editorial proportion**.
- **Body-read requirements:** long leg line, high-waist visual balance, long lower-body silhouette, slim but healthy athletic build, elegant vertical posture, clean shoulder line, defined waist through tailoring/silhouette, graceful neck line.
- **Compact-ban:** no short-legged read, no squat body, no compact torso-heavy figure, no boxy silhouette, no childlike proportions.

- **Feminine appeal hard lock:** feminine but premium, refined, realistic, and trustworthy.
- **Attractive but non-sexualized:** appeal comes from confidence, styling, silhouette, gesture, expression, and editorial composition.
- **Face/expression:** soft but alert eyes, composed warmth, subtle vitality, no stiff mannequin expression.

- **Negative lock (absolute):** no cheap glamour, no lingerie, no excessive cleavage, no nightclub styling, no over-sexualized pose.
- **Pose lock (absolute):** no stiff catalogue mannequin pose, no flat symmetrical standing pose.

- **Top application:** keep premium briefing anchor presence; confident and attractive; polished fashion-editorial proportion; professional but not stiff; strong 3/4 or full-body allowed; avoid cropped news-thumb framing that shrinks the figure.
- **Bottom application:** keep daily-life but visibly elegant read; maintain long silhouette even in casual clothing; movement-based pose preferred; not another blazer mannequin; practical but attractive city styling; prefer full-body or medium-wide environmental framing when possible.
