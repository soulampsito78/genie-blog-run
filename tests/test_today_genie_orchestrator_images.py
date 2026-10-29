"""Tests for Today_Geenee orchestrator-path generated images."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from orchestrator import (
    OrchestrationResult,
    execute_orchestrator_run,
    persist_orchestrator_run_artifact,
    send_email_if_allowed,
)
from publishing_policy import PublishingDecision
from service_full_run_contract import (
    IMAGE_GEN_GENERATED,
    IMAGE_SOURCE_GENERATED,
    ServiceImageOutcome,
    TodayGenieServiceImageBundle,
)
from today_genie_orchestrator_images import (
    IMAGE_SOURCE_STATIC_FALLBACK,
    STATIC_FALLBACK_ISSUE_CODE,
    TodayGenieOrchestratorImageResult,
    generate_today_genie_orchestrator_images,
)


def _pass_today_result(validation_result: str = "pass") -> OrchestrationResult:
    return OrchestrationResult(
        decision=PublishingDecision(
            send_email=True,
            create_naver_draft=False,
            auto_publish=False,
            require_review=(validation_result != "pass"),
            suppress_external=False,
        ),
        reason_summary="ok" if validation_result == "pass" else "draft preview",
        response_status=200,
        mode="today_genie",
        response_data={
            "validation_result": validation_result,
            "workflow_status": "validated" if validation_result == "pass" else "draft_only",
            "data": {
                "title": "오늘 시장 점검",
                "summary": "핵심 브리핑 요약 문장입니다.",
                "greeting": "좋은 아침입니다.",
                "closing_message": "원칙을 지키는 투자가 중요합니다.",
                "image_prompt_studio": "studio prompt",
                "image_prompt_outdoor": "outdoor prompt",
                "key_watchpoints": [
                    {
                        "headline": "핵심 이슈 1",
                        "detail": "상세 분석 내용입니다.",
                        "source_name": "연합뉴스",
                        "source_url": "https://example.com/news/1",
                        "source_published_at": "2026-06-15 06:00",
                        "source_provenance_status": "INPUT_URL_BOUND_NOT_FACT_PASS",
                    }
                ],
                "channel_drafts": {"email_subject": "오늘 브리핑"},
            },
            "runtime_input": {"target_date": "2026-06-15"},
        },
    )


def _generated_bundle(run_id: str) -> TodayGenieServiceImageBundle:
    top_path = f"output/images/today_genie/{run_id}/{run_id}_top.jpg"
    bot_path = f"output/images/today_genie/{run_id}/{run_id}_bottom.jpg"
    return TodayGenieServiceImageBundle(
        top=ServiceImageOutcome(
            called_image_api=True,
            image_generation_status=IMAGE_GEN_GENERATED,
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path=top_path,
        ),
        bottom=ServiceImageOutcome(
            called_image_api=True,
            image_generation_status=IMAGE_GEN_GENERATED,
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path=bot_path,
        ),
        primary_generated_image_path=top_path,
    )


class TodayGenieOrchestratorImageGenerationTests(unittest.TestCase):
    def test_scheduler_path_calls_image_generation(self) -> None:
        result = _pass_today_result()
        with patch("orchestrator.run_genie_job", return_value=result):
            with patch(
                "today_genie_orchestrator_images.generate_today_genie_orchestrator_images"
            ) as mock_images:
                mock_images.return_value = TodayGenieOrchestratorImageResult(
                    inline_parts=[("/tmp/top.jpg", "cid:top", "top.jpg")],
                    called_image_api=True,
                    image_source=IMAGE_SOURCE_GENERATED,
                    image_generation_status=IMAGE_GEN_GENERATED,
                    generated_image_paths={"top": "output/top.jpg", "bottom": "output/bot.jpg"},
                )
                with patch("orchestrator.send_email_if_allowed", return_value=True) as mock_send:
                    with patch("orchestrator.persist_orchestrator_run_artifact", return_value="rid") as mock_persist:
                        execute_orchestrator_run(
                            "today_genie",
                            trigger_source="scheduler",
                            schedule_now=datetime(
                                2026,
                                6,
                                19,
                                6,
                                30,
                                tzinfo=ZoneInfo("Asia/Seoul"),
                            ),
                        )
        mock_images.assert_called_once()
        mock_send.assert_called_once()
        self.assertIsNotNone(mock_send.call_args.kwargs.get("today_image_result"))
        mock_persist.assert_called_once()

    @patch("today_genie_service_full_run.invoke_vertex_image_generation")
    def test_generated_paths_used_for_inline_parts(self, mock_invoke: MagicMock) -> None:
        run_id = "20260615_060000_today_genie_aabbccdd"
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / f"{run_id}_top.jpg"
            bot = Path(tmp) / f"{run_id}_bottom.jpg"
            top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            bot.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)

            def _fake_invoke(*, prompt: str, output_path: Path, **kwargs: object) -> ServiceImageOutcome:
                if "studio" in prompt.lower() or "hero" in prompt.lower() or output_path.name.endswith("_top.jpg"):
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(top.read_bytes())
                    rel = str(output_path)
                else:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(bot.read_bytes())
                    rel = str(output_path)
                return ServiceImageOutcome(
                    called_image_api=True,
                    image_generation_status=IMAGE_GEN_GENERATED,
                    image_source=IMAGE_SOURCE_GENERATED,
                    generated_image_path=rel,
                )

            mock_invoke.side_effect = _fake_invoke
            data = {
                "image_prompt_studio": "studio hero",
                "image_prompt_outdoor": "outdoor daily",
            }
            image_result = generate_today_genie_orchestrator_images(
                run_id,
                data,
                {"target_date": "2026-06-15"},
            )

        self.assertEqual(image_result.image_source, IMAGE_SOURCE_GENERATED)
        self.assertFalse(image_result.fallback_used)
        self.assertEqual(len(image_result.inline_parts), 2)
        used_paths = {Path(row[0]).name for row in image_result.inline_parts}
        self.assertIn(f"{run_id}_top.jpg", used_paths)
        self.assertIn(f"{run_id}_bottom.jpg", used_paths)

    @patch("today_genie_orchestrator_images.generate_today_genie_service_images")
    def test_static_fallback_only_when_generation_fails(self, mock_gen: MagicMock) -> None:
        repo = Path(__file__).resolve().parents[1]
        top_latest = repo / "static" / "email" / "GENIE_EMAIL_today_genie_top_latest.jpg"
        bottom_latest = repo / "static" / "email" / "GENIE_EMAIL_today_genie_bottom_latest.jpg"
        if not top_latest.is_file() or not bottom_latest.is_file():
            self.skipTest("static latest images missing")

        mock_gen.return_value = TodayGenieServiceImageBundle(
            top=ServiceImageOutcome(called_image_api=True, error_code="IMAGE_GENERATION_FAILED"),
            bottom=ServiceImageOutcome(called_image_api=True, error_code="IMAGE_GENERATION_FAILED"),
        )
        image_result = generate_today_genie_orchestrator_images(
            "20260615_070000_today_genie_bbccddee",
            {"image_prompt_studio": "x", "image_prompt_outdoor": "y"},
            {},
        )
        self.assertTrue(image_result.fallback_used)
        self.assertEqual(image_result.image_source, IMAGE_SOURCE_STATIC_FALLBACK)
        self.assertIn(STATIC_FALLBACK_ISSUE_CODE, image_result.issue_codes)
        self.assertEqual(
            {Path(p).resolve() for p, _, _ in image_result.inline_parts},
            {top_latest.resolve(), bottom_latest.resolve()},
        )

    def test_metadata_records_generated_image_paths(self) -> None:
        run_id = "20260615_080000_today_genie_ccddeeff"
        bundle = _generated_bundle(run_id)
        image_result = TodayGenieOrchestratorImageResult(
            bundle=bundle,
            inline_parts=[
                (f"/tmp/{run_id}_top.jpg", "cid:top", "top.jpg"),
                (f"/tmp/{run_id}_bottom.jpg", "cid:bottom", "bottom.jpg"),
            ],
            called_image_api=True,
            image_source=IMAGE_SOURCE_GENERATED,
            image_generation_status=IMAGE_GEN_GENERATED,
            generated_image_paths={
                "top": bundle.top.generated_image_path,
                "bottom": bundle.bottom.generated_image_path,
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp) / "admin_runs"
            runs_dir.mkdir(parents=True)
            with patch("admin_store.admin_runs_dir", return_value=runs_dir):
                rid = persist_orchestrator_run_artifact(
                    _pass_today_result(),
                    email_sent=False,
                    run_id=run_id,
                    today_image_result=image_result,
                )
                meta_path = runs_dir / f"{rid}.json"
                self.assertTrue(meta_path.is_file())
                import json

                meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta.get("image_source"), IMAGE_SOURCE_GENERATED)
        self.assertEqual(meta.get("generated_image_paths", {}).get("top"), bundle.top.generated_image_path)
        self.assertEqual(meta.get("generated_image_paths", {}).get("bottom"), bundle.bottom.generated_image_path)
        self.assertFalse(meta.get("fallback_used"))

    @patch.dict(
        os.environ,
        {"GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com"},
        clear=False,
    )
    @patch("orchestrator.send_genie_email")
    def test_owner_email_inline_parts_not_static_latest(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260615_090000_today_genie_ddeeff00"
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / f"{run_id}_top.jpg"
            bot = Path(tmp) / f"{run_id}_bottom.jpg"
            top.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            bot.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            image_result = TodayGenieOrchestratorImageResult(
                inline_parts=[
                    (str(top), "cid:top", top.name),
                    (str(bot), "cid:bottom", bot.name),
                ],
                called_image_api=True,
                image_source=IMAGE_SOURCE_GENERATED,
                image_generation_status=IMAGE_GEN_GENERATED,
                generated_image_paths={"top": str(top), "bottom": str(bot)},
            )
            sent = send_email_if_allowed(
                _pass_today_result(),
                run_id=run_id,
                today_image_result=image_result,
            )
        self.assertTrue(sent)
        inline = mock_send.call_args.kwargs.get("inline_jpeg_parts") or []
        used = {Path(row[0]).resolve() for row in inline}
        latest_top = (repo / "static" / "email" / "GENIE_EMAIL_today_genie_top_latest.jpg").resolve()
        self.assertIn(top.resolve(), used)
        self.assertNotIn(latest_top, used)

    @patch.dict(
        os.environ,
        {"GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com"},
        clear=False,
    )
    @patch("orchestrator.send_genie_email")
    def test_none_image_operator_preview_omits_static_images_and_cid_slots_with_truthful_notice(
        self, mock_send: MagicMock
    ) -> None:
        from renderers import TODAY_GENIE_EMAIL_CID_BOTTOM, TODAY_GENIE_EMAIL_CID_TOP

        mock_send.return_value = True
        run_id = "20260615_100000_today_genie_11223344"
        sent = send_email_if_allowed(
            _pass_today_result(),
            run_id=run_id,
            today_image_result=None,
        )
        self.assertTrue(sent)
        inline = mock_send.call_args.kwargs.get("inline_jpeg_parts")
        self.assertEqual(inline, [])
        html = mock_send.call_args.args[0]
        self.assertIn("genie-no-image-notice", html)
        self.assertIn("이미지 미생성 초안", html)
        self.assertIn("이번 실행의 이미지는 생성되지 않았습니다", html)
        self.assertNotIn("<img", html.lower())
        self.assertNotIn("cid:", html.lower())
        self.assertNotIn("genie_email_today_genie", html.lower())
        self.assertNotIn("static/email", html.lower())
        self.assertNotIn(TODAY_GENIE_EMAIL_CID_TOP, html)
        self.assertNotIn(TODAY_GENIE_EMAIL_CID_BOTTOM, html)
        self.assertIn("오늘 시장 점검", html)
        self.assertIn("핵심 브리핑 요약 문장입니다.", html)
        self.assertIn("출처: 연합뉴스", html)
        self.assertIn("https://example.com/news/1", html)
        self.assertIn("운영자 검수 화면 열기", html)
        self.assertIn(run_id, html)

    @patch.dict(
        os.environ,
        {"GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com"},
        clear=False,
    )
    @patch("orchestrator.send_genie_email")
    def test_no_call_validation_draft_operator_preview_labeled_distinctly(
        self, mock_send: MagicMock
    ) -> None:
        mock_send.return_value = True
        run_id = "20260615_110000_today_genie_55667788"
        result = _pass_today_result(validation_result="draft_only")
        sent = send_email_if_allowed(
            result,
            run_id=run_id,
            today_image_result=None,
        )
        self.assertTrue(sent)
        inline = mock_send.call_args.kwargs.get("inline_jpeg_parts")
        self.assertEqual(inline, [])
        html = mock_send.call_args.args[0]
        self.assertIn("genie-no-image-notice", html)
        self.assertIn("no-call validation draft", html)
        self.assertIn("검증으로 인한 이미지 미생성 초안", html)
        self.assertNotIn("<img", html.lower())
        self.assertNotIn("cid:", html.lower())
        self.assertIn("출처: 연합뉴스", html)

    @patch.dict(
        os.environ,
        {"GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com"},
        clear=False,
    )
    def test_execute_orchestrator_run_none_image_shares_identical_snapshot_between_send_and_persist(
        self,
    ) -> None:
        import json
        from today_geenee_customer_delivery import prepare_customer_final_html

        result = _pass_today_result(validation_result="draft_only")
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp) / "admin_runs"
            runs_dir.mkdir(parents=True)
            with patch("admin_store.admin_runs_dir", return_value=runs_dir):
                with patch("orchestrator.run_genie_job", return_value=result):
                    with patch("orchestrator.send_genie_email", return_value=True) as mock_send:
                        run_id, res, email_sent = execute_orchestrator_run(
                            "today_genie",
                            trigger_source="scheduler",
                            schedule_now=datetime(
                                2026,
                                6,
                                19,
                                6,
                                30,
                                tzinfo=ZoneInfo("Asia/Seoul"),
                            ),
                        )
            self.assertTrue(email_sent)
            self.assertTrue(mock_send.called)
            sent_html = mock_send.call_args.args[0]
            sent_inline = mock_send.call_args.kwargs.get("inline_jpeg_parts")
            self.assertEqual(sent_inline, [])
            self.assertIn("genie-no-image-notice", sent_html)
            self.assertNotIn("<img", sent_html.lower())

            meta_path = runs_dir / f"{run_id}.json"
            html_path = runs_dir / f"{run_id}.email.html"
            self.assertTrue(meta_path.is_file())
            self.assertTrue(html_path.is_file())
            persisted_html = html_path.read_text(encoding="utf-8")
            self.assertEqual(sent_html, persisted_html)

            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertNotEqual(meta.get("image_source"), IMAGE_SOURCE_GENERATED)

            cleaned = prepare_customer_final_html(persisted_html)
            self.assertNotIn("genie-no-image-notice", cleaned)
            self.assertNotIn("<!--auto-remediation-notice-start-->", cleaned)

    @patch.dict(
        os.environ,
        {"GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com"},
        clear=False,
    )
    @patch("orchestrator.send_genie_email")
    def test_caller_supplied_invalid_snapshots_rejected_and_valid_snapshot_sent(
        self, mock_send: MagicMock
    ) -> None:
        from orchestrator import extract_email_html_for_artifact
        from renderers import TODAY_GENIE_EMAIL_CID_TOP

        mock_send.return_value = True
        run_id = "20260615_120000_today_genie_99aabbcc"
        result = _pass_today_result()

        # 1. Stale CID snapshot rejected before send, SMTP boundary not called
        cid_html = f"<html><body><p>Draft</p><img src=\"cid:{TODAY_GENIE_EMAIL_CID_TOP}\">운영자 검수 화면 열기</body></html>"
        sent = send_email_if_allowed(
            result,
            run_id=run_id,
            today_image_result=None,
            owner_email_html_snapshot=cid_html,
        )
        self.assertFalse(sent)
        mock_send.assert_not_called()

        # 2. Static HTTP IMG snapshot rejected before send, SMTP boundary not called
        http_html = "<html><body><p>Draft</p><img src=\"https://example.com/static/email/GENIE_EMAIL_today_genie_top_latest.jpg\">운영자 검수 화면 열기</body></html>"
        sent = send_email_if_allowed(
            result,
            run_id=run_id,
            today_image_result=None,
            owner_email_html_snapshot=http_html,
        )
        self.assertFalse(sent)
        mock_send.assert_not_called()

        # 3. Snapshot lacking required no-image notice rejected before send, SMTP boundary not called
        no_notice_html = f"<html><body><p>Draft text without notice</p><div>운영자 검수 화면 열기</div>{run_id}</body></html>"
        sent = send_email_if_allowed(
            result,
            run_id=run_id,
            today_image_result=None,
            owner_email_html_snapshot=no_notice_html,
        )
        self.assertFalse(sent)
        mock_send.assert_not_called()

        # 4. Valid frozen no-image snapshot from actual producer sends successfully without rewrite
        valid_html = extract_email_html_for_artifact(
            result,
            run_id=run_id,
            today_image_result=None,
        )
        self.assertIn("genie-no-image-notice", valid_html)
        self.assertNotIn("<img", valid_html.lower())
        sent = send_email_if_allowed(
            result,
            run_id=run_id,
            today_image_result=None,
            owner_email_html_snapshot=valid_html,
        )
        self.assertTrue(sent)
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args.args[0], valid_html)
        self.assertEqual(mock_send.call_args.kwargs.get("inline_jpeg_parts"), [])


if __name__ == "__main__":
    unittest.main()
