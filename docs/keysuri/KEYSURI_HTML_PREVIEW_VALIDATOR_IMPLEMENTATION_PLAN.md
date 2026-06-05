# Kee-Suri HTML Preview Validator — Implementation Plan

## 1. Purpose

Kee-Suri now requires **automated validation** for HTML previews written under:

`output/keysuri_preview/html_test/`

These previews are owner-review artifacts — not production email bodies, not scheduler jobs, and not image-API outputs. Contract rules live in `docs/keysuri/KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md` (§13–§15).

This document defines the **implementation boundary** for a new Kee-Suri HTML preview validator. It exists to:

1. **Automate** §15 checks (filename, sections, TOP 5 sources, 딥-다이브 layers, rights footer, negative guards, Korea 18:30 placement, validation result box honesty).
2. **Separate** Kee-Suri HTML preview validation from the Genie runtime stack (`validators.py` → `renderers.py` → `publishing_policy.py`).
3. **Prevent accidental reuse** of Today_Geenee / Tomorrow_Geenee JSON validators, delivery gates, or proof scripts on Kee-Suri preview HTML.

**This plan is documentation only.** No validator code, production wiring, renderer changes, or preview mutation is authorized by this document alone.

---

## 2. Inspection conclusion

The Genie validator inspection (2026-06) recorded the following repo facts:

| Finding | Detail |
|---------|--------|
| No committed “3-layer HTML validator” | No module, script, or test suite with that name exists in the committed tree. |
| Genie validation stack | **Normalize → JSON validate → publishing gate** — operates on parsed briefing JSON and runtime metadata, not rendered HTML files. |
| `validators.py` | Validates `today_genie` / `tomorrow_genie` dicts; does not read `.html` files. |
| `publishing_policy.py` | Converts validation outcome into email/naver send permissions; irrelevant to read-only preview QA. |
| Historical ops artifacts | Untracked `ops/preview/*.json` records `html_order_indices` / `html_order_pass` for today_genie email HTML — **no committed Python implementation** of those checks. |
| Kee-Suri JSON validators | `keysuri_private_briefing.py`, `keysuri_generated_briefing.py`, `keysuri_news_contract.py` validate **JSON shape** upstream of render — not §15 HTML preview surface. |
| Kee-Suri renderer tests | `tests/test_keysuri_renderer.py` checks in-memory HTML strings for owner-review renderer — **not** §15 preview contract (no validation box, no rights footer, different scope). |

**Conclusion:** Kee-Suri requires its **own HTML preview validator** — a read-only rule adapter over rendered HTML files, not a fork of Genie JSON validation.

---

## 3. Reuse decision

**Decision: Option B** — Reuse core parser/check **patterns** and Kee-Suri **constants** where safe; implement a **Kee-Suri rule adapter** for HTML preview files.

### 3.1 Reusable (with safe decoupling)

| Asset | Source | Use in validator |
|-------|--------|------------------|
| Issue/result pattern | `validators.py` (`ValidationIssue`, `ValidationResult`) or parallel Kee-Suri dataclass with same shape | Structured PASS/FAIL reporting |
| Text normalization | `_norm_text`-style helper — **copy inline or thin local helper**; do not import finance-specific validator modules | Whitespace collapse for substring / order checks |
| Section constants | `keysuri_private_briefing.py`, `keysuri_news_contract.py` | Required section labels, program → TOP 5 heading map |
| Index order checks | Pattern inspired by ops `html_order_indices` | `str.find()` / anchor order for Korea 18:30 placement |
| Regex section presence | Pattern from `tests/test_keysuri_renderer.py` | Section heading and card counts |

### 3.2 Not reusable as-is

| Asset | Reason |
|-------|--------|
| `validate_today_genie` | Finance feeds, market_snapshot, TOP 3, mandatory hashtags — incompatible with Kee-Suri §14 |
| `validate_common_structure` | Requires `hashtags`, `channel_drafts`, naver fields |
| `publishing_policy.decide_publishing_actions` | Email/scheduler delivery semantics |
| `scripts/run_tpo_proof_once.py` | today_genie proof + image generation |
| `scripts/run_owner_review_full_tpo_v2.py` | today_genie owner email path |
| `scripts/send_today_genie_email_test.py` | Email send test harness |
| Genie hashtag requirements | Kee-Suri §14: no hashtag section by default |
| Today/Tomorrow renderer assumptions | Different section order, identity, and delivery contract |

### 3.3 Dependency rule

