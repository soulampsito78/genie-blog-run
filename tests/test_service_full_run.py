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


def _minimal_contract_preview_document(
    *,
    body_inner: str | None = None,
    theme_class: str = "premium-briefing theme-global",
) -> str:
    inner = body_inner or (
        '<header class="premium-hero" id="premium-hero">'
        '<h1 class="hero-title">키수리 글로벌 테크 브리핑</h1>'
        '<img src="cid:keysuri_topshot_global_20260611" class="top-shot-hero"/>'
        "</header>"
    )
    return (
        '<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"/>'
        "<style>.premium-briefing.theme-global{--g-accent:#3f7ecb;}</style>"
        f"</head><body class=\"{theme_class}\"><div class=\"briefing-shell\">{inner}</div></body></html>"
    )
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


def _mock_keysuri_watermark(source: Path, target: Path) -> Path:
    src = Path(source)
    dst = Path(target)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes() + b"MirAI:ON")
    return dst.resolve()


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

    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
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
        mock_watermark: MagicMock,
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
        img_file = repo / "output" / "images" / "keysuri_global_canary.jpg"
        img_file.parent.mkdir(parents=True, exist_ok=True)
        img_file.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
        mock_watermark.side_effect = _mock_keysuri_watermark
        mock_prompt_input.return_value = {"program_id": PROGRAM_GLOBAL, "prompt_status": "ready_for_generation"}
        mock_reload.return_value = {"title": "t", "summary": "s", "top_5_news": []}

        def _render_side_effect(*_args, **_kwargs):
            mode = _kwargs.get("image_mode", "preview")
            if mode == "email":
                return (
                    _minimal_contract_preview_document(),
                    "output/admin_runs/keysuri_service/x.html",
                )
            return (_minimal_contract_preview_document(), "output/admin_runs/keysuri_service/x.html")

        mock_render.side_effect = _render_side_effect
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
        mock_send.assert_called_once()
        send_kwargs = mock_send.call_args.kwargs
        self.assertIn("inline_jpeg_parts", send_kwargs)
        inline = send_kwargs.get("inline_jpeg_parts") or []
        self.assertTrue(inline)
        self.assertIn("_mirai_on_watermarked", Path(inline[0][0]).name)
        email_html = mock_save.call_args.kwargs.get("email_html") or mock_save.call_args.args[1]
        self.assertIn("운영자 검수 화면 열기", email_html)
        self.assertIn(payload["run_id"], email_html)
        self.assertIn("cid:", email_html)
        saved_meta = mock_save.call_args.args[0]
        self.assertFalse(saved_meta.get("artifact_storage_durable"))
        self.assertIn("/admin/runs/", str(saved_meta.get("owner_review_url") or ""))
        self.assertEqual(saved_meta.get("top_shot_watermark_status"), "applied")
        self.assertEqual(saved_meta.get("generated_image_path_raw"), "output/images/keysuri_global_canary.jpg")
        self.assertIn("_mirai_on_watermarked", str(saved_meta.get("generated_image_path")))

    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.save_run_artifact")
    @patch("keysuri_service_full_run._generate_keysuri_service_image")
    def test_korea_program_id_not_cross_contaminated(
        self,
        mock_image: MagicMock,
        mock_save: MagicMock,
        mock_prompt_input: MagicMock,
        mock_watermark: MagicMock,
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
        img_file = repo / "output" / "images" / "keysuri_korea_canary.jpg"
        img_file.parent.mkdir(parents=True, exist_ok=True)
        img_file.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
        mock_watermark.side_effect = _mock_keysuri_watermark
        mock_prompt_input.return_value = {"program_id": PROGRAM_KOREA, "prompt_status": "ready_for_generation"}
        with patch("keysuri_service_full_run._reload_generated_briefing", return_value={"title": "k"}):
            with patch("keysuri_service_full_run._render_service_html", return_value=(_minimal_contract_preview_document(), "out/k.html")):
                with patch("keysuri_service_full_run.send_genie_email", return_value=True):
                    with patch.dict(os.environ, {
                        "GENIE_OWNER_REVIEW_SEND": "1",
                        "GENIE_ADMIN_PUBLIC_BASE_URL": "https://ex.com",
                        "KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED": "off",
                    }, clear=False):
                        payload = run_keysuri_service_full_run(PROGRAM_KOREA, smoke_runner=_smoke, send_fn=MagicMock(return_value=True))
        self.assertEqual(payload.get("program_id"), PROGRAM_KOREA)
        self.assertNotEqual(payload.get("program_id"), PROGRAM_GLOBAL)


class KeysuriGlobalServiceFullRunEmailTests(unittest.TestCase):
    """Kee-Suri Global service_full_run owner-review email uses CID (Gmail-safe)."""

    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {
                "GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com",
                "GENIE_OWNER_REVIEW_SEND": "1",
                "GENIE_INTERNAL_JOB_TOKEN": "not-used",
            },
            clear=False,
        )
        self._env.start()
        self._token = "unit-test-internal-token"

    def tearDown(self) -> None:
        self._env.stop()

    def _global_smoke(self, pack_path: Path, raw_path: Path) -> LiveSourceSmokeResult:
        return LiveSourceSmokeResult(
            ok=True,
            program_id=PROGRAM_GLOBAL,
            source_pack_path=str(pack_path),
            html_path=str(pack_path.parent / "h.html"),
            fetched_item_count=5,
            feed_urls_used=["https://example.com/feed"],
            sample_marker_pass=True,
            called_gemini=True,
            use_gemini=True,
            contract_preview=False,
            parse_status="parsed_valid",
            raw_response_path=str(raw_path),
            preview_overall_status="PASS_OWNER_REVIEW_READY",
            validation_status="PASS",
            generated_briefing={"title": "글로벌 브리핑", "summary": "요약", "top_5_news": []},
            side_effects={"called_gemini": True, "called_image_api": False},
        )

    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.save_run_artifact")
    @patch("keysuri_service_full_run.send_genie_email")
    @patch("keysuri_service_full_run._generate_keysuri_service_image")
    @patch("keysuri_service_full_run.generate_run_id")
    def test_global_email_uses_cid_not_local_paths(
        self,
        mock_run_id: MagicMock,
        mock_image: MagicMock,
        mock_send: MagicMock,
        mock_save: MagicMock,
        mock_prompt_input: MagicMock,
        mock_watermark: MagicMock,
    ) -> None:
        from keysuri_service_full_run import (
            keysuri_global_service_email_cid_src,
            run_keysuri_service_full_run,
        )

        repo = Path(__file__).resolve().parents[1]
        run_id = "20260611_150810_keysuri_global_tech_5cf81e6a"
        mock_run_id.return_value = run_id
        pack_path = repo / "output" / "keysuri_preview" / "test_pack_global_cid.json"
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(json.dumps({"sources": [], "program_id": PROGRAM_GLOBAL}), encoding="utf-8")
        raw_path = repo / "output" / "keysuri_preview" / "raw_global_cid.txt"
        raw_path.write_text("{}", encoding="utf-8")

        image_rel = repo / "output" / "images" / "keysuri_global_service_test.jpg"
        image_rel.parent.mkdir(parents=True, exist_ok=True)
        image_rel.write_bytes(b"\xff\xd8\xff" + b"\x00" * 128)
        mock_watermark.side_effect = _mock_keysuri_watermark

        mock_image.return_value = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path=str(image_rel.relative_to(repo)),
        )
        mock_prompt_input.return_value = {
            "program_id": PROGRAM_GLOBAL,
            "prompt_status": "ready_for_generation",
            "source_pack": {"sources": []},
        }
        mock_send.return_value = True

        payload = run_keysuri_service_full_run(
            PROGRAM_GLOBAL,
            smoke_runner=lambda **_kw: self._global_smoke(pack_path, raw_path),
            send_fn=mock_send,
        )

        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("service_full_run"))
        self.assertEqual(payload.get("program_id"), PROGRAM_GLOBAL)
        self.assertTrue(payload.get("called_image_api"))
        self.assertEqual(payload.get("image_source"), IMAGE_SOURCE_GENERATED)
        self.assertTrue(payload.get("email_sent"))
        self.assertFalse(payload.get("artifact_storage_durable"))
        self.assertIn(run_id, str(payload.get("owner_review_url") or ""))
        self.assertIn("/admin/runs/", str(payload.get("owner_review_url") or ""))
        self.assertNotIn(self._token, str(payload.get("owner_review_url") or ""))

        mock_send.assert_called_once()
        send_kwargs = mock_send.call_args.kwargs
        inline = send_kwargs.get("inline_jpeg_parts") or []
        self.assertEqual(len(inline), 1)
        fs_path, cid_token, _fname = inline[0]
        self.assertTrue(Path(fs_path).is_file())
        self.assertIn("_mirai_on_watermarked", Path(fs_path).name)
        self.assertEqual(cid_token, keysuri_global_service_email_cid_src(run_id).replace("cid:", ""))

        email_html = mock_send.call_args.args[0]
        self.assertIn(keysuri_global_service_email_cid_src(run_id), email_html)
        self.assertNotIn("cid:keysuri_bottomshot_korea_", email_html)
        self.assertNotIn('id="bottom-shot-image"', email_html)
        self.assertNotIn('id="bottom-shot-placeholder"', email_html)
        self.assertNotIn("output/images/", email_html)
        self.assertNotIn("image_canary/", email_html)
        self.assertNotIn("../", email_html)
        self.assertIn("운영자 검수 화면 열기", email_html)
        self.assertIn(f"/admin/runs/{run_id}", email_html)
        self.assertNotIn("GENIE_INTERNAL_JOB_TOKEN", email_html)
        self.assertNotIn(self._token, email_html)
        # Gmail-safe Global owner email renderer
        self.assertIn("키수리 글로벌 테크 브리핑", email_html)
        self.assertIn("글로벌 신호", email_html)
        self.assertIn('role="presentation"', email_html)
        self.assertNotIn("<style", email_html.lower())
        self.assertNotIn("audit-fold", email_html)
        self.assertNotIn("preview-metadata", email_html)
        self.assertNotIn("서비스 full-run", email_html)
        self.assertNotIn("image_source=generated", email_html)
        self.assertEqual(email_html.lower().count("<!doctype html>"), 1)
        self.assertEqual(email_html.lower().count("<html"), 1)
        self.assertEqual(email_html.lower().count("<head>"), 1)

        saved_meta = mock_save.call_args.args[0]
        self.assertTrue(saved_meta.get("service_full_run"))
        self.assertTrue(saved_meta.get("called_image_api"))
        self.assertEqual(saved_meta.get("image_source"), IMAGE_SOURCE_GENERATED)
        self.assertEqual(saved_meta.get("top_shot_watermark_status"), "applied")
        self.assertEqual(saved_meta.get("top_shot_watermark_text"), "MirAI:ON")
        self.assertEqual(saved_meta.get("generated_image_path_raw"), str(image_rel.relative_to(repo)))
        self.assertIn("_mirai_on_watermarked", str(saved_meta.get("generated_image_path")))
        self.assertIn("_mirai_on_watermarked", str(saved_meta.get("generated_image_path_watermarked")))
        self.assertFalse(saved_meta.get("artifact_storage_durable"))

    def test_registry_image_cannot_pass_global_service_full_run_contract(self) -> None:
        outcome = ServiceImageOutcome(
            called_image_api=False,
            image_source=IMAGE_SOURCE_REGISTRY,
            generated_image_path="output/keysuri_preview/image_canary/x.jpg",
        )
        self.assertFalse(service_image_passes(outcome))


