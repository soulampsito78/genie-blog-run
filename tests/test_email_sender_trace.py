"""Tests for SMTP trace persistence in email_sender."""
from __future__ import annotations

import os
import tempfile
import unittest
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


class EmailSenderTraceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
