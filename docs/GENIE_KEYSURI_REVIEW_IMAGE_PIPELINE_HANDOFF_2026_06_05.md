# Genie / Kee-Suri Review-Box & Image-Manifest Pipeline — Handoff (2026-06-05)

Concise current-state handoff for the Kee-Suri image pipeline and Genie/Kee-Suri review-operation-box work completed through 2026-06-05.

---

## 1. Scope

This handoff covers:

- **Kee-Suri image watermark / manifest pipeline** — MirAI:ON overlay, CLI, manifest writer, tests
- **Kee-Suri review confirmation policy / tests** — shared policy alignment, contract preview renderer, separation tests, validator deferral decision
- **Today_Geenee owner/customer review operation box semantics** — admin box wording fix, owner vs customer surface separation (active Genie track)
- **Today_Geenee customer outbound `review_passed` behavior** — approved-send injection, `sent_archived` deferral

**Active operating tracks:** **Today_Geenee** and **Kee-Suri** only.

**Closed / dormant track:** **Tomorrow_Geenee** — not a remaining implementation gap. Customer delivery and further review-box work for Tomorrow_Geenee are out of scope due to platform risk and weak monetization; do not plan or suggest implementing Tomorrow_Geenee customer delivery.

Out of scope here: scheduler runs, live email send, image API production calls, Content Shield, admin web redesign, Tomorrow_Geenee customer delivery.

---

## 2. Completed commits (chronological)

| Commit | Summary |
|--------|---------|
| `530fded` | Document Kee-Suri image watermark policy |
| `60308ca` | Add Kee-Suri image overlay tests |
| `b090c87` | Add Kee-Suri MirAI:ON image overlay utility |
| `7646f02` | Add Kee-Suri image watermark CLI |
| `7cf3c93` | Design Kee-Suri image asset manifest |
| `c46061a` | Add Kee-Suri image asset manifest writer tests |
| `fda8bcf` | Add Kee-Suri image asset manifest writer |
| `e484d39` | Extend Kee-Suri watermark CLI with manifest writing |
| `16b4c66` | Document shared review operation box policy |
| `2f0cbde` | Align Kee-Suri docs with review operation policy |
| `8bc8418` | Strengthen Kee-Suri review box separation tests |
| `5c5d7c6` | Document Kee-Suri review box validator decision |
| `90f0af7` | Document Genie email operation box semantics fix plan |
| `d97d7fb` | Fix Genie email operation box semantics |
| `64985ff` | Add Genie customer review confirmation on approved send |
| `705a50f` | Document Genie sent archived wording decision |

**Key docs:** `docs/REVIEW_OPERATION_BOX_POLICY.md`, `docs/genie/GENIE_EMAIL_OPERATION_BOX_SEMANTICS_FIX_PLAN.md`, `docs/genie/GENIE_SENT_ARCHIVED_WORDING_DECISION.md`

---

## 3. Kee-Suri current state

| Area | State |
|------|-------|
| Visible watermark | MirAI:ON required on raster preview/output images |
| Prompt/model watermark | Contamination → **FAIL** |
| Watermark application | Post-processing overlay (`keysuri_image_overlay` / CLI) |
| CLI manifest | `--write-manifest` writes sidecar JSON |
| Manifest fields | `source` / `watermarked` paths, SHA-256 hashes, dimensions, `review_status`, `production_ready=false` |
| Contract preview | `#review-confirmation-box` with `preview_pending` / `review_passed` / `sent_archived` (preview surface) |
| Renderer tests | Lock review box separation from validation / operation metadata |
| HTML preview validator | Does **not** enforce `review-confirmation-box` yet (by decision in `KEYSURI_HTML_PREVIEW_VALIDATOR_REVIEW_BOX_DECISION.md`) |

---

## 4. Today_Geenee current state (active Genie track)

| Area | State |
|------|-------|
| Owner/admin operation box title | **운영자 검수 상태** (`#genie-operational-handoff`) |
| Validation pass label | **자동 검증 통과** (not 기본 검수 통과) |
| Email delivery label | No longer **이메일 발송 완료** from `validation_result` alone |
| Customer final HTML | Strips `#genie-operational-handoff` |
| Approved outbound email | Injects `#review-confirmation-box` with **`review_passed` only** |
| Review confirmation text | `본 브리핑은 운영책임자의 직접 검수를 통과했습니다.` |
| Rejected outbound states | `preview_pending`, `sent_archived` → `ValueError` |
| `sent_archived` / 발송되었습니다 | Deferred to explicit post-send/archive surfaces (`GENIE_SENT_ARCHIVED_WORDING_DECISION.md`) |
| Saved owner artifact HTML | Pre-approval; no customer review box persisted |

