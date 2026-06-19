"""Kee-Suri customer delivery tests (Global enabled; Korea gated by bottom QA baseline)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from admin_store import approve_run, can_approve_customer_send, load_run_artifact, save_run_artifact
from fastapi.testclient import TestClient
from keysuri_live_source_smoke import PROGRAM_GLOBAL, PROGRAM_KOREA
from keysuri_service_full_run import keysuri_global_service_email_cid_src
from main import app
from programs.registry import list_programs, resolve_program_id
from tests.test_admin_routes import post_customer_approve_with_confirm


def _keysuri_global_gmail_owner_review_email_html(
    run_id: str = "20260612_120000_keysuri_global_tech_aabbccdd",
) -> str:
    from keysuri_contract_preview_renderer import build_keysuri_global_gmail_owner_email_html
    from tests.test_keysuri_contract_preview_renderer import build_global_contract_fixture

    fixture = build_global_contract_fixture()
    fixture["top_shot_image_src"] = keysuri_global_service_email_cid_src(run_id)
    return build_keysuri_global_gmail_owner_email_html(
        fixture,
        subject="[운영자 검토] Kee-Suri Global Tech",
        admin_url=f"https://example.com/admin/runs/{run_id}",
        run_id=run_id,
    )


def _keysuri_global_legacy_owner_review_email_html(
    run_id: str = "20260612_120000_keysuri_global_tech_aabbccdd",
) -> str:
    cid = keysuri_global_service_email_cid_src(run_id)
    inner = f"""
<header class="premium-hero" id="premium-hero">
  <span class="owner-review-badge">운영자 검수용 미리보기 · 아직 발송 전</span>
  <h1 class="hero-title">키수리 글로벌 테크 브리핑</h1>
  <img src="{cid}" alt="키수리" class="top-shot-hero"/>
</header>
<section class="top-item" data-top-item="1">
  <h3 class="top-headline">글로벌 AI 인프라 확장</h3>
  <p class="top-source"><a href="https://example.com/source-1">출처</a></p>
</section>
<section class="top-item" data-top-item="2"><h3>두 번째 신호</h3></section>
<section class="top-item" data-top-item="3"><h3>세 번째 신호</h3></section>
<section class="top-item" data-top-item="4"><h3>네 번째 신호</h3></section>
<section class="top-item" data-top-item="5"><h3>다섯 번째 신호</h3></section>
<section id="review-confirmation-box" class="review-box" data-review-state="preview_pending">
  <p class="review-confirmation-text">본 브리핑은 운영책임자의 직접 검수 대기 상태입니다.</p>
</section>
<div class="owner-review-admin-entry" id="owner-review-admin-entry">
  <a href="https://example.com/admin/runs/{run_id}">운영자 검수 화면 열기</a>
