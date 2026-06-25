"""Tests for admin-managed beta customer recipient list.

Covers:
  - env-only recipients still work
  - admin-only additional recipients merge with env
  - duplicate removal
  - invalid email rejection
  - remove recipient
  - missing GCS config (no file) returns env baseline only
  - today_genie uses merged recipients
  - keysuri_global_tech uses merged recipients
  - keysuri_korea_tech uses merged recipients
  - owner/review recipient list is unchanged
  - admin add/remove forms do not send email
  - route requires admin login
  - header injection / newline blocked
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from admin_store import (
    _is_valid_email,
    add_beta_recipient,
    load_beta_recipient_config,
    remove_beta_recipient,
    resolve_customer_recipients,
    save_beta_recipient_config,
)
from fastapi.testclient import TestClient
from main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_env(**kw):
    """Patch os.environ for test duration; return original values for teardown."""
    orig = {}
    for k, v in kw.items():
        orig[k] = os.environ.get(k)
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return orig


def _restore_env(orig):
    for k, v in orig.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ---------------------------------------------------------------------------
# Email validation
# ---------------------------------------------------------------------------

class EmailValidationTests(unittest.TestCase):
    def test_valid_simple(self):
        self.assertTrue(_is_valid_email("user@example.com"))

    def test_valid_plus_tag(self):
        self.assertTrue(_is_valid_email("user+tag@example.co.kr"))

    def test_valid_dots(self):
        self.assertTrue(_is_valid_email("first.last@sub.domain.com"))

    def test_invalid_missing_at(self):
        self.assertFalse(_is_valid_email("nodomain.com"))

    def test_invalid_empty(self):
        self.assertFalse(_is_valid_email(""))

    def test_invalid_none(self):
        self.assertFalse(_is_valid_email(None))  # type: ignore[arg-type]

    def test_invalid_newline_injection(self):
        self.assertFalse(_is_valid_email("user@example.com\nBcc: evil@evil.com"))

    def test_invalid_carriage_return(self):
        self.assertFalse(_is_valid_email("user@example.com\rBcc: x"))

    def test_invalid_comma_packed(self):
        self.assertFalse(_is_valid_email("a@a.com,b@b.com"))

    def test_invalid_angle_bracket(self):
        self.assertFalse(_is_valid_email("<user@example.com>"))

    def test_invalid_missing_tld(self):
        self.assertFalse(_is_valid_email("user@nodot"))

    def test_invalid_double_at(self):
        self.assertFalse(_is_valid_email("a@@example.com"))


# ---------------------------------------------------------------------------
# Recipient config store (local backend)
# ---------------------------------------------------------------------------

class BetaRecipientConfigStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # Use local backend (no GCS bucket configured)
        self._prev = os.environ.get("GENIE_ADMIN_ARTIFACT_BUCKET")
        os.environ.pop("GENIE_ADMIN_ARTIFACT_BUCKET", None)
        os.environ.pop("GENIE_ARTIFACT_BUCKET", None)
        # Redirect local config path inside tmp dir
        self._local_path_patch = patch(
            "admin_store._beta_recipients_local_path",
            return_value=Path(self._tmp.name) / "customer_recipients.json",
        )
        self._local_path_patch.start()

    def tearDown(self):
        self._local_path_patch.stop()
        self._tmp.cleanup()
        if self._prev is None:
            os.environ.pop("GENIE_ADMIN_ARTIFACT_BUCKET", None)
        else:
            os.environ["GENIE_ADMIN_ARTIFACT_BUCKET"] = self._prev

    def test_missing_config_returns_empty(self):
        cfg = load_beta_recipient_config()
        self.assertEqual(cfg["recipients"], [])
        self.assertEqual(cfg["disabled_recipients"], [])

    def test_save_and_load_round_trip(self):
        save_beta_recipient_config(["alpha@example.com", "beta@example.com"])
        cfg = load_beta_recipient_config()
        self.assertIn("alpha@example.com", cfg["recipients"])
        self.assertIn("beta@example.com", cfg["recipients"])

    def test_save_normalises_to_lowercase(self):
        save_beta_recipient_config(["UPPER@EXAMPLE.COM"])
        cfg = load_beta_recipient_config()
        self.assertIn("upper@example.com", cfg["recipients"])
        self.assertNotIn("UPPER@EXAMPLE.COM", cfg["recipients"])

    def test_add_recipient_persists(self):
        ok, err = add_beta_recipient("new@example.com")
        self.assertTrue(ok, err)
        cfg = load_beta_recipient_config()
        self.assertIn("new@example.com", cfg["recipients"])

    def test_add_duplicate_rejected(self):
        add_beta_recipient("dup@example.com")
        ok, err = add_beta_recipient("dup@example.com")
        self.assertFalse(ok)
        self.assertEqual(err, "already_exists")

    def test_add_invalid_email_rejected(self):
        ok, err = add_beta_recipient("not-an-email")
        self.assertFalse(ok)
        self.assertEqual(err, "invalid_format")

    def test_add_empty_rejected(self):
        ok, err = add_beta_recipient("")
        self.assertFalse(ok)
        self.assertEqual(err, "empty_email")

    def test_add_newline_injection_rejected(self):
        ok, err = add_beta_recipient("x@x.com\nBcc: y@y.com")
        self.assertFalse(ok)
        self.assertEqual(err, "invalid_format")

    def test_remove_existing(self):
        add_beta_recipient("toremove@example.com")
        ok, err = remove_beta_recipient("toremove@example.com")
        self.assertTrue(ok, err)
        cfg = load_beta_recipient_config()
        self.assertNotIn("toremove@example.com", cfg["recipients"])

    def test_remove_nonexistent_returns_error(self):
        ok, err = remove_beta_recipient("ghost@example.com")
        self.assertFalse(ok)
        self.assertEqual(err, "not_found")

    def test_remove_empty_returns_error(self):
        ok, err = remove_beta_recipient("")
        self.assertFalse(ok)
        self.assertEqual(err, "empty_email")

    def test_add_aborts_when_config_read_fails_does_not_wipe(self):
        """A transient read failure during add must NOT overwrite existing data."""
        # Seed a real, non-empty config first.
        save_beta_recipient_config(["existing@example.com"])
        # Simulate a read failure: load returns load_ok=False (e.g. GCS/network error).
        bad_cfg = {
            "recipients": [],
            "disabled_recipients": [],
            "updated_at": "",
            "updated_by": "admin",
            "version": 1,
            "load_ok": False,
        }
        with patch("admin_store.load_beta_recipient_config", return_value=bad_cfg), \
             patch("admin_store.save_beta_recipient_config") as mock_save:
            ok, err = add_beta_recipient("new@example.com")
        self.assertFalse(ok)
        self.assertEqual(err, "config_unavailable")
        mock_save.assert_not_called()
        # Original config must be intact (real load, not the patched one).
        cfg = load_beta_recipient_config()
        self.assertIn("existing@example.com", cfg["recipients"])
        self.assertNotIn("new@example.com", cfg["recipients"])

    def test_remove_aborts_when_config_read_fails_does_not_wipe(self):
        """A transient read failure during remove must NOT overwrite existing data."""
        save_beta_recipient_config(["keepme@example.com"])
        bad_cfg = {
            "recipients": [],
            "disabled_recipients": [],
            "updated_at": "",
            "updated_by": "admin",
            "version": 1,
            "load_ok": False,
        }
        with patch("admin_store.load_beta_recipient_config", return_value=bad_cfg), \
             patch("admin_store.save_beta_recipient_config") as mock_save:
            ok, err = remove_beta_recipient("keepme@example.com")
        self.assertFalse(ok)
        self.assertEqual(err, "config_unavailable")
        mock_save.assert_not_called()
        cfg = load_beta_recipient_config()
        self.assertIn("keepme@example.com", cfg["recipients"])

    def test_missing_config_load_ok_true_allows_first_add(self):
        """First-ever add (genuinely missing config) must still succeed."""
        cfg = load_beta_recipient_config()
        self.assertTrue(cfg.get("load_ok"))
        ok, err = add_beta_recipient("first@example.com")
        self.assertTrue(ok, err)

    def test_load_reports_load_ok_false_on_corrupt_json(self):
        """Corrupt JSON must surface load_ok=False (not silently treated as empty)."""
        p = Path(self._tmp.name) / "customer_recipients.json"
        p.write_text("{ this is not valid json", encoding="utf-8")
        cfg = load_beta_recipient_config()
        self.assertFalse(cfg.get("load_ok"))
        # And add must refuse rather than overwrite the corrupt file blindly.
        ok, err = add_beta_recipient("x@example.com")
        self.assertFalse(ok)
        self.assertEqual(err, "config_unavailable")


# ---------------------------------------------------------------------------
# Recipient resolver
# ---------------------------------------------------------------------------

class ResolveCustomerRecipientsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ.pop("GENIE_ADMIN_ARTIFACT_BUCKET", None)
        os.environ.pop("GENIE_ARTIFACT_BUCKET", None)
        self._local_path_patch = patch(
            "admin_store._beta_recipients_local_path",
            return_value=Path(self._tmp.name) / "customer_recipients.json",
        )
        self._local_path_patch.start()
        self._prev_env = os.environ.get("GENIE_CUSTOMER_EMAIL_TO")

    def tearDown(self):
        self._local_path_patch.stop()
        self._tmp.cleanup()
        if self._prev_env is None:
            os.environ.pop("GENIE_CUSTOMER_EMAIL_TO", None)
        else:
            os.environ["GENIE_CUSTOMER_EMAIL_TO"] = self._prev_env

    def _set_customer_env(self, value: str):
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = value

    def test_env_only_no_admin_config(self):
        self._set_customer_env("env@example.com")
        result = resolve_customer_recipients()
        self.assertEqual(result["final_recipients"], ["env@example.com"])
        self.assertEqual(result["env_recipients"], ["env@example.com"])
        self.assertEqual(result["admin_recipients"], [])

    def test_admin_only_no_env(self):
        os.environ.pop("GENIE_CUSTOMER_EMAIL_TO", None)
        save_beta_recipient_config(["admin@example.com"])
        result = resolve_customer_recipients()
        self.assertIn("admin@example.com", result["final_recipients"])
        self.assertEqual(result["env_recipients"], [])
        self.assertIn("admin@example.com", result["admin_recipients"])

    def test_merge_env_and_admin(self):
        self._set_customer_env("env@example.com")
        save_beta_recipient_config(["extra@example.com"])
        result = resolve_customer_recipients()
        self.assertIn("env@example.com", result["final_recipients"])
        self.assertIn("extra@example.com", result["final_recipients"])
        self.assertEqual(len(result["final_recipients"]), 2)

    def test_deduplication_env_and_admin_same(self):
        self._set_customer_env("dup@example.com")
        save_beta_recipient_config(["dup@example.com"])
        result = resolve_customer_recipients()
        self.assertEqual(result["final_recipients"].count("dup@example.com"), 1)

    def test_deduplication_case_insensitive(self):
        self._set_customer_env("DUP@EXAMPLE.COM")
        save_beta_recipient_config(["dup@example.com"])
        result = resolve_customer_recipients()
        # Both normalise to dup@example.com; should appear once
        self.assertEqual(len([r for r in result["final_recipients"] if "dup" in r]), 1)

    def test_invalid_admin_entry_rejected_with_reason(self):
        save_beta_recipient_config(["good@example.com", "not-an-email"])
        # Force raw entry with invalid address by writing manually
        p = Path(self._tmp.name) / "customer_recipients.json"
        p.write_text(
            json.dumps({"recipients": ["good@example.com", "bad-email"], "disabled_recipients": []}),
            encoding="utf-8",
        )
        result = resolve_customer_recipients()
        final = result["final_recipients"]
        self.assertIn("good@example.com", final)
        self.assertNotIn("bad-email", final)
        self.assertTrue(any(e["email"] == "bad-email" for e in result["invalid_entries"]))

    def test_missing_config_falls_back_to_env(self):
        self._set_customer_env("env@example.com")
        # No config file written — should fall back to env-only
        result = resolve_customer_recipients()
        self.assertEqual(result["final_recipients"], ["env@example.com"])
        self.assertEqual(result["admin_recipients"], [])

    def test_source_summary_env_only(self):
        self._set_customer_env("a@a.com")
        result = resolve_customer_recipients()
        self.assertIn("env(1)", result["source_summary"])

    def test_source_summary_env_and_admin(self):
        self._set_customer_env("a@a.com")
        save_beta_recipient_config(["b@b.com"])
        result = resolve_customer_recipients()
        self.assertIn("env(1)", result["source_summary"])
        self.assertIn("admin_config(1)", result["source_summary"])

    def test_empty_env_empty_admin_is_empty(self):
        os.environ.pop("GENIE_CUSTOMER_EMAIL_TO", None)
        result = resolve_customer_recipients()
        self.assertEqual(result["final_recipients"], [])

    def test_five_recipients_merged(self):
        self._set_customer_env("e1@e.com,e2@e.com")
        save_beta_recipient_config(["a1@a.com", "a2@a.com", "a3@a.com"])
        result = resolve_customer_recipients()
        self.assertEqual(len(result["final_recipients"]), 5)

    def test_owner_review_env_not_affected(self):
        """GENIE_EMAIL_TO (owner/review) must stay separate from GENIE_CUSTOMER_EMAIL_TO."""
        os.environ["EMAIL_TO"] = "owner@example.com"
        self._set_customer_env("customer@example.com")
        result = resolve_customer_recipients()
        self.assertNotIn("owner@example.com", result["final_recipients"])


# ---------------------------------------------------------------------------
# today_genie delivery uses merged recipients
# ---------------------------------------------------------------------------

class TodayGenieDeliveryMergedRecipientsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ.pop("GENIE_ADMIN_ARTIFACT_BUCKET", None)
        os.environ.pop("GENIE_ARTIFACT_BUCKET", None)
        self._local_path_patch = patch(
            "admin_store._beta_recipients_local_path",
            return_value=Path(self._tmp.name) / "customer_recipients.json",
        )
        self._local_path_patch.start()
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "env@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"

    def tearDown(self):
        self._local_path_patch.stop()
        self._tmp.cleanup()
        for k in ("GENIE_CUSTOMER_EMAIL_TO", "SMTP_HOST", "SMTP_USER"):
            os.environ.pop(k, None)

    def test_config_ready_with_env_only(self):
        from today_geenee_customer_delivery import customer_delivery_config_ready
        ok, reason = customer_delivery_config_ready()
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_config_ready_with_admin_recipient_no_env(self):
        os.environ.pop("GENIE_CUSTOMER_EMAIL_TO", None)
        save_beta_recipient_config(["admin@example.com"])
        from today_geenee_customer_delivery import customer_delivery_config_ready
        ok, reason = customer_delivery_config_ready()
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_config_not_ready_when_both_empty(self):
        os.environ.pop("GENIE_CUSTOMER_EMAIL_TO", None)
        from today_geenee_customer_delivery import customer_delivery_config_ready
        ok, reason = customer_delivery_config_ready()
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_customer_to")

    @patch("today_geenee_customer_delivery.send_genie_email")
    @patch("today_geenee_customer_delivery._resolve_today_genie_inline_jpeg_parts")
    def test_send_uses_merged_recipient_list(self, mock_parts, mock_send):
        """send_today_geenee_customer_final_email passes merged list to send_genie_email."""
        mock_parts.return_value = [("top.jpg", "cid_top", b"\xff\xd8")]
        mock_send.return_value = True
        save_beta_recipient_config(["admin@example.com"])

        from today_geenee_customer_delivery import send_today_geenee_customer_final_email
        # Signature: send_today_geenee_customer_final_email(saved_html, meta)
        send_today_geenee_customer_final_email(
            "<html><body>test</body></html>",
            {},
        )
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        to_addrs = call_kwargs.get("to_addrs_override", [])
        self.assertIn("env@example.com", to_addrs)
        self.assertIn("admin@example.com", to_addrs)


# ---------------------------------------------------------------------------
# keysuri delivery uses merged recipients
# ---------------------------------------------------------------------------

class KeysuriDeliveryMergedRecipientsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ.pop("GENIE_ADMIN_ARTIFACT_BUCKET", None)
        os.environ.pop("GENIE_ARTIFACT_BUCKET", None)
        self._local_path_patch = patch(
            "admin_store._beta_recipients_local_path",
            return_value=Path(self._tmp.name) / "customer_recipients.json",
        )
        self._local_path_patch.start()
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "env@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"

    def tearDown(self):
        self._local_path_patch.stop()
        self._tmp.cleanup()
        for k in ("GENIE_CUSTOMER_EMAIL_TO", "SMTP_HOST", "SMTP_USER"):
            os.environ.pop(k, None)

    def test_keysuri_config_ready_with_env(self):
        from keysuri_customer_delivery import customer_delivery_config_ready
        ok, reason = customer_delivery_config_ready()
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_keysuri_config_ready_admin_only(self):
        os.environ.pop("GENIE_CUSTOMER_EMAIL_TO", None)
        save_beta_recipient_config(["admin@example.com"])
        from keysuri_customer_delivery import customer_delivery_config_ready
        ok, reason = customer_delivery_config_ready()
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_keysuri_config_not_ready_both_empty(self):
        os.environ.pop("GENIE_CUSTOMER_EMAIL_TO", None)
        from keysuri_customer_delivery import customer_delivery_config_ready
        ok, reason = customer_delivery_config_ready()
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_customer_to")

    @patch("keysuri_customer_delivery.send_genie_email")
    @patch("keysuri_customer_delivery.resolve_keysuri_inline_jpeg_parts")
    def test_keysuri_global_send_uses_merged_list(self, mock_parts, mock_send):
        """Global send passes merged recipient list to send_genie_email."""
        mock_parts.return_value = [("top.jpg", "cid_top", b"\xff\xd8")]
        mock_send.return_value = True
        save_beta_recipient_config(["admin@example.com"])

        from keysuri_customer_delivery import send_keysuri_customer_final_email
        from keysuri_live_source_smoke import PROGRAM_GLOBAL
        meta = {
            "program_id": PROGRAM_GLOBAL,
            "mode": PROGRAM_GLOBAL,
            "service_full_run": True,
            "run_id": "20260623_120000_keysuri_global_tech_aabbccdd",
            "keysuri_global_top_image_cid": "cid_top",
            "keysuri_global_top_image_source": "static_latest",
        }
        # Signature: send_keysuri_customer_final_email(saved_html, meta)
        send_keysuri_customer_final_email(
            "<html><body>global brief</body></html>",
            meta,
        )
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        to_addrs = call_kwargs.get("to_addrs_override", [])
        self.assertIn("env@example.com", to_addrs)
        self.assertIn("admin@example.com", to_addrs)

    @patch("keysuri_customer_delivery.send_genie_email")
    @patch("keysuri_customer_delivery.resolve_keysuri_inline_jpeg_parts")
    def test_keysuri_korea_send_uses_merged_list(self, mock_parts, mock_send):
        """Korea send passes merged recipient list to send_genie_email."""
        mock_parts.return_value = [
            ("top.jpg", "cid_top", b"\xff\xd8"),
            ("bottom.jpg", "cid_bottom", b"\xff\xd8"),
        ]
        mock_send.return_value = True
        save_beta_recipient_config(["admin@example.com"])

        from keysuri_customer_delivery import send_keysuri_customer_final_email
        from keysuri_live_source_smoke import PROGRAM_KOREA

        meta = {
            "program_id": PROGRAM_KOREA,
            "mode": PROGRAM_KOREA,
            "service_full_run": True,
            "run_id": "20260623_120000_keysuri_korea_tech_aabbccdd",
            "keysuri_korea_top_image_cid": "cid_top",
            "korea_bottom_shot_cid": "cid_bottom",
        }
        send_keysuri_customer_final_email(
            "<html><body>korea brief</body></html>",
            meta,
        )
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        to_addrs = call_kwargs.get("to_addrs_override", [])
        self.assertIn("env@example.com", to_addrs)
        self.assertIn("admin@example.com", to_addrs)


# ---------------------------------------------------------------------------
# Admin route — customer-recipients UI
# ---------------------------------------------------------------------------

class AdminCustomerRecipientsRouteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ.pop("GENIE_ADMIN_ARTIFACT_BUCKET", None)
        os.environ.pop("GENIE_ARTIFACT_BUCKET", None)
        self._local_path_patch = patch(
            "admin_store._beta_recipients_local_path",
            return_value=Path(self._tmp.name) / "customer_recipients.json",
        )
        self._local_path_patch.start()
        self._prev_pwd = os.environ.get("GENIE_ADMIN_PASSWORD")
        os.environ["GENIE_ADMIN_PASSWORD"] = "test-admin-secret"
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "env@example.com"
        self.client = TestClient(app)
        # Log in and store session cookie for authenticated requests
        resp = self.client.post("/admin/login", data={"password": "test-admin-secret"})
        self.session_cookie = resp.cookies.get("genie_admin_session")
        # Separate unauthenticated client (no stored cookies)
        self.unauthed_client = TestClient(app, cookies={})

    def tearDown(self):
        self._local_path_patch.stop()
        self._tmp.cleanup()
        if self._prev_pwd is None:
            os.environ.pop("GENIE_ADMIN_PASSWORD", None)
        else:
            os.environ["GENIE_ADMIN_PASSWORD"] = self._prev_pwd
        os.environ.pop("GENIE_CUSTOMER_EMAIL_TO", None)

    def _authed_get(self, url: str):
        return self.client.get(url, cookies={"genie_admin_session": self.session_cookie})

    def _authed_post(self, url: str, data: dict):
        return self.client.post(url, data=data, cookies={"genie_admin_session": self.session_cookie})

    def test_get_requires_login(self):
        # Use unauthenticated client (no session cookie)
        resp = self.unauthed_client.get("/admin/customer-recipients", follow_redirects=False)
        # Should redirect to /admin login page (not render the management page)
        self.assertIn(resp.status_code, (302, 303, 307, 308))

    def test_get_page_renders_for_logged_in_user(self):
        resp = self._authed_get("/admin/customer-recipients")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("베타 고객 수신자 관리", resp.text)
        self.assertIn("env@example.com", resp.text)

    def test_get_shows_note_no_immediate_send(self):
        resp = self._authed_get("/admin/customer-recipients")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("발송되지 않습니다", resp.text)

    def test_add_valid_recipient(self):
        resp = self._authed_post(
            "/admin/customer-recipients/add",
            {"email": "newbeta@example.com"},
        )
        self.assertIn(resp.status_code, (200, 302, 303))
        cfg = load_beta_recipient_config()
        self.assertIn("newbeta@example.com", cfg["recipients"])

    def test_add_invalid_email_returns_error(self):
        resp = self._authed_post(
            "/admin/customer-recipients/add",
            {"email": "bad-email"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("유효하지 않은", resp.text)

    def test_add_does_not_send_email(self):
        with patch("today_geenee_customer_delivery.send_genie_email") as mock_send, \
             patch("keysuri_customer_delivery.send_genie_email") as mock_ksend:
            self._authed_post(
                "/admin/customer-recipients/add",
                {"email": "safe@example.com"},
            )
            mock_send.assert_not_called()
            mock_ksend.assert_not_called()

    def test_remove_existing_recipient(self):
        add_beta_recipient("tobedeleted@example.com")
        resp = self._authed_post(
            "/admin/customer-recipients/remove",
            {"email": "tobedeleted@example.com"},
        )
        self.assertIn(resp.status_code, (200, 302, 303))
        cfg = load_beta_recipient_config()
        self.assertNotIn("tobedeleted@example.com", cfg["recipients"])

    def test_remove_does_not_send_email(self):
        add_beta_recipient("willremove@example.com")
        with patch("today_geenee_customer_delivery.send_genie_email") as mock_send, \
             patch("keysuri_customer_delivery.send_genie_email") as mock_ksend:
            self._authed_post(
                "/admin/customer-recipients/remove",
                {"email": "willremove@example.com"},
            )
            mock_send.assert_not_called()
            mock_ksend.assert_not_called()

    def test_add_requires_login(self):
        # Use unauthenticated client (no session cookie)
        resp = self.unauthed_client.post(
            "/admin/customer-recipients/add",
            data={"email": "noauth@x.com"},
            follow_redirects=False,
        )
        self.assertIn(resp.status_code, (302, 303, 307, 308))
        # Must not have been added (gate rejected before handler ran)
        cfg = load_beta_recipient_config()
        self.assertNotIn("noauth@x.com", cfg["recipients"])

    def test_remove_requires_login(self):
        add_beta_recipient("locked@example.com")
        # Use unauthenticated client (no session cookie)
        resp = self.unauthed_client.post(
            "/admin/customer-recipients/remove",
            data={"email": "locked@example.com"},
            follow_redirects=False,
        )
        self.assertIn(resp.status_code, (302, 303, 307, 308))
        # Must still be in list (gate rejected before handler ran)
        cfg = load_beta_recipient_config()
        self.assertIn("locked@example.com", cfg["recipients"])

    def test_add_newline_header_injection_rejected(self):
        resp = self._authed_post(
            "/admin/customer-recipients/add",
            {"email": "x@x.com\nBcc: evil@evil.com"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("유효하지 않은", resp.text)
        cfg = load_beta_recipient_config()
        for addr in cfg["recipients"]:
            self.assertNotIn("\n", addr)

    def test_page_shows_env_and_admin_counts(self):
        save_beta_recipient_config(["extra@example.com"])
        resp = self._authed_get("/admin/customer-recipients")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("env@example.com", resp.text)
        self.assertIn("extra@example.com", resp.text)


if __name__ == "__main__":
    unittest.main()
