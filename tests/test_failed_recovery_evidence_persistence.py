"""Failed recovery admin_run evidence persistence closeout.

Proves that a terminal post-generation failure equivalent to recovery #1
(20260807_131133_keysuri_global_tech_96d921fa / keysuri_korean_connector_ellipsis_blocked)
persists a bounded diagnostic contract on admin_run — without changing generation
or validation semantics, and without SMTP/customer send.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from keysuri_live_source_smoke import PROGRAM_GLOBAL, PROGRAM_KOREA, LiveSourceSmokeResult
from keysuri_visible_text_quality import KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED
from service_full_run_contract import IMAGE_SOURCE_GENERATED, ServiceImageOutcome

_REPO = Path(__file__).resolve().parents[1]
_FIXTURE = (
    _REPO
    / "ops"
    / "feeds"
    / "incident_fixtures"
    / "20260807_131133_keysuri_global_recovery1_ellipsis.json"
)
_FORBIDDEN_SUBSTRINGS = (
    "sk-",
    "Bearer ",
    "smtp_password",
    "BEGIN PRIVATE KEY",
    "raw_prompt",
    "hidden_reasoning",
)


def _still_blocking_ellipsis_briefing() -> dict:
    """Pattern that remains blocked after the curly-quote delimiter patch."""
    return {
        "title": "글로벌 브리핑",
        "summary": "요약",
        "top_5_news": {
            "items": [
                {
                    "news_id": "n1",
                    "headline": "제목1",
                    "what_happened": "확인 불가 (…)",
                },
                {"news_id": "n2", "headline": "제목2", "what_happened": "정상 문장입니다."},
                {"news_id": "n3", "headline": "제목3", "what_happened": "정상입니다."},
            ]
        },
    }


def _prompt_with_selected_news() -> dict:
    return {
        "program_id": PROGRAM_GLOBAL,
        "prompt_status": "ready_for_generation",
        "news_scope": "global_tech",
        "top_5_news": {
            "items": [
                {"news_id": "news_alpha_001", "headline": "Alpha headline"},
                {"news_id": "news_beta_002", "headline": "Beta headline"},
                {"news_id": "news_gamma_003", "headline": "Gamma headline"},
            ]
        },
        "selected_items": [
            {"news_id": "news_alpha_001"},
            {"news_id": "news_beta_002"},
            {"news_id": "news_gamma_003"},
        ],
        "source_pack": {"sources": [], "program_id": PROGRAM_GLOBAL},
    }


def _smoke_with_evidence(pack_path: Path, raw_path: Path) -> LiveSourceSmokeResult:
    smoke = LiveSourceSmokeResult(
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
        generated_briefing=_still_blocking_ellipsis_briefing(),
        side_effects={"called_gemini": True, "called_image_api": False},
    )
    smoke.generation_diagnostics = {
        "program_id": PROGRAM_GLOBAL,
        "finish_reason": "STOP",
        "text_length": 4200,
        "candidate_count": 1,
        "max_output_tokens": 8192,
        "retry_applied": False,
        "generation_attempt_count": 2,
        "global_generation_call_count": 2,
        "global_generation_call_budget": 2,
        "issue_codes": [],
        "raw_model_response": "SHOULD_NEVER_PERSIST_FULL_BODY",
        "prompt_text": "SHOULD_NEVER_PERSIST_PROMPT",
    }
    smoke.generation_contract = {
        "model_identifier": "gemini-test-model",
        "schema_fingerprint": "fp_test_abc",
        "program_id": PROGRAM_GLOBAL,
    }
    smoke.parse_meta = {
        "global_contract_scaffold_attempted": True,
        "global_contract_scaffold_applied": False,
    }
    return smoke


class FailedRecoveryEvidencePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._artifact_root = Path(self._tmpdir.name) / "artifacts"
        self._artifact_root.mkdir(parents=True, exist_ok=True)
        self._env = patch.dict(
            os.environ,
            {
                "GENIE_OWNER_REVIEW_SEND": "1",
                "GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com",
                "GENIE_ADMIN_ARTIFACT_BUCKET": "",
                "GENIE_ARTIFACT_BUCKET": "",
                "K_REVISION": "genie-blog-run-00283-p77",
                "COMMIT_SHA": "39ff1df9d870a7e0c0999f950a51a82d236be679",
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def _assert_no_forbidden_leak(self, payload: object) -> None:
        blob = json.dumps(payload, ensure_ascii=False, default=str)
        for needle in _FORBIDDEN_SUBSTRINGS:
            self.assertNotIn(needle, blob)
        self.assertNotIn("SHOULD_NEVER_PERSIST", blob)
        self.assertNotIn("owner@private.example", blob.lower())

    @patch("keysuri_service_full_run.emit_owner_review_failure_from_artifact_meta")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run._generate_keysuri_service_image")
    @patch("keysuri_service_full_run.generate_run_id")
    def test_01_global_recovery_visible_text_failure_persists_full_bounded_diagnostics(
        self,
        mock_run_id: MagicMock,
        mock_image: MagicMock,
        mock_prompt_input: MagicMock,
        _mock_emit: MagicMock,
    ) -> None:
        from admin_store import load_run_artifact, update_run_artifact
        from keysuri_service_full_run import run_keysuri_service_full_run

        fx = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        run_id = fx["run_id"]
        mock_run_id.return_value = run_id
        pack_path = self._artifact_root / "pack_recovery1.json"
        pack_path.write_text(
            json.dumps({"sources": [], "program_id": PROGRAM_GLOBAL}), encoding="utf-8"
        )
        raw_path = self._artifact_root / "raw_recovery1.txt"
        raw_path.write_text("{}", encoding="utf-8")
        image_rel = _REPO / "output" / "images" / "keysuri_global_evidence_block.jpg"
        image_rel.parent.mkdir(parents=True, exist_ok=True)
        image_rel.write_bytes(b"\xff\xd8\xff" + b"\x00" * 128)
        mock_image.return_value = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path=str(image_rel.relative_to(_REPO)),
        )
        mock_prompt_input.return_value = _prompt_with_selected_news()
        smoke = _smoke_with_evidence(pack_path, raw_path)
        mock_send = MagicMock(return_value=True)

        payload = run_keysuri_service_full_run(
            PROGRAM_GLOBAL,
            trigger_source="manual_service_full_run",
            smoke_runner=lambda **_kw: smoke,
            send_fn=mock_send,
        )

        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("error"), KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED)
        mock_send.assert_not_called()

        # Stamp recovery identity the same way natural_run_recovery does.
        def _stamp(meta: dict) -> None:
            meta["execution_class"] = "recovery"
            meta["original_incident_id"] = fx["incident_id"]
            meta["incident_id"] = fx["incident_id"]

        update_run_artifact(run_id, _stamp)
        saved = load_run_artifact(run_id, normalize=False) or {}

        self.assertEqual(saved.get("execution_class"), "recovery")
        self.assertEqual(saved.get("incident_id"), fx["incident_id"])
        self.assertEqual(saved.get("run_id"), run_id)
        self.assertEqual(saved.get("program_id"), PROGRAM_GLOBAL)
        self.assertEqual(saved.get("deployed_revision"), "genie-blog-run-00283-p77")
        self.assertEqual(
            saved.get("deployed_commit_sha"),
            "39ff1df9d870a7e0c0999f950a51a82d236be679",
        )
        self.assertEqual(saved.get("selected_news_ids"), [
            "news_alpha_001",
            "news_beta_002",
            "news_gamma_003",
        ])
        self.assertTrue(isinstance(saved.get("generation_diagnostics"), dict))
        self.assertEqual(
            saved["generation_diagnostics"].get("generation_attempt_count"), 2
        )
        self.assertIn(
            KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED,
            saved.get("issue_codes") or [],
        )
        self.assertEqual(saved.get("first_failed_stage"), "generation_validation")
        self.assertEqual(saved.get("model_identifier"), "gemini-test-model")
        scaffold = saved.get("scaffold_status") or {}
        self.assertTrue(scaffold.get("eligible") or scaffold.get("attempted"))
        self.assertFalse(scaffold.get("applied"))
        self.assertFalse(saved.get("email_sent"))
        self.assertEqual(saved.get("customer_send"), 0)
        self.assertFalse(saved.get("smtp_attempted"))
        samples = saved.get("visible_text_quality_samples") or []
        self.assertTrue(samples)
        self._assert_no_forbidden_leak(saved)

        # Survive reload / restart (second load).
        reloaded = load_run_artifact(run_id, normalize=False) or {}
        self.assertEqual(reloaded.get("generation_diagnostics"), saved.get("generation_diagnostics"))
        self.assertEqual(reloaded.get("selected_news_ids"), saved.get("selected_news_ids"))
        self.assertEqual(reloaded.get("deployed_revision"), saved.get("deployed_revision"))
        self.assertEqual(reloaded.get("first_failed_stage"), "generation_validation")

    def test_02_attach_helper_malformed_contract_and_deepest_stage(self) -> None:
        from keysuri_service_full_run import attach_bounded_post_generation_failure_evidence
        from owner_review_failure_events import infer_first_failed_stage

        smoke = LiveSourceSmokeResult(
            ok=False,
            program_id=PROGRAM_GLOBAL,
            source_pack_path="",
            html_path="",
            fetched_item_count=0,
            feed_urls_used=[],
            sample_marker_pass=False,
            called_gemini=True,
            use_gemini=True,
            contract_preview=False,
            parse_status="parsed_invalid",
            raw_response_path="",
            preview_overall_status="FAIL",
            validation_status="FAIL",
            generated_briefing=None,
            side_effects={"called_gemini": True},
        )
        smoke.generation_diagnostics = {
            "program_id": PROGRAM_GLOBAL,
            "finish_reason": "MAX_TOKENS",
            "issue_codes": ["malformed_contract"],
            "generation_attempt_count": 2,
            "global_generation_call_budget": 2,
        }
        smoke.parse_meta = {
            "global_contract_scaffold_attempted": True,
            "global_contract_scaffold_applied": True,
        }
        meta = {
            "run_id": "20260807_999999_keysuri_global_tech_deadbeef",
            "program_id": PROGRAM_GLOBAL,
            "error_code": "validation_blocked",
            "validation_result": "block",
            "issue_codes": ["malformed_contract"],
            "first_failed_stage": "generation_validation",
            "raw_prompt": "DROP_ME",
            "raw_model_response": "DROP_ME_TOO",
        }
        out = attach_bounded_post_generation_failure_evidence(meta, smoke=smoke)
        self.assertEqual(out.get("first_failed_stage"), "generation_validation")
        self.assertNotIn("raw_prompt", out)
        self.assertNotIn("raw_model_response", out)
        self.assertTrue(isinstance(out.get("generation_diagnostics"), dict))
        self.assertEqual(out.get("scaffold_status", {}).get("applied"), True)
        # Watchdog can consume without inventing a shallower stage.
        derived = infer_first_failed_stage(
            error_code=out.get("error_code"),
            validation_result=out.get("validation_result"),
        )
        self.assertEqual(derived, "generation_validation")
        self.assertEqual(out.get("first_failed_stage"), derived)

    def test_03_attach_does_not_overwrite_deeper_first_failed_stage(self) -> None:
        from keysuri_service_full_run import attach_bounded_post_generation_failure_evidence

        smoke = LiveSourceSmokeResult(
            ok=True,
            program_id=PROGRAM_GLOBAL,
            source_pack_path="",
            html_path="",
            fetched_item_count=1,
            feed_urls_used=[],
            sample_marker_pass=True,
            called_gemini=True,
            use_gemini=True,
            contract_preview=False,
            parse_status="parsed_valid",
            raw_response_path="",
            preview_overall_status="PASS",
            validation_status="PASS",
            generated_briefing={},
            side_effects={},
        )
        meta = {
            "error_code": "smtp_delivery_failed",
            "validation_result": "pass",
            "first_failed_stage": "email_delivery",
        }
        out = attach_bounded_post_generation_failure_evidence(meta, smoke=smoke)
        self.assertEqual(out.get("first_failed_stage"), "email_delivery")

    def test_04_success_path_does_not_route_through_failed_artifact_helper(self) -> None:
        import inspect

        from keysuri_service_full_run import (
            _run_keysuri_service_full_run_impl,
            attach_bounded_post_generation_failure_evidence,
        )

        src = inspect.getsource(_run_keysuri_service_full_run_impl)
        self.assertIn("attach_bounded_post_generation_failure_evidence", src)
        self.assertIn("_save_failed_run_artifact", src)
        # Evidence enrichment is only invoked from the failed-artifact helper.
        self.assertEqual(
            src.count("attach_bounded_post_generation_failure_evidence("),
            1,
        )
        self.assertTrue(callable(attach_bounded_post_generation_failure_evidence))
        # Success path still saves via save_run_artifact outside the failure helper.
        self.assertGreater(src.count("save_run_artifact("), 1)

    def test_05_korea_and_today_compatible_attach(self) -> None:
        from keysuri_service_full_run import attach_bounded_post_generation_failure_evidence

        for program_id in (PROGRAM_KOREA, "miraion_today"):
            smoke = LiveSourceSmokeResult(
                ok=False,
                program_id=program_id if program_id != "miraion_today" else PROGRAM_KOREA,
                source_pack_path="",
                html_path="",
                fetched_item_count=0,
                feed_urls_used=[],
                sample_marker_pass=False,
                called_gemini=True,
                use_gemini=True,
                contract_preview=False,
                parse_status="parsed_invalid",
                raw_response_path="",
                preview_overall_status="FAIL",
                validation_status="FAIL",
                generated_briefing=None,
                side_effects={},
            )
            smoke.generation_diagnostics = {
                "program_id": program_id,
                "finish_reason": "STOP",
                "generation_attempt_count": 1,
            }
            meta = {
                "program_id": program_id,
                "error_code": "validation_blocked",
                "validation_result": "block",
                "issue_codes": ["korea_or_today_compatible"],
            }
            out = attach_bounded_post_generation_failure_evidence(meta, smoke=smoke)
            self.assertEqual(out.get("program_id"), program_id)
            self.assertTrue(isinstance(out.get("generation_diagnostics"), dict))
            self.assertEqual(out.get("customer_send"), 0)
            self.assertFalse(out.get("smtp_attempted"))


if __name__ == "__main__":
    unittest.main()