class KeysuriKoreaServiceFullRunBottomEmailTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {
                "GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com",
                "GENIE_OWNER_REVIEW_SEND": "1",
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()

    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    @patch("keysuri_service_full_run.resolve_korea_bottom_email_asset_path")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.save_run_artifact")
    @patch("keysuri_service_full_run._generate_keysuri_service_image")
    @patch("keysuri_service_full_run.generate_run_id")
    def test_korea_owner_email_uses_top_and_bottom_inline_cids(
        self,
        mock_run_id: MagicMock,
        mock_image: MagicMock,
        mock_save: MagicMock,
        mock_prompt_input: MagicMock,
        mock_bottom_asset: MagicMock,
        mock_watermark: MagicMock,
    ) -> None:
        from keysuri_service_full_run import (
            keysuri_korea_bottom_service_email_cid_src,
            keysuri_korea_service_email_cid_src,
            run_keysuri_service_full_run,
        )

        repo = Path(__file__).resolve().parents[1]
        run_id = "20260615_183000_keysuri_korea_tech_5cf81e6a"
        mock_run_id.return_value = run_id
        pack_path = repo / "output" / "keysuri_preview" / "test_pack_korea_bottom_cid.json"
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(json.dumps({"sources": [], "program_id": PROGRAM_KOREA}), encoding="utf-8")
        raw_path = repo / "output" / "keysuri_preview" / "raw_korea_bottom_cid.txt"
        raw_path.write_text("{}", encoding="utf-8")

