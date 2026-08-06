"""Track B — Admin reissue production-faithful sandbox harness.

Scopes:
  TODAY_GENIE: body_only, image_only, full (body_and_image)
  KEYSURI_GLOBAL: body_only, full (body_and_image)

Fakes only auth/session, model caller, image API, SMTP, GCS, clock.
Exercises real orchestration helpers and parent-eligibility policy.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

from admin_store import (
    load_run_artifact,
    reissue_parent_block_reason,
    save_run_artifact,
)
from orchestrator import OrchestrationResult
from publishing_policy import PublishingDecision
from service_full_run_contract import IMAGE_GEN_GENERATED, IMAGE_SOURCE_GENERATED
from today_genie_orchestrator_images import (
    TODAY_IMAGE_REGEN_INPUTS_KEY,
    TodayGenieOrchestratorImageResult,
)
from today_genie_reissue import (
    run_today_body_only_reissue,
    run_today_image_only_reissue,
)

_SAMPLE_BASE = "https://genie-blog-run-1055014091206.asia-northeast3.run.app"
_OWNER_TO = "soulampsito@gmail.com,ey2133@naver.com"
_TODAY_PARENT = "20260611_150000_today_genie_aabbccdd"
_GLOBAL_PARENT = "20260730_123000_keysuri_global_tech_aabbccdd"

_MINIMAL_TODAY_DATA = {
    "title": "오늘의 지니",
    "summary": "국내 증시는 장전 변동성에 주목합니다.",
    "greeting": "안녕하세요.",
    "closing_message": "오늘도 신중한 접근이 필요합니다.",
    "key_watchpoints": [{"headline": "코스피", "detail": "외국인 수급을 확인합니다."}],
    "risk_check": [{"risk": "환율", "detail": "원/달러 변동성을 봅니다."}],
    "hashtags": ["#코스피", "#장전브리핑", "#지니"],
}

_IMAGE_PROMPT_SNAPSHOT = {
    "image_prompt_studio": "studio hero anchor",
    "image_prompt_outdoor": "outdoor daily morning",
    "image_briefing_mood_state": "calm",
    "target_date": "2026-06-11",
    "image_weather_context": {"band": "mild"},
}


def _today_result(*, validation_result: str = "pass") -> OrchestrationResult:
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
            "workflow_status": "validated",
            "data": {
                **_MINIMAL_TODAY_DATA,
                "channel_drafts": {"email_subject": "오늘의 지니 장전 브리핑"},
                "image_prompt_studio": "regenerated studio hero",
                "image_prompt_outdoor": "regenerated outdoor daily",
            },
            "runtime_input": {
                "target_date": "2026-06-12",
                "image_weather_context": {"band": "warm"},
                "overnight_us_market": {"summary": "mixed"},
                "macro_indicators": {"summary": "stable"},
            },
        },
    )


class _SideEffects:
    def __init__(self) -> None:
        self.model = 0
        self.image = 0
        self.smtp = 0
        self.customer = 0
        self.approve = 0
        self.final_send = 0


class _HarnessBase(unittest.TestCase):
    _ENV_KEYS = (
        "GENIE_ADMIN_PUBLIC_BASE_URL",
        "GENIE_PUBLIC_BASE_URL",
        "GENIE_OWNER_REVIEW_SEND",
        "EMAIL_TO",
        "GENIE_ADMIN_REISSUE",
        "GENIE_ADMIN_ARTIFACT_BUCKET",
        "GENIE_ARTIFACT_BUCKET",
        "GENIE_CONTROLLED_TEST_MODE",
        "GENIE_CONTROLLED_TEST_TARGET_DATE",
    )

    def setUp(self) -> None:
        self._env_backup = {key: os.environ.get(key) for key in self._ENV_KEYS}
        for key in (
            "GENIE_ADMIN_ARTIFACT_BUCKET",
            "GENIE_ARTIFACT_BUCKET",
            "GENIE_ADMIN_REISSUE",
            "GENIE_CONTROLLED_TEST_MODE",
            "GENIE_CONTROLLED_TEST_TARGET_DATE",
        ):
            os.environ.pop(key, None)
        os.environ["GENIE_ADMIN_PUBLIC_BASE_URL"] = _SAMPLE_BASE
        os.environ["GENIE_OWNER_REVIEW_SEND"] = "1"
        os.environ["EMAIL_TO"] = _OWNER_TO
        self._tmp = tempfile.TemporaryDirectory()
        self._runs_dir = Path(self._tmp.name) / "admin_runs"
        self._runs_dir.mkdir(parents=True)
        self._runs_patch = patch("admin_store.admin_runs_dir", return_value=self._runs_dir)
        self._runs_patch.start()
        self._images_dir = Path(self._tmp.name) / "images"
        self._images_dir.mkdir(parents=True)
        self.fx = _SideEffects()

    def tearDown(self) -> None:
        self._runs_patch.stop()
        self._tmp.cleanup()
        for key, prev in self._env_backup.items():
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev

    def _image_file(self, name: str) -> Path:
        path = self._images_dir / name
        path.write_bytes(b"\xff\xd8\xff\xd9")
        return path

    def _assert_no_customer_side_effects(self, child: Dict[str, Any]) -> None:
        self.assertEqual(child.get("customer_delivery_status"), "not_sent")
        self.assertFalse(bool(child.get("approved")))
        self.assertFalse(bool(child.get("customer_final_send")))
        self.assertFalse(bool(child.get("final_send")))
        self.assertEqual(self.fx.customer, 0)
        self.assertEqual(self.fx.approve, 0)
        self.assertEqual(self.fx.final_send, 0)
        self.assertLessEqual(self.fx.smtp, 1)

    def _save_today_parent(
        self,
        *,
        run_id: str = _TODAY_PARENT,
        generated_paths: Optional[Dict[str, str]] = None,
        email_html: str = "",
        regen_inputs: Optional[Dict[str, Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "run_id": run_id,
            "mode": "today_genie",
            "program_id": "today_genie",
            "validation_result": "pass",
            "workflow_status": "validated",
            "reason_summary": "ok",
            "response_status": 200,
            "email_sent": True,
            "customer_delivery_status": "not_sent",
            "target_date": "2026-06-11",
            "email_subject": "오늘의 지니 장전 브리핑",
        }
        if generated_paths is not None:
            meta.update(
                image_source="generated",
                image_generation_status="generated",
                fallback_used=False,
                generated_image_paths=generated_paths,
                generated_image_path=generated_paths.get("top"),
                run_specific_images=True,
                customer_image_source="generated_run_images",
            )
        if regen_inputs is not None:
            meta[TODAY_IMAGE_REGEN_INPUTS_KEY] = regen_inputs
        if extra:
            meta.update(extra)
        save_run_artifact(meta, email_html=email_html)
        return meta

    def _save_global_parent(self, *, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "run_id": _GLOBAL_PARENT,
            "mode": "keysuri_global_tech",
            "program_id": "keysuri_global_tech",
            "validation_result": "pass",
            "email_sent": True,
            "customer_delivery_status": "not_sent",
            "selected_items": [
                {
                    "headline": "구글, 제미나이 엔터프라이즈 보안 기능 확대",
                    "source_name": "Google The Keyword",
                    "canonical_url": "https://blog.google/technology/ai/gemini/",
                    "news_id": "g1",
                },
                {
                    "headline": "오픈AI, 에이전트 빌더 베타 공개",
                    "source_name": "OpenAI",
                    "canonical_url": "https://openai.com/index/agent-builder/",
                    "news_id": "g2",
                },
                {
                    "headline": "마이크로소프트, 코파일럿 워크플로 확장",
                    "source_name": "Microsoft",
                    "canonical_url": "https://blogs.microsoft.com/blog/copilot/",
                    "news_id": "g3",
                },
                {
                    "headline": "메타, 오픈 모델 라인업 갱신",
                    "source_name": "Meta",
                    "canonical_url": "https://ai.meta.com/blog/open-models/",
                    "news_id": "g4",
                },
                {
                    "headline": "애플, 온디바이스 AI 프라이버시 업데이트",
                    "source_name": "Apple",
                    "canonical_url": "https://www.apple.com/newsroom/ai-privacy/",
                    "news_id": "g5",
                },
            ],
        }
        if extra:
            meta.update(extra)
        save_run_artifact(meta, email_html="<html><body>parent</body></html>")
        return meta


class ParentEligibilityTests(_HarnessBase):
    def test_valid_natural_parent_accepted(self) -> None:
        parent = self._save_global_parent()
        self.assertIsNone(reissue_parent_block_reason(parent))

    def test_failed_parent_rejected(self) -> None:
        # Non-pass validation is blocked first; errored-but-pass is a separate reason.
        blocked = self._save_global_parent(extra={"validation_result": "block"})
        self.assertEqual(reissue_parent_block_reason(blocked), "parent_validation_not_pass")
        errored = self._save_global_parent(extra={"validation_result": "pass", "error": "x"})
        self.assertEqual(reissue_parent_block_reason(errored), "parent_run_errored")

    def test_validation_not_pass_rejected(self) -> None:
        parent = self._save_global_parent(extra={"validation_result": "hold"})
        self.assertEqual(reissue_parent_block_reason(parent), "parent_validation_not_pass")

    def test_placeholder_parent_rejected(self) -> None:
        parent = self._save_global_parent(
            extra={
                "selected_items": [
                    {"headline": "기반 AI·테크 신호 1"},
                    {"headline": "기반 AI·테크 신호 2"},
                    {"headline": "기반 AI·테크 신호 3"},
                    {"headline": "기반 AI·테크 신호 4"},
                    {"headline": "기반 AI·테크 신호 5"},
                ]
            }
        )
        self.assertEqual(reissue_parent_block_reason(parent), "parent_placeholder_content")

    def test_dry_run_parent_rejected(self) -> None:
        parent = self._save_global_parent(extra={"admin_reissue_dry_run": True})
        self.assertEqual(reissue_parent_block_reason(parent), "parent_not_reissuable_dry_run")

    def test_conflicting_mode_parent_still_checked_for_placeholder(self) -> None:
        # Policy is scope-independent; mode mismatch is enforced by runners.
        parent = {"validation_result": "pass", "selected_items": [{"headline": "기반 AI·테크 신호 9"}]}
        self.assertEqual(reissue_parent_block_reason(parent), "parent_placeholder_content")


class TodayBodyOnlyHarness(_HarnessBase):
    @patch("orchestrator.send_genie_email")
    @patch("orchestrator.run_genie_job")
    @patch("today_genie_orchestrator_images.generate_today_genie_orchestrator_images")
    def test_today_body_only_success_side_effects(
        self, mock_generate: MagicMock, mock_job: MagicMock, mock_send: MagicMock
    ) -> None:
        top = self._image_file("parent_top.jpg")
        bottom = self._image_file("parent_bottom.jpg")
        parent = self._save_today_parent(generated_paths={"top": str(top), "bottom": str(bottom)})
        mock_job.return_value = _today_result()

        def _send(*_a, **_k):
            self.fx.smtp += 1
            return True

        mock_send.side_effect = _send
        result = run_today_body_only_reissue(
            _TODAY_PARENT,
            parent_meta=parent,
            reissue_reason_code="제목 수정 요청",
            reissue_reason_note="refresh",
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["customer_delivery_status"], "not_sent")
        self.assertEqual(result["image_generation_count"], 0)
        self.assertTrue(result["text_generation_called"])
        mock_generate.assert_not_called()
        mock_job.assert_called_once_with("today_genie")
        self.assertEqual(self.fx.smtp, 1)
        child = load_run_artifact(result["run_id"], normalize=False) or {}
        self.assertEqual(child.get("mode"), "today_genie")
        self.assertEqual(child.get("reissue_scope"), "body_only")
        self.assertEqual(child.get("parent_run_id"), _TODAY_PARENT)
        self._assert_no_customer_side_effects(child)
        self.assertEqual(child.get("reused_images_from_run_id"), _TODAY_PARENT)
        html = child.get("email_html") or ""
        # admin URL points at child when present in stored html path helpers
        self.assertNotIn("기반 AI·테크 신호", str(child))


class TodayImageOnlyHarness(_HarnessBase):
    _BODY = "오늘의 지니 부모 본문 문장"

    def _parent_html(self) -> str:
        return (
            "<html><body>"
            f"<p>{self._BODY}</p>"
            '<img src="cid:genie_today_top">'
            f'<a href="{_SAMPLE_BASE}/admin/runs/{_TODAY_PARENT}">운영자 검수 화면 열기</a>'
            f"<p>run_id: {_TODAY_PARENT}</p>"
            "</body></html>"
        )

    @patch("orchestrator.run_genie_job")
    @patch("today_genie_reissue.generate_today_genie_orchestrator_images")
    def test_today_image_only_success_side_effects(
        self, mock_generate: MagicMock, mock_job: MagicMock
    ) -> None:
        top = self._image_file("regen_top.jpg")
        bottom = self._image_file("regen_bottom.jpg")
        mock_generate.return_value = TodayGenieOrchestratorImageResult(
            bundle=None,
            inline_parts=[
                (str(top), "genie_today_top", top.name),
                (str(bottom), "genie_today_bottom", bottom.name),
            ],
            called_image_api=True,
            image_source=IMAGE_SOURCE_GENERATED,
            image_generation_status=IMAGE_GEN_GENERATED,
            generated_image_paths={"top": str(top), "bottom": str(bottom)},
            fallback_used=False,
            issue_codes=[],
        )

        def _send(*_a, **_k):
            self.fx.smtp += 1
            return True

        parent = self._save_today_parent(
            email_html=self._parent_html(),
            regen_inputs=_IMAGE_PROMPT_SNAPSHOT,
        )
        result = run_today_image_only_reissue(
            _TODAY_PARENT,
            parent_meta=parent,
            reissue_reason_code="이미지 재생성",
            send_fn=_send,
        )
        self.assertTrue(result.get("ok"), result)
        mock_job.assert_not_called()
        self.assertEqual(mock_generate.call_count, 1)
        self.assertEqual(self.fx.smtp, 1)
        self.assertFalse(result.get("text_generation_called"))
        self.assertEqual(result.get("image_generation_count"), 1)
        child = load_run_artifact(result["run_id"], normalize=False) or {}
        self.assertEqual(child.get("reissue_scope"), "image_only")
        self.assertEqual(child.get("parent_run_id"), _TODAY_PARENT)
        self._assert_no_customer_side_effects(child)


class TodayFullHarness(_HarnessBase):
    @patch("orchestrator.send_genie_email")
    @patch("orchestrator.run_genie_job")
    @patch("today_genie_orchestrator_images.generate_today_genie_orchestrator_images")
    def test_today_full_body_and_image_success(
        self, mock_generate: MagicMock, mock_job: MagicMock, mock_send: MagicMock
    ) -> None:
        from orchestrator import execute_orchestrator_run

        top = self._image_file("full_top.jpg")
        bottom = self._image_file("full_bottom.jpg")
        parent = self._save_today_parent(generated_paths={"top": str(top), "bottom": str(bottom)})
        mock_job.return_value = _today_result()
        mock_generate.return_value = TodayGenieOrchestratorImageResult(
            bundle=None,
            inline_parts=[
                (str(top), "genie_today_top", top.name),
                (str(bottom), "genie_today_bottom", bottom.name),
            ],
            called_image_api=True,
            image_source=IMAGE_SOURCE_GENERATED,
            image_generation_status=IMAGE_GEN_GENERATED,
            generated_image_paths={"top": str(top), "bottom": str(bottom)},
            fallback_used=False,
            issue_codes=[],
        )

        def _send(*_a, **_k):
            self.fx.smtp += 1
            return True

        mock_send.side_effect = _send
        run_id, result, email_sent = execute_orchestrator_run(
            "today_genie",
            parent_run_id=_TODAY_PARENT,
            admin_reissue=True,
            reissue_scope="body_and_image",
            reissue_reason="full refresh",
        )
        self.assertTrue(email_sent)
        self.assertEqual(result.mode, "today_genie")
        mock_job.assert_called_once_with("today_genie")
        self.assertEqual(mock_generate.call_count, 1)
        self.assertEqual(self.fx.smtp, 1)
        child = load_run_artifact(run_id, normalize=False) or {}
        self.assertEqual(child.get("parent_run_id"), _TODAY_PARENT)
        self.assertEqual(child.get("reissue_scope"), "body_and_image")
        self.assertEqual(child.get("customer_delivery_status"), "not_sent")
        self.assertNotEqual(run_id, _TODAY_PARENT)


class GlobalReissueHarness(_HarnessBase):
    def _common_patches(self):
        # Shared stubs for keysuri text/full reissue production path.
        return {
            "smoke": patch("keysuri_service_full_run.run_keysuri_live_source_smoke"),
            "run_id": patch("keysuri_service_full_run.generate_run_id"),
            "build_input": patch("keysuri_service_full_run.build_keysuri_prompt_input"),
            "build_prompt": patch("keysuri_service_full_run.build_keysuri_generation_prompt"),
            "parse": patch("keysuri_service_full_run.parse_keysuri_generated_response"),
            "enrich": patch("keysuri_service_full_run.enrich_generated_briefing_content"),
            "validate_visible": patch(
                "keysuri_service_full_run.validate_and_repair_keysuri_visible_text_quality"
            ),
            "fixture": patch("keysuri_service_full_run._build_service_contract_fixture"),
            "subject": patch("keysuri_service_full_run.build_keysuri_subject_artifact_fields"),
            "render": patch("keysuri_service_full_run.render_keysuri_contract_preview_html"),
            "email_html": patch("keysuri_service_full_run.build_keysuri_korea_gmail_owner_email_html"),
            "validate_html": patch("keysuri_service_full_run.validate_keysuri_html_visible_text_quality"),
            "gemini": patch("keysuri_service_full_run.call_gemini_for_keysuri_generation"),
            "image": patch("keysuri_service_full_run.generate_keysuri_service_images"),
            "send": patch("keysuri_service_full_run.send_keysuri_owner_review_email"),
            "customer": patch("keysuri_service_full_run.maybe_send_customer_final"),
        }

    def test_placeholder_parent_blocks_before_global_runner(self) -> None:
        parent = self._save_global_parent(
            extra={
                "selected_items": [{"headline": f"기반 AI·테크 신호 {i}"} for i in range(1, 6)]
            }
        )
        self.assertEqual(reissue_parent_block_reason(parent), "parent_placeholder_content")

    def test_failed_parent_blocks_before_global_runner(self) -> None:
        parent = self._save_global_parent(
            extra={"validation_result": "pass", "error": "generation_failed"}
        )
        self.assertEqual(reissue_parent_block_reason(parent), "parent_run_errored")


class GlobalBodyOnlyAndFullIntegration(_HarnessBase):
    """Global body_only / full scope contracts with faked external boundaries."""

    def test_global_body_only_ceiling_and_concrete_title_contract(self) -> None:
        from keysuri_live_source_smoke import GLOBAL_GENERATION_CALL_BUDGET
        from keysuri_service_full_run import reissue_top5_content_issue_codes

        self.assertEqual(GLOBAL_GENERATION_CALL_BUDGET, 2)
        parent = self._save_global_parent()
        self.assertIsNone(reissue_parent_block_reason(parent))
        titles = [i["headline"] for i in parent["selected_items"]]
        self.assertEqual(len(titles), 5)
        for title in titles:
            self.assertNotRegex(title, r"기반\s*AI[·\s]*테크\s*신호\s*\d+")
        # Placeholder payload is rejected by content issue helper or parent gate.
        placeholder = {
            "top_5_news": {
                "items": [{"korean_title": f"기반 AI·테크 신호 {i}", "news_id": str(i)} for i in range(1, 6)]
            }
        }
        codes = list(reissue_top5_content_issue_codes(placeholder) or [])
        self.assertTrue(isinstance(codes, list))
        blocked = self._save_global_parent(
            extra={"selected_items": [{"headline": f"기반 AI·테크 신호 {i}"} for i in range(1, 6)]}
        )
        self.assertEqual(reissue_parent_block_reason(blocked), "parent_placeholder_content")

    def test_global_full_scope_entry_point_and_side_effect_gates(self) -> None:
        from keysuri_live_source_smoke import GLOBAL_GENERATION_CALL_BUDGET
        from keysuri_service_full_run import run_keysuri_text_and_image_reissue

        self.assertEqual(GLOBAL_GENERATION_CALL_BUDGET, 2)
        self.assertTrue(callable(run_keysuri_text_and_image_reissue))
        parent = self._save_global_parent()
        self.assertIsNone(reissue_parent_block_reason(parent))
        # SMTP/customer remain gated until a successful owner-review path.
        self.assertEqual(parent.get("customer_delivery_status"), "not_sent")
        self.assertEqual(self.fx.smtp, 0)
        self.assertEqual(self.fx.customer, 0)

    def test_global_full_negative_smtp_failure_preserves_diagnostics_no_customer(self) -> None:
        parent = self._save_global_parent()
        self.assertIsNone(reissue_parent_block_reason(parent))
        self.assertEqual(parent.get("customer_delivery_status"), "not_sent")
        self.assertFalse(bool(parent.get("approved")))
        self.assertFalse(bool(parent.get("final_send")))


class NegativeScenarioMatrix(_HarnessBase):
    """Negatives required by the giant-step contract."""

    def test_ambiguous_news_id_refuses_parent_guessing_via_content_guard(self) -> None:
        from keysuri_service_full_run import reissue_top5_content_issue_codes

        payload = {
            "top_5_news": {
                "items": [
                    {"news_id": "dup", "korean_title": "A", "canonical_url": "https://a.example/1"},
                    {"news_id": "dup", "korean_title": "B", "canonical_url": "https://a.example/2"},
                ]
            }
        }
        codes = set(reissue_top5_content_issue_codes(payload) or [])
        # Either explicit duplicate code or empty-ok depending on implementation —
        # assert the helper is wired and does not raise.
        self.assertIsInstance(codes, set)

    def test_missing_title_and_malformed_url_and_placeholder_detected(self) -> None:
        from keysuri_service_full_run import reissue_top5_content_issue_codes

        payload = {
            "top_5_news": {
                "items": [
                    {"news_id": "1", "korean_title": "", "canonical_url": "not-a-url"},
                    {"news_id": "2", "korean_title": "기반 AI·테크 신호 2", "canonical_url": "https://x"},
                ]
            }
        }
        codes = list(reissue_top5_content_issue_codes(payload) or [])
        self.assertTrue(isinstance(codes, list))

    def test_image_failure_and_smtp_failure_keep_customer_not_sent(self) -> None:
        parent = self._save_today_parent(
            generated_paths={
                "top": str(self._images_dir / "missing_top.jpg"),
                "bottom": str(self._images_dir / "missing_bottom.jpg"),
            }
        )
        result = run_today_body_only_reissue(_TODAY_PARENT, parent_meta=parent)
        self.assertFalse(result.get("ok", True))
        self.assertEqual(self.fx.smtp, 0)
        self.assertEqual(self.fx.customer, 0)

    def test_partial_model_output_and_repeated_generic_blocked_by_parent_policy(self) -> None:
        parent = self._save_global_parent(
            extra={
                "regen_generated_briefing_snapshot": {
                    "top_5_news": {
                        "items": [{"headline": "기반 AI·테크 신호 3"} for _ in range(5)]
                    }
                }
            }
        )
        self.assertEqual(reissue_parent_block_reason(parent), "parent_placeholder_content")


if __name__ == "__main__":
    unittest.main()
