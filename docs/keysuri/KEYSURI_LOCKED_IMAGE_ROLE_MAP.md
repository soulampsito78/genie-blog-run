# Kee-Suri Locked Image Role Map

Status: **Locked** role alignment (2026-06-08).

## Canonical locked assets

| Role | Asset ID | File | Program | Slot |
|------|----------|------|---------|------|
| **global_top** | `keysuri_global_top_20260604_221233` | `output/keysuri_preview/image_canary/keysuri_global_canary_20260604_221233.jpg` | `keysuri_global_tech` | 12:30 |
| **korea_top** | `keysuri_korea_top_20260604_225207` | `output/keysuri_preview/image_canary/keysuri_korea_canary_20260604_225207.jpg` | `keysuri_korea_tech` | 18:30 |
| **korea_bottom** | `keysuri_korea_bottom_20260605_105936` | `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg` | `keysuri_korea_tech` | 18:30 |

Watermarked korea_bottom variant:

- `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936_mirai_on_watermarked.jpg`
- Manifest: `...105936_mirai_on_watermarked.manifest.json` (`image_role: bottom_shot`, `offduty_02C`)

Owner-review-only operating state for `105936`:

- `owner_review_email_attachment_ready=true`
- `customer_email_attachment_ready=false`
- `scheduler_variation_ready=false`
- `production_prompt_default=false`
- `generated_variation_allowed=false`
- `role=korea_bottom only`
- Allowed surface: KeeSuri Korea owner-review email bottom CID only.
- Blocked surfaces: customer email, scheduler variation generation, Global top-shot, Korea top-shot, Today/Tomorrow_Geenee.

Basis:

- Global top — `KEYSURI_IMAGE_PROFILE_LOCK.md` R2-L (`221233`)
- Korea top — `KEYSURI_IMAGE_PROFILE_LOCK.md` R3B-2-L (`225207`)
- Korea bottom — `KEYSURI_IMAGE_TRACK_CURRENT_STATE_HANDOFF.md` offduty_02C PASS_DIRECTION (`105936`)

## 105936 registry misuse history

Previously `keysuri_global_hero_105936` pointed the **korea_bottom** watermarked file (`105936_mirai_on_watermarked.jpg`) at **global_top / hero_topshot**. That was incorrect:

- Manifest explicitly records `image_role: bottom_shot`
- Filename prefix `keysuri_global_canary_*` is historical canary naming only

**Superseded entry:** `keysuri_global_hero_105936_misassigned` (status `superseded`).

## Rejected — do not use

| Asset / batch | Reason |
|---------------|--------|
| `keysuri_global_hero_refresh_20260608_155717` | Owner rejected — persona drift; files deleted |
| `keysuri_asset_refresh_20260608_155452/*` | Unpromoted refresh candidates |
| `keysuri_korea_canary_20260604_223121.jpg` | Rejected daytime Korea (profile lock §8) |
| Profile-lock rejected globals (202528, 204748, 211616, 214359, …) | QA failures |

## Resolver rules

1. **Role mismatch blocks resolver** — `korea_bottom` must never resolve for `global_top` or `korea_top`.
2. **No silent fallback** — `global_top` cannot fall back to `bottom_shot` / `105936` hashes.
3. **Program match** — `keysuri_global_tech` → `global_top`; `keysuri_korea_tech` top → `korea_top`; bottom → `korea_bottom` only.
4. **Manifest conflict** — if manifest `image_role=bottom_shot` but request is top hero → visual gate **fail** (`manifest_role_conflict`).

## Issue codes (visual gate)

- `asset_role_mismatch`
- `manifest_role_conflict`
- `wrong_locked_asset_for_program`
- `fallback_role_mismatch`

## Registry source of truth

`assets/keysuri/keysuri_approved_image_assets.json`

Runtime: `keysuri_approved_image_assets.py`
