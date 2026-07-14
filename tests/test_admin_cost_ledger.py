"""Tests for best-effort generation cost ledger export."""
from __future__ import annotations

import csv
import io
import os
import unittest
from unittest import mock

from admin_cost_ledger import (
    build_cost_record,
    cost_ledger_object_key,
    cost_record_object_key,
    cost_record_to_csv_row,
    month_from_run_meta,
    save_cost_record_best_effort,
)


def _cost_meta() -> dict:
    return {
        "run_id": "20260709_183000_keysuri_korea_tech_aabbccdd",
        "created_at": "2026-07-09T18:30:00+09:00",
        "mode": "keysuri_korea_tech",
        "program_id": "keysuri_korea_tech",
        "trigger_source": "scheduled_service_full_run",
        "validation_result": "pass",
        "email_sent": True,
        "customer_delivery_status": "not_sent",
        "owner_review_url": "https://example.com/admin/runs/20260709_183000_keysuri_korea_tech_aabbccdd",
        "cost_estimate": {
            "estimate_only": True,
            "service_family": "keysuri",
            "program_id": "keysuri_korea_tech",
            "run_id": "20260709_183000_keysuri_korea_tech_aabbccdd",
            "model": {
                "text_model": "gemini-2.5-flash",
                "image_model": "gemini-2.5-flash-image",
            },
            "usage": {
                "prompt_token_count": 1000,
                "candidates_token_count": 2000,
                "thoughts_token_count": 3000,
                "total_token_count": 6000,
                "generated_image_count": 1,
            },
            "image_usage": {
                "generated_image_count_semantics": "paid_successful_api_outputs",
                "image_api_provider": "google_cloud_vertex_ai",
                "image_model_raw": "gemini-2.5-flash-image",
                "image_model_normalized": "gemini-2.5-flash-image",
                "image_pricing_mode": "standard_paygo",
                "image_request_count": 1,
                "image_successful_output_count": 1,
                "image_failed_request_count": 0,
                "image_retry_count": 0,
                "image_discarded_output_count": 0,
                "image_locally_derived_asset_count": 1,
                "image_cache_reuse_count": 0,
                "image_static_fallback_count": 0,
                "image_output_tokens": 1290,
            },
            "components": {
                "text_input_cost_usd": 0.0003,
                "text_output_cost_usd": 0.005,
                "text_thoughts_cost_usd": 0.0075,
                "text_total_cost_usd": 0.0128,
                "image_cost_usd": None,
            },
            "total_cost_usd": 0.0128,
            "total_cost_krw": None,
            "cost_estimate_status": "partial",
            "pricing_source": "env",
            "price_env_configured": True,
            "missing_price_env": [
                "GENIE_COST_GEMINI_2_5_FLASH_IMAGE_USD_PER_IMAGE",
            ],
        },
    }


class CostRecordSchemaTests(unittest.TestCase):
    def test_cost_estimate_builds_cost_record(self) -> None:
        record = build_cost_record(_cost_meta())
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record["run_id"], "20260709_183000_keysuri_korea_tech_aabbccdd")
        self.assertEqual(record["service_family"], "keysuri")
        self.assertEqual(record["text_model"], "gemini-2.5-flash")
        self.assertEqual(record["image_model"], "gemini-2.5-flash-image")
        self.assertEqual(record["prompt_token_count"], 1000)
        self.assertEqual(record["generated_image_count"], 1)
        self.assertEqual(record["image_successful_output_count"], 1)
        self.assertEqual(record["image_output_tokens"], 1290)
        self.assertEqual(record["generated_image_count_semantics"], "paid_successful_api_outputs")
        self.assertEqual(record["cost_estimate_status"], "partial")

    def test_missing_price_env_is_csv_safe_pipe_joined(self) -> None:
        record = build_cost_record(_cost_meta())
        assert record is not None
        row = cost_record_to_csv_row(record)
        self.assertEqual(
            row["missing_price_env"],
            "GENIE_COST_GEMINI_2_5_FLASH_IMAGE_USD_PER_IMAGE",
        )
        self.assertEqual(row["text_total_cost_usd"], "0.0128")
        self.assertEqual(row["total_cost_usd"], "0.0128")

    def test_null_costs_are_empty_in_csv_row(self) -> None:
        record = build_cost_record(_cost_meta())
        assert record is not None
        row = cost_record_to_csv_row(record)
        self.assertEqual(row["image_cost_usd"], "")
        self.assertEqual(row["total_cost_krw"], "")

    def test_monthly_paths_use_yyyy_mm(self) -> None:
        meta = _cost_meta()
        self.assertEqual(month_from_run_meta(meta), "2026-07")
        self.assertEqual(
            cost_record_object_key(meta["run_id"], "2026-07"),
            "admin_runs/cost_records/2026-07/20260709_183000_keysuri_korea_tech_aabbccdd.cost.json",
        )
        self.assertEqual(
            cost_ledger_object_key("2026-07"),
            "admin_runs/cost_reports/genie_cost_ledger_2026-07.csv",
        )


class CostRecordPersistenceTests(unittest.TestCase):
    def test_gcs_record_write_failure_does_not_raise_or_block_ledger(self) -> None:
        uploads: dict[str, str] = {}

        def _upload(key: str, text: str, *, content_type: str) -> None:
            if key.endswith(".cost.json"):
                raise RuntimeError("record write failed")
            uploads[key] = text

        with mock.patch.dict(os.environ, {"GENIE_ADMIN_ARTIFACT_BUCKET": "bucket"}, clear=False):
            with mock.patch("admin_cost_ledger._gcs_upload_text", side_effect=_upload):
                with mock.patch("admin_cost_ledger._gcs_download_text", return_value=None):
                    result = save_cost_record_best_effort(_cost_meta())
        self.assertFalse(result["cost_record_saved"])
        self.assertTrue(result["cost_ledger_saved"])
        self.assertIn("record write failed", str(result["cost_record_error"]))
        ledger_text = next(iter(uploads.values()))
        rows = list(csv.DictReader(io.StringIO(ledger_text)))
        self.assertEqual(rows[0]["run_id"], "20260709_183000_keysuri_korea_tech_aabbccdd")


if __name__ == "__main__":
    unittest.main()
