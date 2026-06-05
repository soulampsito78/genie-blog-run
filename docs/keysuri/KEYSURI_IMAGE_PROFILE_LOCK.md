# Kee-Suri Image Profile Lock — Global 12:30 / Korea 18:30

## 1. Purpose

This file locks the accepted Kee-Suri image profile criteria before any production wiring.

It is **not** a runtime file. It is **not** the prompt source of truth by itself (that remains `keysuri_weather_visual_prompt_integration.py` at the commits listed below).

It is a **QA / design lock document** for:

- Future production wiring and scheduler integration
- Manual canary and regression checks
- Reviewer alignment on Global vs Korea separation

Do not treat this document as permission to auto-call the image API or change Cloud Scheduler without explicit approval.

---

## 2. Current locked commits

| Program | Commit | Message |
|---------|--------|---------|
| **Global 12:30** | `0c0d459b427334f2f7e098eb21e662410716fc77` | Add Kee-Suri stable production image prompt profile |
| **Korea 18:30** | `ae0e162148f18a0139bea102af4b6eb1ac98428b` | Add Kee-Suri Korea winter evening image prompt profile |

**Production wiring:** Not connected. Kee-Suri image generation is design-ready / canary-only; `runtime_wiring` remains `none` in gate and canary reports.

**Cloud Scheduler:** Unchanged. No Kee-Suri image jobs wired to production scheduler in these commits.

---

## 3. Fixed Kee-Suri identity

Shared across Global and Korea:

- Same person as reference asset 01 (identity + wardrobe continuity only)
- Refined Korean female **private tech secretary** (테크 비서 키수리)
- Sleek short bob
- Thin metal glasses
- Calm intelligent gaze
- Charcoal fitted suit
- Ivory or cream blouse
- Pencil skirt / refined business silhouette
- Premium private office setting

**Must not become:**

- Public news anchor or announcer
- Weathercaster / weather-presenter styling
- CEO portrait or power-CEO dominance
- Generic office worker
- Fashion model or editorial styling

**Variation policy (R2):** `minimal_micro` — small head angle, gaze, shoulder orientation; do not require large pose or composition change.

---

## 4. Global 12:30 locked profile

| Field | Value |
|-------|--------|
| `program_id` | `keysuri_global_tech` |
| Schedule identity | **12:30 KST** Global Tech |
| Visual mood | Daytime / early afternoon |
| Window / weather | Bright grey overcast or cloudy Seoul office window light; weather affects window light and atmosphere only |
| Briefing mood | Global tech / big tech / AI / platform executive briefing |
| Tablet | **Allowed** — held simply at waist or low chest |
| Hands | Simple edge grip; no pointing, tapping, or stylus |
| Face | Premium, clear, stable |
| Pose policy | `calm_briefing_stable_tablet` |

**Accepted live QA reference (production direction):**

`output/keysuri_preview/image_canary/keysuri_global_canary_20260604_221233.jpg`

---

## 5. Korea 18:30 locked profile

| Field | Value |
|-------|--------|
| `program_id` | `keysuri_korea_tech` |
| Schedule identity | **18:30 KST** Korea Tech |
| Visual mood | **Winter after-sunset** private office (not generic dusk with daylight remaining) |
| Exterior | Sun already set; deep blue-gray Seoul evening city; city lights visible but not flashy |
| Interior | Warm premium office light; subdued but not gloomy |
| Briefing mood | Domestic Korean tech / startup / platform; organized after-work private briefing |
| Tablet | **Optional or absent** |
| Hands | Calmly clasped at waist or simple relaxed posture — information already organized, ready to brief (not handing work to the user) |
| Face | Clearly lit and premium; evening mood must not darken, muddy, or soften the face |
| Pose policy | `calm_briefing_optional_tablet` |

**Accepted live QA reference (production direction):**

`output/keysuri_preview/image_canary/keysuri_korea_canary_20260604_225207.jpg`

---

## 6. Global vs Korea separation rule