        top_image = repo / "output" / "images" / "keysuri_korea_service_test.jpg"
        top_image.parent.mkdir(parents=True, exist_ok=True)
        top_image.write_bytes(b"\xff\xd8\xff" + b"\x00" * 128)
        anchor_image = repo / "output" / "images" / "keysuri_korea_bottom_anchor_105936_test.jpg"
        anchor_image.write_bytes(b"\xff\xd8\xff" + b"\x11" * 128)
        mock_bottom_asset.return_value = (anchor_image, [])
        bottom_raw = repo / "output/admin_runs/keysuri_service_assets" / f"{run_id}_korea_bottom_v6.jpg"
        bottom_image = bottom_raw.with_name(f"{bottom_raw.stem}_mirai_on_watermarked.jpg")
        mock_watermark.side_effect = _mock_keysuri_watermark

        def _mock_bottom_generate(**kwargs):
            self.assertEqual(kwargs["primary_reference_path"], anchor_image)
            self.assertIn("image_keysuri_asset_01_main_briefing.png", str(kwargs["secondary_reference_path"]))
            kwargs["output_path"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["output_path"].write_bytes(b"\xff\xd8\xff" + b"\x12" * 128)
            return kwargs["output_path"]

        mock_image.return_value = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path=str(top_image.relative_to(repo)),
        )
        mock_prompt_input.return_value = {
            "program_id": PROGRAM_KOREA,
            "prompt_status": "ready_for_generation",
            "source_pack": {"sources": []},
        }
        mock_send = MagicMock(return_value=True)

        smoke = LiveSourceSmokeResult(
            ok=True,
            program_id=PROGRAM_KOREA,
            source_pack_path=str(pack_path),
            html_path=str(pack_path.parent / "k.html"),
            fetched_item_count=5,
            feed_urls_used=["https://example.com/feed"],
            sample_marker_pass=True,
            called_gemini=True,
            use_gemini=True,
            contract_preview=False,
            parse_status="parsed_valid",
            raw_response_path=str(raw_path),
            preview_overall_status="PASS_OWNER_REVIEW_READY",
            validation_status="PASS",
            generated_briefing={"title": "국내 브리핑", "summary": "요약", "top_5_news": []},
            side_effects={"called_gemini": True, "called_image_api": False},
        )

