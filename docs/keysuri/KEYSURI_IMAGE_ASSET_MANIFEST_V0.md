# Kee-Suri Image Asset Manifest — v0 Design

Status:
Design document only / no production wiring / no code in this document

Purpose:
Define a **lightweight internal asset manifest** for Kee-Suri raster images **after** visible MirAI:ON watermark overlay — for QA, ownership proof, and controlled preview handoff.

Last updated:
2026-06-05 (post overlay utility `b090c87`, watermark CLI `7646f02`, manual smoke on `keysuri_global_canary_20260605_105936_mirai_on_watermarked.jpg`)

Non-scope:

- implementation in this document
- file-copy tracking
- forensic / invisible watermarking
- recipient-specific tracking
- download or leak detection
- MirAI:ON Content Shield SaaS features
- committing `output/**` manifest files

Reference:

- `keysuri_image_overlay.py` — pixel overlay utility
- `scripts/apply_keysuri_image_watermark.py` — local watermark CLI
- `docs/keysuri/KEYSURI_IMAGE_TRACK_CURRENT_STATE_HANDOFF.md`
- `docs/keysuri/KEYSURI_IMAGE_PROFILE_LOCK.md` §9.1
- `docs/keysuri/KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md` §10.1, §10.2, §10.3

---

## 1. Purpose

Kee-Suri generated raster images intended for preview or output handoff must carry a **visible `MirAI:ON` watermark on pixels** (contract §10.1). The overlay utility and local CLI apply that mark by post-processing; they do **not** replace ownership documentation.

After overlay, each **selected** image asset should have a **sidecar JSON manifest** recording:

| Question | Manifest answers |
|----------|------------------|
| What is this asset? | `image_role`, `program_id`, `slot`, `prompt_profile` |
| Where did it come from? | `source_image_path`, `source_sha256`, `source_generation_id` |
| Was overlay applied? | `overlay_applied`, `watermark_text`, `watermark_position`, `watermarked_sha256` |
| May it be used in preview? | `review_status`, `review_notes` — **not** `production_ready` |

The manifest is an **internal QA / ownership record** for operators and future contract-preview wiring. It is **not** a rights-enforcement or distribution-tracking system.

---

## 2. Scope

### In scope (v0)

| Item | Notes |
|------|-------|
| Local generated Kee-Suri canary images | Under `output/keysuri_preview/image_canary/` (gitignored) |
| Top-shot and bottom-shot assets | `image_role`: `top_shot` \| `bottom_shot` |
| Watermarked sibling images | `*_mirai_on_watermarked.jpg` (or `.png`) |
| QA / review status | `pending` → `pass_direction` → `approved_for_preview` or `rejected` |
| File integrity | `source_sha256`, `watermarked_sha256` |
| Ownership watermark status | `overlay_applied`, `watermark_text: MirAI:ON` |
| Dimensions | `width`, `height` — must match source after overlay |

### Out of scope (v0)

| Item | Reason |
|------|--------|
| Invisible watermark | Pixel-visible `MirAI:ON` only (§10.1) |
| Forensic tracking | Not preview-pipeline scope (§10.3) |
| Per-recipient tracking | Future Content Shield — not Kee-Suri manifest |
| File-copy tracking | Explicit non-goal (§10.2, §10.3) |
| Download / publish logs | Not v0 |
| External leak detection | Not v0 |
| MirAI:ON Content Shield SaaS | Separate product surface (§10) |

---

## 3. Manifest file location

### Sidecar placement

Place the manifest in the **same directory** as the **watermarked** raster file.

### Filename pattern

```
<watermarked_image_stem>.manifest.json
```

The stem is the watermarked file name **without** extension.

### Example (manual smoke reference)

| Asset | Path |
|-------|------|
| Source (unwatermarked) | `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg` |
| Watermarked | `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936_mirai_on_watermarked.jpg` |
| Manifest | `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936_mirai_on_watermarked.manifest.json` |

### Git hygiene

- Manifests under `output/**` are **local QA artifacts only**.
- **Do not commit** `output/**` manifest files.
- Commit **design and code** (writer, tests, CLI flags) — not operator-generated sidecars.

---

## 4. Required manifest fields

### Schema identifier

```json
"schema_version": "keysuri_image_asset_manifest_v0"
```

### Full v0 example

```json
{
  "schema_version": "keysuri_image_asset_manifest_v0",
  "asset_id": "keysuri_global_canary_20260605_105936_mirai_on_watermarked",
  "program_id": "keysuri_global_tech",
  "slot": "manual_canary",
  "image_role": "bottom_shot",
  "source_image_path": "output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg",
  "watermarked_image_path": "output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936_mirai_on_watermarked.jpg",
  "generated_at": "2026-06-05T10:59:00+09:00",
  "watermarked_at": "2026-06-05T14:30:00+09:00",
  "overlay_applied": true,
  "watermark_text": "MirAI:ON",
  "watermark_position": "bottom_right",
  "source_sha256": "abc123...",
  "watermarked_sha256": "def456...",
  "width": 896,
  "height": 1152,
  "review_status": "pending",
  "review_notes": "",
  "prompt_profile": "offduty_02C_luxury_knit_silk_skirt_farewell",
  "source_generation_id": null,
  "created_by": "local_cli",
  "tool": "scripts/apply_keysuri_image_watermark.py",
  "production_ready": false
}
```

