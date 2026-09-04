#!/usr/bin/env python3
"""Bounded, deterministic, no-network GENIE product release gate."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


TEST_MODULES = (
    "test_product_surface_contract",
    "test_product_regression_corpus",
    "test_product_acceptance_authority",
    "test_owner_review_send_policy",
    "test_today_genie_20260902_surgical_incident",
    "test_today_genie_grounding",
    "test_today_genie_grounding_stabilization",
    "test_today_genie_email_render_quality",
    "test_keysuri_news_contract",
    "test_keysuri_visible_text_quality",
    "test_keysuri_briefing_content_quality",
    "test_keysuri_renderer_validator_compat",
    "test_keysuri_global_visible_quality_20260814",
    "test_keysuri_global_corpus_20260828",
    "test_keysuri_reader_surface_contract_20260828",
    "test_keysuri_korea_20260814_1830_slash_label_harness",
)


def main() -> int:
    # The suite must never inherit production mutation intent.
    os.environ["GENIE_PRODUCT_REGRESSION_OFFLINE"] = "1"
    os.environ.pop("GENIE_OWNER_REVIEW_SEND", None)
    os.environ.pop("GENIE_CUSTOMER_DELIVERY_ENABLED", None)
    os.environ.pop("GENIE_KEYSURI_CUSTOMER_DELIVERY_ENABLED", None)
    sys.dont_write_bytecode = True
    repo_dir = Path(__file__).resolve().parents[1]
    tests_dir = repo_dir / "tests"
    sys.path.insert(0, str(repo_dir))
    sys.path.insert(0, str(tests_dir))

    suite = unittest.defaultTestLoader.loadTestsFromNames(TEST_MODULES)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    passed = result.wasSuccessful()
    verdict = "PASS" if passed else "FAIL"
    print(f"TECHNICAL_TEST_PASS={verdict}")
    print(f"RUNTIME_SAFETY_CONTRACT={verdict}")
    print(f"CUSTOMER_SURFACE_CONTRACT={verdict}")
    print(f"RELEASE_REGRESSION_{verdict}")
    print(f"GENIE_PRODUCT_REGRESSION_GATE={verdict}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