        with patch.dict(os.environ, {"KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED": "true"}, clear=False):
            payload = run_keysuri_service_full_run(
                PROGRAM_KOREA,
                smoke_runner=lambda **_kw: smoke,
                bottom_generate_fn=_mock_bottom_generate,
                bottom_watermark_fn=_mock_keysuri_watermark,
                send_fn=mock_send,
            )

        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("program_id"), PROGRAM_KOREA)
        self.assertEqual(payload.get("korea_bottom_shot_status"), "available")
        inline = mock_send.call_args.kwargs.get("inline_jpeg_parts") or []
        self.assertEqual(len(inline), 2)
        self.assertEqual(inline[0][1], keysuri_korea_service_email_cid_src(run_id).replace("cid:", ""))
        self.assertEqual(inline[1][1], keysuri_korea_bottom_service_email_cid_src(run_id).replace("cid:", ""))
        self.assertIn("_mirai_on_watermarked", Path(inline[0][0]).name)
        self.assertEqual(Path(inline[1][0]).resolve(), bottom_image.resolve())
        self.assertIn("korea_bottom_v6", Path(inline[1][0]).name)

        email_html = mock_send.call_args.args[0]
        self.assertIn(keysuri_korea_service_email_cid_src(run_id), email_html)
        self.assertIn(keysuri_korea_bottom_service_email_cid_src(run_id), email_html)
        self.assertIn('id="bottom-shot-image"', email_html)
        self.assertNotIn('id="bottom-shot-placeholder"', email_html)
        self.assertLess(email_html.find("원-라인 체크포인트"), email_html.find('id="bottom-shot-image"'))
        self.assertLess(email_html.find('id="bottom-shot-image"'), email_html.find("본 브리핑은 운영책임자의 직접 검수 대기 상태입니다"))

        saved_meta = mock_save.call_args.args[0]
        self.assertEqual(saved_meta.get("customer_delivery_status"), "not_sent")
        self.assertTrue(saved_meta.get("bottom_shot_variation_enabled"))
        self.assertEqual(saved_meta.get("bottom_shot_source"), "generated_v6_multi_ref")
        self.assertTrue(saved_meta.get("bottom_shot_generated"))
        self.assertEqual(saved_meta.get("bottom_anchor_asset_id"), "keysuri_korea_bottom_20260605_105936")
        self.assertEqual(saved_meta.get("bottom_anchor_slot"), 0)
        self.assertEqual(saved_meta.get("secondary_reference_asset_id"), "Asset01")
        self.assertEqual(saved_meta.get("secondary_reference_slot"), 1)
        self.assertEqual(saved_meta.get("bottom_shot_image_path"), str(bottom_image.relative_to(repo)))
        self.assertEqual(saved_meta.get("bottom_shot_watermark_status"), "applied")
        self.assertTrue(saved_meta.get("bottom_shot_wardrobe_family"))
        self.assertTrue(saved_meta.get("bottom_shot_wardrobe_descriptor"))
        self.assertTrue(saved_meta.get("bottom_shot_color_palette"))
        self.assertTrue(saved_meta.get("bottom_shot_silhouette"))
        self.assertTrue(saved_meta.get("bottom_shot_prop"))
        self.assertTrue(saved_meta.get("bottom_shot_scene"))
        self.assertTrue(saved_meta.get("bottom_shot_anti_copy_instruction_applied"))
        self.assertIn("Selected wardrobe:", saved_meta.get("bottom_shot_prompt_preview", ""))
        self.assertIsInstance(saved_meta.get("bottom_shot_prompt_metadata"), dict)
        self.assertEqual(saved_meta.get("korea_bottom_shot_asset_id"), f"keysuri_korea_bottom_generated_{run_id}")
        self.assertEqual(saved_meta.get("korea_bottom_shot_status"), "available")
        self.assertEqual(saved_meta.get("top_shot_watermark_status"), "applied")
        self.assertEqual(saved_meta.get("generated_image_path_raw"), str(top_image.relative_to(repo)))
        self.assertIn("_mirai_on_watermarked", str(saved_meta.get("generated_image_path_watermarked")))

    def test_korea_bottom_variation_defaults_enabled_when_env_unset(self) -> None:
        from keysuri_service_full_run import korea_bottom_variation_enabled

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED", None)
            self.assertTrue(korea_bottom_variation_enabled())

    @patch("keysuri_service_full_run.generate_keysuri_korea_bottom_v6")
    @patch("keysuri_service_full_run.resolve_korea_bottom_email_asset_path")
    def test_korea_bottom_generated_success_does_not_use_fixed_fallback(
        self,
        mock_fixed_bottom: MagicMock,
        mock_generate: MagicMock,
    ) -> None:
        from keysuri_bottom_shot_generation import BottomShotGenerationResult
        from keysuri_service_full_run import resolve_korea_bottom_email_image_path

        repo = Path(__file__).resolve().parents[1]
        bottom_image = repo / "output" / "images" / "keysuri_korea_bottom_generated_gate_test.jpg"
        bottom_image.parent.mkdir(parents=True, exist_ok=True)
        bottom_image.write_bytes(b"\xff\xd8\xff" + b"\x22" * 128)
        anchor_image = repo / "output" / "images" / "keysuri_korea_bottom_anchor_gate_test.jpg"
        anchor_image.write_bytes(b"\xff\xd8\xff" + b"\x21" * 128)
        mock_fixed_bottom.return_value = (anchor_image, [])
        mock_generate.return_value = BottomShotGenerationResult(
            ok=True,
            image_path=bottom_image,
            raw_image_path=bottom_image,
            metadata={
                "bottom_shot_source": "generated_v6_multi_ref",
                "bottom_shot_generated": True,
                "bottom_shot_model": "gemini-2.5-flash-image",
                "bottom_shot_weather_key": "clear_cool",
                "bottom_shot_wardrobe_variant": 1,
                "bottom_shot_pose_variant": "pose-b",
                "bottom_anchor_asset_id": "keysuri_korea_bottom_20260605_105936",
                "bottom_anchor_role": "primary_bottom_visual_anchor",
                "bottom_anchor_slot": 0,
                "secondary_reference_asset_id": "Asset01",
                "secondary_reference_role": "secondary_same_person_continuity_reference",
                "secondary_reference_slot": 1,
                "bottom_shot_watermark_status": "applied",
            },
        )

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED", None)
            path, issues, meta = resolve_korea_bottom_email_image_path("20260615_183000_keysuri_korea_tech_gate")

        self.assertEqual(path, bottom_image)
        self.assertEqual(issues, [])
        self.assertTrue(meta.get("bottom_shot_variation_enabled"))
        self.assertEqual(meta.get("bottom_shot_source"), "generated_v6_multi_ref")
        self.assertTrue(meta.get("bottom_shot_generated"))
        self.assertEqual(meta.get("bottom_anchor_slot"), 0)
        self.assertEqual(meta.get("secondary_reference_slot"), 1)
        self.assertEqual(meta.get("bottom_shot_watermark_status"), "applied")
        mock_generate.assert_called_once()
        self.assertEqual(mock_generate.call_args.kwargs.get("primary_reference_path"), anchor_image)
        mock_fixed_bottom.assert_called_once()

    @patch("keysuri_service_full_run.generate_keysuri_korea_bottom_v6")
    @patch("keysuri_service_full_run.resolve_korea_bottom_email_asset_path")
    def test_korea_bottom_generation_failure_uses_fixed_105936_fallback(
        self,
        mock_fixed_bottom: MagicMock,
        mock_generate: MagicMock,
    ) -> None:
        from keysuri_bottom_shot_generation import BottomShotGenerationResult
        from keysuri_service_full_run import resolve_korea_bottom_email_image_path

        repo = Path(__file__).resolve().parents[1]
        bottom_image = repo / "output" / "images" / "keysuri_korea_bottom_105936_failure_test.jpg"
        bottom_image.parent.mkdir(parents=True, exist_ok=True)
        bottom_image.write_bytes(b"\xff\xd8\xff" + b"\x33" * 128)
        mock_fixed_bottom.return_value = (bottom_image, [])
        mock_generate.return_value = BottomShotGenerationResult(
            ok=False,
            metadata={"bottom_shot_generation_status": "failed"},
            error_code="bottom_v6_generation_failed",
            error_message="mock failure",
        )

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED", None)
            path, issues, meta = resolve_korea_bottom_email_image_path("20260615_183000_keysuri_korea_tech_gate")

        self.assertEqual(path, bottom_image)
        self.assertEqual(issues, [])
        self.assertTrue(meta.get("bottom_shot_variation_enabled"))
        self.assertEqual(meta.get("bottom_shot_source"), "fixed_105936_fallback")
        self.assertFalse(meta.get("bottom_shot_generated"))
        self.assertIn("bottom_v6_generation_failed", meta.get("bottom_shot_fallback_reason"))
        self.assertEqual(meta.get("bottom_shot_watermark_status"), "applied")
        mock_fixed_bottom.assert_called_once()
        mock_generate.assert_called_once()

    @patch("keysuri_service_full_run.generate_keysuri_korea_bottom_v6")
    @patch("keysuri_service_full_run.resolve_korea_bottom_email_asset_path")
    def test_korea_bottom_explicit_off_uses_fallback_without_generation(
        self,
        mock_fixed_bottom: MagicMock,
        mock_generate: MagicMock,
    ) -> None:
        from keysuri_service_full_run import resolve_korea_bottom_email_image_path

        bottom_image = Path(__file__).resolve().parents[1] / "output/images/keysuri_korea_bottom_off.jpg"
        bottom_image.parent.mkdir(parents=True, exist_ok=True)
        bottom_image.write_bytes(b"\xff\xd8\xff" + b"\x44" * 128)
        mock_fixed_bottom.return_value = (bottom_image, [])

        with patch.dict(os.environ, {"KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED": "off"}, clear=False):
            path, issues, meta = resolve_korea_bottom_email_image_path("20260615_183000_keysuri_korea_tech_off")

        self.assertEqual(path, bottom_image)
        self.assertEqual(issues, [])
        self.assertFalse(meta.get("bottom_shot_variation_enabled"))
        self.assertEqual(meta.get("bottom_shot_source"), "fixed_105936_fallback")
        self.assertEqual(meta.get("bottom_shot_fallback_reason"), "variation_explicitly_disabled")
        mock_generate.assert_not_called()


