"""Authoritative persisted/excerpt corpus for the cross-mode release gate."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any, Dict, Tuple

from product_surface_contract import (
    CUSTOMER_SURFACE_PASS,
    PRODUCT_REVIEW_REQUIRED,
    PRODUCT_SURFACE_DIAGNOSTIC_KEY,
    evaluate_product_surface,
    prepare_final_customer_copy,
)

_BASE = Path(__file__).resolve().parent / "fixtures" / "product_surface"


def _load_case(entry: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any] | None]:
    relative = entry.get("fixture") or entry.get("source_ref")
    raw = json.loads((_BASE / str(relative)).resolve().read_text(encoding="utf-8"))
    structured = raw.get("structured_output") if isinstance(raw, dict) else None
    return (structured if isinstance(structured, dict) else raw), raw.get("source_input")


class ProductRegressionCorpusTests(unittest.TestCase):
    def test_manifest_expectations_and_0904_proof_repair(self) -> None:
        manifest = json.loads((_BASE / "manifest.json").read_text(encoding="utf-8"))
        fixtures = manifest["fixtures"]
        self.assertEqual(len(fixtures), 6)
        self.assertEqual(
            {entry["mode"] for entry in fixtures},
            {"today_genie", "keysuri_global_tech", "keysuri_korea_tech"},
        )

        for entry in fixtures:
            with self.subTest(fixture=entry["id"]):
                structured, source_input = _load_case(entry)
                result = evaluate_product_surface(
                    entry["mode"], structured, source_input=source_input
                )
                expected = entry["expectation"]
                if expected == "GOOD_EXPECTED_PASS":
                    self.assertEqual(result.status, CUSTOMER_SURFACE_PASS)
                else:
                    self.assertEqual(result.status, PRODUCT_REVIEW_REQUIRED)
                expected_codes = set(entry.get("expected_issue_codes") or [])
                actual_codes = {finding.code for finding in result.findings}
                self.assertTrue(expected_codes.issubset(actual_codes))

                if entry.get("proof_repair"):
                    # The boundary diagnoses; it never repairs.  A defective
                    # fixture must come back byte-identical and still failing, so
                    # the defect reaches owner review instead of being masked.
                    # (Before 2026-09-07 this asserted a repair that manufactured
                    # titles such as "Lululemon 주가 변동" — the defect class itself.)
                    before = copy.deepcopy(structured)
                    inspected = prepare_final_customer_copy(
                        entry["mode"], structured, source_input=source_input
                    )
                    self.assertEqual(structured, before)
                    echoed = {
                        key: value
                        for key, value in inspected.items()
                        if key != PRODUCT_SURFACE_DIAGNOSTIC_KEY
                    }
                    self.assertEqual(echoed, before)
                    inspected_result = evaluate_product_surface(
                        entry["mode"], inspected, source_input=source_input
                    )
                    self.assertEqual(inspected_result.status, PRODUCT_REVIEW_REQUIRED)
                    self.assertEqual(
                        [item["news_id"] for item in inspected["key_watchpoints"]],
                        [item["news_id"] for item in before["key_watchpoints"]],
                    )
                    self.assertEqual(
                        [item["headline"] for item in inspected["key_watchpoints"]],
                        [item["headline"] for item in before["key_watchpoints"]],
                    )
                    # No layer may manufacture a generic reader title.
                    reader_copy = " ".join(
                        str(item.get("headline", "")) + " " + str(item.get("detail", ""))
                        for item in inspected["key_watchpoints"]
                    )
                    for fabricated in ("관련 시장 소식", "주가 변동", "해외시장 주요 이슈"):
                        self.assertNotIn(fabricated, reader_copy)


if __name__ == "__main__":
    unittest.main()
