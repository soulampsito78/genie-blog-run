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


def _pass_today_result() -> OrchestrationResult:
    return OrchestrationResult(
        decision=PublishingDecision(
            send_email=True,
            create_naver_draft=False,
            auto_publish=False,
            require_review=False,
            suppress_external=False,
        ),
        reason_summary="ok",
        response_status=200,
        mode="today_genie",
        response_data={
            "validation_result": "pass",
            "workflow_status": "validated",
            "data": {
                "image_prompt_studio": "studio prompt",
                "image_prompt_outdoor": "outdoor prompt",
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

    @patch("orchestrator.send_genie_email")
    def test_owner_email_inline_parts_not_static_latest(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        os.environ["GENIE_ADMIN_PUBLIC_BASE_URL"] = "https://example.com"
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


if __name__ == "__main__":
    unittest.main()
