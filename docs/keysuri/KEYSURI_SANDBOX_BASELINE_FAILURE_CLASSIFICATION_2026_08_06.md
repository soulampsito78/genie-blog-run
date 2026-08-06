# Track A — Baseline Failure Classification

Starting HEAD: 7d19869bde8201e91a0ba02f1d8a1d8786c00998
Working tree at identity gate already included uncommitted fixes for skip/xfail conversion.

## Clean HEAD (git archive) full suite
- collected ~2486 (+skips)
- 2 failed, 2466 passed, 17 skipped, 1 xfailed

## Failed nodes (clean HEAD)

### 1. tests/test_keysuri_contract_preview_quality.py::KeysuriContractPreviewQualityTests::test_passes_premium_korean_fixture_with_data_uri_hero
- assertion: assertIsNotNone(img_match) — hero img with class top-shot-hero missing (fallback rendered)
- production path: keysuri_contract_preview_renderer.resolve_top_shot_asset_path → resolve_approved_hero_image_path → output/keysuri_preview/image_canary/*.jpg
- current-head behavior with local canary present: PASS
- clean-baseline behavior without canary: FAIL
- active path: contract preview renderer (active)
- classification: ENVIRONMENT_DEPENDENT (untracked/local canary JPEG required)
- remedy: inject deterministic tiny PNG data URI into fixture (top_shot_image_src); do not weaken production validation
- changed: tests/test_keysuri_contract_preview_quality.py
- final result: PASS

### 2. tests/test_keysuri_contract_preview_renderer.py::KeysuriPremiumHandoffRendererTests::test_hero_uses_data_uri_not_relative_path
- assertion: assertIn('class="top-shot-hero"', html)
- same production path / same root cause
- classification: ENVIRONMENT_DEPENDENT
- remedy: same — set top_shot_image_src to deterministic data URI in the test
- changed: tests/test_keysuri_contract_preview_renderer.py
- final result: PASS

## Historical documented failures (closeout 21)
Previously attributed to manual_opt_in / offline_dry_run / prompt_input / renderer.
At HEAD 7d19869 those suites PASS (resolved by commit 07531d8 and follow-ons).
Classification: ALREADY_FIXED_BUT_STALE_BASELINE (documentation lag).

## Pre-existing dirty-tree conversions (preserved)
- test_keysuri_image_overlay.py: removed unconditional skip → REAL assertions (TRANSIENT_TEST_DEFECT → fixed)
- test_keysuri_renderer_validator_compat.py: removed expectedFailure → REAL assertions (INVALID_TEST_EXPECTATION/xfail → fixed)
- test_keysuri_global_reissue_content.py: replaced external scratchpad skips with in-repo incident shape fixtures (STALE_FIXTURE → fixed)
- admin_store/admin_routes: reissue_parent_block_reason gate (REAL_PRODUCT_DEFECT prevention for placeholder parents)

## xfail
- Clean HEAD had 1 xfailed (renderer validator compat) — removed by dirty-tree fix; no new xfail introduced.
