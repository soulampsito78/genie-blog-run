"""Kee-Suri customer delivery tests (Global enabled; Korea blocked)."""
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


class KeysuriApproveRunGateTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "customer@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"
        os.environ["SMTP_PASSWORD"] = "secret"

    def test_keysuri_korea_can_approve_returns_not_ready(self) -> None:
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
        self.assertEqual(err, "keysuri_customer_delivery_not_ready")

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

    def test_keysuri_korea_approve_run_does_not_send(self) -> None:
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
            },
            email_html="<p>brief</p>",
        )
        with patch(
            "keysuri_customer_delivery.send_keysuri_customer_final_email",
            return_value=True,
        ) as mock_send:
            updated, status = approve_run(run_id)
        self.assertIsNone(updated)
        self.assertEqual(status, "keysuri_customer_delivery_not_ready")
        mock_send.assert_not_called()
        meta = load_run_artifact(run_id) or {}
        self.assertEqual(meta.get("owner_review_status"), "pending_review")
        self.assertEqual(meta.get("customer_delivery_status"), "not_sent")


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
        self.assertIn("Kee-Suri 고객 발송은 아직 안전 검증 전입니다", resp.text)


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
        self.assertIn("안전 검증 전", resp.text)
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
                    self.assertFalse(ok)
                    self.assertEqual(err, "keysuri_customer_delivery_not_ready")
                elif mode == PROGRAM_GLOBAL:
                    self.assertTrue(ok, f"expected approvable, got {err!r}")
                    self.assertEqual(err, "ok")
                else:
                    self.assertTrue(ok, f"expected approvable, got {err!r}")
                    self.assertEqual(err, "ok")
            resolved = resolve_program_id(mode)
            self.assertEqual(resolved, spec.program_id)


if __name__ == "__main__":
    unittest.main()