The validator module may import **Kee-Suri constants only** (`keysuri_private_briefing`, `keysuri_news_contract`). It must **not** import `main`, `orchestrator`, `publishing_policy`, `validators.validate_today_genie`, or email/image modules.

---

## 4. Proposed implementation files

### 4.1 New files (future code task — not in this plan commit unless owner approves code)

| Role | Path |
|------|------|
| Validator module | `keysuri_html_preview_validation.py` |
| CLI script | `scripts/validate_keysuri_html_preview.py` |
| Tests | `tests/test_keysuri_html_preview_validation.py` |

### 4.2 Explicit do-not-modify list

The validator implementation must **not** change:

- `main.py`
- `orchestrator.py`
- `run_orchestrator.py`
- `email_sender.py`
- Image API modules (`keysuri_image_api_*`, manual canary runners, etc.)
- Scheduler code and scheduler docs wiring
- Production renderer wiring (`keysuri_renderer.py` behavior changes deferred until validator exists and passes)

### 4.3 Git and output boundaries

- `output/**` remains **gitignored** — preview HTML is never committed.
- Validator and tests **may** be committed after owner approval of the code task.
- This plan document may be committed independently of code.

---

## 5. Validator input/output contract

### 5.1 Primary function

```python
def validate_keysuri_html_preview(
    path: str,
    *,
    program_id: str | None = None,
) -> KeysuriHtmlPreviewValidationResult:
    ...
```

### 5.2 Inputs

| Input | Required | Behavior |
|-------|----------|----------|
| `path` | Yes | Filesystem path to a single `.html` file |
| `program_id` | No | `keysuri_global_tech` or `keysuri_korea_tech`; if omitted, infer from filename and/or visible TOP 5 heading |

**Program inference heuristics (when `program_id` is None):**

- Filename contains `korea` or `1830` → treat as Korea 18:30 preview (enable placement checks).
- Filename contains `global` or `1230` → treat as global preview.
- Visible heading **국내 테크 TOP 5** vs **글로벌 테크 TOP 5** as tie-breaker.

### 5.3 Output structure

Top-level result (mirrors contract §15.2):

| Field | Type | Values |
|-------|------|--------|
| `validation_status` | str | `PASS` or `FAIL` |
| `validation_timestamp` | str | ISO-8601 check time (validator-generated, not read from file) |
| `required_sections` | str | `PASS` / `FAIL` |
| `top5_sources` | str | `PASS` / `FAIL` |
| `deep_dive_readability` | str | `PASS` / `FAIL` |
| `rights_policy` | str | `PASS` / `FAIL` |
| `no_hashtags` | str | `PASS` / `FAIL` |
| `no_production_implication` | str | `PASS` / `FAIL` |
| `warm_close_order` | str | `PASS` / `FAIL` / `N/A` (N/A when not Korea 18:30 preview) |
| `file_path` | str | Resolved path |
| `program_id` | str | Resolved program |
| `issues` | list | `{code, message, severity}` — `severity` ∈ `error`, `warning` |

**Aggregate rule:** If any sub-check is `FAIL`, `validation_status` must be **`FAIL`**.

**Honesty rule:** If the HTML validation result box claims `validation_status: PASS` (or equivalent visible marker) but any sub-check fails, the validator's final `validation_status` is **`FAIL`** with issue code `claimed_pass_mismatch`.

### 5.4 CLI contract

**Script:** `scripts/validate_keysuri_html_preview.py`

| Behavior | Detail |
|----------|--------|
| Arguments | One file path, or glob under `output/keysuri_preview/html_test/` |
| Mode | **Read-only** — open file, run checks, print JSON to stdout |
| Exit code | `0` on aggregate `PASS`; non-zero on `FAIL` or I/O error |
| Side effects | **None** — no HTML mutation, no API calls, no email, no scheduler |
| Optional flags | `--program-id`, `--pretty` (implementation detail) |

---

## 6. Required validation rules

Rules below align with `KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md` §15.3. Implementation should map each failing rule to a stable `code` in `issues`.

### 6.A File / path

| Check | Rule |
|-------|------|
| Exists | File path resolves to a readable file |
| Directory | Path is under `output/keysuri_preview/html_test/` (relative to repo root or absolute equivalent) |
| Timestamp filename | Basename matches `*_YYYYMMDD_HHMMSS.html` (seconds granularity) |
| Non-empty | File size > 0 |
| Basic HTML | Contains `<!DOCTYPE html>`, `<html`, `<head`, `<body` (case Relaxed for doctype) |

