"""Tests for admin_notice_store.py: notice persistence and state machine."""
from __future__ import annotations

import json
import unittest

from admin_notice_store import (
    NOTICE_TYPES,
    admin_notices_dir,
    create_notice_draft,
    generate_notice_id,
    list_notices,
    load_notice,
    mark_failed,
    mark_previewed,
    mark_sent,
    validate_notice_id,
)


class NoticeIdTests(unittest.TestCase):
    def test_generate_notice_id_matches_expected_format(self) -> None:
        notice_id = generate_notice_id("delay_notice")
        self.assertTrue(validate_notice_id(notice_id))
        self.assertTrue(notice_id.startswith("notice_delay_notice_"))

    def test_generate_notice_id_rejects_unknown_type(self) -> None:
        with self.assertRaises(ValueError):
            generate_notice_id("not_a_real_type")

    def test_validate_notice_id_rejects_garbage(self) -> None:
        self.assertFalse(validate_notice_id("../../etc/passwd"))
        self.assertFalse(validate_notice_id(""))
        self.assertFalse(validate_notice_id("notice_delay_notice_20260625"))


class NoticeStateMachineTests(unittest.TestCase):
    def test_create_draft_has_no_pii_fields(self) -> None:
        notice = create_notice_draft(
            notice_type="quality_check_notice",
            program_id="keysuri_global_tech",
            related_run_id=None,
            subject="제목",
            body_text="본문",
            body_html="<p>본문</p>",
        )
        self.assertEqual(notice["status"], "draft")
        self.assertEqual(notice["recipients_count"], 0)
        self.assertIsNone(notice["previewed_at"])
        self.assertIsNone(notice["sent_at"])

        path = admin_notices_dir() / f"{notice['notice_id']}.json"
        self.assertTrue(path.is_file())
        raw = path.read_text(encoding="utf-8")
        self.assertNotIn("@", raw)  # no email address ever written to disk

    def test_preview_then_sent_transition(self) -> None:
        notice = create_notice_draft(
            notice_type="delay_notice",
            program_id="keysuri_global_tech",
            related_run_id=None,
            subject="지연 안내",
            body_text="지연되었습니다",
            body_html="<p>지연되었습니다</p>",
        )
        notice = mark_previewed(notice, recipients_count=3, recipient_source="beta_recipients_config_merged")
        self.assertEqual(notice["status"], "previewed")
        self.assertIsNotNone(notice["previewed_at"])
        self.assertEqual(notice["recipients_count"], 3)

        notice = mark_sent(notice, sent_by="admin")
        self.assertEqual(notice["status"], "sent")
        self.assertTrue(notice["smtp_accepted"])
        self.assertIsNone(notice["send_error"])
        self.assertIsNotNone(notice["sent_at"])

        reloaded = load_notice(notice["notice_id"])
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded["status"], "sent")

    def test_preview_then_failed_transition(self) -> None:
        notice = create_notice_draft(
            notice_type="incident_notice",
            program_id="keysuri_korea_tech",
            related_run_id="20260625_000000_keysuri_korea_tech_aabbccdd",
            subject="장애 안내",
            body_text="장애가 발생했습니다",
            body_html="<p>장애가 발생했습니다</p>",
        )
        notice = mark_previewed(notice, recipients_count=5, recipient_source="beta_recipients_config_merged")
        notice = mark_failed(notice, send_error="smtp_send_failed", sent_by="admin")
        self.assertEqual(notice["status"], "failed")
        self.assertFalse(notice["smtp_accepted"])
        self.assertEqual(notice["send_error"], "smtp_send_failed")

    def test_load_notice_unknown_id_returns_none(self) -> None:
        self.assertIsNone(load_notice("notice_delay_notice_20260625_00000000"))

    def test_list_notices_includes_created_draft(self) -> None:
        notice = create_notice_draft(
            notice_type="custom_notice",
            program_id="all",
            related_run_id=None,
            subject="공지",
            body_text="본문",
            body_html="<p>본문</p>",
        )
        ids = [n["notice_id"] for n in list_notices(limit=200)]
        self.assertIn(notice["notice_id"], ids)

    def test_all_notice_types_generate_valid_ids(self) -> None:
        for t in NOTICE_TYPES:
            self.assertTrue(validate_notice_id(generate_notice_id(t)))


if __name__ == "__main__":
    unittest.main()
