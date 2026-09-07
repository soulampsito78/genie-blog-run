"""2026-09-07: tapping the customer-send affordance must never be a no-op.

Owner report (iPhone): the run detail page showed a red panel headed
"승인하고 12명에게 발송"; tapping it produced no request, no navigation and no
error. The heading was an inert <strong>, and the only real control carried a
different label ("승인 검토 페이지 열기").

These tests pin the invariants: the send wording lives on a real control, the
approval form is a plain HTML POST that works without JavaScript, and every
server-side rejection comes back as an owner-visible reason.
"""
from __future__ import annotations

import os
import re
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from admin_store import load_run_artifact, save_run_artifact
from main import app
from tests.test_admin_routes import post_customer_approve_with_confirm

_SEND_WORDING = re.compile(r"승인하고\s*[^<]{0,24}에게\s*발송")


def _tag_around(html: str, needle_match: re.Match) -> str:
    """The innermost tag that directly contains the matched text."""
    open_idx = html.rfind("<", 0, needle_match.start())
    tag = re.match(r"<\s*([a-zA-Z][a-zA-Z0-9]*)", html[open_idx:])
    return tag.group(1).lower() if tag else ""


class AdminApproveAffordanceTests(unittest.TestCase):
    def setUp(self) -> None:
        # Customer dispatch is never invoked in these tests; the delivery config
        # only has to look ready so the approval affordance renders at all.
        self._env = patch.dict(
            os.environ,
            {
                "GENIE_ADMIN_PASSWORD": "test-admin-secret",
                "GENIE_CUSTOMER_EMAIL_TO": "qa1@example.invalid,qa2@example.invalid",
                "SMTP_HOST": "smtp.example.invalid",
                "SMTP_USER": "qa@example.invalid",
            },
            clear=False,
        )
        self._env.start()
        self.addCleanup(self._env.stop)
        self.client = TestClient(app)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})

    def _save_today_run(self, run_id: str, **overrides) -> None:
        meta = {
            "run_id": run_id,
            "mode": "today_genie",
            "validation_result": "pass",
            "workflow_status": "validated",
            "response_status": 200,
            "reason_summary": "ok",
            "owner_review_status": "pending_review",
            "customer_delivery_status": "not_sent",
        }
        meta.update(overrides)
        save_run_artifact(meta, email_html="<p>brief</p>")

    # --- the defect itself ---------------------------------------------------

    def test_send_wording_on_run_detail_is_always_inside_a_real_control(self) -> None:
        run_id = "20260907_120000_today_genie_aabbccdd"
        self._save_today_run(run_id)
        html = self.client.get(f"/admin/runs/{run_id}").text
        matches = list(_SEND_WORDING.finditer(html))
        self.assertTrue(matches, "run detail should offer the customer-send action")
        for m in matches:
            tag = _tag_around(html, m)
            self.assertIn(
                tag,
                {"a", "button"},
                f"send wording rendered in inert <{tag}> — tapping it does nothing",
            )

    def test_run_detail_send_control_links_to_the_confirm_page(self) -> None:
        run_id = "20260907_120100_today_genie_aabbccdd"
        self._save_today_run(run_id)
        html = self.client.get(f"/admin/runs/{run_id}").text
        anchor = re.search(
            r'<a[^>]+href="/admin/runs/' + run_id + r'/approve-confirm"[^>]*>(.*?)</a>',
            html,
            re.S,
        )
        self.assertIsNotNone(anchor, "no link to the approval confirm page")
        self.assertRegex(anchor.group(1), _SEND_WORDING)

    def test_blocked_run_shows_an_explicit_reason_and_no_send_control(self) -> None:
        run_id = "20260907_120200_today_genie_aabbccdd"
        self._save_today_run(run_id, customer_surface_status="PRODUCT_REVIEW_REQUIRED")
        html = self.client.get(f"/admin/runs/{run_id}").text
        self.assertIn("승인 발송 불가", html)
        self.assertIn("product_surface_remediation_needed", html)
        self.assertNotIn("/approve-confirm", html)

    # --- the form is a plain, mobile-safe HTML POST ---------------------------

    def test_confirm_form_is_native_post_without_javascript(self) -> None:
        run_id = "20260907_120300_today_genie_aabbccdd"
        self._save_today_run(run_id)
        html = self.client.get(f"/admin/runs/{run_id}/approve-confirm").text
        form = re.search(
            r'<form[^>]*action="/admin/runs/' + run_id + r'/approve"[^>]*>(.*?)</form>',
            html,
            re.S,
        )
        self.assertIsNotNone(form)
        self.assertRegex(form.group(0), r'method="post"')
        body = form.group(1)
        for field in (
            "approve_nonce",
            "approval_snapshot_id",
            "csrf_token",
            "customer_send_confirm",
        ):
            self.assertIn(f'name="{field}"', body)
        self.assertRegex(body, r'<button[^>]*type="submit"')
        # No script and no JS-only activation anywhere in the form.
        self.assertNotIn("<script", body.lower())
        self.assertNotIn("onclick", body.lower())
        self.assertNotIn("disabled", body.lower())

    def test_confirm_page_has_no_nested_form(self) -> None:
        run_id = "20260907_120400_today_genie_aabbccdd"
        self._save_today_run(run_id)
        html = self.client.get(f"/admin/runs/{run_id}/approve-confirm").text
        depth = 0
        for m in re.finditer(r"</?form\b", html, re.I):
            if m.group(0).startswith("</"):
                depth -= 1
            else:
                depth += 1
                self.assertLessEqual(depth, 1, "nested <form> breaks submit in browsers")
            self.assertGreaterEqual(depth, 0, "stray </form>")
        self.assertEqual(depth, 0, "unclosed <form>")

    # --- server side: every rejection is visible ------------------------------

    @patch("today_geenee_customer_delivery.send_today_geenee_customer_final_email")
    def test_missing_checkbox_redirects_with_visible_reason(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260907_120500_today_genie_aabbccdd"
        self._save_today_run(run_id)
        resp = post_customer_approve_with_confirm(
            self.client, run_id, include_checkbox=False
        )
        self.assertEqual(resp.status_code, 303)
        location = resp.headers.get("location", "")
        self.assertIn("approve_error=missing_customer_send_confirm", location)
        mock_send.assert_not_called()
        page = self.client.get(location).text
        self.assertIn("승인 실패", page)
        self.assertIn("체크박스", page)

    @patch("today_geenee_customer_delivery.send_today_geenee_customer_final_email")
    def test_missing_nonce_redirects_with_visible_reason(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260907_120600_today_genie_aabbccdd"
        self._save_today_run(run_id)
        resp = self.client.post(
            f"/admin/runs/{run_id}/approve",
            data={"approve_note": "x", "customer_send_confirm": "1"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        location = resp.headers.get("location", "")
        self.assertIn("missing_approval_nonce", location)
        mock_send.assert_not_called()
        page = self.client.get(location).text
        self.assertIn("승인 실패", page)
        self.assertEqual(
            (load_run_artifact(run_id) or {}).get("customer_delivery_status"), "not_sent"
        )

    def test_every_approve_error_code_has_owner_facing_text(self) -> None:
        """No rejection may surface as a bare code or an empty banner."""
        from admin_routes import _APPROVE_ERROR_MESSAGES

        for code in (
            "product_surface_remediation_needed",
            "review_required_remediation_needed",
            "missing_customer_send_confirm",
            "missing_approval_nonce",
            "invalid_approval_nonce",
            "approval_nonce_expired",
            "INVALID_APPROVAL_SNAPSHOT",
            "STALE_APPROVAL_SNAPSHOT",
            "APPROVAL_TARGET_CHANGED",
            "DUPLICATE_DELIVERY_COMMAND",
            "send_failed",
        ):
            with self.subTest(code=code):
                message = _APPROVE_ERROR_MESSAGES.get(code, "")
                self.assertTrue(message.strip(), f"{code} has no owner-facing message")
                self.assertNotEqual(message.strip(), code)

    # --- protections that must survive this change ---------------------------

    @patch("today_geenee_customer_delivery.send_today_geenee_customer_final_email")
    def test_double_submit_is_still_blocked(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260907_120700_today_genie_aabbccdd"
        self._save_today_run(run_id, customer_delivery_status="smtp_accepted")
        resp = post_customer_approve_with_confirm(self.client, run_id)
        self.assertEqual(resp.status_code, 303)
        self.assertIn("approve_error=", resp.headers.get("location", ""))
        mock_send.assert_not_called()

    @patch("today_geenee_customer_delivery.send_today_geenee_customer_final_email")
    def test_approval_snapshot_protection_still_required(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260907_120800_today_genie_aabbccdd"
        self._save_today_run(run_id)
        confirm = self.client.get(f"/admin/runs/{run_id}/approve-confirm")
        nonce = re.search(r'name="approve_nonce" value="([^"]+)"', confirm.text).group(1)
        resp = self.client.post(
            f"/admin/runs/{run_id}/approve",
            data={
                "approve_note": "x",
                "approve_nonce": nonce,
                "customer_send_confirm": "1",
                "approval_snapshot_id": "aps_forged_0000000000000000",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("approve_error=", resp.headers.get("location", ""))
        mock_send.assert_not_called()
        self.assertEqual(
            (load_run_artifact(run_id) or {}).get("customer_delivery_status"), "not_sent"
        )


if __name__ == "__main__":
    unittest.main()