</div>
<div class="op-meta" id="operation-metadata"><span>preview_path: /secret</span></div>
<div class="meta-box" id="preview-metadata"><span>program_id: keysuri_global_tech</span></div>
<div class="validation-box" id="validation-result-box">validation_status: PASS</div>
"""
    return (
        '<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"/>'
        "<style>.premium-briefing.theme-global{--g-accent:#3f7ecb;}</style>"
        "</head><body class=\"premium-briefing theme-global\">"
        f'<div class="briefing-shell">{inner}</div></body></html>'
    )


_KEYSURI_KOREA_BOTTOM_BASELINE_ASSET_ID = "keysuri_korea_bottom_20260605_105936"


def _keysuri_global_artifact_meta(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "mode": PROGRAM_GLOBAL,
        "program_id": PROGRAM_GLOBAL,
        "service_full_run": True,
        "validation_result": "pass",
        "workflow_status": "PASS_OWNER_REVIEW_READY",
        "response_status": 200,
        "email_sent": True,
        "owner_review_status": "pending_review",
        "customer_delivery_status": "not_sent",
        "generated_image_path": "output/images/keysuri_global_service_test.jpg",
        "image_source": "generated",
        "artifact_status": "emailed",
    }


def _keysuri_korea_artifact_meta_with_baseline(run_id: str) -> dict:
    """Korea artifact meta with 041559 bottom QA baseline confirmed (bc78424)."""
    return {
        "run_id": run_id,
        "mode": PROGRAM_KOREA,
        "program_id": PROGRAM_KOREA,
        "service_full_run": True,
        "validation_result": "pass",
        "owner_review_status": "pending_review",
        "customer_delivery_status": "not_sent",
        "artifact_status": "emailed",
        "bottom_shot_asset_id": _KEYSURI_KOREA_BOTTOM_BASELINE_ASSET_ID,
        "korea_bottom_shot_asset_id": _KEYSURI_KOREA_BOTTOM_BASELINE_ASSET_ID,
        "bottom_shot_source": "fixed_105936_fallback",
        "bottom_shot_watermark_status": "applied",
    }


def _keysuri_korea_artifact_meta_with_generated_bottom(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "mode": PROGRAM_KOREA,
        "program_id": PROGRAM_KOREA,
        "service_full_run": True,
        "validation_result": "pass",
        "owner_review_status": "pending_review",
        "customer_delivery_status": "not_sent",
        "artifact_status": "emailed",
        "bottom_shot_asset_id": f"keysuri_korea_bottom_generated_{run_id}",
        "bottom_shot_source": "generated_v6_multi_ref",
        "bottom_shot_generated": True,
        "bottom_anchor_asset_id": _KEYSURI_KOREA_BOTTOM_BASELINE_ASSET_ID,
        "bottom_anchor_role": "primary_bottom_visual_anchor",
        "bottom_anchor_slot": 0,
        "secondary_reference_asset_id": "Asset01",
        "secondary_reference_role": "secondary_same_person_continuity_reference",
        "secondary_reference_slot": 1,
        "bottom_shot_watermark_status": "applied",
    }


class KeysuriApproveRunGateTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "customer@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"
        os.environ["SMTP_PASSWORD"] = "secret"

    def test_keysuri_korea_can_approve_blocked_without_bottom_baseline(self) -> None:
        # Korea without bottom QA baseline metadata → blocked (asset_id missing)
        run_id = "20260612_120000_keysuri_korea_tech_aabbccdd"
        meta = {
            "run_id": run_id,
            "mode": PROGRAM_KOREA,
            "program_id": PROGRAM_KOREA,
            "validation_result": "pass",
            "owner_review_status": "pending_review",
            "customer_delivery_status": "not_sent",
        }
        ok, err = can_approve_customer_send(meta, has_email_html=True)
        self.assertFalse(ok)
        self.assertEqual(err, "korea_bottom_baseline_asset_id_missing")

    def test_keysuri_korea_can_approve_blocked_wrong_source(self) -> None:
        # Korea with asset_id correct but wrong bottom_shot_source → blocked
        run_id = "20260612_120000_keysuri_korea_tech_aabbccdd"
        meta = {
            "run_id": run_id,
            "mode": PROGRAM_KOREA,
            "program_id": PROGRAM_KOREA,
            "validation_result": "pass",
            "owner_review_status": "pending_review",
            "customer_delivery_status": "not_sent",
            "bottom_shot_asset_id": _KEYSURI_KOREA_BOTTOM_BASELINE_ASSET_ID,
            "bottom_shot_source": "generated_variation",  # not in approved set
        }
        ok, err = can_approve_customer_send(meta, has_email_html=True)
        self.assertFalse(ok)
        self.assertEqual(err, "korea_bottom_baseline_source_unconfirmed")

    def test_keysuri_korea_can_approve_when_baseline_confirmed(self) -> None:
        # Korea with 041559 baseline confirmed → allowed (owner PASS gate next)
        run_id = "20260612_120000_keysuri_korea_tech_aabbccdd"
        meta = _keysuri_korea_artifact_meta_with_baseline(run_id)
        ok, err = can_approve_customer_send(meta, has_email_html=True)
        self.assertTrue(ok, f"expected approvable with baseline, got err={err!r}")
        self.assertEqual(err, "ok")

    def test_keysuri_korea_can_approve_generated_v6_with_valid_anchor_contract(self) -> None:
        run_id = "20260618_183000_keysuri_korea_tech_generated"
        meta = _keysuri_korea_artifact_meta_with_generated_bottom(run_id)
        ok, err = can_approve_customer_send(meta, has_email_html=True)
        self.assertTrue(ok, f"expected generated Bottom to be approvable, got err={err!r}")
        self.assertEqual(err, "ok")

    def test_keysuri_korea_generated_v6_blocks_wrong_anchor_metadata(self) -> None:
        run_id = "20260618_183000_keysuri_korea_tech_bad_anchor"
        meta = _keysuri_korea_artifact_meta_with_generated_bottom(run_id)
        meta["bottom_anchor_asset_id"] = "wrong-anchor"
        ok, err = can_approve_customer_send(meta, has_email_html=True)
        self.assertFalse(ok)
        self.assertEqual(err, "korea_bottom_generated_anchor_id_invalid")

    def test_keysuri_korea_generated_v6_blocks_wrong_secondary_slot(self) -> None:
        run_id = "20260618_183000_keysuri_korea_tech_bad_slot"
        meta = _keysuri_korea_artifact_meta_with_generated_bottom(run_id)
        meta["secondary_reference_slot"] = 0
        ok, err = can_approve_customer_send(meta, has_email_html=True)
        self.assertFalse(ok)
        self.assertEqual(err, "korea_bottom_generated_secondary_slot_invalid")

    def test_keysuri_korea_can_approve_blocked_when_already_approved(self) -> None:
        # Korea with baseline confirmed but already approved → blocked (not double-send)
        run_id = "20260612_120000_keysuri_korea_tech_aabbccdd"
        meta = _keysuri_korea_artifact_meta_with_baseline(run_id)
        meta["owner_review_status"] = "approved"
        ok, err = can_approve_customer_send(meta, has_email_html=True)
        self.assertFalse(ok)
        self.assertEqual(err, "already_approved")

    def test_keysuri_global_can_approve_when_ready(self) -> None:
        run_id = "20260612_120000_keysuri_global_tech_aabbccdd"
        meta = _keysuri_global_artifact_meta(run_id)
        ok, err = can_approve_customer_send(meta, has_email_html=True)
        self.assertTrue(ok)
        self.assertEqual(err, "ok")


class KeysuriGlobalApproveRunTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "customer@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"
        os.environ["SMTP_PASSWORD"] = "secret"

    @patch("keysuri_customer_delivery.send_keysuri_customer_final_email")
    def test_keysuri_global_approve_run_sends_customer_email(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260612_120000_keysuri_global_tech_aabbccdd"
        save_run_artifact(
            _keysuri_global_artifact_meta(run_id),
            email_html=_keysuri_global_gmail_owner_review_email_html(run_id),
        )
        updated, status = approve_run(run_id)
        self.assertEqual(status, "ok")
        self.assertIsNotNone(updated)
        mock_send.assert_called_once()
        meta = load_run_artifact(run_id) or {}
        self.assertEqual(meta.get("owner_review_status"), "approved")
        self.assertEqual(meta.get("customer_delivery_status"), "smtp_accepted")


class KeysuriApproveRunBlockedTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "customer@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"
        os.environ["SMTP_PASSWORD"] = "secret"

    def test_keysuri_korea_approve_run_blocked_without_bottom_baseline(self) -> None:
        # Korea without bottom baseline metadata → approve_run blocked, no email sent
        run_id = "20260612_120000_keysuri_korea_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": PROGRAM_KOREA,
                "program_id": PROGRAM_KOREA,
                "service_full_run": True,
                "validation_result": "pass",
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
                "artifact_status": "emailed",
                # no bottom_shot_asset_id / bottom_shot_source
            },
            email_html="<p>brief</p>",
        )
        with patch(
            "keysuri_customer_delivery.send_keysuri_customer_final_email",
            return_value=True,
        ) as mock_send:
            updated, status = approve_run(run_id)
        self.assertIsNone(updated)
        self.assertEqual(status, "korea_bottom_baseline_asset_id_missing")
        mock_send.assert_not_called()
        meta = load_run_artifact(run_id) or {}
        self.assertEqual(meta.get("owner_review_status"), "pending_review")
        self.assertEqual(meta.get("customer_delivery_status"), "not_sent")

    def test_keysuri_korea_approve_run_sends_when_baseline_confirmed(self) -> None:
        # Korea with 041559 baseline confirmed → approve_run sends customer email
        run_id = "20260612_120001_keysuri_korea_tech_aabbccdd"
        save_run_artifact(
            _keysuri_korea_artifact_meta_with_baseline(run_id),
            email_html="<p>키수리 코리아 브리핑</p>",
        )
        with patch(
            "keysuri_customer_delivery.send_keysuri_customer_final_email",
            return_value=True,
        ) as mock_send:
            updated, status = approve_run(run_id)
        self.assertEqual(status, "ok")
        self.assertIsNotNone(updated)
        mock_send.assert_called_once()
        meta = load_run_artifact(run_id) or {}
        self.assertEqual(meta.get("owner_review_status"), "approved")
        self.assertEqual(meta.get("customer_delivery_status"), "smtp_accepted")


class KeysuriCustomerDeliveryHtmlTests(unittest.TestCase):
    def test_keysuri_gmail_customer_delivery_strips_owner_admin_block(self) -> None:
        from keysuri_customer_delivery import prepare_keysuri_customer_final_html

        run_id = "20260612_120000_keysuri_global_tech_aabbccdd"
        html = prepare_keysuri_customer_final_html(
            _keysuri_global_gmail_owner_review_email_html(run_id),
            meta=_keysuri_global_artifact_meta(run_id),
        )
        lowered = html.lower()
        self.assertNotIn("owner-review-admin-entry", html)
        self.assertNotIn("운영자 검수 화면 열기", html)
        self.assertNotIn("/admin/runs/", html)
        self.assertNotIn("운영자 검수용", html)
        self.assertNotIn("아직 발송 전", html)
        self.assertNotIn("run_id:", lowered)
        self.assertNotIn("<style", lowered)
        self.assertNotIn("var(--", html)
        self.assertNotIn("display:flex", html.replace(" ", ""))
        self.assertIn("키수리 글로벌 테크 브리핑", html)
        self.assertIn("키수리의 딥-다이브", html)
        self.assertIn("원-라인 체크포인트", html)
        self.assertIn("다음 48시간 관찰 포인트", html)
        self.assertLess(html.find("원-라인 체크포인트"), html.find("다음 48시간 관찰 포인트"))
        self.assertIn('role="presentation"', html)
        self.assertIn("https://blog.google/technology/ai/", html)
        self.assertIn(keysuri_global_service_email_cid_src(run_id), html)
        self.assertNotIn("원문 확인이 필요", html)
        self.assertIn(
            "향후 공식 발표를 통해 세부 내용이 보완될 가능성이 있습니다.",
            html,
        )

    def test_keysuri_gmail_customer_delivery_sent_archived_box(self) -> None:
        from keysuri_contract_preview_renderer import REVIEW_CONFIRMATION_TEXT, REVIEW_STATE_SENT_ARCHIVED
        from keysuri_customer_delivery import prepare_keysuri_customer_final_html

        run_id = "20260612_120000_keysuri_global_tech_aabbccdd"
        html = prepare_keysuri_customer_final_html(
            _keysuri_global_gmail_owner_review_email_html(run_id),
            meta=_keysuri_global_artifact_meta(run_id),
        )
        self.assertIn(REVIEW_CONFIRMATION_TEXT[REVIEW_STATE_SENT_ARCHIVED], html)
        self.assertNotIn("preview_pending", html)
        self.assertNotIn("검수 대기", html)

    def test_keysuri_legacy_customer_delivery_strips_owner_admin_block(self) -> None:
        from keysuri_customer_delivery import prepare_keysuri_customer_final_html

        run_id = "20260612_120000_keysuri_global_tech_aabbccdd"
        html = prepare_keysuri_customer_final_html(
            _keysuri_global_legacy_owner_review_email_html(run_id),
            meta=_keysuri_global_artifact_meta(run_id),
        )
        self.assertNotIn("owner-review-admin-entry", html)
        self.assertNotIn("운영자 검수 화면 열기", html)
        self.assertNotIn("/admin/runs/", html)
        self.assertNotIn("운영자 검수용", html)
        self.assertNotIn("아직 발송 전", html)
        self.assertNotIn("operation-metadata", html)
        self.assertNotIn("preview-metadata", html)
        self.assertNotIn("validation-result-box", html)
        self.assertIn("키수리 글로벌 테크 브리핑", html)
        self.assertIn("premium-briefing", html)
        self.assertIn("theme-global", html)
        self.assertIn('data-top-item="1"', html)
        self.assertIn("https://example.com/source-1", html)
        self.assertIn(keysuri_global_service_email_cid_src(run_id), html)

    def test_keysuri_legacy_customer_delivery_sent_archived_box(self) -> None:
        from keysuri_contract_preview_renderer import REVIEW_CONFIRMATION_TEXT, REVIEW_STATE_SENT_ARCHIVED
        from keysuri_customer_delivery import prepare_keysuri_customer_final_html

        run_id = "20260612_120000_keysuri_global_tech_aabbccdd"
        html = prepare_keysuri_customer_final_html(
            _keysuri_global_legacy_owner_review_email_html(run_id),
            meta=_keysuri_global_artifact_meta(run_id),
        )
        self.assertIn('id="review-confirmation-box"', html)
        self.assertIn(f'data-review-state="{REVIEW_STATE_SENT_ARCHIVED}"', html)
        self.assertIn(REVIEW_CONFIRMATION_TEXT[REVIEW_STATE_SENT_ARCHIVED], html)
        self.assertNotIn("preview_pending", html)
        self.assertNotIn("검수 대기", html)


class KeysuriAdminApproveButtonTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_pwd = os.environ.get("GENIE_ADMIN_PASSWORD")
        os.environ["GENIE_ADMIN_PASSWORD"] = "test-admin-secret"
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "customer@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"
        os.environ["SMTP_PASSWORD"] = "secret"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        if self._prev_pwd is None:
            os.environ.pop("GENIE_ADMIN_PASSWORD", None)
        else:
            os.environ["GENIE_ADMIN_PASSWORD"] = self._prev_pwd

    def test_admin_run_detail_keysuri_global_shows_active_approve_button(self) -> None:
        run_id = "20260612_130000_keysuri_global_tech_bbccddee"
        save_run_artifact(
            _keysuri_global_artifact_meta(run_id),
            email_html=_keysuri_global_gmail_owner_review_email_html(run_id),
        )
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        resp = self.client.get(f"/admin/runs/{run_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("승인 검토 페이지 열기", resp.text)
        self.assertNotIn("Kee-Suri 고객 발송은 아직 안전 검증 전입니다", resp.text)

    def test_admin_run_detail_keysuri_korea_no_active_approve_button(self) -> None:
        run_id = "20260612_130000_keysuri_korea_tech_bbccddee"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": PROGRAM_KOREA,
                "program_id": PROGRAM_KOREA,
                "service_full_run": True,
                "validation_result": "pass",
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
                "artifact_status": "emailed",
            },
            email_html="<p>brief</p>",
        )
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        resp = self.client.get(f"/admin/runs/{run_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("승인 검토 페이지 열기", resp.text)
        # Korea without bottom baseline → admin UI shows the gate error code
        self.assertIn("korea_bottom_baseline_asset_id_missing", resp.text)


class KeysuriApproveRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_pwd = os.environ.get("GENIE_ADMIN_PASSWORD")
        self._prev_customer = os.environ.get("GENIE_CUSTOMER_EMAIL_TO")
        os.environ["GENIE_ADMIN_PASSWORD"] = "test-admin-secret"
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "customer@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"
        os.environ["SMTP_PASSWORD"] = "secret"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        for key, prev in (
            ("GENIE_ADMIN_PASSWORD", self._prev_pwd),
            ("GENIE_CUSTOMER_EMAIL_TO", self._prev_customer),
        ):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev

    @patch("keysuri_customer_delivery.send_keysuri_customer_final_email")
    def test_approve_post_keysuri_global_sends_via_confirm_flow(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260612_140000_keysuri_global_tech_ccddeeff"
        save_run_artifact(
            _keysuri_global_artifact_meta(run_id),
            email_html=_keysuri_global_gmail_owner_review_email_html(run_id),
        )
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        resp = post_customer_approve_with_confirm(self.client, run_id, note="ok")
        self.assertEqual(resp.status_code, 303)
        self.assertNotIn("approve_error", resp.headers.get("location", ""))
        mock_send.assert_called_once()
        meta = load_run_artifact(run_id) or {}
        self.assertEqual(meta.get("owner_review_status"), "approved")
        self.assertEqual(meta.get("approval_channel"), "browser_confirm")
        self.assertTrue(meta.get("approval_nonce_used"))

    @patch("keysuri_customer_delivery.send_keysuri_customer_final_email")
    def test_direct_post_keysuri_global_without_nonce_blocked(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260612_140100_keysuri_global_tech_ccddeeff"
        save_run_artifact(
            _keysuri_global_artifact_meta(run_id),
            email_html=_keysuri_global_gmail_owner_review_email_html(run_id),
        )
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        resp = self.client.post(
            f"/admin/runs/{run_id}/approve",
            data={"approve_note": "ok", "customer_send_confirm": "1"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("missing_approval_nonce", resp.headers.get("location", ""))
        mock_send.assert_not_called()

    @patch("keysuri_customer_delivery.send_keysuri_customer_final_email")
    def test_approve_post_keysuri_korea_blocked(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260612_140000_keysuri_korea_tech_ccddeeff"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": PROGRAM_KOREA,
                "program_id": PROGRAM_KOREA,
                "service_full_run": True,
                "validation_result": "pass",
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
                "artifact_status": "emailed",
            },
            email_html="<p>brief</p>",
        )
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        resp = self.client.get(f"/admin/runs/{run_id}/approve-confirm")
        self.assertEqual(resp.status_code, 400)
        # Korea without bottom baseline → gate error code in response
        self.assertIn("korea_bottom_baseline_asset_id_missing", resp.text)
        mock_send.assert_not_called()
        meta = load_run_artifact(run_id) or {}
        self.assertEqual(meta.get("owner_review_status"), "pending_review")


class TodayServiceFullRunCustomerImageTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "customer@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"
        os.environ["SMTP_PASSWORD"] = "secret"

    @patch("today_geenee_customer_delivery.send_genie_email")
    def test_today_service_full_run_approve_uses_generated_images(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "run_top.jpg"
            bottom = Path(tmp) / "run_bottom.jpg"
            top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            bottom.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)

            run_id = "20260612_150000_today_genie_aabbccdd"
            save_run_artifact(
                {
                    "run_id": run_id,
                    "mode": "today_genie",
                    "service_full_run": True,
                    "image_source": "generated",
                    "image_generation_status": "generated",
                    "fallback_used": False,
                    "validation_result": "pass",
                    "workflow_status": "validated",
                    "response_status": 200,
                    "email_sent": True,
                    "owner_review_status": "pending_review",
                    "customer_delivery_status": "not_sent",
                    "generated_image_paths": {
                        "top": str(top),
                        "bottom": str(bottom),
                    },
                },
                email_html='<p>brief</p><section id="genie-operational-handoff"></section>',
            )
            from admin_store import load_run_email_html
            from today_geenee_customer_delivery import send_today_geenee_customer_final_email

            meta = load_run_artifact(run_id) or {}
            send_today_geenee_customer_final_email(load_run_email_html(run_id) or "", meta)

        mock_send.assert_called_once()
        inline = mock_send.call_args.kwargs.get("inline_jpeg_parts") or []
        self.assertEqual(len(inline), 2)
        used_paths = {Path(row[0]).resolve() for row in inline}
        self.assertIn(top.resolve(), used_paths)
        self.assertIn(bottom.resolve(), used_paths)
        latest_top = (repo / "static" / "email" / "GENIE_EMAIL_today_genie_top_latest.jpg").resolve()
        self.assertNotIn(latest_top, used_paths)


class ServiceFullRunRegistryApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "customer@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"
        os.environ["SMTP_PASSWORD"] = "secret"

    def test_today_still_approvable_via_registry(self) -> None:
        for spec in list_programs():
            if not spec.customer_send_requires_approval:
                continue
            mode = spec.legacy_mode or spec.program_id
            run_id = {
                "today_genie": "20260612_160000_today_genie_aabbccdd",
                PROGRAM_GLOBAL: "20260612_160000_keysuri_global_tech_aabbccdd",
                PROGRAM_KOREA: "20260612_160000_keysuri_korea_tech_aabbccdd",
            }.get(mode, f"20260612_160000_{mode}_aabbccdd")
            meta = {
                "run_id": run_id,
                "mode": mode,
                "program_id": spec.program_id,
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
            }
            ok, err = can_approve_customer_send(meta, has_email_html=True)
            with self.subTest(program_id=spec.program_id, mode=mode):
                if mode == PROGRAM_KOREA:
                    # Korea blocked without bottom baseline metadata in artifact
                    self.assertFalse(ok)
                    self.assertEqual(err, "korea_bottom_baseline_asset_id_missing")
                elif mode == PROGRAM_GLOBAL:
                    self.assertTrue(ok, f"expected approvable, got {err!r}")
                    self.assertEqual(err, "ok")
                else:
                    self.assertTrue(ok, f"expected approvable, got {err!r}")
                    self.assertEqual(err, "ok")
            resolved = resolve_program_id(mode)
            self.assertEqual(resolved, spec.program_id)


class KeysuriKoreaCustomerEmailBottomCidTests(unittest.TestCase):
    """Korea customer email must carry both Top and Bottom MIME inline parts."""

    def setUp(self) -> None:
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "customer@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"
        os.environ["SMTP_PASSWORD"] = "secret"

    def _korea_owner_email_html(self, run_id: str, *, with_bottom_cid: bool = True) -> str:
        from keysuri_contract_preview_renderer import build_keysuri_korea_gmail_owner_email_html
        from keysuri_service_full_run import (
            keysuri_korea_bottom_service_email_cid_src,
            keysuri_korea_service_email_cid_src,
        )
        from tests.test_keysuri_contract_preview_renderer import build_korea_contract_fixture

        fixture = build_korea_contract_fixture()
        fixture["top_shot_image_src"] = keysuri_korea_service_email_cid_src(run_id)
        if with_bottom_cid:
            fixture["bottom_shot_image_src"] = keysuri_korea_bottom_service_email_cid_src(run_id)
        return build_keysuri_korea_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Korea Tech",
            admin_url=f"https://example.com/admin/runs/{run_id}",
            run_id=run_id,
        )

    def _meta_with_baseline_and_paths(
        self,
        run_id: str,
        top_path: str,
        bottom_path: str,
        bottom_source: str = "fixed_105936_fallback",
    ) -> dict:
        return {
            "run_id": run_id,
            "mode": PROGRAM_KOREA,
            "program_id": PROGRAM_KOREA,
            "service_full_run": True,
            "validation_result": "pass",
            "owner_review_status": "pending_review",
            "customer_delivery_status": "not_sent",
            "artifact_status": "emailed",
            "generated_image_path": top_path,
            "bottom_shot_asset_id": _KEYSURI_KOREA_BOTTOM_BASELINE_ASSET_ID,
            "korea_bottom_shot_asset_id": _KEYSURI_KOREA_BOTTOM_BASELINE_ASSET_ID,
            "bottom_shot_source": bottom_source,
            "korea_bottom_shot_path": bottom_path,
            "bottom_shot_image_path": bottom_path,
            "bottom_shot_watermark_status": "applied",
        }

    # T1: Korea customer HTML references both Top and Bottom CIDs
    def test_korea_owner_html_contains_top_and_bottom_cids(self) -> None:
        from keysuri_service_full_run import (
            keysuri_korea_bottom_service_email_cid_src,
            keysuri_korea_service_email_cid_src,
        )

        run_id = "20260619_120000_keysuri_korea_tech_cidtest1"
        html = self._korea_owner_email_html(run_id, with_bottom_cid=True)
        self.assertIn(keysuri_korea_service_email_cid_src(run_id), html)
        self.assertIn(keysuri_korea_bottom_service_email_cid_src(run_id), html)
        self.assertIn('id="bottom-shot-image"', html)
        self.assertNotIn('id="bottom-shot-placeholder"', html)

    # T2: Korea customer MIME inline parts includes Top and Bottom
    def test_korea_resolve_inline_parts_returns_top_and_bottom(self) -> None:
        import tempfile

        from keysuri_customer_delivery import resolve_keysuri_inline_jpeg_parts
        from keysuri_service_full_run import (
            keysuri_korea_bottom_service_email_cid_token,
            keysuri_korea_service_email_cid_token,
        )

        run_id = "20260619_120000_keysuri_korea_tech_cidtest2"
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "top.jpg"
            bottom = Path(tmp) / "bottom.jpg"
            top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            bottom.write_bytes(b"\xff\xd8\xff" + b"\x11" * 64)
            top_rel = str(top)
            bottom_rel = str(bottom)
            meta = self._meta_with_baseline_and_paths(run_id, top_rel, bottom_rel)
            html = self._korea_owner_email_html(run_id, with_bottom_cid=True)
            parts = resolve_keysuri_inline_jpeg_parts(html, meta)
        self.assertIsNotNone(parts)
        self.assertEqual(len(parts), 2)
        cid_tokens = [row[1] for row in parts]
        self.assertIn(keysuri_korea_service_email_cid_token(run_id), cid_tokens)
        self.assertIn(keysuri_korea_bottom_service_email_cid_token(run_id), cid_tokens)

    # T3: All cid: references in HTML have corresponding MIME inline parts
    def test_all_html_cids_covered_by_inline_parts(self) -> None:
        import re
        import tempfile

        from keysuri_customer_delivery import resolve_keysuri_inline_jpeg_parts

        run_id = "20260619_120000_keysuri_korea_tech_cidtest3"
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "top.jpg"
            bottom = Path(tmp) / "bottom.jpg"
            top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            bottom.write_bytes(b"\xff\xd8\xff" + b"\x11" * 64)
            meta = self._meta_with_baseline_and_paths(run_id, str(top), str(bottom))
            html = self._korea_owner_email_html(run_id, with_bottom_cid=True)
            parts = resolve_keysuri_inline_jpeg_parts(html, meta)
        self.assertIsNotNone(parts)
        html_cids = set(re.findall(r"cid:([^\s\"'<>]+)", html))
        mime_cids = {row[1] for row in parts}
        missing = html_cids - mime_cids
        self.assertEqual(missing, set(), f"CIDs in HTML but not in MIME parts: {missing}")

    # T4: Bottom CID missing → customer email blocked with specific reason code
    def test_bottom_missing_blocks_customer_email_with_reason_code(self) -> None:
        import tempfile

        from keysuri_customer_delivery import (
            last_keysuri_delivery_result,
            send_keysuri_customer_final_email,
        )

        run_id = "20260619_120000_keysuri_korea_tech_cidtest4"
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "top.jpg"
            top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            # meta has top path but NO bottom path
            meta = {
                "run_id": run_id,
                "mode": PROGRAM_KOREA,
                "program_id": PROGRAM_KOREA,
                "service_full_run": True,
                "validation_result": "pass",
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
                "generated_image_path": str(top),
                "bottom_shot_asset_id": _KEYSURI_KOREA_BOTTOM_BASELINE_ASSET_ID,
                "bottom_shot_source": "fixed_105936_fallback",
                "bottom_shot_watermark_status": "applied",
                # No korea_bottom_shot_path / bottom_shot_image_path
            }
            html = self._korea_owner_email_html(run_id, with_bottom_cid=True)
            with patch("keysuri_customer_delivery.send_genie_email") as mock_send:
                result = send_keysuri_customer_final_email(html, meta)
        self.assertFalse(result)
        mock_send.assert_not_called()
        dr = last_keysuri_delivery_result()
        self.assertIsNotNone(dr)
        self.assertFalse(dr.sent)
        self.assertEqual(dr.reason, "korea_bottom_image_missing_for_customer_email")

    # T5: generated_v6_multi_ref Bottom path → customer email inline part
    def test_generated_v6_bottom_path_used_in_customer_inline_part(self) -> None:
        import tempfile

        from keysuri_customer_delivery import resolve_keysuri_inline_jpeg_parts
        from keysuri_service_full_run import keysuri_korea_bottom_service_email_cid_token

        run_id = "20260619_120000_keysuri_korea_tech_cidtest5"
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "top.jpg"
            bottom = Path(tmp) / "bottom_v6.jpg"
            top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            bottom.write_bytes(b"\xff\xd8\xff" + b"\x22" * 64)
            meta = self._meta_with_baseline_and_paths(
                run_id,
                str(top),
                str(bottom),
                bottom_source="generated_v6_multi_ref",
            )
            meta["bottom_shot_generated"] = True
            html = self._korea_owner_email_html(run_id, with_bottom_cid=True)
            parts = resolve_keysuri_inline_jpeg_parts(html, meta)
        self.assertIsNotNone(parts)
        self.assertEqual(len(parts), 2)
        bottom_part = next(
            (row for row in parts if row[1] == keysuri_korea_bottom_service_email_cid_token(run_id)),
            None,
        )
        self.assertIsNotNone(bottom_part, "Bottom inline part not found")
        self.assertEqual(Path(bottom_part[0]).resolve(), bottom.resolve())

    # T6: fixed_105936_fallback Bottom path → customer email inline part
    def test_fixed_105936_fallback_bottom_path_used_in_customer_inline_part(self) -> None:
        import tempfile

        from keysuri_customer_delivery import resolve_keysuri_inline_jpeg_parts
        from keysuri_service_full_run import keysuri_korea_bottom_service_email_cid_token

        run_id = "20260619_120000_keysuri_korea_tech_cidtest6"
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "top.jpg"
            bottom = Path(tmp) / "bottom_105936.jpg"
            top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            bottom.write_bytes(b"\xff\xd8\xff" + b"\x33" * 64)
            meta = self._meta_with_baseline_and_paths(
                run_id,
                str(top),
                str(bottom),
                bottom_source="fixed_105936_fallback",
            )
            html = self._korea_owner_email_html(run_id, with_bottom_cid=True)
            parts = resolve_keysuri_inline_jpeg_parts(html, meta)
        self.assertIsNotNone(parts)
        self.assertEqual(len(parts), 2)
        bottom_part = next(
            (row for row in parts if row[1] == keysuri_korea_bottom_service_email_cid_token(run_id)),
            None,
        )
        self.assertIsNotNone(bottom_part)
        self.assertEqual(Path(bottom_part[0]).resolve(), bottom.resolve())

    # T7: Owner and customer use the same artifact fields for image CIDs
    def test_owner_and_customer_cids_sourced_from_same_artifact_fields(self) -> None:
        import tempfile

        from keysuri_customer_delivery import resolve_keysuri_inline_jpeg_parts
        from keysuri_service_full_run import (
            keysuri_korea_bottom_service_email_cid_token,
            keysuri_korea_service_email_cid_token,
        )

        run_id = "20260619_120000_keysuri_korea_tech_cidtest7"
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "top.jpg"
            bottom = Path(tmp) / "bottom.jpg"
            top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            bottom.write_bytes(b"\xff\xd8\xff" + b"\x44" * 64)
            meta = self._meta_with_baseline_and_paths(run_id, str(top), str(bottom))
            # Simulate service_full_run artifact metadata with CID tracking fields
            meta["top_image_cid"] = keysuri_korea_service_email_cid_token(run_id)
            meta["bottom_image_cid"] = keysuri_korea_bottom_service_email_cid_token(run_id)
            meta["owner_email_image_cids"] = [
                keysuri_korea_service_email_cid_token(run_id),
                keysuri_korea_bottom_service_email_cid_token(run_id),
            ]
            meta["customer_email_image_cids"] = meta["owner_email_image_cids"]
            html = self._korea_owner_email_html(run_id, with_bottom_cid=True)
            parts = resolve_keysuri_inline_jpeg_parts(html, meta)
        self.assertIsNotNone(parts)
        customer_cids = {row[1] for row in parts}
        owner_cids = set(meta["owner_email_image_cids"])
        self.assertEqual(customer_cids, owner_cids)


class KeysuriKoreaGeneratedV6PersistenceTests(unittest.TestCase):
    """GCS restore + generated provenance enforcement for generated_v6_multi_ref artifacts."""

    def setUp(self) -> None:
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "customer@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"
        os.environ["SMTP_PASSWORD"] = "secret"

    def _generated_meta(
        self,
        run_id: str,
        top_path: str,
        bottom_path: str,
        *,
        gen_status: str = "generated",
        gcs_bucket: str = "",
        gcs_top_object: str = "",
        gcs_bottom_object: str = "",
    ) -> dict:
        meta: dict = {
            "run_id": run_id,
            "mode": PROGRAM_KOREA,
            "program_id": PROGRAM_KOREA,
            "service_full_run": True,
            "validation_result": "pass",
            "owner_review_status": "pending_review",
            "customer_delivery_status": "not_sent",
            "artifact_status": "emailed",
            "generated_image_path": top_path,
            "bottom_shot_source": "generated_v6_multi_ref",
            "bottom_shot_generated": True,
            "bottom_shot_generation_status": gen_status,
            "korea_bottom_shot_path": bottom_path,
            "bottom_shot_image_path": bottom_path,
            "bottom_shot_asset_id": f"keysuri_korea_bottom_generated_{run_id}",
            "korea_bottom_shot_asset_id": f"keysuri_korea_bottom_generated_{run_id}",
            "bottom_anchor_asset_id": _KEYSURI_KOREA_BOTTOM_BASELINE_ASSET_ID,
            "bottom_anchor_slot": 0,
            "secondary_reference_asset_id": "Asset01",
            "secondary_reference_slot": 1,
            "bottom_shot_watermark_status": "applied",
        }
        if gcs_bucket:
            meta["korea_generated_image_gcs_bucket"] = gcs_bucket
        if gcs_top_object:
            meta["korea_generated_top_gcs_object"] = gcs_top_object
        if gcs_bottom_object:
            meta["korea_generated_bottom_gcs_object"] = gcs_bottom_object
        return meta

    def _korea_owner_email_html(self, run_id: str) -> str:
        from keysuri_contract_preview_renderer import build_keysuri_korea_gmail_owner_email_html
        from keysuri_service_full_run import (
            keysuri_korea_bottom_service_email_cid_src,
            keysuri_korea_service_email_cid_src,
        )
        from tests.test_keysuri_contract_preview_renderer import build_korea_contract_fixture

        fixture = build_korea_contract_fixture()
        fixture["top_shot_image_src"] = keysuri_korea_service_email_cid_src(run_id)
        fixture["bottom_shot_image_src"] = keysuri_korea_bottom_service_email_cid_src(run_id)
        return build_keysuri_korea_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Korea Tech",
            admin_url=f"https://example.com/admin/runs/{run_id}",
            run_id=run_id,
        )

    # T_GCS1: local Top + Bottom exist → uses local paths, no GCS needed
    def test_generated_v6_local_files_used_directly(self) -> None:
        import tempfile

        from keysuri_customer_delivery import resolve_keysuri_inline_jpeg_parts
        from keysuri_service_full_run import keysuri_korea_bottom_service_email_cid_token

        run_id = "20260619_200000_keysuri_korea_tech_gcs001"
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "top.jpg"
            bottom = Path(tmp) / "bottom_v6.jpg"
            top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            bottom.write_bytes(b"\xff\xd8\xff" + b"\xaa" * 64)
            meta = self._generated_meta(run_id, str(top), str(bottom))
            html = self._korea_owner_email_html(run_id)
            parts = resolve_keysuri_inline_jpeg_parts(html, meta)
        self.assertIsNotNone(parts)
        self.assertEqual(len(parts), 2)
        used_top = Path(parts[0][0]).resolve()
        used_bottom = Path(parts[1][0]).resolve()
        self.assertEqual(used_top, top.resolve())
        self.assertEqual(used_bottom, bottom.resolve())
        self.assertIn(keysuri_korea_bottom_service_email_cid_token(run_id), [row[1] for row in parts])

    # T_GCS2: local Bottom deleted + GCS path → GCS restore → inline part uses restored path
    def test_generated_v6_bottom_restored_from_gcs(self) -> None:
        import tempfile

        from keysuri_customer_delivery import resolve_keysuri_inline_jpeg_parts
        from keysuri_service_full_run import keysuri_korea_bottom_service_email_cid_token

        run_id = "20260619_200000_keysuri_korea_tech_gcs002"
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "top.jpg"
            top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            # bottom NOT created — simulates missing local file
            bottom_placeholder = Path(tmp) / "bottom_v6_missing.jpg"
            meta = self._generated_meta(
                run_id,
                str(top),
                str(bottom_placeholder),
                gcs_bucket="test-bucket",
                gcs_top_object="admin_runs/run.images/korea_top.jpg",
                gcs_bottom_object="admin_runs/run.images/korea_bottom.jpg",
            )
            html = self._korea_owner_email_html(run_id)

            restored_files: list = []

            def _mock_download(bucket: str, obj: str, dest: Path) -> None:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"\xff\xd8\xff" + b"\xbb" * 64)
                restored_files.append(str(dest))

            parts = resolve_keysuri_inline_jpeg_parts(html, meta, download_fn=_mock_download)

        self.assertIsNotNone(parts, "Expected parts after GCS restore")
        self.assertEqual(len(parts), 2)
        cid_tokens = [row[1] for row in parts]
        self.assertIn(keysuri_korea_bottom_service_email_cid_token(run_id), cid_tokens)
        # Bottom part must use the restored file, not the missing original
        bottom_part = next(
            r for r in parts if r[1] == keysuri_korea_bottom_service_email_cid_token(run_id)
        )
        self.assertIn("restored_korea_bottom", Path(bottom_part[0]).name)

    # T_GCS3: local Bottom missing + no GCS path → blocked
    def test_generated_v6_bottom_missing_no_gcs_blocks(self) -> None:
        import tempfile

        from keysuri_customer_delivery import (
            KOREA_GENERATED_PERSISTENCE_MISSING,
            last_korea_inline_resolve_reason,
            resolve_keysuri_inline_jpeg_parts,
        )

        run_id = "20260619_200000_keysuri_korea_tech_gcs003"
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "top.jpg"
            top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            bottom_missing = Path(tmp) / "bottom_v6_missing.jpg"
            meta = self._generated_meta(run_id, str(top), str(bottom_missing))
            # No GCS fields in meta
            html = self._korea_owner_email_html(run_id)
            parts = resolve_keysuri_inline_jpeg_parts(html, meta)
        self.assertIsNone(parts)
        self.assertEqual(last_korea_inline_resolve_reason(), KOREA_GENERATED_PERSISTENCE_MISSING)

    # T_GCS4: local Top missing + no GCS path → blocked
    def test_generated_v6_top_missing_no_gcs_blocks(self) -> None:
        import tempfile

        from keysuri_customer_delivery import (
            KOREA_GENERATED_PERSISTENCE_MISSING,
            last_korea_inline_resolve_reason,
            resolve_keysuri_inline_jpeg_parts,
        )

        run_id = "20260619_200000_keysuri_korea_tech_gcs004"
        with tempfile.TemporaryDirectory() as tmp:
            top_missing = Path(tmp) / "top_missing.jpg"
            bottom = Path(tmp) / "bottom_v6.jpg"
            bottom.write_bytes(b"\xff\xd8\xff" + b"\xcc" * 64)
            meta = self._generated_meta(run_id, str(top_missing), str(bottom))
            # No GCS fields
            html = self._korea_owner_email_html(run_id)
            parts = resolve_keysuri_inline_jpeg_parts(html, meta)
        self.assertIsNone(parts)
        self.assertEqual(last_korea_inline_resolve_reason(), KOREA_GENERATED_PERSISTENCE_MISSING)

    # T_GCS5: bottom_shot_generation_status != "generated" → blocked
    def test_generated_v6_status_invalid_blocks(self) -> None:
        import tempfile

        from keysuri_customer_delivery import (
            KOREA_GENERATED_STATUS_INVALID,
            last_korea_inline_resolve_reason,
            resolve_keysuri_inline_jpeg_parts,
        )

        run_id = "20260619_200000_keysuri_korea_tech_gcs005"
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "top.jpg"
            bottom = Path(tmp) / "bottom_v6.jpg"
            top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            bottom.write_bytes(b"\xff\xd8\xff" + b"\xdd" * 64)
            meta = self._generated_meta(
                run_id, str(top), str(bottom), gen_status="failed"
            )
            html = self._korea_owner_email_html(run_id)
            parts = resolve_keysuri_inline_jpeg_parts(html, meta)
        self.assertIsNone(parts)
        self.assertEqual(last_korea_inline_resolve_reason(), KOREA_GENERATED_STATUS_INVALID)

    # T_GCS6: source/generated conflict → blocked
    def test_generated_v6_source_generated_conflict_blocks(self) -> None:
        import tempfile

        from keysuri_customer_delivery import (
            KOREA_GENERATED_SOURCE_INVALID,
            last_korea_inline_resolve_reason,
            resolve_keysuri_inline_jpeg_parts,
        )

        run_id = "20260619_200000_keysuri_korea_tech_gcs006"
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "top.jpg"
            bottom = Path(tmp) / "bottom.jpg"
            top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            bottom.write_bytes(b"\xff\xd8\xff" + b"\xee" * 64)
            # bottom_shot_generated=True but source is NOT generated_v6_multi_ref → conflict
            meta = self._generated_meta(run_id, str(top), str(bottom))
            meta["bottom_shot_source"] = "fixed_105936_fallback"  # mismatch with generated=True
            html = self._korea_owner_email_html(run_id)
            parts = resolve_keysuri_inline_jpeg_parts(html, meta)
        # fixed_105936_fallback with generated=True → goes through fixed path
        # The conflict check runs only in _resolve_korea_generated_inline_parts
        # which is called when _is_korea_generated_v6 returns True (source==generated_v6_multi_ref).
        # Here source is fixed → goes through fixed path, but generated=True is inconsistent.
        # We check: _validate_korea_generated_provenance catches it in send_keysuri path.
        # For resolve_keysuri_inline_jpeg_parts, fixed path is taken, bottom exists → parts returned.
        # The provenance conflict (generated=True, source=fixed) must be caught via
        # send_keysuri_customer_final_email when it checks _validate_korea_generated_provenance.
        # Direct resolve test: fixed path, local files exist → returns parts (not None).
        # So we verify conflict is detectable via validate function directly:
        from keysuri_customer_delivery import _validate_korea_generated_provenance

        conflict = _validate_korea_generated_provenance(meta)
        self.assertEqual(conflict, KOREA_GENERATED_SOURCE_INVALID)

    # T_GCS6b: generated_v6_multi_ref source but generated=False → blocked via delivery
    def test_generated_v6_fallback_conflict_blocks(self) -> None:
        import tempfile

        from keysuri_customer_delivery import (
            KOREA_GENERATED_FALLBACK_CONFLICT,
            last_korea_inline_resolve_reason,
            resolve_keysuri_inline_jpeg_parts,
        )

        run_id = "20260619_200000_keysuri_korea_tech_gcs006b"
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "top.jpg"
            bottom = Path(tmp) / "bottom.jpg"
            top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            bottom.write_bytes(b"\xff\xd8\xff" + b"\xff" * 64)
            meta = self._generated_meta(run_id, str(top), str(bottom))
            meta["bottom_shot_generated"] = False  # conflict: source=generated but generated=False
            html = self._korea_owner_email_html(run_id)
            parts = resolve_keysuri_inline_jpeg_parts(html, meta)
        self.assertIsNone(parts)
        self.assertEqual(last_korea_inline_resolve_reason(), KOREA_GENERATED_FALLBACK_CONFLICT)

    # T_GCS7: generated success artifact → fixed_105936 NOT silently used when files missing
    def test_generated_v6_no_silent_fixed_fallback(self) -> None:
        import tempfile

        from keysuri_customer_delivery import resolve_keysuri_inline_jpeg_parts

        run_id = "20260619_200000_keysuri_korea_tech_gcs007"
        repo = Path(__file__).resolve().parents[1]
        fixed_fallback = repo / "output" / "admin_runs" / "keysuri_service_assets" / "fixed_105936.jpg"
        with tempfile.TemporaryDirectory() as tmp:
            top_missing = Path(tmp) / "top_missing.jpg"
            bottom_missing = Path(tmp) / "bottom_missing.jpg"
            meta = self._generated_meta(run_id, str(top_missing), str(bottom_missing))
            html = self._korea_owner_email_html(run_id)
            parts = resolve_keysuri_inline_jpeg_parts(html, meta)
        self.assertIsNone(parts, "Must block when generated files are missing, not use fixed_105936")
        if parts is not None:
            for row in parts:
                self.assertNotIn("105936", Path(row[0]).name, "Must not silently use fixed_105936 image")

    # T_GCS8: GCS restore success → MIME inline part source is restored file
    def test_generated_v6_gcs_restore_inline_part_source_matches(self) -> None:
        import tempfile

        from keysuri_customer_delivery import resolve_keysuri_inline_jpeg_parts
        from keysuri_service_full_run import keysuri_korea_bottom_service_email_cid_token

        run_id = "20260619_200000_keysuri_korea_tech_gcs008"
        with tempfile.TemporaryDirectory() as tmp:
            top_missing = Path(tmp) / "top_missing.jpg"
            bottom_missing = Path(tmp) / "bottom_missing.jpg"
            meta = self._generated_meta(
                run_id,
                str(top_missing),
                str(bottom_missing),
                gcs_bucket="test-bucket",
                gcs_top_object="admin_runs/run.images/korea_top.jpg",
                gcs_bottom_object="admin_runs/run.images/korea_bottom.jpg",
            )
            html = self._korea_owner_email_html(run_id)
            restored_paths: list = []

            def _mock_download(bucket: str, obj: str, dest: Path) -> None:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"\xff\xd8\xff" + b"\x99" * 64)
                restored_paths.append(str(dest))

            parts = resolve_keysuri_inline_jpeg_parts(html, meta, download_fn=_mock_download)

        self.assertIsNotNone(parts)
        self.assertEqual(len(parts), 2)
        used_paths = {Path(row[0]).resolve() for row in parts}
        for rp in restored_paths:
            self.assertIn(Path(rp).resolve(), used_paths, "MIME part source must be the GCS-restored file")
        # Must NOT use the missing original paths
        self.assertNotIn(top_missing.resolve(), used_paths)
        self.assertNotIn(bottom_missing.resolve(), used_paths)

    # T_GCS9: GCS restore download raises exception → blocked
    def test_generated_v6_gcs_restore_failure_blocks(self) -> None:
        import tempfile

        from keysuri_customer_delivery import (
            KOREA_GENERATED_ARTIFACT_RESTORE_FAILED,
            last_korea_inline_resolve_reason,
            resolve_keysuri_inline_jpeg_parts,
        )

        run_id = "20260619_200000_keysuri_korea_tech_gcs009"
        with tempfile.TemporaryDirectory() as tmp:
            top_missing = Path(tmp) / "top_missing.jpg"
            bottom_missing = Path(tmp) / "bottom_missing.jpg"
            meta = self._generated_meta(
                run_id,
                str(top_missing),
                str(bottom_missing),
                gcs_bucket="test-bucket",
                gcs_top_object="admin_runs/run.images/korea_top.jpg",
                gcs_bottom_object="admin_runs/run.images/korea_bottom.jpg",
            )
            html = self._korea_owner_email_html(run_id)

            def _failing_download(bucket: str, obj: str, dest: Path) -> None:
                raise RuntimeError("simulated GCS download failure")

            parts = resolve_keysuri_inline_jpeg_parts(html, meta, download_fn=_failing_download)
        self.assertIsNone(parts)
        self.assertEqual(last_korea_inline_resolve_reason(), KOREA_GENERATED_ARTIFACT_RESTORE_FAILED)

    # T_GCS10: fixed fallback artifact uses existing fallback path (regression)
    def test_fixed_105936_fallback_still_uses_local_paths(self) -> None:
        import tempfile

        from keysuri_customer_delivery import resolve_keysuri_inline_jpeg_parts

        run_id = "20260619_200000_keysuri_korea_tech_gcs010"
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "top.jpg"
            bottom = Path(tmp) / "bottom_105936.jpg"
            top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            bottom.write_bytes(b"\xff\xd8\xff" + b"\x33" * 64)
            meta = {
                "run_id": run_id,
                "mode": PROGRAM_KOREA,
                "program_id": PROGRAM_KOREA,
                "service_full_run": True,
                "validation_result": "pass",
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
                "artifact_status": "emailed",
                "generated_image_path": str(top),
                "bottom_shot_source": "fixed_105936_fallback",
                "bottom_shot_generated": False,
                "bottom_shot_generation_status": "failed",
                "bottom_shot_asset_id": _KEYSURI_KOREA_BOTTOM_BASELINE_ASSET_ID,
                "korea_bottom_shot_path": str(bottom),
                "bottom_shot_image_path": str(bottom),
                "bottom_shot_watermark_status": "applied",
            }
            from keysuri_service_full_run import keysuri_korea_bottom_service_email_cid_token
            from tests.test_keysuri_contract_preview_renderer import build_korea_contract_fixture
            from keysuri_contract_preview_renderer import build_keysuri_korea_gmail_owner_email_html
            from keysuri_service_full_run import keysuri_korea_service_email_cid_src, keysuri_korea_bottom_service_email_cid_src
            fixture = build_korea_contract_fixture()
            fixture["top_shot_image_src"] = keysuri_korea_service_email_cid_src(run_id)
            fixture["bottom_shot_image_src"] = keysuri_korea_bottom_service_email_cid_src(run_id)
            html = build_keysuri_korea_gmail_owner_email_html(
                fixture,
                subject="[운영자 검토] Kee-Suri Korea Tech",
                admin_url=f"https://example.com/admin/runs/{run_id}",
                run_id=run_id,
            )
            parts = resolve_keysuri_inline_jpeg_parts(html, meta)
        self.assertIsNotNone(parts)
        self.assertEqual(len(parts), 2)
        self.assertEqual(Path(parts[0][0]).resolve(), top.resolve())
        self.assertEqual(Path(parts[1][0]).resolve(), bottom.resolve())

    # T_GCS11: send_keysuri_customer_final_email blocks with generated reason code
    def test_send_keysuri_blocks_with_generated_reason_when_files_missing(self) -> None:
        import tempfile

        from keysuri_customer_delivery import (
            KOREA_GENERATED_PERSISTENCE_MISSING,
            last_keysuri_delivery_result,
            send_keysuri_customer_final_email,
        )

        run_id = "20260619_200000_keysuri_korea_tech_gcs011"
        with tempfile.TemporaryDirectory() as tmp:
            top_missing = Path(tmp) / "top_missing.jpg"
            bottom_missing = Path(tmp) / "bottom_missing.jpg"
            meta = self._generated_meta(run_id, str(top_missing), str(bottom_missing))
            html = self._korea_owner_email_html(run_id)
            with patch("keysuri_customer_delivery.send_genie_email") as mock_send:
                result = send_keysuri_customer_final_email(html, meta)
        self.assertFalse(result)
        mock_send.assert_not_called()
        dr = last_keysuri_delivery_result()
        self.assertIsNotNone(dr)
        self.assertFalse(dr.sent)
        self.assertEqual(dr.reason, KOREA_GENERATED_PERSISTENCE_MISSING)
        # Must NOT be the fixed_105936 bottom missing reason
        self.assertNotEqual(dr.reason, "korea_bottom_image_missing_for_customer_email")


if __name__ == "__main__":
    unittest.main()