**Send path:** `admin_store.approve_run()` → `send_today_geenee_customer_final_email()` → `prepare_customer_final_html(..., review_confirmation_state="review_passed")`

---

## 5. Important separations

| Must not conflate | Correct separation |
|-------------------|-------------------|
| Automated validation PASS | Owner **검수완료** (human approval) |
| Owner Gmail sent (`email_sent`) | Customer sent (`customer_delivery_status`) |
| `review_passed` | `sent_archived` |
| Validation result box | Customer review confirmation box |
| Operation metadata box | Customer-facing confirmation |
| MirAI:ON rights footer | Image watermark on raster assets |
| Kee-Suri `html_test` contract preview | Final customer email (Today_Geenee or Kee-Suri) |

---

## 6. Manual smoke already passed

Kee-Suri global canary watermark + manifest (local, not committed):

| Item | Path / value |
|------|----------------|
| Input image | `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg` |
| Output image | `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936_mirai_on_watermarked.jpg` |
| Manifest | `output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936_mirai_on_watermarked.manifest.json` |
| Status | **PASS** |
| `watermark_text` | MirAI:ON |
| `review_status` | pass_direction |
| Dimensions | 896×1152 preserved |
| Hashes | `source_sha256` ≠ `watermarked_sha256` |
| Visual QA | Watermark visible; face not covered; lower-corner placement acceptable |

---

## 7. Do not touch / out of scope

- **README.md** — modified locally, unrelated; **do not stage**
- **output/** — gitignored; remains uncommitted
- Unrelated **PDFs**, **ops/**, **static/email/**, **scripts** — remain uncommitted
- No **scheduler** / **email** / **image API** without explicit instruction
- No **`sent_archived`** in Genie outbound customer email
- No **customer review box** in owner artifact HTML
- No **Content Shield** features in Kee-Suri pipeline
- **Tomorrow_Geenee customer delivery** — closed/dormant track; not pending work (platform risk, weak monetization). Historical `tomorrow_genie` code paths may exist but are not an open review-box or delivery gap.

---

## 8. Next recommended steps

### A. Commit this handoff document

```bash
git add docs/GENIE_KEYSURI_REVIEW_IMAGE_PIPELINE_HANDOFF_2026_06_05.md
git commit -m "Document Genie Kee-Suri review image pipeline handoff"
```

### B. Focused regression set

```bash
python3 -m unittest tests.test_genie_email_operation_box_semantics -v
python3 -m unittest tests.test_batch_8_3_today_geenee_delivery -v
python3 -m unittest tests.test_owner_review_send_policy -v
python3 -m unittest tests.test_keysuri_contract_preview_renderer -v
python3 -m unittest tests.test_keysuri_image_overlay_script -v
python3 -m unittest tests.test_keysuri_image_asset_manifest -v
```

### C. Choose next branch (Today_Geenee + Kee-Suri only)

| Option | Focus |
|--------|-------|
| **Today_Geenee** | Post-send archive surface design (`sent_archived` only after `customer_sent_at`) |
| **Kee-Suri** | Manifest-approved image path integration into contract preview renderer |
| **Hygiene** | Cleanup / ignore rules for unrelated generated artifacts in working tree |

**Not a next step:** Tomorrow_Geenee customer delivery or review-box extension — closed/dormant; do not treat as a backlog item.

---

## 9. Current git hygiene rule

- Stage **only** explicitly allowed files per task
- **Never** `git add -A`
- **Never** stage `README.md`
- **Never** stage `output/**`
- **Never** stage `static/email/**`
- **Never** stage `ops/**`
- **Never** stage unrelated generated PDFs / HTML / scripts

---

## Quick reference — test files

| Track | Primary tests |
|-------|---------------|
| Today_Geenee review box | `tests/test_genie_email_operation_box_semantics.py`, `tests/test_batch_8_3_today_geenee_delivery.py` |
| Today_Geenee owner gate | `tests/test_owner_review_send_policy.py` |
| Kee-Suri review box | `tests/test_keysuri_contract_preview_renderer.py` |
| Kee-Suri watermark | `tests/test_keysuri_image_overlay_script.py` |
| Kee-Suri manifest | `tests/test_keysuri_image_asset_manifest.py` |