### Field reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_version` | string | yes | Fixed: `keysuri_image_asset_manifest_v0` |
| `asset_id` | string | yes | Stable id; recommend watermarked stem |
| `program_id` | enum | yes | `keysuri_global_tech` \| `keysuri_korea_tech` |
| `slot` | enum | yes | `12:30` \| `18:30` \| `manual_canary` |
| `image_role` | enum | yes | `top_shot` \| `bottom_shot` |
| `source_image_path` | string | yes | Repo-relative or absolute path to pre-overlay file |
| `watermarked_image_path` | string | yes | Path to overlay output |
| `generated_at` | ISO-8601 | yes | Source image creation time (best known) |
| `watermarked_at` | ISO-8601 | yes | Overlay application time |
| `overlay_applied` | boolean | yes | `true` only after visible overlay on pixels |
| `watermark_text` | string | yes | Must be exactly `MirAI:ON` |
| `watermark_position` | enum | yes | `bottom_right` \| `bottom_left` |
| `source_sha256` | hex string | yes | SHA-256 of source file bytes |
| `watermarked_sha256` | hex string | yes | SHA-256 of watermarked file bytes |
| `width` | integer | yes | Raster width in pixels |
| `height` | integer | yes | Raster height in pixels |
| `review_status` | enum | yes | See §6 |
| `review_notes` | string | no | Operator QA notes; default `""` |
| `prompt_profile` | string | no | e.g. `profile_v4_01`, `offduty_02C_...` |
| `source_generation_id` | string \| null | no | Future link to canary report / API run id |
| `created_by` | string | yes | e.g. `local_cli`, `operator_manual` |
| `tool` | string | yes | e.g. `scripts/apply_keysuri_image_watermark.py` |
| `production_ready` | boolean | yes | **Must default to `false`** in v0 |

### Forbidden strings

No manifest field value may contain:

- `Heemang`
- `Today_Geenee`
- `Tomorrow_Geenee`

(Aligned with `FORBIDDEN_LEGACY_TEXTS` in `keysuri_image_overlay.py`.)

---

## 5. Field rules

| Rule | Enforcement |
|------|-------------|
| `overlay_applied` | `true` **only** when visible `MirAI:ON` overlay was applied to `watermarked_image_path` |
| `watermark_text` | Must equal exactly `MirAI:ON` — no legacy brand bleed |
| `production_ready` | Defaults to `false`; v0 writers must not set `true` |
| `review_status` | Defaults to `pending` unless operator explicitly supplies another allowed value |
| `approved_for_preview` | Allows contract preview wiring — **does not** imply `production_ready` |
| `source_sha256` vs `watermarked_sha256` | Must **differ** after successful overlay (pixel change proof) |
| `width` / `height` | Must match source dimensions; overlay must not resize |
| Manifest under `output/**` | Local only — **never committed** |
| `asset_id` | Should be unique per watermarked file; recommend stem of watermarked image |
| `tool` | Records which script created the manifest for audit |

### Validation failures (future writer)

Reject or mark manifest invalid when:

- `overlay_applied` is `true` but hashes are identical
- `watermark_text` ≠ `MirAI:ON`
- dimensions missing or zero
- `image_role` or `program_id` missing
- forbidden legacy substring in any string field

---

## 6. Review status meanings

| Status | Meaning | May embed in contract preview? |
|--------|---------|-------------------------------|
| `pending` | Overlay created; visual QA not recorded | **No** — placeholder only |
| `pass_direction` | Direction accepted (e.g. R6B PASS_DIRECTION); not final production asset | **Yes** (v0 future wiring) |
| `approved_for_preview` | Explicitly cleared for contract preview / owner visual review | **Yes** |
| `rejected` | Must not be used in any preview or handoff | **No** |

### Not a review status in v0

| Term | Rule |
|------|------|
| `production_ready` | **Not** a `review_status` value. Separate boolean field; v0 must remain `false`. Production promotion requires a separate documented gate (R6B checklist, scheduler design). |

### Typical flow

```
canary generated → overlay CLI → manifest (pending)
       → operator visual QA → pass_direction | approved_for_preview | rejected
```

`pass_direction` images (e.g. `offduty_02C`) are **QA direction references** — not automatic production assets.

---

## 7. CLI integration plan

### v0 preference

Extend the existing watermark CLI later (do **not** implement in this document task):

```bash
python3 scripts/apply_keysuri_image_watermark.py \
  --input output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg \
  --role bottom_shot \
  --write-manifest \
  --program keysuri_global_tech \
  --slot manual_canary \
  --review-status pending \
  --pretty
```

### Proposed flags (future)

| Flag | Purpose |
|------|---------|
| `--write-manifest` | Emit sidecar JSON after successful overlay |
| `--program` | `keysuri_global_tech` \| `keysuri_korea_tech` |
| `--slot` | `12:30` \| `18:30` \| `manual_canary` |
| `--role` | Already exists: `top_shot` \| `bottom_shot` |
| `--review-status` | Default `pending` |
| `--prompt-profile` | Optional wardrobe / R6B profile id |
| `--review-notes` | Optional operator note |

