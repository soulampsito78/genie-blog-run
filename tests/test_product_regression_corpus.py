"""Authoritative persisted/excerpt corpus for the cross-mode release gate."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Dict, Tuple

from product_surface_contract import (
    CUSTOMER_SURFACE_PASS,
    PRODUCT_REVIEW_REQUIRED,
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
                    repaired = prepare_final_customer_copy(
                        entry["mode"], structured, source_input=source_input
                    )
                    repaired_result = evaluate_product_surface(
                        entry["mode"], repaired, source_input=source_input
                    )
                    self.assertEqual(repaired_result.status, CUSTOMER_SURFACE_PASS)
                    self.assertEqual(
                        [item["news_id"] for item in repaired["key_watchpoints"]],
                        [item["news_id"] for item in structured["key_watchpoints"]],
                    )
                    self.assertEqual(
                        [item["headline"] for item in repaired["key_watchpoints"]],
                        [
                            "미국 통화정책 발언과 금리 경로",
                            "Lululemon 주가 변동",
                            "8월 고용지표 발표",
                        ],
                    )
                    reader_copy = " ".join(
                        str(item.get("headline", "")) + " " + str(item.get("detail", ""))
                        for item in repaired["key_watchpoints"]
                    )
                    for leaked in (
                        "Vance says Fed should low…",
                        "Lululemon stock plunges 1…",
                        "The big August jobs repor…",
                        "Lululemon·Plunges 관련",
                        "야간·장전 맥락에서",
                        "흐름이 대응 축으로 남아",
                    ):
                        self.assertNotIn(leaked, reader_copy)


if __name__ == "__main__":
    unittest.main()
