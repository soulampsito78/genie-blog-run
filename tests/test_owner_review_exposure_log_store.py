from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from owner_review_exposure_log_store import (
    ALLOWED_EXPOSURE_KINDS,
    append_owner_review_exposure,
    load_owner_review_exposure_log,
    load_owner_review_exposure_log_with_status,
    recent_owner_review_exposure_log,
    recent_owner_review_exposure_log_with_status,
)


def _item(title: str, url: str = "https://example.com/a", **extra) -> dict:
    base = {
        "title": title,
        "url": url,
        "source": "Example",
        "normalized_source": "example",
        "topic_key": "topic",
    }
    base.update(extra)
    return base


class OwnerReviewExposureLogStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.log_path = Path(self.tmp.name) / "owner_review_exposure_log.json"
        self.env = mock.patch.dict(
            os.environ, {"GENIE_OWNER_REVIEW_EXPOSURE_LOG_PATH": str(self.log_path)}, clear=False
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_empty_log_loads_as_empty_list(self) -> None:
        self.assertEqual(load_owner_review_exposure_log(), [])
        status = load_owner_review_exposure_log_with_status()
        self.assertTrue(status["read_ok"])
        self.assertIsNone(status["error_code"])

    def test_append_writes_rows_with_expected_schema(self) -> None:
        now = datetime(2026, 6, 25, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        result = append_owner_review_exposure(
            run_id="r1",
            program_id="keysuri_global_tech",
            exposure_kind="owner_review_email",
            selected_items=[_item("Nvidia launches X", entity_keys=["nvidia"], editorial_cluster_key="ai_infra")],
            now=now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["appended_count"], 1)
        rows = load_owner_review_exposure_log()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        for field in (
            "program_id",
            "run_id",
            "exposed_at",
            "exposed_date_kst",
            "title",
            "normalized_title",
            "source",
            "normalized_source",
            "url",
            "canonical_url",
            "entity_keys",
            "editorial_cluster_key",
            "topic_key",
            "story_key",
            "exposure_kind",
        ):
            self.assertIn(field, row)
        self.assertEqual(row["entity_keys"], ["nvidia"])
        self.assertEqual(row["editorial_cluster_key"], "ai_infra")
        self.assertEqual(row["exposure_kind"], "owner_review_email")

    def test_rejects_disallowed_exposure_kind(self) -> None:
        with self.assertRaises(ValueError):
            append_owner_review_exposure(
                run_id="r1",
                program_id="keysuri_global_tech",
                exposure_kind="owner_review_reissue_image_only",
                selected_items=[_item("Title")],
            )

    def test_allowed_exposure_kinds_excludes_image_only(self) -> None:
        self.assertNotIn("owner_review_reissue_image_only", ALLOWED_EXPOSURE_KINDS)
        self.assertIn("owner_review_email", ALLOWED_EXPOSURE_KINDS)
        self.assertIn("owner_review_reissue_body", ALLOWED_EXPOSURE_KINDS)
        self.assertIn("owner_review_reissue_body_and_image", ALLOWED_EXPOSURE_KINDS)

    def test_same_run_id_upserts_instead_of_duplicating(self) -> None:
        now = datetime(2026, 6, 25, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        append_owner_review_exposure(
            run_id="same-run",
            program_id="keysuri_global_tech",
            exposure_kind="owner_review_email",
            selected_items=[_item("First")],
            now=now,
        )
        append_owner_review_exposure(
            run_id="same-run",
            program_id="keysuri_global_tech",
            exposure_kind="owner_review_email",
            selected_items=[_item("First")],
            now=now,
        )
        self.assertEqual(len(load_owner_review_exposure_log()), 1)

    def test_programs_are_kept_separate_on_read(self) -> None:
        now = datetime(2026, 6, 25, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        append_owner_review_exposure(
            run_id="r1",
            program_id="keysuri_global_tech",
            exposure_kind="owner_review_email",
            selected_items=[_item("Global", "https://example.com/g")],
            now=now,
        )
        append_owner_review_exposure(
            run_id="r2",
            program_id="keysuri_korea_tech",
            exposure_kind="owner_review_email",
            selected_items=[_item("Korea", "https://example.com/k")],
            now=now,
        )
        self.assertEqual(len(recent_owner_review_exposure_log("keysuri_global_tech", now=now)), 1)
        self.assertEqual(len(recent_owner_review_exposure_log("keysuri_korea_tech", now=now)), 1)

    def test_recent_window_default_is_five_days(self) -> None:
        now = datetime(2026, 6, 25, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        append_owner_review_exposure(
            run_id="r-old",
            program_id="keysuri_global_tech",
            exposure_kind="owner_review_email",
            selected_items=[_item("Old", "https://example.com/old")],
            now=now - timedelta(days=6),
        )
        append_owner_review_exposure(
            run_id="r-new",
            program_id="keysuri_global_tech",
            exposure_kind="owner_review_email",
            selected_items=[_item("New", "https://example.com/new")],
            now=now,
        )
        rows = recent_owner_review_exposure_log("keysuri_global_tech", now=now)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "New")

    def test_pruning_retains_up_to_ten_days(self) -> None:
        now = datetime(2026, 6, 25, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        append_owner_review_exposure(
            run_id="r-9d",
            program_id="keysuri_global_tech",
            exposure_kind="owner_review_email",
            selected_items=[_item("Nine days old", "https://example.com/nine")],
            now=now - timedelta(days=9),
        )
        result = append_owner_review_exposure(
            run_id="r-new",
            program_id="keysuri_global_tech",
            exposure_kind="owner_review_email",
            selected_items=[_item("New", "https://example.com/new")],
            now=now,
        )
        self.assertEqual(result["pruned_count"], 0)
        self.assertEqual(len(load_owner_review_exposure_log()), 2)

    def test_pruning_drops_items_older_than_ten_days(self) -> None:
        now = datetime(2026, 6, 25, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        append_owner_review_exposure(
            run_id="r-11d",
            program_id="keysuri_global_tech",
            exposure_kind="owner_review_email",
            selected_items=[_item("Eleven days old", "https://example.com/eleven")],
            now=now - timedelta(days=11),
        )
        result = append_owner_review_exposure(
            run_id="r-new",
            program_id="keysuri_global_tech",
            exposure_kind="owner_review_email",
            selected_items=[_item("New", "https://example.com/new")],
            now=now,
        )
        self.assertEqual(result["pruned_count"], 1)
        self.assertEqual(len(load_owner_review_exposure_log()), 1)

    def test_read_failure_on_corrupted_json_fails_open(self) -> None:
        self.log_path.write_text("{not valid json", encoding="utf-8")
        status = load_owner_review_exposure_log_with_status()
        self.assertFalse(status["read_ok"])
        self.assertEqual(status["error_code"], "JSONDecodeError")
        self.assertEqual(status["items"], [])
        # fail-open convenience wrapper must not raise either
        self.assertEqual(load_owner_review_exposure_log(), [])

    def test_recent_with_status_surfaces_read_failure(self) -> None:
        self.log_path.write_text("{not valid json", encoding="utf-8")
        status = recent_owner_review_exposure_log_with_status("keysuri_global_tech")
        self.assertFalse(status["read_ok"])
        self.assertEqual(status["error_code"], "JSONDecodeError")
        self.assertEqual(status["items"], [])

    def test_malformed_payload_shape_fails_open(self) -> None:
        self.log_path.write_text(json.dumps({"schema": "owner_review_exposure_log_v1", "items": "not-a-list"}), encoding="utf-8")
        status = load_owner_review_exposure_log_with_status()
        self.assertFalse(status["read_ok"])
        self.assertEqual(status["error_code"], "malformed_log_payload")


if __name__ == "__main__":
    unittest.main()
