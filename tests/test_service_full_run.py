"""Tests: service-level full runs with generated images (Unit 6p)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from admin_store import load_run_artifact, load_run_email_html
from fastapi.testclient import TestClient
from internal_jobs import create_keysuri_owner_review_job
from keysuri_live_source_smoke import PROGRAM_GLOBAL, PROGRAM_KOREA, LiveSourceSmokeResult
from main import app
from orchestrator import OrchestrationResult
from publishing_policy import PublishingDecision
from service_full_run_contract import (
    IMAGE_SOURCE_GENERATED,
    IMAGE_SOURCE_REGISTRY,
    IMAGE_SOURCE_STATIC,
    ServiceImageOutcome,
    is_smoke_only_image_source,
    service_image_passes,
)
from service_image_api import invoke_vertex_image_generation
from today_genie_service_full_run import (
    generate_today_genie_service_images,
    run_today_genie_service_full_run,
)

_TOKEN = "unit-test-internal-token"
_MINIMAL_TODAY_DATA = {
    "title": "오늘의 지니",
    "summary": "국내 증시는 장전 변동성에 주목합니다.",
    "greeting": "안녕하세요.",
    "closing_message": "오늘도 신중한 접근이 필요합니다.",
    "image_briefing_mood_state": "mixed_cautious",
    "image_mood_basis": "신중한 장전 분위기",
    "image_prompt_studio": "Professional Korean financial anchor in studio with market screens.",
    "image_prompt_outdoor": "Same anchor outdoors on Seoul morning street, smart casual.",
    "key_watchpoints": [{"headline": "코스피", "detail": "외국인 수급을 확인합니다."}],
    "risk_check": [{"risk": "환율", "detail": "원/달러 변동성을 봅니다."}],
    "hashtags": ["#코스피"],
    "channel_drafts": {"email_subject": "오늘의 지니 장전 브리핑"},
}
_RUNTIME_INPUT = {"target_date": "2026-06-08", "top_market_news": [{"headline": "OpenAI IPO filing"}]}


def _mock_generate(_path: Path) -> Path:
    _path.parent.mkdir(parents=True, exist_ok=True)
    _path.write_bytes(b"\xff\xd8\xff" + b"\x00" * 128)
    return _path


def _pass_today_orchestration_result() -> OrchestrationResult:
    return OrchestrationResult(
        decision=PublishingDecision(
            send_email=True,
            create_naver_draft=False,
            auto_publish=False,
            require_review=True,
            suppress_external=False,
            send_customer_email=False,
        ),
        reason_summary="ok",
        response_status=200,
        mode="today_genie",
        response_data={
            "validation_result": "pass",
            "workflow_status": "validated",
            "runtime_input": _RUNTIME_INPUT,
            "data": _MINIMAL_TODAY_DATA,
        },
    )


def _fake_keysuri_smoke(program_id: str, **_kwargs) -> LiveSourceSmokeResult:
    return LiveSourceSmokeResult(
        ok=True,
        program_id=program_id,
        source_pack_path=str(Path(__file__).resolve().parents[1] / "output" / "keysuri_preview" / "pack.json"),
        html_path="/tmp/smoke.html",
        fetched_item_count=5,
        feed_urls_used=["https://example.com/feed"],
        sample_marker_pass=True,
        called_gemini=True,
        use_gemini=True,
        contract_preview=True,
        parse_status="parsed_valid",
        raw_response_path="/tmp/raw.txt",
        preview_overall_status="PASS_OWNER_REVIEW_READY",
        validation_status="PASS",
        side_effects={"called_gemini": True, "called_image_api": False},
    )


class ServiceFullRunContractTests(unittest.TestCase):
    def test_generated_image_source_passes(self) -> None:
        outcome = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path="output/images/x.jpg",
        )
        self.assertTrue(service_image_passes(outcome))

    def test_registry_image_cannot_pass_service_full_run(self) -> None:
        self.assertTrue(is_smoke_only_image_source(IMAGE_SOURCE_REGISTRY))
        self.assertTrue(is_smoke_only_image_source(IMAGE_SOURCE_STATIC))
        outcome = ServiceImageOutcome(
            called_image_api=False,
            image_source=IMAGE_SOURCE_REGISTRY,
            generated_image_path="static/x.jpg",
        )
        self.assertFalse(service_image_passes(outcome))

    def test_called_image_api_false_when_wrapper_not_invoked(self) -> None:
        outcome = invoke_vertex_image_generation(
            prompt="",
            output_path=Path("/tmp/empty.jpg"),
        )
        self.assertFalse(outcome.called_image_api)


class TodayGenieServiceFullRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {
                "GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com",
                "GENIE_OWNER_REVIEW_SEND": "1",
                "EMAIL_TO": "soulampsito@gmail.com",
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()

    def test_service_images_call_image_api_wrapper(self) -> None:
        with patch("today_genie_service_full_run.invoke_vertex_image_generation") as mock_invoke:
            mock_invoke.side_effect = [
                ServiceImageOutcome(
                    called_image_api=True,
                    image_generation_status="generated",
                    image_source=IMAGE_SOURCE_GENERATED,
                    generated_image_path="output/images/t.jpg",
                ),
                ServiceImageOutcome(
                    called_image_api=True,
                    image_generation_status="generated",
                    image_source=IMAGE_SOURCE_GENERATED,
                    generated_image_path="output/images/b.jpg",
                ),
            ]
            bundle = generate_today_genie_service_images(
                _MINIMAL_TODAY_DATA,
                _RUNTIME_INPUT,
                run_id="20260611_150000_today_genie_aabbccdd",
            )
        self.assertEqual(mock_invoke.call_count, 2)
        self.assertTrue(bundle.ok)
        self.assertTrue(bundle.called_image_api)

    def test_static_image_bundle_cannot_pass_service_full_run(self) -> None:
        bundle = generate_today_genie_service_images(
            {"image_prompt_studio": "", "image_prompt_outdoor": ""},
            {},
            run_id="20260611_150000_today_genie_aabbccdd",
        )
        self.assertFalse(bundle.ok)
        self.assertFalse(bundle.called_image_api)

    @patch("today_genie_service_full_run.save_run_artifact")
    @patch("today_genie_service_full_run.run_genie_job")
    def test_service_full_run_persists_generated_image_and_email_html(
        self,
        mock_job: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        mock_job.return_value = _pass_today_orchestration_result()
        with patch(
            "today_genie_service_full_run.generate_today_genie_service_images"
        ) as mock_images:
            mock_images.return_value = type(
                "B",
                (),
                {
                    "ok": True,
                    "called_image_api": True,
                    "top": ServiceImageOutcome(
                        called_image_api=True,
                        image_generation_status="generated",
                        image_source=IMAGE_SOURCE_GENERATED,
                        generated_image_path="output/images/t.jpg",
                    ),
                    "bottom": ServiceImageOutcome(
                        called_image_api=True,
                        image_generation_status="generated",
                        image_source=IMAGE_SOURCE_GENERATED,
                        generated_image_path="output/images/b.jpg",
                    ),
                    "primary_generated_image_path": "output/images/t.jpg",
                },
            )()
            with patch("today_genie_service_full_run._inline_parts_from_bundle") as mock_inline:
                repo = Path(__file__).resolve().parents[1]
                top = repo / "output" / "images" / "t.jpg"
                bot = repo / "output" / "images" / "b.jpg"
                top.parent.mkdir(parents=True, exist_ok=True)
                top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
                bot.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
                mock_inline.return_value = [(str(top), "cid.top", "t.jpg"), (str(bot), "cid.bot", "b.jpg")]
                payload = run_today_genie_service_full_run(send_fn=MagicMock(return_value=True))
        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("called_image_api"))
        self.assertEqual(payload.get("image_source"), IMAGE_SOURCE_GENERATED)
        mock_save.assert_called_once()
        email_html = mock_save.call_args.kwargs.get("email_html") or mock_save.call_args.args[1]
        self.assertIn("운영자 검수 화면 열기", email_html)
        self.assertIn(payload["run_id"], email_html)

    @patch("today_genie_service_full_run.save_run_artifact")
    @patch("today_genie_service_full_run.run_genie_job")
    def test_image_generation_failure_prevents_email(
        self,
        mock_job: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        mock_job.return_value = _pass_today_orchestration_result()
        with patch("today_genie_service_full_run.generate_today_genie_service_images") as mock_images:
            mock_images.return_value = type(
                "B",
                (),
                {
                    "ok": False,
                    "called_image_api": True,
                    "top": ServiceImageOutcome(called_image_api=True, image_generation_status="failed"),
                    "bottom": ServiceImageOutcome(called_image_api=True, image_generation_status="failed"),
                    "primary_generated_image_path": None,
                },
            )()
            payload = run_today_genie_service_full_run(send_fn=MagicMock(return_value=True))
        self.assertFalse(payload.get("ok"))
        self.assertFalse(payload.get("email_sent"))
        mock_save.assert_called_once()

    @patch("today_genie_service_full_run.run_genie_job")
    def test_validation_block_prevents_email(self, mock_job: MagicMock) -> None:
        blocked = _pass_today_orchestration_result()
        blocked.response_data = {"validation_result": "block", "workflow_status": "review_required", "data": {}}
        blocked.decision = PublishingDecision(
            send_email=False,
            create_naver_draft=False,
            auto_publish=False,
            require_review=True,
            suppress_external=True,
            send_customer_email=False,
        )
        mock_job.return_value = blocked
        payload = run_today_genie_service_full_run()
        self.assertFalse(payload.get("ok"))
        self.assertFalse(payload.get("email_sent"))


class KeysuriServiceFullRunTests(unittest.TestCase):
    def test_smoke_contract_preview_job_not_service_full_run(self) -> None:
        with patch("internal_jobs.run_keysuri_live_source_smoke") as mock_smoke:
            mock_smoke.return_value = LiveSourceSmokeResult(
                ok=True,
                program_id=PROGRAM_GLOBAL,
                source_pack_path="/tmp/p.json",
                html_path="/tmp/h.html",
                fetched_item_count=5,
                feed_urls_used=[],
                sample_marker_pass=True,
                side_effects={"called_image_api": False},
            )
            payload = create_keysuri_owner_review_job(PROGRAM_GLOBAL, dry_run=False, service_full_run=False)
        self.assertFalse(payload.get("service_full_run", False))
        self.assertFalse(payload.get("side_effects", {}).get("called_image_api"))

    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.save_run_artifact")
    @patch("keysuri_service_full_run.send_genie_email")
    @patch("keysuri_service_full_run._render_service_html")
    @patch("keysuri_service_full_run._reload_generated_briefing")
    @patch("keysuri_service_full_run._generate_keysuri_service_image")
    def test_global_service_full_run_calls_gemini_and_image_api(
        self,
        mock_image: MagicMock,
        mock_reload: MagicMock,
        mock_render: MagicMock,
        mock_send: MagicMock,
        mock_save: MagicMock,
        mock_prompt_input: MagicMock,
    ) -> None:
        from keysuri_service_full_run import run_keysuri_service_full_run

        repo = Path(__file__).resolve().parents[1]
        pack_path = repo / "output" / "keysuri_preview" / "test_pack_service.json"
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(json.dumps({"sources": [], "program_id": PROGRAM_GLOBAL}), encoding="utf-8")
        raw_path = repo / "output" / "keysuri_preview" / "raw_service.txt"
        raw_path.write_text("{}", encoding="utf-8")

        def _smoke(**_kwargs):
            return LiveSourceSmokeResult(
                ok=True,
                program_id=PROGRAM_GLOBAL,
                source_pack_path=str(pack_path),
                html_path=str(repo / "output" / "keysuri_preview" / "h.html"),
                fetched_item_count=5,
                feed_urls_used=["https://x"],
                sample_marker_pass=True,
                called_gemini=True,
                use_gemini=True,
                contract_preview=True,
                raw_response_path=str(raw_path),
                preview_overall_status="PASS_OWNER_REVIEW_READY",
                validation_status="PASS",
                side_effects={"called_gemini": True, "called_image_api": False},
            )

        mock_image.return_value = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path="output/images/keysuri_global_canary.jpg",
        )
        mock_prompt_input.return_value = {"program_id": PROGRAM_GLOBAL, "prompt_status": "ready_for_generation"}
        mock_reload.return_value = {"title": "t", "summary": "s", "top_5_news": []}
        mock_render.return_value = ("<html>body</html>", "output/admin_runs/keysuri_service/x.html")
        mock_send.return_value = True

        with patch.dict(os.environ, {"GENIE_OWNER_REVIEW_SEND": "1", "GENIE_ADMIN_PUBLIC_BASE_URL": "https://ex.com"}, clear=False):
            payload = run_keysuri_service_full_run(
                PROGRAM_GLOBAL,
                smoke_runner=_smoke,
                send_fn=mock_send,
            )
        self.assertEqual(payload.get("program_id"), PROGRAM_GLOBAL)
        self.assertTrue(payload.get("called_gemini"))
        self.assertTrue(payload.get("called_image_api"))
        self.assertEqual(payload.get("image_source"), IMAGE_SOURCE_GENERATED)
        self.assertTrue(payload.get("email_sent"))
        mock_save.assert_called_once()

    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.save_run_artifact")
    @patch("keysuri_service_full_run._generate_keysuri_service_image")
    def test_korea_program_id_not_cross_contaminated(
        self,
        mock_image: MagicMock,
        mock_save: MagicMock,
        mock_prompt_input: MagicMock,
    ) -> None:
        from keysuri_service_full_run import run_keysuri_service_full_run

        repo = Path(__file__).resolve().parents[1]
        pack_path = repo / "output" / "keysuri_preview" / "test_pack_korea.json"
        pack_path.write_text(json.dumps({"sources": [], "program_id": PROGRAM_KOREA}), encoding="utf-8")

        def _smoke(program_id: str, **_kwargs):
            return LiveSourceSmokeResult(
                ok=True,
                program_id=program_id,
                source_pack_path=str(pack_path),
                html_path="/tmp/k.html",
                fetched_item_count=5,
                feed_urls_used=[],
                sample_marker_pass=True,
                called_gemini=True,
                preview_overall_status="PASS_OWNER_REVIEW_READY",
                raw_response_path=str(repo / "output" / "keysuri_preview" / "raw_korea.txt"),
                side_effects={"called_gemini": True},
            )

        mock_image.return_value = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path="output/images/keysuri_korea_canary.jpg",
        )
        mock_prompt_input.return_value = {"program_id": PROGRAM_KOREA, "prompt_status": "ready_for_generation"}
        with patch("keysuri_service_full_run._reload_generated_briefing", return_value={"title": "k"}):
            with patch("keysuri_service_full_run._render_service_html", return_value=("<p>k</p>", "out/k.html")):
                with patch("keysuri_service_full_run.send_genie_email", return_value=True):
                    with patch.dict(os.environ, {"GENIE_OWNER_REVIEW_SEND": "1", "GENIE_ADMIN_PUBLIC_BASE_URL": "https://ex.com"}, clear=False):
                        payload = run_keysuri_service_full_run(PROGRAM_KOREA, smoke_runner=_smoke, send_fn=MagicMock(return_value=True))
        self.assertEqual(payload.get("program_id"), PROGRAM_KOREA)
        self.assertNotEqual(payload.get("program_id"), PROGRAM_GLOBAL)


class ServiceFullRunInternalEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self._env = patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": _TOKEN}, clear=False)
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()

    @patch("today_genie_service_full_run.run_today_genie_service_full_run")
    def test_today_endpoint_service_full_run_flag(self, mock_run: MagicMock) -> None:
        mock_run.return_value = {
            "ok": True,
            "service_full_run": True,
            "run_id": "20260611_150000_today_genie_aabbccdd",
            "called_image_api": True,
            "image_source": "generated",
            "email_sent": True,
        }
        resp = self.client.post(
            "/internal/jobs/create-owner-review",
            headers={"X-Genie-Internal-Job-Token": _TOKEN},
            json={"service_full_run": True, "send_owner_email": True},
        )
        self.assertEqual(resp.status_code, 200)
        mock_run.assert_called_once()

    @patch("keysuri_service_full_run.run_keysuri_service_full_run")
    def test_keysuri_endpoint_service_full_run_flag(self, mock_run: MagicMock) -> None:
        mock_run.return_value = {
            "ok": True,
            "service_full_run": True,
            "program_id": PROGRAM_GLOBAL,
            "called_image_api": True,
            "email_sent": True,
        }
        resp = self.client.post(
            "/internal/jobs/create-keysuri-owner-review",
            headers={"X-Genie-Internal-Job-Token": _TOKEN},
            json={
                "program_id": PROGRAM_GLOBAL,
                "service_full_run": True,
                "send_owner_email": True,
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body.get("service_full_run"))


if __name__ == "__main__":
    unittest.main()
