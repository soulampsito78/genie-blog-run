# Kee-Suri Korea Unit 5 Final Live Contract-Preview Validation

Status: **Recorded snapshot** — one-shot final validation after `eaa4532` (2026-06-09).

Classification: **PASS_OWNER_REVIEW_READY**

---

## 1. Commit baseline

| Commit | Summary |
|--------|---------|
| **eaa4532** | Add Kee-Suri Korea contract and owner-review UX guards |
| 301af68 | Add Kee-Suri Korea briefing generation lens |
| 83a2a10 | Add Kee-Suri Global/Korea duplicate guard |
| 2c754fc | Add Kee-Suri Korea Tech scoring and TOP5 selection |
| 06042ce | Add Kee-Suri Korea Tech live feed configuration |

Working tree was **clean** before and after validation. No patch, retry, stage, or commit during Unit 5.

---

## 2. Validation scope

- Korea **18:30** contract-preview path (`keysuri_korea_tech`)
- **One-shot** Gemini live smoke (`--use-gemini --contract-preview`)
- **Single** smoke run — no retry, no second HTML
- No runtime source or test changes during validation

**Explicitly excluded / not run:**

- Image API
- Email send
- Scheduler mutation
- Today_Geenee / Tomorrow_Geenee
- `admin_runs` mutation
- `static/email/**` changes
- `output/**` staging or commit

---

## 3. Test results (pre-smoke)

| Suite | Result |
|-------|--------|
| `py_compile` (11 modules) | **PASS** |
| Main unittest (10 modules) | **271 tests — OK** |
| Narrow regression (3 modules) | **33 tests — OK** |

**py_compile modules:**

- `keysuri_visible_text.py`
- `keysuri_korea_longform_ux.py`
- `keysuri_news_contract.py`
- `keysuri_briefing_content_enricher.py`
- `keysuri_briefing_body_ux_normalizer.py`
- `keysuri_briefing_content_quality.py`
- `keysuri_contract_preview_fixture.py`
- `keysuri_contract_preview_renderer.py`
- `keysuri_generation_prompt.py`
- `keysuri_live_source_smoke.py`
- `keysuri_html_preview_validation.py`

---

## 4. Single smoke command

```bash
export PROJECT_ID=gen-lang-client-0667098249

python3 scripts/run_keysuri_live_source_smoke.py \
  --program keysuri_korea_tech \
  --max-items 15 \
  --use-gemini \
  --contract-preview
```

---

## 5. Smoke result

| Field | Value |
|-------|-------|
| **ok** | `true` |
| **called_gemini** | `true` |
| **called_image_api** | `false` |
| **send_attempted** | `false` |
| **parse_status** | `parsed_valid` |
| **structural gate** | `pass` |
| **content gate** | `pass` |
| **visual gate** | `pass` (warning: `watermark_pending` only) |
| **owner_visual_review_ready** | `true` |
| **preview_overall_status** | `owner_visual_review_ready` |

**Artifact paths:**

| Artifact | Path |
|----------|------|
| **HTML** | `output/keysuri_preview/html_test/keysuri_korea_live_generated_contract_preview_20260609_002826.html` |
| **Source pack / selection debug** | `output/keysuri_preview/keysuri_korea_live_source_smoke_generated_20260609_002826.json` |
| **Raw Gemini response** | `output/keysuri_preview/keysuri_live_gemini_raw_response_20260609_002926.txt` |

**Image context (smoke metadata):**

- `image_source_mode`: `approved_registry`
- `approved_asset_id`: `keysuri_korea_top_20260604_225207`
- `image_in_html`: `true`

---

## 6. TOP5 titles

1. 삼성전자 전영현 부회장, 젠슨 황 CEO와 HBM4·파운드리 협력 논의
2. 한미반도체, SK하이닉스 청주 공장에 HBM4 TC 본더 첫 공급 계약
3. 젠슨 황 엔비디아 CEO, 방한 중 국내 AI 기업에 GPU 우선 공급 약속
4. 한국원자력협력재단, 원자력 기술 스타트업 육성 프로그램 '아토믹 네스트' 5기 모집
5. 업스테이지 김성훈 대표, "젠슨 황, 한국 AI 기업 투자 필요성 강조

> **Non-blocking copy note:** TOP5 card #5 is missing a closing `"` in the rendered visible headline. Gates passed; headline quote sanitizer is a future follow-up only.

