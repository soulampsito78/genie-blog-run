# Kee-Suri Contract Preview Renderer — Design

## Document status

| Field | Value |
|-------|-------|
| Mode | **Documentation only** — no code, renderer, prompt, schema, or validator changes authorized by this document |
| Core decision | **Option B** — dedicated contract preview renderer; do **not** force the existing owner-review renderer to pass the html_test validator |
| Related commits | `038c4b4` (HTML preview validator v0), `1e28fe0` (renderer–validator compatibility gap tests) |

**References:**

- `docs/keysuri/KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md` — title/body contract (§10–§15)
- `docs/keysuri/KEYSURI_HTML_PREVIEW_VALIDATOR_IMPLEMENTATION_PLAN.md` — validator boundary
- `keysuri_html_preview_validation.py` — read-only html_test validator (v0)
- `scripts/validate_keysuri_html_preview.py` — CLI entrypoint
- `tests/test_keysuri_renderer_validator_compat.py` — documents current FAIL matrix
- `keysuri_renderer.py` — existing **owner-review** renderer (unchanged by this design)

---

## 1. Purpose

Kee-Suri currently has **two separate HTML surfaces** that must not be conflated:

| Surface | Role |
|---------|------|
| **Owner-review HTML** | Operational / audit preview for offline dry-run — source gate, guardrails, scheduler context |
| **Contract-validation HTML** | User-facing briefing structure under `output/keysuri_preview/html_test/` — must pass `keysuri_html_preview_validation.py` |

The **existing owner-review renderer** (`keysuri_renderer.render_keysuri_owner_review_html`) serves the first surface. Compatibility tests in commit `1e28fe0` prove that its output **does not** and **should not** be expected to pass the html_test validator without structural changes that would blur the two purposes.

This document designs a **new dedicated contract preview renderer** that:

1. Generates timestamped HTML under `output/keysuri_preview/html_test/`.
2. Embodies the customer-facing briefing structure defined in `KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md`.
3. Is validated with `scripts/validate_keysuri_html_preview.py` before owner visual review.
4. Supports **owner visual review and contract validation** — not production sending, not scheduler jobs, not email delivery, not image API calls.

**Non-purpose:** Replacing, extending, or retrofitting the owner-review renderer in the first implementation pass.

---

## 2. Surface separation

### A. Owner-review renderer (current — unchanged)

| Attribute | Detail |
|-----------|--------|
| Module | `keysuri_renderer.py` |
| Script | `scripts/render_keysuri_owner_review_preview.py` (when used) |
| Typical output path | `output/keysuri_preview/` (non–`html_test` filenames) |
| Audience | Operator / owner doing **operational** review |
| Content | Audit blocks, source gate, review status, forbidden-output guardrails, active scheduler table |
| Today_Geenee | May appear in internal scheduler tables — acceptable for this surface |
| html_test validator | **Not expected to PASS** — documented in `tests/test_keysuri_renderer_validator_compat.py` |
| Lifecycle | Remains the operational review UI for staged dry-run |

**Known gaps vs contract validator (documented, intentional for this surface):**

- TOP 5 uses `news-card` / `data-rank` with `source_ids` — not item-level `source_name` / `source_url` display
- **키수리의 딥-다이브** is a single paragraph — no 1/2/3 layer cards
- No rights policy footer, validation result box, contract compliance checklist, or preview metadata blocks
- `Today_Geenee` in scheduler section → `no_production_implication: FAIL` on html_test validator

### B. Contract preview renderer (new — to be implemented)

| Attribute | Detail |
|-----------|--------|
| Proposed module | `keysuri_contract_preview_renderer.py` |
| Proposed script | `scripts/render_keysuri_contract_preview.py` |
| Output path | `output/keysuri_preview/html_test/` |
| Filename | Timestamped — see §4 |
| Audience | Owner **visual review** of contract-compliant briefing layout |
| Content | User-facing briefing structure only — no Genie scheduler bleed |
| Today_Geenee / Tomorrow_Geenee | **Forbidden** — must not appear |
| Production / scheduler / email | **No implication** — no `production_ready`, `scheduler_ready`, `email_ready` language |
| Image API | **No call** — placeholders or approved static references only |
| Email | **No send** |
| html_test validator | **Must PASS** after render + CLI validation |
| Lifecycle | Generate → validate CLI → owner opens PASS preview for visual review |

---

## 3. Proposed future files

### 3.1 Recommended implementation files (future code task)