| Axis | Global 12:30 | Korea 18:30 |
|------|----------------|-------------|
| Time / light | Daytime, bright grey/cloudy window | Winter after-sunset, deep blue-gray evening city |
| Briefing scope | Global tech executive | Domestic Korean tech / startup / platform |
| Tablet | Allowed, simple waist/low-chest hold | Optional or absent |
| Hands | Simple edge grip on tablet | Calmly clasped or relaxed; ready-to-brief |
| Shared | Same Kee-Suri person, same wardrobe lock, same anti-drift negatives | Same |

**Rules:**

- **Do not average** Global and Korea into one generic Kee-Suri office image.
- **Do not merge** programs in a single prompt or single scheduler job without explicit design.
- **Do not apply** Korea evening / after-sunset mood to Global.
- **Do not apply** Global bright daytime mood to Korea.
- Same person and wardrobe are shared; **time, mood, and prop/posture are separated.**

---

## 7. Accepted reference images

All paths under `output/keysuri_preview/image_canary/` (local, gitignored).

| File | Role |
|------|------|
| `keysuri_global_canary_20260604_221233.jpg` | **Global production accepted** (R2-L) |
| `keysuri_korea_canary_20260604_225207.jpg` | **Korea winter evening accepted** (R3B-2-L) |
| `keysuri_global_canary_20260604_210937.jpg` | Identity baseline support (R1-T1) |
| `keysuri_global_canary_20260604_214828.jpg` | Weather/time ambient support (R1-T4) |

---

## 8. Rejected / caution images

| File | Verdict | Notes |
|------|---------|-------|
| `keysuri_korea_canary_20260604_223121.jpg` | **Rejected** (Korea time separation) | R3-L technical pass; too bright / cloudy daytime / white-night office for winter 18:30. Useful only for no-tablet / clasped-hands discovery. |
| `keysuri_global_canary_20260604_211616.jpg` | **Rejected** | Hand/finger gesture risk |
| `keysuri_global_canary_20260604_214359.jpg` | **Rejected** | Face quality / identity degradation |
| `keysuri_global_canary_20260604_202528.jpg` | **Rejected** | Reference-copy tendency |
| `keysuri_global_canary_20260604_204748.jpg` | **Rejected** | Identity drift |

---

## 9. Hard negative drift list

Block or treat as fail in QA if present visually or in unconstrained prompts:

**Retired / wrong program**

- Tomorrow_Geenee
- Today_Geenee wardrobe logic

**Role / scene drift**

- Public news anchor
- Weathercaster
- Newsroom
- TV studio
- Broadcast desk
- CEO portrait
- Generic office worker
- Fashion editorial
- Hotel lounge
- Bar lounge
- Seductive night scene

**Korea 18:30 time failures**

- Cinematic noir
- Black night
- Bright cloudy daytime (for Korea slot)
- White-night office (for Korea slot)

**Weather / outdoor gear**

- Umbrella
- Raincoat
- Outdoor weather scene (as primary scene)

**Hands / tablet**

- Pointing finger
- Tapping tablet
- Stylus
- Complex exposed fingers
- Hand over tablet screen
- Distorted hands
- Extra fingers

**Identity / quality**

- Different woman with similar clothes only

**Artifacts**

- Readable fake UI text
- Collage / split screen
- **Model-generated watermark / readable logo text** — contamination; distinct from required post-process `MirAI:ON` overlay (contract §10.1)

---

## 9.1 MirAI:ON image watermark policy

**Genie pattern (inspection):** forbid watermark in image prompts; apply `MirAI:ON` by **post-processing overlay** after generation. Kee-Suri adopts the same split with **stricter brand lock**:

| Rule | Detail |
|------|--------|
| Required mark | Visible `MirAI:ON` on raster pixels — top-shot **and** bottom-shot |
| Post-process | Overlay after generation for exact text fidelity |
| Prompt negatives | Keep `no text`, `no logo`, `no watermark`, `no text overlay` in generation prompts |
| HTML §13 footer | Required on HTML surfaces — **does not replace** image watermark |
| Forbidden on Kee-Suri assets | `© Heemang & Tobak`, Today_Geenee, Tomorrow_Geenee |
| Placement | Bottom-right or lower safe area; do not cover face, eyes, hands, tablet, silhouette |