class KeysuriGlobalOwnerReviewEmailDesignRestorationTests(unittest.TestCase):
    """Global service_full_run owner email must use Gmail-safe inline/table renderer."""

    def test_global_gmail_owner_email_is_safe_and_preserves_hierarchy(self) -> None:
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            IMAGE_MODE_PREVIEW,
            build_keysuri_global_gmail_owner_email_html,
            prepare_contract_preview_fixture,
            render_keysuri_contract_preview_html,
        )
        from tests.test_keysuri_contract_preview_renderer import build_global_contract_fixture

        repo = Path(__file__).resolve().parents[1]
        fixture = build_global_contract_fixture()
        fixture["top_shot_image_src"] = "cid:keysuri_topshot_global_20260611"
        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)

        preview_html = render_keysuri_contract_preview_html(
            fixture,
            repo_root=repo,
            image_mode=IMAGE_MODE_PREVIEW,
            auto_prepare=False,
        )
        email_html = build_keysuri_global_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Global Tech",
            admin_url="https://example.com/admin/runs/test_run",
            run_id="test_run",
        )
        lowered = email_html.lower()

        for forbidden in (
            "<style",
            "var(--",
            "display:flex",
            "<details",
            "audit-fold",
            "operation-metadata",
            "validation-result-box",
            "compliance-checklist",
            "운영 정보",
            "contract compliance checklist",
            "output/",
            "image_canary/",
            "../",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden.lower(), lowered)

        self.assertIn("cid:keysuri_topshot_global_", email_html)
        self.assertIn("키수리 글로벌 테크 브리핑", email_html)
        self.assertIn("글로벌 신호", email_html)
        self.assertIn("테크 비서 키수리", email_html)
        self.assertIn("TOP 5", email_html.upper())
        self.assertIn("키수리의 딥-다이브", email_html)
        self.assertIn("원-라인 체크포인트", email_html)
        self.assertIn("다음 48시간 관찰 포인트", email_html)
        self.assertIn("산업 레이어가 어디로 이동하나", email_html)
        self.assertLess(
            email_html.find("키수리의 딥-다이브"),
            email_html.find("원-라인 체크포인트"),
        )
        self.assertLess(
            email_html.find("원-라인 체크포인트"),
            email_html.find("다음 48시간 관찰 포인트"),
        )
        self.assertIn("https://blog.google/technology/ai/", email_html)
        self.assertIn("운영자 검수 화면 열기", email_html)
        self.assertIn("/admin/runs/test_run", email_html)
        self.assertIn('role="presentation"', email_html)
        self.assertNotIn("원문 확인이 필요", email_html)
        self.assertIn(
            "향후 공식 발표를 통해 세부 내용이 보완될 가능성이 있습니다.",
            email_html,
        )

        self.assertIn("premium-briefing theme-global", preview_html)
        self.assertIn('<div class="briefing-shell">', preview_html)
        self.assertIn('id="top5-section"', preview_html)
        self.assertIn("키수리의 딥-다이브", preview_html)
        self.assertIn("원-라인 체크포인트", preview_html)
        self.assertIn("<style", preview_html.lower())

    def test_korea_renderer_available_but_not_sent_by_global_service_full_run(self) -> None:
        from keysuri_contract_preview_renderer import render_keysuri_contract_preview_html
        from tests.test_keysuri_contract_preview_renderer import build_korea_contract_fixture

        repo = Path(__file__).resolve().parents[1]
        korea_html = render_keysuri_contract_preview_html(
            build_korea_contract_fixture(),
            repo_root=repo,
        )
        self.assertIn("theme-korea", korea_html)
        self.assertIn("키수리 국내 테크 브리핑", korea_html)