| Role | Path |
|------|------|
| Contract preview renderer module | `keysuri_contract_preview_renderer.py` |
| CLI render script | `scripts/render_keysuri_contract_preview.py` |
| Tests | `tests/test_keysuri_contract_preview_renderer.py` |

### 3.2 Explicit do-not-modify list (first pass)

| Asset | Rule |
|-------|------|
| `keysuri_renderer.py` | Do **not** change behavior unless a **later, owner-approved** task chooses **shared helpers only** (e.g. HTML escape, identity constants) |
| `keysuri_prompt_profiles.py`, generation prompts | No changes in first pass |
| JSON schema / briefing validators | No changes in first pass |
| `keysuri_html_preview_validation.py` | No changes in first pass — renderer must conform to existing v0 rules |
| Scheduler / email / image pipeline | No wiring |
| `main.py`, `orchestrator.py` | No wiring |
| Genie validators (`validators.py`, `publishing_policy.py`) | No reuse |

### 3.3 Optional later convergence

After the contract preview renderer is **stable and PASSing** on fixtures:

- Extract **presentation helpers** (CSS shell, identity header, rights footer) into a shared module **only if** duplication cost exceeds maintenance cost.
- Do **not** merge owner-review audit sections into the contract renderer.
- Compatibility tests (`test_keysuri_renderer_validator_compat.py`) remain — owner-review surface stays separate.

---

## 4. Required output path and filename

### 4.1 Output folder

```
output/keysuri_preview/html_test/
```

### 4.2 Filename pattern

```
keysuri_<program>_<slot_or_sample>_<YYYYMMDD_HHMMSS>.html
```

| Component | Rule |
|-----------|------|
| `<program>` | `global`, `korea`, or explicit slot token (e.g. `korea_1830`) |
| `<slot_or_sample>` | Descriptive token — e.g. `contract_preview`, `bottom_close_sample` |
| `<YYYYMMDD_HHMMSS>` | **Required** — timestamp to **seconds** |
| Extension | `.html` |

**Examples:**

- `keysuri_korea_1830_contract_preview_20260605_184500.html`
- `keysuri_global_1230_contract_preview_20260605_123000.html`

### 4.3 Git and artifact boundaries

| Rule | Detail |
|------|--------|
| `output/**` | Remains **gitignored** — generated HTML is **never committed** |
| Validator CLI | Required after every render |
| Command | `python3 scripts/validate_keysuri_html_preview.py <path> --pretty` |

---

## 5. Required section order

Locked section labels must match `KEYSURI_TERMINOLOGY_LOCK.md` and `keysuri_private_briefing.py` exactly.

### 5.1 Korea 18:30 (`keysuri_korea_tech`)

| # | Section |
|---|---------|
| 1 | Preview metadata |
| 2 | Identity (**테크 비서 키수리**) |
| 3 | Title candidates |
| 4 | Selected title |
| 5 | Opening lead |
| 6 | Top-shot placeholder or approved top-shot image reference |
| 7 | **국내 테크 TOP 5** — item-level source boxes per item |
| 8 | **키수리의 딥-다이브** — 1/2/3 layer cards when dense |
| 9 | **원-라인 체크포인트** |
| 10 | Bottom-shot placeholder or approved bottom-shot image reference |
| 11 | **Review confirmation box** — see §6 |
| 12 | **국내 18:30 따뜻한 마무리** — §11 warm close copy |
| 13 | **마무리 및 출처 리스트** |
| 14 | Rights policy footer — §13 |
| 15 | Operation metadata |
| 16 | Contract compliance checklist |
| 17 | Validation result box — §15 (last) |

**Placement notes (Korea):**

- Bottom-shot **before** review confirmation box and warm close.
- Review confirmation box **before** warm close.
- Warm close **before** **마무리 및 출처 리스트**.
- Rights policy **after** **마무리 및 출처 리스트**, **before** operation metadata.
- Validation result box **last**.

### 5.2 Global 12:30 (`keysuri_global_tech`)

| # | Section |
|---|---------|
| 1 | Preview metadata |
| 2 | Identity (**테크 비서 키수리**) |
| 3 | Title candidates |
| 4 | Selected title |
| 5 | Opening lead |
| 6 | Top-shot placeholder or approved top-shot image reference |
| 7 | **글로벌 테크 TOP 5** — item-level source boxes per item |
| 8 | **키수리의 딥-다이브** — 1/2/3 layer cards when dense |
| 9 | **원-라인 체크포인트** |
| 10 | **Review confirmation box** — see §6 |
| 11 | **마무리 및 출처 리스트** |
| 12 | Rights policy footer — §13 |
| 13 | Operation metadata |
| 14 | Contract compliance checklist |
| 15 | Validation result box — §15 (last) |

