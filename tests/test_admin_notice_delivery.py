"""Tests for admin_notice_delivery.py: reuse of email_sender, isolation guarantees."""
from __future__ import annotations

import os
import unittest
from email import message_from_string
from unittest.mock import patch

from admin_notice_delivery import send_admin_notice_email
from admin_notice_store import create_notice_draft, mark_previewed


class _CapturingSMTP:
    last_to_addrs: list[str] = []
    last_payload = ""

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __enter__(self) -> "_CapturingSMTP":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def starttls(self) -> None:
        return None

    def login(self, _user: str, _password: str) -> None:
        return None

    def sendmail(self, _from_addr: str, to_addrs: list[str], payload: str) -> dict:
        type(self).last_to_addrs = list(to_addrs)
        type(self).last_payload = payload
        return {}


def _make_previewed_notice() -> dict:
    notice = create_notice_draft(
        notice_type="quality_check_notice",
        program_id="keysuri_global_tech",
        related_run_id=None,
        subject="[키수리 글로벌테크] 오늘 브리핑 품질 점검 안내",
        body_text="검수 완료 후 발송하겠습니다.",
        body_html="<p>검수 완료 후 발송하겠습니다.</p>",
    )
    return mark_previewed(notice, recipients_count=2, recipient_source="beta_recipients_config_merged")


class AdminNoticeDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        _CapturingSMTP.last_to_addrs = []
        _CapturingSMTP.last_payload = ""

    def test_send_admin_notice_email_calls_send_genie_email_with_override(self) -> None:
        notice = _make_previewed_notice()
        with patch("admin_notice_delivery.resolve_customer_recipients") as mock_resolve:
            mock_resolve.return_value = {"final_recipients": ["alpha@example.com", "beta@example.com"]}
            with patch("admin_notice_delivery.send_genie_email") as mock_send:
                mock_send.return_value = True
                ok = send_admin_notice_email(notice)

        self.assertTrue(ok)
        mock_send.assert_called_once()
        _, kwargs = mock_send.call_args
        self.assertEqual(kwargs["to_addrs_override"], ["alpha@example.com", "beta@example.com"])

    def test_send_admin_notice_email_blocks_when_no_recipients(self) -> None:
        notice = _make_previewed_notice()
        with patch("admin_notice_delivery.resolve_customer_recipients") as mock_resolve:
            mock_resolve.return_value = {"final_recipients": []}
            with patch("admin_notice_delivery.send_genie_email") as mock_send:
                ok = send_admin_notice_email(notice)

        self.assertFalse(ok)
        mock_send.assert_not_called()

    def test_notice_email_to_header_is_undisclosed_and_no_cc_bcc(self) -> None:
        notice = _make_previewed_notice()
        env = {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "sender@example.com",
            "SMTP_PASSWORD": "secret",
        }
        customer_addrs = ["alpha@example.com", "beta@example.com"]
        with patch.dict(os.environ, env, clear=False):
            with patch("admin_notice_delivery.resolve_customer_recipients") as mock_resolve:
                mock_resolve.return_value = {"final_recipients": customer_addrs}
                with patch("email_sender.smtplib.SMTP", _CapturingSMTP):
                    ok = send_admin_notice_email(notice)

        self.assertTrue(ok)
        self.assertEqual(_CapturingSMTP.last_to_addrs, customer_addrs)
        msg = message_from_string(_CapturingSMTP.last_payload)
        self.assertEqual(msg.get("To"), "undisclosed-recipients:;")
        self.assertIsNone(msg.get("Cc"))
        self.assertIsNone(msg.get("Bcc"))
        for addr in customer_addrs:
            self.assertNotIn(addr, str(msg.get("To") or ""))

    def test_send_admin_notice_email_never_touches_sent_news_log(self) -> None:
        notice = _make_previewed_notice()
        with patch("admin_notice_delivery.resolve_customer_recipients") as mock_resolve:
            mock_resolve.return_value = {"final_recipients": ["alpha@example.com"]}
            with patch("admin_notice_delivery.send_genie_email", return_value=True):
                with patch("admin_store.append_or_upsert_sent_news") as mock_log:
                    send_admin_notice_email(notice)
        mock_log.assert_not_called()

    def test_send_admin_notice_email_never_calls_approve_run(self) -> None:
        notice = _make_previewed_notice()
        with patch("admin_notice_delivery.resolve_customer_recipients") as mock_resolve:
            mock_resolve.return_value = {"final_recipients": ["alpha@example.com"]}
            with patch("admin_notice_delivery.send_genie_email", return_value=True):
                with patch("admin_store.approve_run") as mock_approve:
                    send_admin_notice_email(notice)
        mock_approve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
