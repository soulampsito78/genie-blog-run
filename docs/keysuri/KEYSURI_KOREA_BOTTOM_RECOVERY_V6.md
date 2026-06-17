# Key-Suri Korea Bottom Recovery — Contract v6

Status: **Patch applied, tests passing, pending QA pilot + owner approval**

## Problem (Contract v5)

Contract v5 bottom-shot builder produced **corporate executive portraits** instead of Key-Suri:

- Identity Gene encoded "quiet authority / processed the room / never performative" → aged-up executive
- Outfit was blazer + mock-neck → corporate uniform
- Negative prompt blocked required traits: satin, smile, gesture
- Camera had 4× anti-body negatives vs 1 positive → headshot
- Missing: secretary role noun, owner relationship, fresh smile, handbag, farewell gesture

QA run 233752 was owner-rejected as complete failure.

## Solution (Contract v6)

Rewrite `keysuri_bottom_shot_prompt_builder.py` with 8-gene assembly:

| Gene | v5 | v6 |
|------|----|----|
| Identity | quiet authority, processed the room | fresh, attractive, magnetic, side-parted bob |
| Role | chairman's office threshold | Key-Suri private AI secretary, 대표님 farewell |
| Expression | (none) | fresh composed smile, not motherly |
| Wardrobe | 12-entry blazer/mock-neck weather map | 8 taste-cluster catalog (A–H), weather as fabric modifier |
| Prop/Gesture | (none) | premium handbag + gentle farewell hand gesture |
| Camera | knee-up + 4× "no full-body" | single knee-up signal, no anti-body stack |
| Negative | blocks satin, smile with teeth, active wave | blocks executive portrait, blazer, mock-neck, motherly smile, headshot crop |

## Files Changed

| File | Change |
|------|--------|
| `keysuri_bottom_shot_prompt_builder.py` | v6 rewrite — 8 genes, taste clusters, retargeted negatives |
| `tests/test_keysuri_bottom_shot_prompt_builder.py` | v6 persona-based tests |
| `scripts/run_keysuri_bottom_shot_qa_pilot_v6.py` | New manual-only runner, PASS/FAIL only |
| `docs/keysuri/KEYSURI_KOREA_BOTTOM_RECOVERY_V6.md` | This document |

## Unchanged (verified)

- `keysuri_service_full_run.py` — not touched
- `admin_store.py` — customer delivery block intact
- `image_generator.py` — not touched
- `keysuri_approved_image_assets.json` — not touched
- Asset01 — still primary identity reference (image input)
- 105936 — still direction reference only (NOT image input)
- `KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED` — remains false
- Scheduler — not touched
- Top image assets — not touched

## Backward Compatibility

- `build_bottom_shot_prompt()` — same required args (`weather_condition`, `temperature_c`, `season`); new optional: `taste_cluster`, `emotional_temperature`, `gesture_variant`
- `build_bottom_shot_prompt_metadata_only()` — same signature, same return keys (`bottom_shot_weather_case`, `bottom_shot_outfit_map_key`, `bottom_shot_weather_outfit_source`, `bottom_shot_prompt_preview`)
- `NEGATIVE_PROMPT_V5` alias kept pointing to v6 content

## Next Steps

1. Owner approves patch → commit + push
2. Run `scripts/run_keysuri_bottom_shot_qa_pilot_v6.py` with `GENIE_VERTEX_PROJECT_ID` — generates max 2 images
3. Owner visual inspection: PASS or FAIL (no CONDITIONAL_PASS)
4. If PASS → deploy, begin customer delivery recovery investigation
5. If FAIL → iterate prompt genes, re-run QA