**Placement notes (global):**

- No bottom-shot warm close section (contract §11 — Korea 18:30 only).
- Review confirmation box **before** **마무리 및 출처 리스트**.
- Validation result box **last**.

---

## 6. Review confirmation box policy

The contract preview renderer adds a **visible review confirmation box** — distinct from the validation result box (§15) and operation metadata.

### 6.1 Purpose

Communicate **human review / send lifecycle state** to the owner during visual review. This is an **owner-facing status** block, not an automated contract check result.

### 6.2 States and copy

| State | Display text |
|-------|--------------|
| `preview_pending` | 본 브리핑은 운영책임자의 직접 검수 대기 상태입니다. |
| `review_passed` | 본 브리핑은 운영책임자의 직접 검수를 통과했습니다. |
| `sent_archived` | 본 브리핑은 운영책임자의 직접 검수를 통과하여 발송되었습니다. |

### 6.3 Rules

| Rule | Detail |
|------|--------|
| Default state | `preview_pending` for all newly generated contract previews |
| `review_passed` | Requires **explicit owner approval** input — not inferred from validator PASS |
| `sent_archived` | May **only** be used when a **real send-completion record** exists — not from renderer alone |
| “발송되었습니다” timing | Do **not** use send-complete language before actual send completion |
| vs validation result box | Review confirmation box **must not replace** validation result box |
| vs operation metadata | Review confirmation box **must not replace** operation metadata |
| Korea placement | **Before** **국내 18:30 따뜻한 마무리** |
| Global placement | **Before** **마무리 및 출처 리스트** |

### 6.4 Suggested DOM hook (implementation hint)

```html
<section id="review-confirmation-box" data-review-state="preview_pending">
  ...
</section>
```

**Note:** Validator v0 (`keysuri_html_preview_validation.py`) does **not** yet enforce review confirmation box presence. Contract preview renderer tests should assert it; a future validator v1 task may add optional checks after owner approval.

---

## 7. Required content structures

### 7.1 TOP 5 item (each of 5 items)

Each item must **visibly** include:

| Field | Required | Notes |
|-------|----------|-------|
| headline | Yes | |
| what_happened | Yes | Signal capture — may map from `summary` in JSON |
| why_it_matters | Yes | |
| business_implication | Yes | |
| risk_note | Optional | Include when present in source JSON |
| source_name | Yes | Visible 출처명 |
| source_url | Yes | `https://` URL in v0 validator |
| checked_at | Yes | 기준시각 when available |
| verification_status | Yes | e.g. `sample_only` / `not_verified` |

**Markup expectation (validator v0):** Items should use `data-top-item="1"` … `"5"` or `.top-item` blocks — **not** owner-review `news-card` / `data-rank` alone.

### 7.2 **키수리의 딥-다이브**

| Rule | Detail |
|------|--------|
| Layer structure | Supports **1 / 2 / 3** layer card structure when analysis is dense |
| Korea validated model | Layer titles: **물리·인프라 병목**, **규제·주권·조달 압력**, **워크플로·락인** |
| Global | May use different 1/2/3 labels — still requires readable layers when dense |
| Anti-pattern | Single giant paragraph with no layer markers when content is dense |
| DOM hint | `class="deep-layer"`, `deep-layer-number`, `deep-layer-title` |

### 7.3 Rights policy footer

Exact visible text (contract §13):

```
Copyright Ⓒ MirAI:ON. All rights reserved.
무단 전재, 재배포 및 AI학습 이용 절대 금지
```

**Note:** §13 protects the **HTML page**. It does **not** replace raster image watermarking — see §7.6.

### 7.4 Hashtags

**No hashtag section by default** — contract §14. Validator v0 enforces `no_hashtags: PASS`.

### 7.5 Negative content guards

Contract preview HTML must **not** contain:

- Today_Geenee / Tomorrow_Geenee language
- Active scheduler tables referencing Genie programs
- `production_ready: true`, `scheduler_ready: true`, `email_ready: true`
- `static/email` paths or image API output paths presented as production assets
- **테크 앵커** / **뉴스 앵커** identity bleed

### 7.6 Image watermark and placeholder policy

**Genie inspection pattern (read-only):** prompt negatives forbid model-generated watermarks; post-process overlay applies exact `MirAI:ON` (`genie_image_overlay.py`). Kee-Suri uses **MirAI:ON only** — not `© Heemang & Tobak`, not Today_Geenee / Tomorrow_Geenee.

