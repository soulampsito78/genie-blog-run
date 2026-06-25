"""Tests for SMTP trace persistence in email_sender."""
from __future__ import annotations

import os
import tempfile
import unittest
from email import message_from_string
from pathlib import Path
from unittest.mock import patch

from email_sender import last_send_trace, send_genie_email


class _FakeSMTP:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __enter__(self) -> "_FakeSMTP":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def starttls(self) -> None:
        return None

    def login(self, _user: str, _password: str) -> None:
        return None

    def sendmail(self, _from_addr: str, _to_addrs: list[str], _payload: str) -> dict[str, tuple[int, bytes]]:
        return {"bad@example.com": (550, b"Rejected")}


class _CapturingSMTP:
    last_from_addr = ""
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

    def sendmail(self, from_addr: str, to_addrs: list[str], payload: str) -> dict:
        type(self).last_from_addr = from_addr
        type(self).last_to_addrs = list(to_addrs)
        type(self).last_payload = payload
        return {}


class EmailSenderTraceTests(unittest.TestCase):
    def setUp(self) -> None:
        _CapturingSMTP.last_from_addr = ""
        _CapturingSMTP.last_to_addrs = []
        _CapturingSMTP.last_payload = ""

    def test_sendmail_refused_dict_is_recorded_in_last_send_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "inline.jpg"
            image.write_bytes(b"\xff\xd8\xff" + b"\x00" * 32)
            env = {
                "SMTP_HOST": "smtp.example.com",
                "SMTP_PORT": "587",
                "SMTP_USER": "sender@example.com",
                "SMTP_PASSWORD": "secret",
                "GENIE_EMAIL_RICH_MODE": "1",
            }
            with patch.dict(os.environ, env, clear=False):
                with patch("email_sender.smtplib.SMTP", _FakeSMTP):
                    ok = send_genie_email(
                        "<p>hello<img src=\"cid:top\"></p>",
                        "Subject",
                        inline_jpeg_parts=[(str(image), "top", "inline.jpg")],
                        attachment_jpeg_parts=[],
                        to_addrs_override=["good@example.com", "bad@example.com"],
                    )

        self.assertTrue(ok)
        trace = last_send_trace()
        self.assertEqual(trace.get("smtp_refused_recipient_count"), 1)
        self.assertEqual(trace.get("smtp_refused_recipients"), ["bad@example.com"])
        self.assertTrue(trace.get("smtp_partial_refusal"))
        self.assertEqual(trace.get("smtp_accepted_recipient_count"), 1)
        self.assertEqual(trace.get("subject"), "Subject")

    def test_customer_recipients_are_envelope_only_for_plain_mime(self) -> None:
        customer_addrs = ["alpha@example.com", "beta@example.com"]
        env = {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "sender@example.com",
            "SMTP_PASSWORD": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("email_sender.smtplib.SMTP", _CapturingSMTP):
                ok = send_genie_email(
                    "<p>hello</p>",
                    "Subject",
                    to_addrs_override=customer_addrs,
                )

        self.assertTrue(ok)
        self.assertEqual(_CapturingSMTP.last_to_addrs, customer_addrs)
        msg = message_from_string(_CapturingSMTP.last_payload)
        self.assertEqual(msg.get("To"), "undisclosed-recipients:;")
        self.assertIsNone(msg.get("Cc"))
        self.assertIsNone(msg.get("Bcc"))
        for addr in customer_addrs:
            self.assertNotIn(addr, str(msg.get("To") or ""))
            self.assertNotIn(addr, _CapturingSMTP.last_payload.split("\n\n", 1)[0])
        trace = last_send_trace()
        self.assertEqual(trace.get("envelope_to"), customer_addrs)
        self.assertEqual(trace.get("to_header"), "undisclosed-recipients:;")
        self.assertEqual(trace.get("cc_header"), "")
        self.assertEqual(trace.get("bcc_header"), "")

    def test_customer_recipients_are_envelope_only_for_rich_mime(self) -> None:
        customer_addrs = ["global@example.com", "korea@example.com"]
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "inline.jpg"
            image.write_bytes(b"\xff\xd8\xff" + b"\x00" * 32)
            env = {
                "SMTP_HOST": "smtp.example.com",
                "SMTP_PORT": "587",
                "SMTP_USER": "sender@example.com",
                "SMTP_PASSWORD": "secret",
                "GENIE_EMAIL_RICH_MODE": "1",
            }
            with patch.dict(os.environ, env, clear=False):
                with patch("email_sender.smtplib.SMTP", _CapturingSMTP):
                    ok = send_genie_email(
                        "<p>hello<img src=\"cid:top\"></p>",
                        "Subject",
                        inline_jpeg_parts=[(str(image), "top", "inline.jpg")],
                        attachment_jpeg_parts=[],
                        to_addrs_override=customer_addrs,
                    )

        self.assertTrue(ok)
        self.assertEqual(_CapturingSMTP.last_to_addrs, customer_addrs)
        msg = message_from_string(_CapturingSMTP.last_payload)
        self.assertEqual(msg.get("To"), "undisclosed-recipients:;")
        self.assertIsNone(msg.get("Cc"))
        self.assertIsNone(msg.get("Bcc"))
        header_block = _CapturingSMTP.last_payload.split("\n\n", 1)[0]
        for addr in customer_addrs:
            self.assertNotIn(addr, str(msg.get("To") or ""))
            self.assertNotIn(addr, header_block)
        trace = last_send_trace()
        self.assertEqual(trace.get("envelope_to"), customer_addrs)
        self.assertEqual(trace.get("to_header"), "undisclosed-recipients:;")
        self.assertEqual(trace.get("cc_header"), "")
        self.assertEqual(trace.get("bcc_header"), "")


if __name__ == "__main__":
    unittest.main()