class KeysuriKoreaOwnerReviewEmailDesignTests(unittest.TestCase):
    """Korea service_full_run owner email must use Gmail-safe inline/table renderer."""

    def test_korea_gmail_owner_email_is_safe_and_preserves_hierarchy(self) -> None:
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            build_keysuri_korea_gmail_owner_email_html,
            prepare_contract_preview_fixture,
        )
        from keysuri_service_full_run import keysuri_korea_service_email_cid_src
        from tests.test_keysuri_contract_preview_renderer import build_korea_contract_fixture

        repo = Path(__file__).resolve().parents[1]
        fixture = build_korea_contract_fixture()
        fixture["top_shot_image_src"] = keysuri_korea_service_email_cid_src("20260615_180000_keysuri_korea_tech_test")
        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)

        email_html = build_keysuri_korea_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Korea Tech",
            admin_url="https://example.com/admin/runs/test_korea_run",
            run_id="test_korea_run",
        )
        lowered = email_html.lower()

        for forbidden in (
            "<style",
            "var(--",
            "display:flex",
            "<details",
            "audit-fold",
            "operation-metadata",
            "validation-result-box",
            "compliance-checklist",
            "운영 정보",
            "contract compliance checklist",
            "output/",
            "image_canary/",
            "../",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden.lower(), lowered)

        self.assertIn("cid:keysuri_topshot_korea_", email_html)
        self.assertIn("키수리 국내 테크 브리핑", email_html)
        self.assertIn("오늘 국내에서 움직인 것", email_html)
        self.assertIn("국내 테크 TOP", email_html.upper())
        self.assertIn("키수리의 딥-다이브", email_html)
        self.assertIn("원-라인 체크포인트", email_html)
        self.assertIn("한국 시장 관찰 포인트", email_html)
        self.assertIn("글로벌·국내 TOP5", email_html)
        self.assertIn('id="bottom-shot-placeholder"', email_html)
        self.assertIn("마무리 및 출처 리스트", email_html)
        self.assertIn("운영자 검수 화면 열기", email_html)
        self.assertIn("/admin/runs/test_korea_run", email_html)
        self.assertIn('role="presentation"', email_html)
        self.assertIn("#14110d", email_html)
        self.assertNotIn("105936", email_html)
        self.assertNotIn("cid:keysuri_bottom", email_html.lower())
        self.assertNotIn("production-ready", email_html.lower())
        self.assertNotIn("production_asset", email_html.lower())
        review_marker = "본 브리핑은 운영책임자의 직접 검수 대기 상태입니다"
        self.assertLess(email_html.find("키수리의 딥-다이브"), email_html.find("원-라인 체크포인트"))
        self.assertLess(email_html.find("원-라인 체크포인트"), email_html.find('id="bottom-shot-placeholder"'))
        self.assertLess(email_html.find('id="bottom-shot-placeholder"'), email_html.find(review_marker))
        self.assertLess(email_html.find(review_marker), email_html.find("퇴근 전 메모"))
        self.assertLess(email_html.find("퇴근 전 메모"), email_html.find("마무리 및 출처 리스트"))

    def test_korea_gmail_owner_email_renders_bottom_cid_when_available(self) -> None:
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            build_keysuri_korea_gmail_owner_email_html,
            prepare_contract_preview_fixture,
        )
        from keysuri_service_full_run import (
            keysuri_korea_bottom_service_email_cid_src,
            keysuri_korea_service_email_cid_src,
        )
        from tests.test_keysuri_contract_preview_renderer import build_korea_contract_fixture

        repo = Path(__file__).resolve().parents[1]
        run_id = "20260615_180000_keysuri_korea_tech_test"
        fixture = build_korea_contract_fixture()
        fixture["top_shot_image_src"] = keysuri_korea_service_email_cid_src(run_id)
        fixture["bottom_shot_image_src"] = keysuri_korea_bottom_service_email_cid_src(run_id)
        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)

        email_html = build_keysuri_korea_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Korea Tech",
            admin_url="https://example.com/admin/runs/test_korea_bottom",
            run_id="test_korea_bottom",
        )
        review_marker = "본 브리핑은 운영책임자의 직접 검수 대기 상태입니다"
        self.assertIn("cid:keysuri_topshot_korea_", email_html)
        self.assertIn("cid:keysuri_bottomshot_korea_", email_html)
        self.assertIn('id="bottom-shot-image"', email_html)
        self.assertNotIn('id="bottom-shot-placeholder"', email_html)
        self.assertLess(email_html.find("원-라인 체크포인트"), email_html.find('id="bottom-shot-image"'))
        self.assertLess(email_html.find('id="bottom-shot-image"'), email_html.find(review_marker))

    def test_korea_gmail_email_rejects_known_broken_endings_and_synthesizes_deep_dive(self) -> None:
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            build_keysuri_korea_gmail_owner_email_html,
            prepare_contract_preview_fixture,
        )
        from keysuri_service_full_run import keysuri_korea_service_email_cid_src
        from tests.test_keysuri_contract_preview_renderer import build_korea_contract_fixture

        repo = Path(__file__).resolve().parents[1]
        fixture = build_korea_contract_fixture()
        fixture["top_shot_image_src"] = keysuri_korea_service_email_cid_src("20260615_180000_keysuri_korea_tech_test")
        for idx, item in enumerate(fixture.get("top_5_items") or []):
            if not isinstance(item, dict):
                continue
            if idx == 0:
                item["selection_reason"] = (
                    "이 뉴스는 삼성전자의 국내 스타트업 생태계 지원 의지를 보여주는 중요한 신호입니다. "
                    "특히 AI, 로봇 등 미래 기술 분야 스타트업 발굴은 국내 기술 혁신과 자본 흐름에 직접적인 영향을 미칠 수 있어 국내 스타트업/투"
                )
                item["why_now"] = (
                    "국내 스타트업 생태계에 직접적인 투자 기회를 제공하는 중요한 창구입니"
                )
            if idx == 1:
                item["korean_title"] = "전기공사협회 전북도회, 국토부 장관과 건설산업 활성화 간담회 참석"
                item["selection_reason"] = (
                    "이 뉴스는 국내 건설 및 인프라 산업의 정책 방향과 대기업의 지역 투자 연계 가능성을 보여줍니다. "
                    "특히 새만금 사업과 AI 건설·로봇 혁신센터 설립 논의는 국내 산업 전반에 미칠 파급력이 커 국내 대기업 테크 전략"
                )
            if idx == 2:
                item["korean_title"] = "KH바텍, 휴머노이드 로봇 감속기 공급 협력 논의 중"
                item["selection_reason"] = (
                    "국내 전자부품 기업이 글로벌 휴머노이드 로봇 시장에 핵심 부품을 공급할 가능성은 국내 로봇 산업의 성장 잠재력과 기술력을 보여줍니다. "
                    "이는 글로벌 로봇 트렌드가 국내 기업에 미치는 영향을 분석하는 데 중요하여 글로벌"
                )
            if idx == 3:
                item["why_now"] = (
                    "정부의 자본시장 개편은 시장의 신뢰 회복을 목표로 하지만, 벤처업계는 혁신 기업의 성장을 저해할 수 있다고 보고 있습니다. "
                    "코스닥 시장은 국내 벤처기업의 주요 자금 조달 및 회수 통로이므로, 관련 정책 변화는 국내 스타트업 생태계 전반에 큰 영향을 미 미칩니다."
                )
            item["owner_angle"] = item.get("owner_angle") or "내일 파트너 일정을 점검하시면 됩니다."
        fixture["korea_deep_dive_sections"] = []
        fixture["deep_dive_uncertainty"] = (
            "삼성전자 C랩 아웃사이드 9기 선정 기업들이 실제 어떤 혁신을 이끌어낼지, "
            "그리고 이들이 국내 산업 생태계에 미칠 구체적인 영향은 무엇일까요?"
        )
        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)

        email_html = build_keysuri_korea_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Korea Tech",
            admin_url="https://example.com/admin/runs/test_korea_quality",
            run_id="test_korea_quality",
        )
        import re

        for broken in (
            "국내 스타트업/투",
            "국내 대기업 테크 전략",
            "중요하여 글로벌",
            "무엇일까요",
            "영향을 미 미칩니다",
            "창구입니",
            "사업 전략 수립에",
            "중요한 흐름",
            "주인님의 투",
            "작용합",
            "제공합니",
        ):
            self.assertNotRegex(email_html, rf"{re.escape(broken)}(?:\s|<|$)", msg=f"broken ending leaked: {broken}")
        self.assertNotRegex(email_html, r"조명합(?:\s|<|$)")
        self.assertIn("글로벌 AI 인프라", email_html)
        self.assertIn("한국 기업", email_html)
        deep_start = email_html.find("키수리의 딥-다이브")
        checkpoint_start = email_html.find("원-라인 체크포인트", deep_start)
        deep_section = email_html[deep_start:checkpoint_start]
        self.assertNotIn("삼성전자, &#x27;C랩 아웃사이드&#x27;", deep_section)
        self.assertNotIn("전기공사협회 전북도회", deep_section)
        self.assertIn('id="bottom-shot-placeholder"', email_html)
        risk_start = email_html.find("위험 요인", deep_start)
        judgment_start = email_html.find("키수리 판단", risk_start)
        risk_blob = email_html[risk_start:judgment_start]
        self.assertNotIn("?", risk_blob)
        self.assertNotRegex(
            email_html[judgment_start : judgment_start + 400],
            r"키수리\s*판단\s*[:：]",
        )