Contract preview renderer top-shot and bottom-shot placeholders must indicate:

| Attribute | Value |
|-----------|-------|
| `watermark` | `post_process_required` |
| Meaning | Placeholder HTML does **not** mean overlay was applied |
| Handoff rule | Approved raster assets must be **overlay-verified** before preview/output use |

**Required raster watermark:** visible `MirAI:ON` on image pixels (top-shot and bottom-shot). Optional when safe-area allows: `Copyright Ⓒ MirAI:ON. All rights reserved.`

**Placement:** bottom-right or lower safe area; small but legible; premium neutral tone; consistent opacity; safe margin inside crop zone; do not cover face, eyes, hands, tablet, key UI, outfit silhouette, or briefing gesture.

**Rules:**

- Do not ask the image model to render watermark text.
- Keep prompt negatives (`no text`, `no logo`, `no watermark`, `no text overlay`).
- Apply required ownership mark **after generation** by overlay.
- Metadata-only watermark is insufficient.
- HTML §13 footer remains required separately.

**Future asset manifest (recommendation):** per-image record with `asset_id`, `program_id`, `slot`, `image_role`, `source_generation_id`, `generated_at`, `overlay_applied`, `watermark_text: MirAI:ON`, `review_status`, `file_path`, optional `hash_sha256` — internal QA manifest, not file-copy tracking.

**Non-goal:** Full file-copy tracking, forensic watermarking, and per-download invisible watermarking are out of scope until preview/output workflow stabilizes.

**Future code candidates (do not implement in this design doc):**

| Candidate | Purpose |
|-----------|---------|
| `keysuri_image_overlay.py` or `mirai_on_image_overlay.py` | Post-process `MirAI:ON` overlay |
| `tests/test_keysuri_image_overlay.py` | Overlay text, placement, safe-zone regression |
| Manual canary runner hook | Apply overlay after generation |
| Manifest writer | Record `overlay_applied` / `watermark_text` |

---

## 8. Validation integration

### 8.1 Post-render workflow

```
render_keysuri_contract_preview.py
  → write output/keysuri_preview/html_test/<timestamped>.html
  → python3 scripts/validate_keysuri_html_preview.py <path> --pretty
  → if PASS: eligible for owner visual review
  → if FAIL: fix renderer or input — do not treat as review-ready
```

### 8.2 Honesty rules

| Rule | Detail |
|------|--------|
| Renderer must not fake PASS | If validation box is embedded, values must match **actual CLI result** |
| Pending state | If CLI not yet run, box may show `validation_status: pending` — but v0 validator expects honest PASS/FAIL at review time |
| Validator is read-only | v0 does **not** mutate HTML or inject validation results |
| CLI vs embedded box | If embedded box claims PASS but CLI reports FAIL, treat embedded claim as **incorrect** (contract §15.6) |

### 8.3 Recommended script behavior (future)

The render script should:

1. Write HTML to the timestamped path.
2. Invoke `validate_keysuri_html_preview` programmatically or via subprocess.
3. Print JSON result to stdout.
4. Exit non-zero on FAIL (mirror CLI semantics).
5. Optionally re-write HTML with updated validation box **only** if a separate owner-approved “validation box refresh” step exists — phase 1 may require two-step: render → validate → manual box update if needed.

---

## 9. Implementation strategy

Preferred sequence (each step is a separate owner-approved task):

| Step | Action |
|------|--------|
| 1 | Add `tests/test_keysuri_contract_preview_renderer.py` with fixture-driven expectations (TDD) |
| 2 | Implement `keysuri_contract_preview_renderer.py` — global and Korea paths |
| 3 | Add `scripts/render_keysuri_contract_preview.py` — writes timestamped `html_test` file |
| 4 | Run CLI validator on generated file; iterate until PASS on fixtures |
| 5 | Flip `CONTRACT_PREVIEW_RENDERER_AVAILABLE = True` in compat tests only when intentional PASS path exists |
| 6 | **Only after stable PASS:** consider shared helpers with owner-review renderer |

**Input data sources (expected):**

- `keysuri_generated_briefing` JSON (model output shape)
- `keysuri_prompt_input` / private briefing context
- Staged fixtures under `ops/feeds/` for offline tests — **read only**, no ops/ changes in doc task

**Compatibility tests remain:**

