"""Tests: Today_Geenee scoped admin reissue (body_only / image_only)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

from admin_store import load_run_artifact, load_run_email_html, save_run_artifact
from orchestrator import OrchestrationResult
from publishing_policy import PublishingDecision
from service_full_run_contract import IMAGE_GEN_GENERATED, IMAGE_SOURCE_GENERATED
from today_genie_orchestrator_images import (
    TODAY_IMAGE_REGEN_INPUTS_KEY,
    TodayGenieOrchestratorImageResult,
    today_image_regen_inputs,
    today_image_regen_payload_from_snapshot,
)
from today_genie_reissue import (
    ERROR_BODY_ONLY_PARENT_IMAGES_UNAVAILABLE,
    ERROR_BODY_ONLY_UNSUPPORTED_MODE,
    ERROR_IMAGE_ONLY_IMAGE_FAILED,
    ERROR_IMAGE_ONLY_MISSING_PARENT_HTML,
    ERROR_IMAGE_ONLY_MISSING_PROMPT_SNAPSHOT,
    ERROR_IMAGE_ONLY_UNSUPPORTED_MODE,
    run_today_body_only_reissue,
    run_today_image_only_reissue,
)

_SAMPLE_BASE = "https://genie-blog-run-1055014091206.asia-northeast3.run.app"
_OWNER_TO = "soulampsito@gmail.com,ey2133@naver.com"
_PARENT_RUN_ID = "20260611_150000_today_genie_aabbccdd"

_MINIMAL_DATA = {
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
                **_MINIMAL_DATA,
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


class _TodayReissueTestBase(unittest.TestCase):
    """Isolated artifact store, owner-review send gate on, no GCS bucket."""

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
        for key in ("GENIE_ADMIN_ARTIFACT_BUCKET", "GENIE_ARTIFACT_BUCKET",
                    "GENIE_ADMIN_REISSUE", "GENIE_CONTROLLED_TEST_MODE",
                    "GENIE_CONTROLLED_TEST_TARGET_DATE"):
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

    def _save_today_parent(
        self,
        *,
        run_id: str = _PARENT_RUN_ID,
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


class TodayImageRegenSnapshotTests(unittest.TestCase):
    def test_snapshot_captures_prompts_and_weather_context(self) -> None:
        snapshot = today_image_regen_inputs(
            {
                "image_prompt_studio": " studio ",
                "image_prompt_outdoor": "outdoor",
                "image_briefing_mood_state": "calm",
                "image_mood_basis": "macro",
            },
            {"target_date": "2026-06-11", "image_weather_context": {"band": "mild"}},
        )
        self.assertEqual(snapshot["image_prompt_studio"], "studio")
        self.assertEqual(snapshot["image_prompt_outdoor"], "outdoor")
        self.assertEqual(snapshot["image_briefing_mood_state"], "calm")
        self.assertEqual(snapshot["image_mood_basis"], "macro")
        self.assertEqual(snapshot["target_date"], "2026-06-11")
        self.assertEqual(snapshot["image_weather_context"], {"band": "mild"})

    def test_snapshot_empty_without_prompts(self) -> None:
        self.assertEqual(today_image_regen_inputs({"title": "x"}, {}), {})
        self.assertEqual(today_image_regen_inputs(None, None), {})

    def test_payload_roundtrip_rebuilds_generation_inputs(self) -> None:
        payload = today_image_regen_payload_from_snapshot(_IMAGE_PROMPT_SNAPSHOT)
        self.assertIsNotNone(payload)
        assert payload is not None
        data, runtime_input = payload
        self.assertEqual(data["image_prompt_studio"], "studio hero anchor")
        self.assertEqual(data["image_prompt_outdoor"], "outdoor daily morning")
        self.assertEqual(runtime_input["target_date"], "2026-06-11")
        self.assertEqual(runtime_input["image_weather_context"], {"band": "mild"})

    def test_payload_none_without_prompts(self) -> None:
        self.assertIsNone(today_image_regen_payload_from_snapshot(None))
        self.assertIsNone(today_image_regen_payload_from_snapshot({"target_date": "2026-06-11"}))


class TodayBodyOnlyReissueTests(_TodayReissueTestBase):
    @patch("orchestrator.send_genie_email")
    @patch("orchestrator.run_genie_job")
    @patch("today_genie_orchestrator_images.generate_today_genie_orchestrator_images")
    def test_body_only_regenerates_text_and_reuses_parent_images(
        self,
        mock_generate: MagicMock,
        mock_job: MagicMock,
        mock_send: MagicMock,
    ) -> None:
        top = self._image_file("parent_top.jpg")
        bottom = self._image_file("parent_bottom.jpg")
        parent = self._save_today_parent(
            generated_paths={"top": str(top), "bottom": str(bottom)}
        )
        mock_job.return_value = _today_result()
        mock_send.return_value = True

        result = run_today_body_only_reissue(
            _PARENT_RUN_ID,
            parent_meta=parent,
            reissue_reason_code="제목 수정 요청",
            reissue_reason_note="refresh copy",
        )

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["email_sent"])
        self.assertTrue(result["text_generation_called"])
        self.assertFalse(result["image_generation_called"])
        self.assertEqual(result["image_generation_count"], 0)
        self.assertEqual(result["customer_delivery_status"], "not_sent")
        # body_only must never call the image API
        mock_generate.assert_not_called()
        # text regeneration runs through the normal today pipeline exactly once
        mock_job.assert_called_once_with("today_genie")

        mock_send.assert_called_once()
        subject = mock_send.call_args.args[1]
        self.assertTrue(subject.startswith("[본문 재발행]"), subject)
        inline_paths = [part[0] for part in mock_send.call_args.kwargs["inline_jpeg_parts"]]
        self.assertEqual(inline_paths, [str(top), str(bottom)])

        child = load_run_artifact(result["run_id"], normalize=False) or {}
        self.assertEqual(child.get("reissue_scope"), "body_only")
        self.assertTrue(child.get("reissue_scope_supported"))
        self.assertEqual(child.get("reissue_scope_status"), "executed")
        self.assertEqual(child.get("reissue_reason_code"), "제목 수정 요청")
        self.assertEqual(child.get("reissue_reason_note"), "refresh copy")
        self.assertEqual(child.get("parent_run_id"), _PARENT_RUN_ID)
        self.assertEqual(child.get("customer_delivery_status"), "not_sent")
        self.assertFalse(child.get("called_image_api"))
        self.assertFalse(child.get("image_generation_called"))
        self.assertEqual(child.get("image_generation_count"), 0)
        self.assertEqual(child.get("reused_images_from_run_id"), _PARENT_RUN_ID)
        self.assertEqual(child.get("today_image_reuse_source"), "generated_run_images")
        self.assertEqual(
            child.get("generated_image_paths"), {"top": str(top), "bottom": str(bottom)}
        )
        # the regenerated body is stored, and the child stays image_only-capable
        child_html = load_run_email_html(result["run_id"]) or ""
        self.assertIn(result["run_id"], child_html)
        self.assertIn(TODAY_IMAGE_REGEN_INPUTS_KEY, child)
        self.assertEqual(
            child[TODAY_IMAGE_REGEN_INPUTS_KEY]["image_prompt_studio"],
            "regenerated studio hero",
        )

    @patch("orchestrator.send_genie_email")
    @patch("orchestrator.run_genie_job")
    def test_body_only_no_send_mode_skips_owner_email(
        self, mock_job: MagicMock, mock_send: MagicMock
    ) -> None:
        top = self._image_file("parent_top.jpg")
        bottom = self._image_file("parent_bottom.jpg")
        parent = self._save_today_parent(
            generated_paths={"top": str(top), "bottom": str(bottom)}
        )
        mock_job.return_value = _today_result()

        result = run_today_body_only_reissue(
            _PARENT_RUN_ID,
            parent_meta=parent,
            reissue_reason_code="제목 수정 요청",
            send_owner_email=False,
        )

        self.assertTrue(result["ok"], result)
        self.assertFalse(result["email_sent"])
        mock_send.assert_not_called()
        child = load_run_artifact(result["run_id"], normalize=False) or {}
        self.assertEqual(child.get("verification_mode"), "no_send_verification")
        self.assertEqual(child.get("reissue_scope"), "body_only")

    @patch("orchestrator.run_genie_job")
    def test_body_only_blocked_when_parent_images_unavailable(self, mock_job: MagicMock) -> None:
        parent = self._save_today_parent(
            generated_paths={
                "top": str(self._images_dir / "missing_top.jpg"),
                "bottom": str(self._images_dir / "missing_bottom.jpg"),
            }
        )
        result = run_today_body_only_reissue(_PARENT_RUN_ID, parent_meta=parent)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], ERROR_BODY_ONLY_PARENT_IMAGES_UNAVAILABLE)
        # no text generation when the parent's images cannot be reused
        mock_job.assert_not_called()

    def test_body_only_rejects_non_today_mode(self) -> None:
        result = run_today_body_only_reissue(
            "20260611_150000_keysuri_korea_tech_aabbccdd",
            parent_meta={"mode": "keysuri_korea_tech"},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], ERROR_BODY_ONLY_UNSUPPORTED_MODE)

    def test_body_only_passes_reuse_override_and_scope_to_orchestrator(self) -> None:
        top = self._image_file("parent_top.jpg")
        bottom = self._image_file("parent_bottom.jpg")
        parent = self._save_today_parent(
            generated_paths={"top": str(top), "bottom": str(bottom)}
        )
        calls: List[Dict[str, Any]] = []

        def fake_runner(mode: str, **kwargs: Any) -> Tuple[str, Any, bool]:
            calls.append({"mode": mode, **kwargs})
            save_run_artifact(
                {
                    "run_id": "20260611_160000_today_genie_11223344",
                    "mode": "today_genie",
                    "parent_run_id": _PARENT_RUN_ID,
                    "validation_result": "pass",
                    "response_status": 200,
                    "email_sent": True,
                }
            )
            return "20260611_160000_today_genie_11223344", _today_result(), True

        result = run_today_body_only_reissue(
            _PARENT_RUN_ID,
            parent_meta=parent,
            orchestrator_runner=fake_runner,
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call["mode"], "today_genie")
        self.assertEqual(call["reissue_scope"], "body_only")
        self.assertEqual(call["parent_run_id"], _PARENT_RUN_ID)
        self.assertTrue(call["admin_reissue"])
        override = call["today_image_result_override"]
        self.assertIsInstance(override, TodayGenieOrchestratorImageResult)
        self.assertFalse(override.called_image_api)
        self.assertFalse(override.fallback_used)
        self.assertEqual(override.image_source, IMAGE_SOURCE_GENERATED)
        self.assertEqual(override.image_generation_status, IMAGE_GEN_GENERATED)
        self.assertEqual([part[0] for part in override.inline_parts], [str(top), str(bottom)])


class TodayImageOnlyReissueTests(_TodayReissueTestBase):
    _PARENT_BODY_MARKER = "오늘의 지니 부모 본문 문장"

    def _parent_email_html(self, run_id: str = _PARENT_RUN_ID) -> str:
        return (
            "<html><body>"
            f"<p>{self._PARENT_BODY_MARKER}</p>"
            f'<img src="cid:genie_today_top">'
            f'<a href="{_SAMPLE_BASE}/admin/runs/{run_id}">운영자 검수 화면 열기</a>'
            f"<p>run_id: {run_id}</p>"
            "</body></html>"
        )

    def _fake_image_result(self) -> TodayGenieOrchestratorImageResult:
        top = self._image_file("regen_top.jpg")
        bottom = self._image_file("regen_bottom.jpg")
        return TodayGenieOrchestratorImageResult(
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

    @patch("orchestrator.run_genie_job")
    @patch("today_genie_reissue.generate_today_genie_orchestrator_images")
    def test_image_only_preserves_body_and_generates_images_once(
        self, mock_generate: MagicMock, mock_job: MagicMock
    ) -> None:
        mock_generate.return_value = self._fake_image_result()
        parent = self._save_today_parent(
            email_html=self._parent_email_html(),
            regen_inputs=_IMAGE_PROMPT_SNAPSHOT,
        )
        sent: List[Tuple[Any, ...]] = []

        def fake_send(html: str, subject: str, **kwargs: Any) -> bool:
            sent.append((html, subject, kwargs))
            return True

        result = run_today_image_only_reissue(
            _PARENT_RUN_ID,
            parent_meta=parent,
            reissue_reason_code="이미지 품질 이슈",
            reissue_reason_note="replace only images",
            send_fn=fake_send,
        )

        self.assertTrue(result["ok"], result)
        self.assertFalse(result["text_generation_called"])
        self.assertFalse(result["called_gemini"])
        self.assertTrue(result["image_generation_called"])
        self.assertEqual(result["image_generation_count"], 1)
        self.assertEqual(result["customer_delivery_status"], "not_sent")
        # no second text generation: the today API is never called
        mock_job.assert_not_called()
        # exactly one image generation pass, without a static fallback
        mock_generate.assert_called_once()
        child_run_id = result["run_id"]
        self.assertEqual(mock_generate.call_args.args[0], child_run_id)
        self.assertEqual(
            mock_generate.call_args.args[1]["image_prompt_studio"], "studio hero anchor"
        )
        self.assertEqual(mock_generate.call_args.kwargs["allow_static_fallback"], False)

        self.assertEqual(len(sent), 1)
        html, subject, kwargs = sent[0]
        self.assertTrue(subject.startswith("[이미지 재발행]"), subject)
        self.assertIn(self._PARENT_BODY_MARKER, html)
        self.assertIn(child_run_id, html)
        self.assertNotIn(_PARENT_RUN_ID, html)
        self.assertIn(f"{_SAMPLE_BASE}/admin/runs/{child_run_id}", html)
        self.assertEqual(len(kwargs["inline_jpeg_parts"]), 2)
        self.assertEqual(kwargs["attachment_jpeg_parts"], [])

        child = load_run_artifact(child_run_id, normalize=False) or {}
        self.assertEqual(child.get("reissue_scope"), "image_only")
        self.assertTrue(child.get("reissue_scope_supported"))
        self.assertEqual(child.get("reissue_scope_status"), "executed")
        self.assertEqual(child.get("reissue_reason_code"), "이미지 품질 이슈")
        self.assertEqual(child.get("reissue_reason_note"), "replace only images")
        self.assertEqual(child.get("parent_run_id"), _PARENT_RUN_ID)
        self.assertEqual(child.get("reused_body_from_run_id"), _PARENT_RUN_ID)
        self.assertTrue(child.get("regen_preserved_text"))
        self.assertTrue(child.get("regen_regenerated_images"))
        self.assertFalse(child.get("text_generation_called"))
        self.assertFalse(child.get("called_gemini"))
        self.assertEqual(child.get("image_generation_count"), 1)
        self.assertEqual(child.get("customer_delivery_status"), "not_sent")
        self.assertTrue(child.get("email_sent"))
        # stored owner-review HTML keeps the parent body verbatim
        stored_html = load_run_email_html(child_run_id) or ""
        self.assertIn(self._PARENT_BODY_MARKER, stored_html)

    @patch("today_genie_reissue.generate_today_genie_orchestrator_images")
    def test_image_only_no_send_mode_skips_owner_email(self, mock_generate: MagicMock) -> None:
        mock_generate.return_value = self._fake_image_result()
        parent = self._save_today_parent(
            email_html=self._parent_email_html(),
            regen_inputs=_IMAGE_PROMPT_SNAPSHOT,
        )
        send_fn = MagicMock(return_value=True)

        result = run_today_image_only_reissue(
            _PARENT_RUN_ID,
            parent_meta=parent,
            send_owner_email=False,
            send_fn=send_fn,
        )

        self.assertTrue(result["ok"], result)
        self.assertFalse(result["email_sent"])
        send_fn.assert_not_called()
        child = load_run_artifact(result["run_id"], normalize=False) or {}
        self.assertEqual(child.get("verification_mode"), "no_send_verification")
        self.assertFalse(child.get("smtp_attempted"))

    @patch("today_genie_reissue.generate_today_genie_orchestrator_images")
    def test_image_only_records_gate_off_without_sending(self, mock_generate: MagicMock) -> None:
        os.environ["GENIE_OWNER_REVIEW_SEND"] = "0"
        mock_generate.return_value = self._fake_image_result()
        parent = self._save_today_parent(
            email_html=self._parent_email_html(),
            regen_inputs=_IMAGE_PROMPT_SNAPSHOT,
        )
        send_fn = MagicMock(return_value=True)

        result = run_today_image_only_reissue(
            _PARENT_RUN_ID,
            parent_meta=parent,
            send_fn=send_fn,
        )

        self.assertFalse(result["ok"])
        self.assertFalse(result["email_sent"])
        send_fn.assert_not_called()
        self.assertIn("owner_review_send_gate_off", result["issue_codes"])

    @patch("today_genie_reissue.generate_today_genie_orchestrator_images")
    def test_image_only_requires_prompt_snapshot(self, mock_generate: MagicMock) -> None:
        parent = self._save_today_parent(email_html=self._parent_email_html())
        result = run_today_image_only_reissue(_PARENT_RUN_ID, parent_meta=parent)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], ERROR_IMAGE_ONLY_MISSING_PROMPT_SNAPSHOT)
        mock_generate.assert_not_called()

    @patch("today_genie_reissue.generate_today_genie_orchestrator_images")
    def test_image_only_requires_parent_email_html(self, mock_generate: MagicMock) -> None:
        parent = self._save_today_parent(regen_inputs=_IMAGE_PROMPT_SNAPSHOT)
        result = run_today_image_only_reissue(_PARENT_RUN_ID, parent_meta=parent)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], ERROR_IMAGE_ONLY_MISSING_PARENT_HTML)
        mock_generate.assert_not_called()

    @patch("today_genie_reissue.generate_today_genie_orchestrator_images")
    def test_image_only_image_failure_does_not_send(self, mock_generate: MagicMock) -> None:
        mock_generate.return_value = TodayGenieOrchestratorImageResult(
            inline_parts=[],
            called_image_api=True,
            image_generation_status="image_generation_failed",
            issue_codes=["image_generation_failed"],
        )
        parent = self._save_today_parent(
            email_html=self._parent_email_html(),
            regen_inputs=_IMAGE_PROMPT_SNAPSHOT,
        )
        send_fn = MagicMock(return_value=True)
        result = run_today_image_only_reissue(
            _PARENT_RUN_ID, parent_meta=parent, send_fn=send_fn
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], ERROR_IMAGE_ONLY_IMAGE_FAILED)
        send_fn.assert_not_called()

    @patch("today_genie_reissue.generate_today_genie_orchestrator_images")
    def test_image_only_keeps_customer_subject_free_of_reissue_marker(
        self, mock_generate: MagicMock
    ) -> None:
        from today_geenee_customer_delivery import build_customer_final_subject

        mock_generate.return_value = self._fake_image_result()
        parent = self._save_today_parent(
            email_html=self._parent_email_html(),
            regen_inputs=_IMAGE_PROMPT_SNAPSHOT,
        )
        result = run_today_image_only_reissue(
            _PARENT_RUN_ID,
            parent_meta=parent,
            send_fn=MagicMock(return_value=True),
        )
        child = load_run_artifact(result["run_id"], normalize=False) or {}
        self.assertTrue(str(child.get("owner_email_subject")).startswith("[이미지 재발행]"))
        self.assertNotIn("재발행", str(child.get("email_subject")))
        customer_subject = build_customer_final_subject(
            child, load_run_email_html(result["run_id"]) or ""
        )
        self.assertNotIn("재발행", customer_subject)
        self.assertNotIn("운영자 검토", customer_subject)

    def test_image_only_rejects_non_today_mode(self) -> None:
        result = run_today_image_only_reissue(
            "20260611_150000_keysuri_global_tech_aabbccdd",
            parent_meta={"mode": "keysuri_global_tech"},
            parent_email_html="<html><body>x</body></html>",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], ERROR_IMAGE_ONLY_UNSUPPORTED_MODE)


if __name__ == "__main__":
    unittest.main()