---

## 7. Duplicate guard

| Field | Value |
|-------|-------|
| **policy** | `keysuri_korea_top5_selection_v2_duplicate_guard` |
| **status** | `not_applied_no_global_report` |
| **duplicate_detected_count** | `0` |
| **duplicate_penalized_count** | `0` |

**Final category distribution:**

| Category | Count |
|----------|-------|
| `korea_semiconductor` | 2 |
| `korea_startup_investment` | 1 |
| `korea_big_company_strategy` | 1 |
| `global_to_korea_translation` | 1 |

**Final source distribution:** thelec ×2, venturesquare ×1, zdkorea ×1, aitimes ×1

No `top_5_news_item_category_unknown` content-gate issues observed.

---

## 8. Visible HTML scan

| Check | Result |
|-------|--------|
| Internal label “국내 18:30 따뜻한 마무리” | **0** |
| “퇴근 전 메모” | **1** |
| Concrete memo action lines (`<li>`) | **3** |
| Warm farewell lines | **2** |
| Max deep-dive paragraph length | **164** chars (limit 220) |
| Max closing paragraph / `<li>` length | **49** chars (limit 220) |
| Max memo action line length | **34** chars (limit 180) |
| Malformed headline fragments (H… / 만…) | **0** |
| Internal score/tag leak | **0** |
| Visible snake_case in user prose | **0** |
| Python list repr (`['`, `&#x27;, &#x27;`) | **0** |
| Label-only “내일 영향” emphasis | **0** |
| Duplicate phrases (신호 신호 / 내일 영향: 내일 영향: / → →) | **0** |
| “주인님” count | **8** |

**Warm farewell lines confirmed:**

- 오늘도 수고 많으셨습니다.
- 내일 아침에 다시 볼 흐름만 남겨두겠습니다.

**Source/appendix gate:**

- `source_list_incomplete` — **absent**
- Source URLs read from `source-appendix-section`, not memo-only `closing-section`

**Memo action lines (HTML `<ol class="evening-memo-actions">`):**

1. 삼성전자의 HBM4 개발 로드맵 및 양산 계획 발표
2. 엔비디아의 차세대 GPU 로드맵과 삼성전자 파운드리 활용 여부
3. SK하이닉스와 삼성전자 간 HBM 시장 점유율 변화 추이

---

## 9. Image / visual role check

| Check | Result |
|-------|--------|
| **theme** | `theme-korea` |
| **top image role** | `korea_top` via `keysuri_korea_top_20260604_225207` (approved registry) |
| **bottom image role** | Placeholder only (`bottom-shot-placeholder`) — no bottom asset rendered |
| **221233 global-only preserved** | **yes** — smoke used 225207, not 221233 |
| **105936 not global_top** | **yes** — 105936 not used |
| **visual gate warnings** | `watermark_pending` only (locked asset without MirAI:ON watermark yet) |

**Note:** Standalone HTML re-validation without registry context may report `manifest_missing`; smoke pipeline correctly passed visual via `approved_asset_registry_match`.

---

## 10. Final classification

**PASS_OWNER_REVIEW_READY**

All three gates pass under smoke pipeline context. `owner_visual_review_ready: true` honestly reported.

---

## 11. Non-blocking follow-up note

Headline sanitizer should eventually close unmatched Korean/English quote marks in visible headlines (observed on TOP5 #5). **Do not patch now unless separately approved.**

---

## 12. Safety confirmations

| Confirmation | Status |
|--------------|--------|
| Git working tree clean (tracked files) | **yes** |
| `output/**` not staged | **yes** |
| No image API | **yes** |
| No email | **yes** |
| No scheduler | **yes** |
| No Today_Geenee / Tomorrow_Geenee | **yes** |
| No `admin_runs` / `static/email/**` mutation | **yes** |
| Single smoke only, no retry | **yes** |

---

## 13. References

- `KEYSURI_LIVE_GENERATED_SMOKE_OUTPUT_MATRIX.md`
- `KEYSURI_LOCKED_IMAGE_ROLE_MAP.md`
- `KEYSURI_APPROVED_IMAGE_ASSET_REGISTRY.md`
- `KEYSURI_GLOBAL_KOREA_DESIGN_SEPARATION_HANDOFF_v2.md`
