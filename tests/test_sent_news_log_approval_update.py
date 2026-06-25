from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from admin_store import approve_run, save_run_artifact
from sent_news_log_store import load_sent_news_log


def _selected_items(count: int = 3) -> list[dict]:
    return [
        {
            "title": f"Selected news {idx}",
            "url": f"https://example.com/news/{idx}",
            "source": "Example",
            "topic_key": f"topic-{idx}",
            "summary": f"Summary {idx}",
        }
        for idx in range(count)
    ]


def _save_approvable(run_id: str, *, selected_items=None, required_count=None) -> None:
    meta = {
        "run_id": run_id,
        "mode": "today_genie",
        "validation_result": "pass",
        "workflow_status": "validated",
        "response_status": 200,
        "reason_summary": "ok",
        "email_sent": True,
        "owner_review_status": "pending_review",
        "customer_delivery_status": "not_sent",
    }
    if selected_items is not None:
        meta["selected_items"] = selected_items
    if required_count is not None:
        meta["required_count"] = required_count
        meta["selected_count"] = len(selected_items or [])
    save_run_artifact(meta, email_html="<p>brief</p>")


class SentNewsApprovalUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.log_path = Path(self.tmp.name) / "sent_news_log.json"
        self.env = mock.patch.dict(
            os.environ,
            {
                "GENIE_SENT_NEWS_LOG_PATH": str(self.log_path),
                "GENIE_CUSTOMER_EMAIL_TO": "customer@example.com",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_USER": "user@example.com",
                "SMTP_PASSWORD": "secret",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def _approve_with_send_result(self, run_id: str, send_ok: bool):
        trace = {
            "subject": "Customer subject",
            "envelope_to": ["customer@example.com"],
            "mime_html_sha256": "sha",
            "mime_html_bytes_len": 10,
            "inline_input_hashes": [],
            "smtp_accepted_recipient_count": 1 if send_ok else 0,
            "smtp_refused_recipients": [],
        }
        with mock.patch(
            "today_geenee_customer_delivery.send_today_geenee_customer_final_email",
            return_value=send_ok,
        ):
            with mock.patch("email_sender.last_send_trace", return_value=trace):
                with mock.patch("email_sender.last_send_diagnostic", return_value=""):
                    return approve_run(run_id)

    def test_owner_review_creation_does_not_update_sent_log(self) -> None:
        _save_approvable(
            "20260625_090000_today_genie_aabbcc01",
            selected_items=_selected_items(),
            required_count=3,
        )
        self.assertEqual(load_sent_news_log(), [])

    def test_approve_success_updates_sent_log(self) -> None:
        run_id = "20260625_090000_today_genie_aabbcc02"
        _save_approvable(run_id, selected_items=_selected_items(), required_count=3)
        updated, status = self._approve_with_send_result(run_id, True)
        self.assertEqual(status, "ok")
        assert updated is not None
        self.assertTrue(updated.get("sent_log_updated"))
        self.assertEqual(len(load_sent_news_log()), 3)

    def test_approve_send_failure_does_not_update_sent_log(self) -> None:
        run_id = "20260625_090000_today_genie_aabbcc03"
        _save_approvable(run_id, selected_items=_selected_items(), required_count=3)
        updated, status = self._approve_with_send_result(run_id, False)
        self.assertEqual(status, "send_failed")
        self.assertIsNone(updated)
        self.assertEqual(load_sent_news_log(), [])

    def test_selected_items_missing_does_not_update_sent_log(self) -> None:
        run_id = "20260625_090000_today_genie_aabbcc04"
        _save_approvable(run_id)
        updated, status = self._approve_with_send_result(run_id, True)
        self.assertEqual(status, "ok")
        assert updated is not None
        self.assertFalse(updated.get("sent_log_updated"))
        self.assertEqual(updated.get("sent_log_update_error"), "selected_items_missing")
        self.assertEqual(load_sent_news_log(), [])

    def test_selected_items_below_required_count_does_not_update_sent_log(self) -> None:
        run_id = "20260625_090000_today_genie_aabbcc05"
        _save_approvable(run_id, selected_items=_selected_items(2), required_count=3)
        updated, status = self._approve_with_send_result(run_id, True)
        self.assertEqual(status, "ok")
        assert updated is not None
        self.assertFalse(updated.get("sent_log_updated"))
        self.assertEqual(updated.get("sent_log_update_error"), "selected_items_below_required_count")
        self.assertEqual(load_sent_news_log(), [])

    def test_required_count_missing_does_not_update_sent_log(self) -> None:
        run_id = "20260625_090000_today_genie_aabbcc06"
        _save_approvable(run_id, selected_items=_selected_items())
        updated, status = self._approve_with_send_result(run_id, True)
        self.assertEqual(status, "ok")
        assert updated is not None
        self.assertFalse(updated.get("sent_log_updated"))
        self.assertEqual(updated.get("sent_log_update_error"), "required_count_missing")
        self.assertEqual(load_sent_news_log(), [])


if __name__ == "__main__":
    unittest.main()