### Alternative (deferred)

Standalone `scripts/write_keysuri_image_asset_manifest.py` for retroactive manifest creation on already-watermarked files. Lower priority than `--write-manifest` on the overlay CLI.

### Manifest writer responsibilities (future code)

1. Verify `watermarked_image_path` exists and `overlay_applied` preconditions met.
2. Compute `source_sha256` and `watermarked_sha256`.
3. Read `width` / `height` from raster (Pillow).
4. Write sidecar next to watermarked file.
5. Print JSON status (PASS/FAIL) — mirror watermark CLI pattern.
6. No image API, scheduler, or email side effects.

---

## 8. Contract preview renderer integration

### Current state

`keysuri_contract_preview_renderer.py` uses **placeholders** only (`top-shot-placeholder`, `bottom-shot-placeholder`). Contract design §7.6 requires `watermark: post_process_required` on placeholders until real assets are wired.

### Future rule (manifest-gated)

Contract preview renderer may accept a **real** `<img>` or approved path **only when** a valid sidecar exists and:

| Check | Requirement |
|-------|-------------|
| File exists | `watermarked_image_path` on disk |
| Overlay | `overlay_applied == true` |
| Brand | `watermark_text == "MirAI:ON"` |
| Review | `review_status` in `["pass_direction", "approved_for_preview"]` |
| Production | `production_ready == false` or field absent |
| Role match | `image_role` matches slot (`top_shot` for 12:30; `bottom_shot` for Korea 18:30 bottom) |

### If manifest is missing or invalid

- Renderer **must** keep placeholder HTML.
- **Do not** silently embed raw unwatermarked image.
- **Do not** infer overlay from filename alone (`_mirai_on_watermarked` suffix is a hint, not proof).

### Validator interaction

`keysuri_html_preview_validation.py` already blocks `static/email/` and production-marked canary paths. Future manifest wiring must not introduce paths that bypass production-negative patterns.

---

## 9. Acceptance checklist

A Kee-Suri image asset is **acceptable for preview handoff** (not production) only if **all** are true:

- [ ] Visible `MirAI:ON` watermark on pixels (operator visual QA or pixel regression)
- [ ] Sidecar manifest exists beside watermarked file
- [ ] `overlay_applied` is `true`
- [ ] `watermark_text` is exactly `MirAI:ON`
- [ ] `watermarked_sha256` present and non-empty
- [ ] `source_sha256` present and non-empty
- [ ] `source_sha256` ≠ `watermarked_sha256`
- [ ] `width` and `height` present and match source
- [ ] `image_role` set (`top_shot` or `bottom_shot`)
- [ ] `review_status` set and in allowed preview set (`pass_direction` or `approved_for_preview`)
- [ ] `production_ready` is `false`
- [ ] No `Heemang`, `Today_Geenee`, or `Tomorrow_Geenee` in any manifest string field
- [ ] Watermark does not cover face, hands, tablet, or silhouette (visual QA — §10.1)
- [ ] Manifest and raster under `output/**` remain **uncommitted**

---

## 10. Future Content Shield separation note

This manifest is **intentionally lightweight**. It is **not** MirAI:ON Content Shield.

| Kee-Suri manifest v0 | Future Content Shield SaaS (out of scope) |
|----------------------|-------------------------------------------|
| Single-operator QA record | Recipient-specific watermark |
| Visible `MirAI:ON` only | Invisible / forensic watermark |
| Local sidecar JSON | Download log |
| `review_status` for preview | Publish log |
| SHA-256 integrity | Leak comparison report |
| No recipient tracking | Rights proof report for external distribution |

Kee-Suri preview pipeline uses **only** the lightweight internal manifest until a separate owner-approved Content Shield integration is scoped.

---

## 11. Recommended implementation sequence

After this design document is committed:

| Step | Task | Risk |
|------|------|------|
| 1 | Add `tests/test_keysuri_image_asset_manifest.py` (TDD) | Low |
| 2 | Implement `keysuri_image_asset_manifest.py` writer + validator | Low |
| 3 | Extend `scripts/apply_keysuri_image_watermark.py` with `--write-manifest` (+ program/slot/review flags) | Low–medium |
| 4 | Manual smoke: overlay + manifest on `keysuri_global_canary_20260605_105936` watermarked sibling | Low |
| 5 | Update handoff doc §82–94 (overlay committed; manifest gap) | Doc only |
| 6 | Later: contract preview renderer manifest-gated `<img>` wiring | Medium |
| 7 | Last: optional canary runner post-overlay hook | High — defer |

**Do not** wire scheduler, email, or image API in manifest v0.

---

## Summary

Kee-Suri image asset manifest v0 is a **gitignored sidecar JSON** beside each **watermarked** raster, recording ownership overlay proof, integrity hashes, and review status for controlled preview handoff — explicitly **not** file-copy tracking, invisible watermarking, or Content Shield.