### 6.B Required sections

**All previews:**

| Section / marker | Detection hint |
|------------------|----------------|
| Preview metadata | Visible preview banner or metadata block (e.g. preview mode, review_required) |
| **테크 비서 키수리** | Exact or canonical identity title |
| **글로벌 테크 TOP 5** or **국내 테크 TOP 5** | Per resolved `program_id` — exactly one active TOP 5 heading |
| **키수리의 딥-다이브** | Locked section label |
| **원-라인 체크포인트** | Locked section label |
| **마무리 및 출처 리스트** | Locked section label |
| Operation metadata | Visible op/review box (not confused with rights footer) |
| Contract compliance checklist | Visible checklist section |
| Validation result box | Visible box with §15.2 fields |

**Korea 18:30 preview only** (when `program_id == keysuri_korea_tech` or korea/1830 filename):

| Section / marker | Rule |
|------------------|------|
| 18:30 bottom-shot placeholder | Bottom-shot preview section or placeholder marker |
| **국내 18:30 따뜻한 마무리** | Warm close section label |

**Global preview:** Korea-only sections are **not** required; `warm_close_order` → `N/A`.

### 6.C TOP 5 source display

For each of **5** TOP items (detect via `news-card` class or numbered item blocks):

| Field | Acceptable markers |
|-------|-------------------|
| Source name | `source_name`, `출처명`, or labeled source name line |
| Source URL | `source_url`, `URL`, `http://`, or `https://` within item block |
| Verification status | `verification_status`, `검증 상태`, with value `sample_only`, `not_verified`, or owner-approved equivalent |

**Failure codes (examples):** `top5_item_missing_source_url`, `top5_item_count_not_five`.

### 6.D 딥-다이브 readability

Apply when deep-dive body is **dense** (heuristic: character count or paragraph count above threshold — tunable in tests).

| Check | Rule |
|-------|------|
| Layer structure | Numbered layers `1` / `2` / `3` or equivalent card headings |
| Korea model titles | When Korea preview and dense: accept titles **물리·인프라 병목**, **규제·주권·조달 압력**, **워크플로·락인** (or structural equivalents — not blind copy if global uses equivalent three-layer movement) |
| Not one block | Deep-dive region must not be a single `<p>` wall without layer/card separators |
| Separators | Layer/card/separator CSS class or heading hierarchy present |

When deep-dive is **short** (below density threshold): `deep_dive_readability` → `PASS` with optional warning `deep_dive_density_below_threshold`.

### 6.E Rights policy

Exact visible text (both lines required, allow normalized whitespace):

```
Copyright Ⓒ MirAI:ON. All rights reserved.
무단 전재, 재배포 및 AI학습 이용 절대 금지
```

Must be **visible** in body HTML — not HTML-comment-only.

### 6.F Negative checks

Must **not** be present in customer-visible HTML (exclude raw HTML comments from scan if needed):

| Forbidden | Notes |
|-----------|-------|
| Hashtag section | Section titled 해시태그 or similar |
| Hashtag list | `#키수리` or `#` token list pattern |
| **테크 앵커** / **뉴스 앵커** | Forbidden identity |
| **Today_Geenee** / **Tomorrow_Geenee** | Program bleed — including `tomorrow_genie` |
| `production_ready: true` | Literal or JSON-like marker |
| `scheduler_ready: true` | Literal or JSON-like marker |
| `email_ready: true` | Literal or JSON-like marker |
| `static/email` paths | Production email asset paths |
| Production image paths | Image API or promoted asset paths presented as approved production assets |

**Scope note:** Owner-review metadata that states `No email sent` is **allowed** — distinct from `email_ready: true`.

### 6.G Korea 18:30 placement checks

When Korea 18:30 preview is in scope, verify **document order** (character index or DOM walk):

```text
원-라인 체크포인트
  → bottom-shot placeholder / section
  → 국내 18:30 따뜻한 마무리
  → 마무리 및 출처 리스트
  → rights policy (§13 exact text)
  → operation metadata
  → validation result box (last)
```

Each anchor must appear **after** the previous anchor in HTML source order. Failure code example: `warm_close_order_violation`.

---

## 7. Validation result box policy

### 7.1 Validator responsibility (phase 1)