class KeysuriKoreaContractPreviewBottomOrderingTests(unittest.TestCase):
    """Contract preview must be rendered after Bottom decision so it shows actual Bottom."""

    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {
                "GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com",
                "GENIE_OWNER_REVIEW_SEND": "0",
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()

    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    @patch("keysuri_service_full_run.resolve_korea_bottom_email_asset_path")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.save_run_artifact")
    @patch("keysuri_service_full_run._generate_keysuri_service_image")
    @patch("keysuri_service_full_run.generate_run_id")
    def test_korea_contract_preview_shows_bottom_image_not_placeholder(
        self,
        mock_run_id: MagicMock,
        mock_image: MagicMock,
        mock_save: MagicMock,
        mock_prompt_input: MagicMock,
        mock_bottom_asset: MagicMock,
        mock_watermark: MagicMock,
    ) -> None:
        """After bottom resolution is moved before preview build, preview HTML should
        contain bottom image (data-URI) not the placeholder div."""
        from keysuri_service_full_run import run_keysuri_service_full_run

        repo = Path(__file__).resolve().parents[1]
        run_id = "20260619_120000_keysuri_korea_tech_ab120001"
        mock_run_id.return_value = run_id
        pack_path = repo / "output" / "keysuri_preview" / "test_pack_korea_preview_order.json"
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(json.dumps({"sources": [], "program_id": PROGRAM_KOREA}), encoding="utf-8")
        raw_path = repo / "output" / "keysuri_preview" / "raw_korea_preview_order.txt"
        raw_path.write_text("{}", encoding="utf-8")

        top_image = repo / "output" / "images" / "keysuri_korea_preview_order_top.jpg"
        top_image.parent.mkdir(parents=True, exist_ok=True)
        top_image.write_bytes(b"\xff\xd8\xff" + b"\x00" * 128)
        anchor_image = repo / "output" / "images" / "keysuri_korea_preview_order_anchor.jpg"
        anchor_image.write_bytes(b"\xff\xd8\xff" + b"\x11" * 128)
        mock_bottom_asset.return_value = (anchor_image, [])
        bottom_raw = repo / "output/admin_runs/keysuri_service_assets" / f"{run_id}_korea_bottom_v6.jpg"
        bottom_image = bottom_raw.with_name(f"{bottom_raw.stem}_mirai_on_watermarked.jpg")
        mock_watermark.side_effect = _mock_keysuri_watermark

        def _mock_bottom_generate(**kwargs):
            kwargs["output_path"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["output_path"].write_bytes(b"\xff\xd8\xff" + b"\x22" * 128)
            return kwargs["output_path"]

        mock_image.return_value = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path=str(top_image.relative_to(repo)),
        )
        mock_prompt_input.return_value = {
            "program_id": PROGRAM_KOREA,
            "prompt_status": "ready_for_generation",
            "source_pack": {"sources": []},
        }

        smoke = LiveSourceSmokeResult(
            ok=True,
            program_id=PROGRAM_KOREA,
            source_pack_path=str(pack_path),
            html_path=str(pack_path.parent / "ko.html"),
            fetched_item_count=5,
            feed_urls_used=["https://example.com/feed"],
            sample_marker_pass=True,
            called_gemini=True,
            use_gemini=True,
            contract_preview=False,
            parse_status="parsed_valid",
            raw_response_path=str(raw_path),
            preview_overall_status="PASS_OWNER_REVIEW_READY",
            validation_status="PASS",
            generated_briefing={"title": "국내 브리핑", "summary": "요약", "top_5_news": []},
            side_effects={"called_gemini": True, "called_image_api": False},
        )

        with patch.dict(os.environ, {"KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED": "true"}, clear=False):
            payload = run_keysuri_service_full_run(
                PROGRAM_KOREA,
                smoke_runner=lambda **_kw: smoke,
                bottom_generate_fn=_mock_bottom_generate,
                bottom_watermark_fn=_mock_keysuri_watermark,
            )

        self.assertEqual(payload.get("program_id"), PROGRAM_KOREA)
        self.assertEqual(payload.get("korea_bottom_shot_status"), "available")

        # T8: contract preview HTML must NOT contain bottom-shot-placeholder
        html_rel = payload.get("html_path") or ""
        if html_rel:
            preview_html = (repo / html_rel).read_text(encoding="utf-8")
            self.assertNotIn(
                'id="bottom-shot-placeholder"',
                preview_html,
                "preview HTML still shows placeholder — bottom resolution order not fixed",
            )
            # T9: preview HTML contains bottom data-URI image
            self.assertIn('id="bottom-shot-image"', preview_html)

        saved_meta = mock_save.call_args.args[0]
        self.assertIn("top_image_cid", saved_meta)
        self.assertIn("bottom_image_cid", saved_meta)
        self.assertIn("owner_email_image_cids", saved_meta)
        self.assertIn("customer_email_image_cids", saved_meta)
        owner_cids = saved_meta["owner_email_image_cids"]
        customer_cids = saved_meta["customer_email_image_cids"]
        self.assertEqual(len(owner_cids), 2)
        self.assertEqual(owner_cids, customer_cids)


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
