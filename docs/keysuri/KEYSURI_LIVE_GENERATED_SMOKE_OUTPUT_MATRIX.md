# Kee-Suri Live Generated Smoke — Output Surface Matrix

Status: **Locked** for live `--use-gemini --contract-preview` wiring (2026-06-08, updated 2026-06-09 for v2 themes and registry alignment).

References:
- `KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md`
- `KEYSURI_CONTRACT_PREVIEW_RENDERER_DESIGN.md`
- `KEYSURI_LOCKED_IMAGE_ROLE_MAP.md`
- `KEYSURI_GLOBAL_KOREA_DESIGN_SEPARATION_HANDOFF_v2.md`
- `KEYSURI_APPROVED_IMAGE_ASSET_REGISTRY.md`
- `REVIEW_OPERATION_BOX_POLICY.md`

---

## 1. Four surfaces (do not conflate)

| Surface | Path pattern | Renderer | Validator profile | Purpose |
|---------|--------------|----------|-------------------|---------|
| **Operational owner-review** | `output/keysuri_preview/*owner_review*` | `keysuri_renderer.render_keysuri_owner_review_html` | `owner_review` | Audit/debug only — **not** service-quality gate |
| **Contract preview (customer-style)** | `output/keysuri_preview/html_test/*` | `keysuri_contract_preview_renderer.render_keysuri_contract_preview_html` | `contract_preview` | Owner visual review target — **required before any test send** |
| **Design fixture** | `output/keysuri_preview/html_test/*design_fixture*` | Same contract-preview renderer | `contract_preview` (with fixture banner) | **Visual/layout QA only** — staged placeholder content; **not** owner-review content gate |
| **Customer final** | TBD / separate export | Not implemented | Stricter export tests TBD | Requires explicit approve + send record |

**Rule:** Live generated smoke with `--contract-preview` MUST write **contract preview HTML only** as the service-quality artifact. Owner-review audit HTML is optional and must not substitute for contract preview. Design fixtures are for theme/layout side-by-side review, not content approval.

**Output boundary:** Generated HTML, debug artifacts, and canary rasters under `output/**` are **not** registry assets and **must not** be committed to git.

---

## 2. Email preview rule

- Test/owner email harness MUST attach **contract-preview HTML**, not owner-review audit HTML.
- SMTP CID/inline hero image is a **separate harness task** — contract preview may use local relative `<img>` for browser review.

---

## 3. Korean-first visible body

All reader-facing prose in contract preview MUST be **Korean (한국어)**:

- Selected title, opening lead, TOP 5 headlines and item bodies
- 키수리의 딥-다이브, 원-라인 체크포인트, 마무리
- Visible labels: **핵심 요약**, **중요한 이유**, **사업적 시사점**, **키수리 코멘트**, **출처**

English RSS titles may exist in source metadata only — not as primary TOP 5 headlines.

---

## 4. Top-shot hero image (registry-resolved)

Global 12:30 contract preview MUST include a **visible top-shot hero image** resolved from the committed registry — **not** from ad-hoc canary paths.

| Role | Asset ID | Preferred local file |
|------|----------|----------------------|
| **global_top** | `keysuri_global_top_20260604_221233` | `output/keysuri_preview/image_canary/keysuri_global_canary_20260604_221233.jpg` |
| **Watermarked variant** | (same asset) | `output/keysuri_preview/image_canary/keysuri_global_canary_20260604_221233_mirai_on_watermarked.jpg` |

- Global live smoke **must resolve 221233** through `keysuri_approved_image_assets.json`.
- **105936 is korea_bottom only** — must **not** be used as Global 12:30 hero. See `KEYSURI_LOCKED_IMAGE_ROLE_MAP.md` §105936 misuse history.
- **No image API** in live smoke.
- Do not render placeholder if the locked asset is missing — fail the run.
- **`image_refresh_frozen: true`** — no automatic promotion or substitution from newer canary output.

Korea 18:30 image slots (when rendered):

| Role | Asset ID | Stamp |
|------|----------|-------|
| korea_top | `keysuri_korea_top_20260604_225207` | `225207` |
| korea_bottom | `keysuri_korea_bottom_20260605_105936` | `105936` (bottom-shot slot only) |

---

## 5. v2 visual themes (contract preview)

Committed renderer applies program-scoped body classes:

| Program | Body class | Visual mood | Image slots in HTML |
|---------|------------|-------------|---------------------|
| **Global 12:30** | `theme-global` | Bright daytime — off-white / mist grey / signal blue | **Top-shot only** (221233) — no bottom-shot block |
| **Korea 18:30** | `theme-korea` | Warm evening — charcoal / gold / amber | Top-shot (225207) + optional bottom-shot slot (105936) |

Global and Korea must read as **two different Kee-Suri products**, not color variants of the same dashboard.

---

## 6. Live smoke status (2026-06-09)

| Program | Live `--contract-preview` smoke | Notes |
|---------|--------------------------------|-------|
| **Global** (`keysuri_global_tech`) | **Supported and passing** | Content, structural, and visual/layout gates pass; `owner_visual_review_ready`; resolves `221233`; `<body class="premium-briefing theme-global">` |
| **Korea** (`keysuri_korea_tech`) | **Not supported yet** | `run_keysuri_live_source_smoke.py` has no feed list configured for `keysuri_korea_tech` |

**Korea visual review today:** use static design fixture render only:

```bash
python3 scripts/render_keysuri_contract_preview.py --program keysuri_korea_tech --slot 18:30
```

- Output: `output/keysuri_preview/html_test/*design_fixture*` with `theme-korea`
- **Visual/layout QA only** — fixture banner present; content gate warnings expected on staged placeholder text; **not** owner-review content approval

---

## 7. Internal field hiding

The following MUST NOT appear in the **visible body** (above operation metadata):

`category:`, `why_it_matters:`, `business_implication:`, `confidence:`, `source_ids:`, `source_gate_result`, `prompt_status`, `operational_status`, `generated_status`, `output_contract`, `generation_pending`, `source-led cards only`

Operation metadata, compliance checklist, and validation result box belong at the **bottom only**.

---

## 8. Quality gates (contract preview)

Live generated contract preview must pass:

1. `contract_preview` validator (`scripts/validate_keysuri_html_preview.py --profile contract_preview`)
2. Visible-body quality gates (`keysuri_contract_preview_quality.py`)

Design fixtures may fail content gates by design; they are not substitutes for live-generated Global smoke.

---

## 9. Non-goals (live smoke)

- No scheduler, Today_Geenee, Tomorrow_Geenee
- No customer delivery / approve_run
- No image API
- No registry mutation or automatic asset promotion
- No `output/admin_runs` or `static/email/**` mutation
- No committing `output/**` previews, debug HTML, or canary rasters