- **Verify the box exists** and exposes §15.2 sub-fields (visible text or labeled rows).
- **Run all checks independently** — do not trust embedded PASS labels alone.
- **Enforce honesty:** claimed `PASS` in the file + any failed sub-check → aggregate **`FAIL`** + `claimed_pass_mismatch`.

### 7.2 Out of scope for validator (phase 1)

- **Writing** or **updating** the validation result box in HTML.
- Re-rendering previews to inject the box.

### 7.3 Future optional behavior (separate approval)

A **preview writer** or **renderer patch** may inject/update the validation result box after validation runs. That is a **separate task** from this validator module. Until then:

- Manual previews may embed a validation box by hand (as in the revised Korea sample).
- The validator remains **read-only** and is the source of truth for whether embedded claims are honest.

---

## 8. Test plan

Implement in `tests/test_keysuri_html_preview_validation.py` using **inline HTML fixture strings** (preferred) — not committed files under `output/**`.

| Case | Expected aggregate |
|------|-------------------|
| Minimal PASS — global preview | `PASS` — all sub-checks pass; `warm_close_order` = `N/A` |
| Minimal PASS — Korea 18:30 preview | `PASS` — includes placement order |
| Missing `source_url` on one TOP item | `FAIL` — `top5_sources` |
| Missing rights policy | `FAIL` — `rights_policy` |
| Hashtag section present | `FAIL` — `no_hashtags` |
| Wrong warm-close order (warm close before bottom-shot) | `FAIL` — `warm_close_order` |
| `production_ready: true` in body | `FAIL` — `no_production_implication` |
| Dense 딥-다이브 without 1/2/3 layers | `FAIL` — `deep_dive_readability` |
| Claimed PASS in box but missing rights text | `FAIL` — `claimed_pass_mismatch` + `rights_policy` |
| Invalid filename (no timestamp) | `FAIL` — file/path check |
| Wrong directory path | `FAIL` — file/path check |

**Optional smoke test:** If `output/keysuri_preview/html_test/keysuri_korea_1830_bottom_close_sample_revised_20260605_130753.html` exists locally, skip or run as non-CI integration — file is gitignored.

---

## 9. Implementation guardrails

| Guardrail | Enforcement |
|-----------|-------------|
| Read-only | No write mode in CLI; no file mutation API |
| No HTML generation | Validator does not render previews |
| No image API | No imports from image/canary modules |
| No scheduler | No orchestrator or Cloud Scheduler calls |
| No email | No `email_sender` or SMTP |
| No preview mutation | Do not modify `output/**` files |
| No production wiring | No changes to runtime entrypoints in first implementation batch |
| Gitignore preserved | Preview HTML stays untracked |
| Commit gate | Validator code/tests committed only after explicit owner approval of code task |

---

## 10. Recommended next steps

| Step | Action | Gate |
|------|--------|------|
| 1 | **Commit this implementation plan** | Owner request |
| 2 | Implement `keysuri_html_preview_validation.py` + tests + CLI as a **narrow code-only batch** | After plan commit |
| 3 | Run validator against local Korea revised preview (manual) | Local only; `output/**` not committed |
| 4 | Align renderer to write validation box + rights footer (if not already) | **After** validator passes on fixtures |
| 5 | Scheduler / email / image production wiring | Separate explicit approval per scheduler design doc |

**Do not** touch renderer or production pipeline until the validator passes on fixture tests and at least one local preview smoke run.

---

## Appendix A — Document dependency chain

```text
KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md (§13–§15)
        ↓
Genie validator inspection report (2026-06 — no reusable HTML validator)
        ↓
KEYSURI_HTML_PREVIEW_VALIDATOR_IMPLEMENTATION_PLAN.md (this document)
        ↓
[future] keysuri_html_preview_validation.py + tests + CLI
        ↓
[future] renderer alignment (validation box + rights footer)
```

## Appendix B — Reference validated preview (local, gitignored)

| Field | Value |
|-------|-------|
| File | `output/keysuri_preview/html_test/keysuri_korea_1830_bottom_close_sample_revised_20260605_130753.html` |
| Manual validation | PASS (ad hoc, pre-validator) |
| Use | Smoke target only — not committed |

## Appendix C — Related source modules (read-only reference)

| Module | Role relative to validator |
|--------|---------------------------|
| `keysuri_private_briefing.py` | Section label constants |
| `keysuri_news_contract.py` | TOP 5 heading constants |
| `validators.py` | Pattern reference only — do not call today_genie validators |
| `tests/test_keysuri_renderer.py` | Render test patterns — different scope |
