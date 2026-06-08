# Kee-Suri Approved Image Asset Registry

## Purpose

Kee-Suri routine contract-preview and owner-review previews must **reuse approved character assets**, not generate a new face every run. This matches the Genie pattern: approved assets for routine output; owner review only when replacing or adding assets.

## Committed source of truth

- **JSON registry:** `assets/keysuri/keysuri_approved_image_assets.json`
- **Runtime module:** `keysuri_approved_image_assets.py`
- **Role map (locked):** `docs/keysuri/KEYSURI_LOCKED_IMAGE_ROLE_MAP.md`
- **Visual theme separation (v2):** `docs/keysuri/KEYSURI_GLOBAL_KOREA_DESIGN_SEPARATION_HANDOFF_v2.md`

Raster files live under `output/keysuri_preview/image_canary/` and are **not committed**. Registry JSON records paths and sha256 only.

## Locked approved roles (three roles)

| Role | Asset ID | Stamp | Program | Slot |
|------|----------|-------|---------|------|
| **global_top** | `keysuri_global_top_20260604_221233` | `221233` | `keysuri_global_tech` | 12:30 |
| **korea_top** | `keysuri_korea_top_20260604_225207` | `225207` | `keysuri_korea_tech` | 18:30 |
| **korea_bottom** | `keysuri_korea_bottom_20260605_105936` | `105936` | `keysuri_korea_tech` | 18:30 |

### global_top — 221233

- **File:** `output/keysuri_preview/image_canary/keysuri_global_canary_20260604_221233.jpg`
- **Watermarked:** `output/keysuri_preview/image_canary/keysuri_global_canary_20260604_221233_mirai_on_watermarked.jpg`
- **Status:** `approved_locked`
- **Resolver:** Global 12:30 live contract-preview **must** resolve this asset through the registry. Do not substitute any other hash or canary file.

### korea_top — 225207

- **File:** `output/keysuri_preview/image_canary/keysuri_korea_canary_20260604_225207.jpg`
- **Status:** `approved_locked`
- **Resolver:** Korea 18:30 top-shot slot.

### korea_bottom — 105936

- **File:** `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg`
- **Watermarked:** `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936_mirai_on_watermarked.jpg`
- **Status:** `approved_direction_locked`
- **Role:** **korea_bottom only** — Korea 18:30 bottom-shot slot. **Must NOT** be used as global_top, global hero, or Korea top-shot.
- **Note:** Filename prefix `keysuri_global_canary_*` is historical canary naming only; manifest records `image_role: bottom_shot`.

## 105936 misuse history (do not repeat)

Previously `keysuri_global_hero_105936` incorrectly pointed the **korea_bottom** watermarked file at **global_top / hero_topshot**. That entry is **superseded** (`keysuri_global_hero_105936_misassigned`, status `superseded`). **105936 must never be described or resolved as global hero or global_top.**

## Policy

1. **Routine contract-preview / live briefing** uses an approved registry asset by default.
2. **No image API** is called during routine preview generation.
3. **No per-briefing owner image selection** is required when the approved asset is reused.
4. **`image_refresh_frozen: true`** — asset refresh and candidate generation are frozen in routine mode. No automatic promotion.
5. **Registry mutation** requires **explicit owner approval**. Never auto-swap to the latest generated candidate or newest file in `image_canary/`.
6. **Canary / test outputs** under `output/**` are **not** approved assets until added to the committed registry JSON with owner sign-off.
7. **Rejected refresh batches** (e.g. `keysuri_global_hero_refresh_20260608_155717`, unpromoted `keysuri_asset_refresh_*` dirs) **must not** be promoted or used in routine preview.
8. **Candidates are not embedded** into routine preview unless promoted to the registry.
9. **Visual identity gate** passes approved registry assets by `approved_asset_registry_match` (sha256 + role + program + status).
10. **Generated candidates** without registry promotion → `manual_review_required` or `blocked`, never routine-ready.

## Visual theme (v2) — preview pairing

Contract-preview HTML uses program-scoped body classes (see design handoff v2):

| Program | Body class | Visual mood | Image slots |
|---------|------------|-------------|-------------|
| Global 12:30 | `theme-global` | Bright daytime — off-white / mist grey / signal blue | **Top-shot only** (221233) |
| Korea 18:30 | `theme-korea` | Warm evening — charcoal / gold / amber | Top-shot (225207) + **bottom-shot slot** (105936 when provided) |

Theme classes affect framing and CSS only; image resolution still follows the locked role map above.

## Candidate generation (frozen — separate mode only)

Image refresh / candidate tooling is **not** part of routine preview. When explicitly unfrozen by owner:

- Candidates belong under `output/keysuri_preview/image_canary/` only.
- Candidates are **not** routine assets.
- Promotion to registry is a **separate explicit owner-approved step** — never automatic.

## Test override

`--image-path` on live smoke is **explicit test override only**:

- Allowed for manual/candidate testing
- Visual gate: `manual_review_required` unless the path matches an approved registry entry (sha256 + role)
- Never treated as routine approved asset by path alone

## Replacement policy

Replace or add registry entries only via explicit owner-approved promotion. Never auto-promote canary output, refresh batches, or newest files in `output/`.
