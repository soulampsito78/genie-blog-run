"""Tests: Today_Geenee owner-review email admin/review link (Unit 6n-C)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from admin_store import load_run_email_html, save_run_artifact
from admin_urls import build_owner_review_admin_url, resolve_admin_public_base_url
from main import build_today_genie_email_html_for_cid_mime_send
from orchestrator import (
    OrchestrationResult,
    extract_email_html_for_artifact,
    persist_orchestrator_run_artifact,
    send_email_if_allowed,
)
from publishing_policy import PublishingDecision
from renderers import render_email_operational_box

_SAMPLE_RUN_ID = "20260611_150000_today_genie_aabbccdd"
_SAMPLE_BASE = "https://genie-blog-run-1055014091206.asia-northeast3.run.app"
_MINIMAL_DATA = {
    "title": "오늘의 지니",
    "summary": "국내 증시는 장전 변동성에 주목합니다.",
    "greeting": "안녕하세요.",
    "closing_message": "오늘도 신중한 접근이 필요합니다.",
    "key_watchpoints": [{"headline": "코스피", "detail": "외국인 수급을 확인합니다."}],
    "risk_check": [{"risk": "환율", "detail": "원/달러 변동성을 봅니다."}],
    "hashtags": ["#코스피", "#장전브리핑", "#지니"],
}
_OWNER_TO = "soulampsito@gmail.com,ey2133@naver.com"


def _pass_today_result(*, validation_result: str = "pass") -> OrchestrationResult:
    return OrchestrationResult(
        decision=PublishingDecision(
            send_email=validation_result == "pass",
            create_naver_draft=False,
            auto_publish=False,
            require_review=True,
            suppress_external=validation_result != "pass",
            send_customer_email=False,
        ),
        reason_summary="ok",
        response_status=200,
        mode="today_genie",
        response_data={
            "type": "today_genie",
            "validation_result": validation_result,
            "workflow_status": "validated" if validation_result == "pass" else "review_required",
            "data": {
                **_MINIMAL_DATA,
                "channel_drafts": {"email_subject": "오늘의 지니 장전 브리핑"},
            },
        },
    )


class TodayGeeneeAdminUrlTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_admin = os.environ.get("GENIE_ADMIN_PUBLIC_BASE_URL")
        self._prev_public = os.environ.get("GENIE_PUBLIC_BASE_URL")
        os.environ["GENIE_ADMIN_PUBLIC_BASE_URL"] = _SAMPLE_BASE

    def tearDown(self) -> None:
        for key, prev in (
            ("GENIE_ADMIN_PUBLIC_BASE_URL", self._prev_admin),
            ("GENIE_PUBLIC_BASE_URL", self._prev_public),
        ):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev

    def test_resolve_admin_public_base_url_prefers_admin_env(self) -> None:
        self.assertEqual(resolve_admin_public_base_url(), _SAMPLE_BASE)

    def test_build_owner_review_admin_url_includes_run_id_path(self) -> None:
        url = build_owner_review_admin_url(_SAMPLE_RUN_ID)
        self.assertEqual(url, f"{_SAMPLE_BASE}/admin/runs/{_SAMPLE_RUN_ID}")

    def test_build_owner_review_admin_url_missing_base_returns_none(self) -> None:
        os.environ.pop("GENIE_ADMIN_PUBLIC_BASE_URL", None)
        os.environ.pop("GENIE_PUBLIC_BASE_URL", None)
        self.assertIsNone(build_owner_review_admin_url(_SAMPLE_RUN_ID))


class TodayGeeneeAdminReviewLinkHtmlTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_admin = os.environ.get("GENIE_ADMIN_PUBLIC_BASE_URL")
        os.environ["GENIE_ADMIN_PUBLIC_BASE_URL"] = _SAMPLE_BASE

    def tearDown(self) -> None:
        if self._prev_admin is None:
            os.environ.pop("GENIE_ADMIN_PUBLIC_BASE_URL", None)
        else:
            os.environ["GENIE_ADMIN_PUBLIC_BASE_URL"] = self._prev_admin

    def test_email_html_includes_admin_button_text(self) -> None:
        html = build_today_genie_email_html_for_cid_mime_send(
            _MINIMAL_DATA,
            validation_result="pass",
            run_id=_SAMPLE_RUN_ID,
        )
        self.assertIn("운영자 검수 화면 열기", html)

    def test_email_html_includes_run_id(self) -> None:
        html = build_today_genie_email_html_for_cid_mime_send(
            _MINIMAL_DATA,
            validation_result="pass",
            run_id=_SAMPLE_RUN_ID,
        )
        self.assertIn(_SAMPLE_RUN_ID, html)

    def test_email_html_includes_admin_review_url(self) -> None:
        html = build_today_genie_email_html_for_cid_mime_send(
            _MINIMAL_DATA,
            validation_result="pass",
            run_id=_SAMPLE_RUN_ID,
        )
        expected = f"{_SAMPLE_BASE}/admin/runs/{_SAMPLE_RUN_ID}"
        self.assertIn(expected, html)

    def test_email_html_excludes_internal_job_token(self) -> None:
        os.environ["GENIE_INTERNAL_JOB_TOKEN"] = "super-secret-internal-token"
        try:
            html = build_today_genie_email_html_for_cid_mime_send(
                _MINIMAL_DATA,
                validation_result="pass",
                run_id=_SAMPLE_RUN_ID,
            )
            self.assertNotIn("super-secret-internal-token", html)
            self.assertNotIn("GENIE_INTERNAL_JOB_TOKEN", html)
        finally:
            os.environ.pop("GENIE_INTERNAL_JOB_TOKEN", None)

    def test_email_html_excludes_smtp_password(self) -> None:
        os.environ["SMTP_PASSWORD"] = "smtp-secret-password"
        try:
            html = build_today_genie_email_html_for_cid_mime_send(
                _MINIMAL_DATA,
                validation_result="pass",
                run_id=_SAMPLE_RUN_ID,
            )
            self.assertNotIn("smtp-secret-password", html)
            self.assertNotIn("SMTP_PASSWORD", html)
        finally:
            os.environ.pop("SMTP_PASSWORD", None)

    def test_operational_box_renders_admin_link_block(self) -> None:
        admin_url = f"{_SAMPLE_BASE}/admin/runs/{_SAMPLE_RUN_ID}"
        html = render_email_operational_box(
            {
                "status_label": "자동 검증 통과",
                "email_delivery_label": "운영자 검수 메일 발송 전",
                "run_id": _SAMPLE_RUN_ID,
                "admin_review_url": admin_url,
            }
        )
        self.assertIn("genie-owner-review-admin-link", html)
        self.assertIn("운영자 검수 화면 열기", html)
        self.assertIn(admin_url, html)


class TodayGeeneeAdminReviewSendPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_backup = {
            k: os.environ.get(k)
            for k in (
                "GENIE_OWNER_REVIEW_SEND",
                "EMAIL_TO",
                "GENIE_ADMIN_PUBLIC_BASE_URL",
                "GENIE_PUBLIC_BASE_URL",
                "GENIE_ADMIN_REISSUE",
            )
        }
        os.environ["GENIE_OWNER_REVIEW_SEND"] = "1"
        os.environ["EMAIL_TO"] = _OWNER_TO
        os.environ["GENIE_ADMIN_PUBLIC_BASE_URL"] = _SAMPLE_BASE
        os.environ.pop("GENIE_ADMIN_REISSUE", None)

    def tearDown(self) -> None:
        for key, prev in self._env_backup.items():
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev

    def test_block_validation_does_not_send_email(self) -> None:
        result = _pass_today_result(validation_result="block")
        with patch("orchestrator.send_genie_email") as mock_send:
            sent = send_email_if_allowed(result, run_id=_SAMPLE_RUN_ID)
        self.assertFalse(sent)
        mock_send.assert_not_called()

    def test_pass_without_run_id_does_not_send_email(self) -> None:
        result = _pass_today_result()
        with patch("orchestrator.send_genie_email") as mock_send:
            sent = send_email_if_allowed(result, run_id=None)
        self.assertFalse(sent)
        mock_send.assert_not_called()

    def test_pass_missing_admin_url_does_not_send_email(self) -> None:
        os.environ.pop("GENIE_ADMIN_PUBLIC_BASE_URL", None)
        os.environ.pop("GENIE_PUBLIC_BASE_URL", None)
        result = _pass_today_result()
        with patch("orchestrator.send_genie_email") as mock_send:
            sent = send_email_if_allowed(result, run_id=_SAMPLE_RUN_ID)
        self.assertFalse(sent)
        mock_send.assert_not_called()

    @patch("orchestrator.send_genie_email")
    def test_pass_with_owner_gate_sends_when_admin_link_present(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        repo = Path(__file__).resolve().parent.parent
        top = repo / "static" / "email" / "GENIE_EMAIL_today_genie_top_latest.jpg"
        bottom = repo / "static" / "email" / "GENIE_EMAIL_today_genie_bottom_latest.jpg"
        if not top.is_file() or not bottom.is_file():
            self.skipTest("today_genie email image assets missing in repo")
        from today_genie_orchestrator_images import TodayGenieOrchestratorImageResult

        image_result = TodayGenieOrchestratorImageResult(
            inline_parts=[
                (str(top), "cid:top", "GENIE_EMAIL_today_genie_top.jpg"),
                (str(bottom), "cid:bottom", "GENIE_EMAIL_today_genie_bottom.jpg"),
            ],
            fallback_used=True,
            image_source="static_fallback",
        )
        result = _pass_today_result()
        sent = send_email_if_allowed(
            result,
            run_id=_SAMPLE_RUN_ID,
            today_image_result=image_result,
        )
        self.assertTrue(sent)
        mock_send.assert_called_once()
        outbound_html = mock_send.call_args.args[0]
        self.assertIn("운영자 검수 화면 열기", outbound_html)
        self.assertIn(_SAMPLE_RUN_ID, outbound_html)
        self.assertIn(f"/admin/runs/{_SAMPLE_RUN_ID}", outbound_html)

    def test_pass_persist_creates_email_html_artifact(self) -> None:
        result = _pass_today_result()
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp) / "admin_runs"
            runs_dir.mkdir(parents=True)
            with patch("admin_store.admin_runs_dir", return_value=runs_dir):
                run_id = persist_orchestrator_run_artifact(
                    result,
                    email_sent=False,
                    run_id=_SAMPLE_RUN_ID,
                )
                self.assertEqual(run_id, _SAMPLE_RUN_ID)
                email_html = load_run_email_html(run_id)
                self.assertIsNotNone(email_html)
                assert email_html is not None
                self.assertIn("운영자 검수 화면 열기", email_html)
                self.assertIn(_SAMPLE_RUN_ID, email_html)

    def test_extract_email_html_for_artifact_includes_admin_link(self) -> None:
        result = _pass_today_result()
        html = extract_email_html_for_artifact(result, run_id=_SAMPLE_RUN_ID)
        self.assertIn("운영자 검수 화면 열기", html)
        self.assertIn(_SAMPLE_RUN_ID, html)


class TodayGeeneeKeeSuriUnchangedSmokeTests(unittest.TestCase):
    """Kee-Suri path must remain untouched by Today_Geenee admin-link patch."""

    @patch("internal_jobs.create_keysuri_owner_review_job")
    def test_keysuri_internal_job_route_still_smoke_only(self, mock_job: MagicMock) -> None:
        from keysuri_live_source_smoke import PROGRAM_GLOBAL

        mock_job.return_value = {
            "ok": True,
            "program_id": PROGRAM_GLOBAL,
            "dry_run": True,
            "trigger_source": "scheduled_owner_review",
            "would_run": True,
        }
        from fastapi.testclient import TestClient
        from main import app

        client = TestClient(app)
        with patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "test-token"}, clear=False):
            resp = client.post(
                "/internal/jobs/create-keysuri-owner-review",
                headers={"X-Genie-Internal-Job-Token": "test-token"},
                json={"program_id": PROGRAM_GLOBAL, "dry_run": True},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body.get("ok"))
        self.assertNotIn("admin_review_url", body)
        mock_job.assert_called_once()


if __name__ == "__main__":
    unittest.main()