- `tests/test_keysuri_renderer_validator_compat.py` continues to assert owner-review **FAIL** on html_test validator.
- New renderer tests assert contract preview **PASS** on html_test validator.

---

## 10. Non-goals

| Non-goal | Reason |
|----------|--------|
| Production sending | Out of scope — server gates remain off |
| Scheduler wiring | `scheduler_allowed=false` boundary preserved |
| Email sending | No `email_sender` integration |
| Image API call | Placeholders only in contract preview phase |
| Owner-review renderer mutation | First pass adds **new** module, not retrofit |
| Committing `output/**` | Gitignored preview artifacts |
| Genie validator reuse | Kee-Suri HTML rules stay in `keysuri_html_preview_validation.py` |
| Source/fact verification | Contract display only — verification pipeline separate |
| Automatic `sent_archived` state | Requires future send-completion record |
| Forensic / invisible watermarking | Out of scope — §7.6 |

---

## 11. Acceptance checklist

A generated contract preview is **acceptable** only if **all** of the following hold:

- [ ] Timestamped file created under `output/keysuri_preview/html_test/`
- [ ] CLI validator run: `python3 scripts/validate_keysuri_html_preview.py <path> --pretty`
- [ ] `validation_status: PASS` from CLI
- [ ] TOP 5 item-level sources visible (name, URL, verification status per item)
- [ ] **키수리의 딥-다이브** readable layer structure present when content is dense
- [ ] Rights policy footer visible with exact §13 text
- [ ] Image placeholders note `watermark: post_process_required` (§7.6)
- [ ] When wired images are used: top-shot watermark `MirAI:ON` applied on pixels
- [ ] When wired images are used: bottom-shot watermark `MirAI:ON` applied on pixels (Korea 18:30)
- [ ] Watermark does not cover face, hands, tablet, or silhouette
- [ ] No model-generated watermark contamination
- [ ] Overlay verified before preview/output handoff
- [ ] HTML rights footer present separately from image watermark
- [ ] Review confirmation box present with correct state text (default: `preview_pending`)
- [ ] No hashtag section
- [ ] No Today_Geenee / Tomorrow_Geenee bleed
- [ ] No production / scheduler / email implication flags or language
- [ ] Korea 18:30: warm close order correct when slot explicitly indicated
- [ ] `output/**` file **not committed**

---

## 12. Open decisions

| # | Question | Current design bias |
|---|----------|---------------------|
| 1 | Should review confirmation state be passed as a renderer argument? | **Yes** — `review_state: preview_pending \| review_passed \| sent_archived` on render function; default `preview_pending` |
| 2 | Should `sent_archived` ever be generated by this renderer, or only by a future archive renderer? | **Future archive renderer or send-completion hook only** — contract preview renderer should not emit `sent_archived` without a send record |
| 3 | Should global 12:30 have a warm close, or only Korea 18:30? | **Korea 18:30 only** per contract §11 — global has no warm close in v1 |
| 4 | Should validation box be inserted before or after CLI run in phase 1? | **After CLI run** (or render with `pending`, then refresh post-CLI in script) — never claim PASS before validator runs |
| 5 | Should `source_url` allow non-`http` placeholder URLs in draft mode? | **No for html_test PASS** — v0 validator requires `https://`; staged `example.com` URLs acceptable if `https://` prefixed |

---

## Appendix A — Gap summary (owner-review vs contract preview)

Documented by commit `1e28fe0` / `tests/test_keysuri_renderer_validator_compat.py`:

| Check | Owner-review renderer | Contract preview renderer (target) |
|-------|----------------------|-----------------------------------|
| `top5_sources` | FAIL — `news-card`, no item URLs | PASS — `data-top-item` + source fields |
| `rights_policy` | FAIL — missing footer | PASS — §13 exact text |
| `required_sections` | FAIL — no validation/metadata blocks | PASS — full §15.3 set |
| `deep_dive_readability` | FAIL — single paragraph | PASS — layer cards when dense |
| `no_production_implication` | FAIL — `Today_Geenee` in scheduler table | PASS — no Genie scheduler bleed |
| Audit / source gate blocks | Present | Absent |
| Review confirmation box | Absent | Present (§6) |

---

## Appendix B — Relationship to contract doc roadmap

`KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md` §15.8 notes renderer integration requires a **separate compatibility pass**. This design implements that pass as a **new renderer**, not as a breaking change to the owner-review renderer.

Contract doc cross-reference: `KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md` §10.1 (image watermark), §13.3 (HTML vs image), §17.2 (renderer responsibility split).