**Current state:** overlay utility **not committed**; canary JPGs under `output/keysuri_preview/image_canary/` are QA references only and may lack overlay until implemented.

**Future candidates:** `keysuri_image_overlay.py`, `tests/test_keysuri_image_overlay.py`, canary runner hook, optional asset manifest (`overlay_applied`, `watermark_text`).

**Non-goal:** File-copy tracking, forensic watermarking, invisible per-download marks — out of scope until preview/output workflow stabilizes.

---

## 10. Production wiring readiness checklist

Use before connecting Kee-Suri image generation to scheduler or production runtime:

- [ ] Confirm active code commit includes Global profile commit `0c0d459`
- [ ] Confirm active code commit includes Korea profile commit `ae0e162`
- [ ] Confirm Global 12:30 uses `keysuri_global_tech`
- [ ] Confirm Korea 18:30 uses `keysuri_korea_tech`
- [ ] Confirm Today_Geenee is not accidentally wired to Kee-Suri image profile
- [ ] Confirm Tomorrow_Geenee is not resurrected
- [ ] Confirm Scheduler remains unchanged until explicit production wiring approval
- [ ] Confirm image API live calls require manual approval in canary mode
- [ ] Confirm generated images remain gitignored
- [ ] Confirm no output images/reports are committed
- [ ] Confirm no secrets/raw provider payloads are saved
- [ ] Confirm top-shot and bottom-shot images receive post-process `MirAI:ON` overlay (§9.1)
- [ ] Confirm watermark does not cover face, hands, tablet, or silhouette
- [ ] Confirm no model-generated watermark contamination
- [ ] Confirm HTML §13 rights footer remains separate from image watermark

---

## 11. Regression QA before any future image prompt change

1. Run targeted tests:
   - `python3 -m unittest tests.test_keysuri_weather_visual_prompt_integration`
   - `python3 -m unittest tests.test_keysuri_image_api_gate`
   - `python3 -m unittest tests.test_keysuri_image_api_canary`
   - `python3 -m unittest tests.test_keysuri_image_provider_contract`
2. Run full discovery: `python3 -m unittest discover -s tests -p 'test_*.py'`
3. Run offline reports:
   - `python3 scripts/build_keysuri_weather_visual_prompt_report.py`
   - `python3 scripts/build_keysuri_image_api_gate_report.py`
4. Run default canary (must stay blocked without approval): `python3 scripts/run_keysuri_image_api_canary.py`
5. Run `python3 scripts/run_keysuri_image_api_canary.py --check-env`
6. Run dry-run for affected program only (example Korea):
   ```bash
   GENIE_KEYSURI_IMAGE_MANUAL_APPROVAL=1 \
   GENIE_KEYSURI_IMAGE_CANARY_PROGRAM=keysuri_korea_tech \
   GENIE_KEYSURI_IMAGE_REFERENCE_ASSET=01 \
   python3 scripts/run_keysuri_image_api_canary.py \
     --manual-approval --program keysuri_korea_tech --reference-asset 01 --dry-run
   ```
7. **Do not run live image** unless explicitly approved (one program, one request).
8. Compare new output against accepted Global/Korea references in §7.
9. **Do not judge solely from report JSON** — inspect the actual image file.

---

## 12. Current status summary

| Item | Status |
|------|--------|
| Global image profile | **Locked** (`0c0d459`, QA `221233.jpg`) |
| Korea image profile | **Locked** (`ae0e162`, QA `225207.jpg`) |
| Production wiring | **Not done** |
| Scheduler | **Unchanged** |
| Output images | **Local / gitignored only** |
| Next possible track | Production wiring design; optional weather-binding context cleanup (legacy “early evening” fragments in Korea append paths) |

---

*Document: GENIE Image Track R4 — profile lock. Last aligned to commits `0c0d459` (Global) and `ae0e162` (Korea).*
