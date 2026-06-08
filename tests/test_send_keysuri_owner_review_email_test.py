"""Tests for Kee-Suri owner-review SMTP harness (report-only and send gates)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "send_keysuri_owner_review_email_test.py"
_HTML = _REPO / "output" / "keysuri_preview" / "keysuri_global_generated_owner_review_preview.html"


def _run_harness(*args: str, env: dict | None = None) -> dict:
    merged = {**os.environ}
    if env:
        merged.update(env)
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), *args, "--no-write-output"],
        cwd=str(_REPO),
        env=merged,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


@unittest.skipUnless(_HTML.is_file(), "Kee-Suri preview HTML fixture missing")
class SendKeysuriOwnerReviewEmailHarnessTests(unittest.TestCase):
    def test_report_only_does_not_send(self) -> None:
        report = _run_harness("--html", str(_HTML.relative_to(_REPO)))
        self.assertFalse(report["send_attempted"])
        self.assertFalse(report["send_success"])
        self.assertIn("report-only", report["send_block_reason"])

    def test_missing_confirm_blocks_send(self) -> None:
        report = _run_harness(
            "--html",
            str(_HTML.relative_to(_REPO)),
            "--send",
            "--to",
            "soulampsito@gmail.com",
            env={"GENIE_EMAIL_SEND_TEST": "1"},
        )
        self.assertFalse(report["send_attempted"])
        self.assertIn("confirm", report["send_block_reason"].lower())

    def test_non_allowlisted_recipient_blocks_send(self) -> None:
        report = _run_harness(
            "--html",
            str(_HTML.relative_to(_REPO)),
            "--send",
            "--confirm",
            "SEND",
            "--to",
            "notallowed@example.com",
            env={"GENIE_EMAIL_SEND_TEST": "1"},
        )
        self.assertFalse(report["send_attempted"])
        self.assertIn("OWNER_REVIEW_EMAIL_ALLOWLIST", report["send_block_reason"])

    def test_send_gate_passes_with_allowlisted_recipient(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("ks_harness", _SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)

        with mock.patch.object(mod, "smtp_configured", return_value=True):
            with mock.patch.dict(
                os.environ,
                {"GENIE_EMAIL_SEND_TEST": "1"},
                clear=False,
            ):
                attempted, reason = mod._evaluate_send_gate(
                    want_send=True,
                    confirm="SEND",
                    recipients=["soulampsito@gmail.com"],
                    html_exists=True,
                )
        self.assertTrue(attempted)
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
