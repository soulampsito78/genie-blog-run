"""Regression harness for the 2026-09-11 12:30 KeeSuri Global failure.

The natural run did not persist its source/raw artifact.  The five literal
headlines below are therefore the persisted 11:45 same-day preflight selection,
not asserted to be the natural run's exact selection.  They reproduce the
observed incident shape faithfully: a structurally valid response echoes five
distinct English evidence headlines; the canonical reader boundary withholds
all five; the old path then let the renderer rediscover five empty headlines.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import keysuri_live_source_smoke as smoke_module
from admin_store import can_approve_customer_send
from keysuri_customer_delivery import prepare_keysuri_customer_delivery
from keysuri_generation_prompt import parse_keysuri_generated_response
from keysuri_live_source_smoke import (
    GLOBAL_GENERATION_CALL_BUDGET,
    GLOBAL_READER_SURFACE_FAILURE,
    KEYSURI_READER_SURFACE_BLOCKED_CODE,
    LiveSourceSmokeResult,
    PROGRAM_GLOBAL,
    _post_parse_reader_surface_gate,
    generate_keysuri_with_bounded_recovery,
    run_keysuri_live_source_smoke,
)
from keysuri_reader_surface import PROSE_ALIASES, reader_surface_run_fields
from keysuri_service_full_run import run_keysuri_service_full_run


_ROOT = Path(__file__).resolve().parents[1]
_PROMPT = _ROOT / "ops" / "feeds" / "keysuri_global_prompt_input.sample.json"
_GENERATED = (
    _ROOT / "ops" / "feeds" / "keysuri_global_generated_briefing.sample.json"
)
_SOURCE_PACK = _ROOT / "ops" / "feeds" / "keysuri_global_sources.sample.json"

# Persisted same-day 11:45 preflight input.  See module docstring for provenance.
SAME_DAY_PREFLIGHT_HEADLINES = (
    "Physical AI Takes the Wheel: How the World’s Robotaxi Leaders Are Building With NVIDIA Technologies",
    "Skild AI Taps NVIDIA Physical AI to Teach Robots New Tasks From a Single Video",
    "Introducing the Agents API",
    "Now everyone can put data to work",
    "Furo’s founders left Silicon Valley — and it’s paying off",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _incident_pair() -> tuple[dict, dict]:
    prompt_input = _load(_PROMPT)
    generated = _load(_GENERATED)
    generated.pop("_fixture_note", None)
    for idx, (evidence, authored, headline) in enumerate(
        zip(
            prompt_input["top_5_news"]["items"],
            generated["top_5_news"]["items"],
            SAME_DAY_PREFLIGHT_HEADLINES,
        ),
        start=1,
    ):
        evidence["headline"] = headline
        evidence["summary"] = (
            f"English evidence summary for same-day preflight item {idx}, kept as input only."
        )
        authored["headline"] = headline
        authored.pop("korean_title", None)
        authored["summary"] = f"{idx}번 기술 발표의 범위와 확인된 변화를 한국어로 정리했습니다."
        authored["why_it_matters"] = (
            f"{idx}번 신호는 도입 일정과 운영 비용의 변화를 따로 확인할 사안입니다."
        )
        authored["business_implication"] = (
            f"{idx}번 항목은 후속 제품 일정과 실제 적용 사례를 우선 보겠습니다."
        )
    return prompt_input, generated


def _reader_safe_recovery(initial: dict) -> dict:
    recovered = copy.deepcopy(initial)
    for idx, item in enumerate(recovered["top_5_news"]["items"], start=1):
        item["headline"] = f"글로벌 기술 신호 {idx}의 구체적 변화"
        item["korean_title"] = item["headline"]
        item["summary"] = (
            f"{idx}번 기업이 공개한 기능과 적용 범위를 확인했습니다. "
            "발표는 제품 동작과 운영 조건을 구분해 설명합니다. "
            "적용 대상과 공개 시점을 확인할 수 있습니다."
        )
        item["what_happened"] = item["summary"]
        item["why_it_matters"] = (
            f"{idx}번 변화는 운영 비용과 도입 순서에 영향을 줍니다. "
            "기존 도구와의 연결 범위를 따로 봐야 합니다. "
            "후속 공개 수치가 판단의 기준이 됩니다."
        )
        item["why_now"] = item["why_it_matters"]
        item["business_implication"] = (
            f"후속 일정 {idx}와 실제 고객 적용 여부를 보겠습니다. "
            "도입 전에 계약 조건과 운영 범위를 확인할 필요가 있습니다. "
            "검증 결과가 나오기 전에는 효과를 단정하지 않겠습니다."
        )
        item["owner_angle"] = item["business_implication"]
        item["next_watch"] = f"{idx}번 공식 후속 일정과 적용 지표"
        item["selection_reason"] = f"{idx}번 항목은 구체적인 제품 변화가 확인돼 골랐습니다."
    return recovered


def _caller(responses: list[str]):
    calls: list[dict] = []

    def call(prompt: str, **kwargs):
        calls.append({"prompt": prompt, "kwargs": kwargs})
        if len(calls) > len(responses):
            raise AssertionError("Gemini call budget exceeded supplied responses")
        return responses[len(calls) - 1]

    return call, calls


class IncidentShapeTests(unittest.TestCase):
    def test_parse_passes_then_all_five_reader_headlines_are_withheld(self) -> None:
        prompt_input, generated = _incident_pair()
        parsed = parse_keysuri_generated_response(
            json.dumps(generated, ensure_ascii=False), PROGRAM_GLOBAL, prompt_input
        )
        self.assertEqual(parsed["parse_status"], "parsed_valid")
        self.assertEqual(parsed["issues"], [])

        blocked, enriched, fields = _post_parse_reader_surface_gate(
            parsed, program_id=PROGRAM_GLOBAL, prompt_input=prompt_input
        )

        self.assertEqual(blocked["parse_status"], "parsed_invalid")
        self.assertIsNone(blocked["generated_briefing"])
        self.assertEqual(fields["reader_surface_ready_item_count"], 0)
        items = enriched["top_5_news"]["items"]
        self.assertEqual([item["headline"] for item in items], [""] * 5)
        headline_issues = [
            issue
            for issue in blocked["issues"]
            if issue.get("code") == "top_5_news_item_headline_missing"
        ]
        self.assertEqual(len(headline_issues), 5)
        self.assertEqual(
            [issue["path"] for issue in headline_issues],
            [f"top_5_news.items[{i}].headline" for i in range(5)],
        )

    def test_withheld_evidence_never_survives_in_any_reader_alias(self) -> None:
        prompt_input, generated = _incident_pair()
        parsed = parse_keysuri_generated_response(
            json.dumps(generated, ensure_ascii=False), PROGRAM_GLOBAL, prompt_input
        )
        _blocked, enriched, _fields = _post_parse_reader_surface_gate(
            parsed, program_id=PROGRAM_GLOBAL, prompt_input=prompt_input
        )
        visible = " ".join(
            str(item.get(field) or "")
            for item in enriched["top_5_news"]["items"]
            for field in PROSE_ALIASES
        )
        for headline in SAME_DAY_PREFLIGHT_HEADLINES:
            self.assertNotIn(headline, visible)


class BoundedReaderRecoveryTests(unittest.TestCase):
    def test_post_enrichment_failure_spends_only_remaining_call_and_recovers(self) -> None:
        prompt_input, initial = _incident_pair()
        recovered = _reader_safe_recovery(initial)
        caller, calls = _caller(
            [
                json.dumps(initial, ensure_ascii=False),
                json.dumps(recovered, ensure_ascii=False),
            ]
        )

        result = generate_keysuri_with_bounded_recovery(
            prompt_input,
            gemini_caller=caller,
            usage_sink={},
            validate_reader_surface=True,
        )

        self.assertEqual(len(calls), 2)
        self.assertLessEqual(len(calls), GLOBAL_GENERATION_CALL_BUDGET)
        self.assertIn("GLOBAL_READER_SURFACE_FAILURE", calls[1]["prompt"])
        self.assertIn("authored Korean reader copy", calls[1]["prompt"])
        self.assertEqual(result["parse_result"]["parse_status"], "parsed_valid")
        fields = reader_surface_run_fields(result["reader_surface_briefing"])
        self.assertTrue(fields["reader_surface_complete"])
        diag = result["generation_diagnostics"]
        self.assertEqual(diag["generation_recovery_family"], GLOBAL_READER_SURFACE_FAILURE)
        self.assertEqual(diag["global_generation_call_count"], 2)
        self.assertEqual(diag["global_recovery_result"], "succeeded")

    def test_second_source_echo_safe_fails_without_restoring_prior_candidate(self) -> None:
        prompt_input, incident = _incident_pair()
        raw = json.dumps(incident, ensure_ascii=False)
        caller, calls = _caller([raw, raw])

        result = generate_keysuri_with_bounded_recovery(
            prompt_input,
            gemini_caller=caller,
            usage_sink={},
            validate_reader_surface=True,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(result["parse_result"]["parse_status"], "parsed_invalid")
        self.assertIsNone(result["parse_result"]["generated_briefing"])
        codes = [issue["code"] for issue in result["parse_result"]["issues"]]
        self.assertEqual(codes.count("top_5_news_item_headline_missing"), 5)
        diag = result["generation_diagnostics"]
        self.assertEqual(diag["global_recovery_result"], "failed")
        self.assertFalse(diag["global_recovery_fallback_to_prior_parse"])
        self.assertEqual(diag["recovery_reader_surface_ready_item_count"], 0)

    def test_production_smoke_call_site_enables_reader_surface_validation(self) -> None:
        prompt_input = _load(_PROMPT)
        blocked_parse = {
            "parse_status": "parsed_invalid",
            "program_id": PROGRAM_GLOBAL,
            "issues": [
                {
                    "code": KEYSURI_READER_SURFACE_BLOCKED_CODE,
                    "message": "reader surface withheld required prose",
                    "path": "top_5_news.items",
                }
            ],
            "generated_briefing": None,
            "parse_meta": {"parse_failure_stage": "post_enrichment_reader_surface"},
            "generation_contract": {},
        }
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp, patch.object(
            smoke_module, "build_keysuri_prompt_input", return_value=prompt_input
        ), patch.object(
            smoke_module,
            "generate_keysuri_with_bounded_recovery",
            return_value={
                "raw_text": "{}",
                "parse_result": blocked_parse,
                "prompt_input": prompt_input,
                "generation_diagnostics": {
                    "generation_attempt_count": 2,
                    "generation_recovery_attempted": True,
                    "generation_recovery_family": GLOBAL_READER_SURFACE_FAILURE,
                    "generation_recovery_result": "failed",
                },
            },
        ) as generate:
            result = run_keysuri_live_source_smoke(
                program_id=PROGRAM_GLOBAL,
                allow_network=False,
                use_gemini=True,
                frozen_source_pack_path=_SOURCE_PACK,
                out_dir=Path(tmp),
                gemini_caller=MagicMock(),
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.parse_status, "parsed_invalid")
        generate.assert_called_once()
        self.assertIs(generate.call_args.kwargs["validate_reader_surface"], True)


class DurableSafeFailureTests(unittest.TestCase):
    @patch("keysuri_service_full_run.save_run_artifact")
    def test_service_wrapper_persists_reader_failure_before_image_or_smtp(
        self, save_artifact: MagicMock
    ) -> None:
        image_runner = MagicMock()
        send_fn = MagicMock()
        diagnostics = {
            "generation_attempt_count": 2,
            "generation_recovery_attempted": True,
            "generation_recovery_family": GLOBAL_READER_SURFACE_FAILURE,
            "generation_recovery_result": "failed",
            "initial_generation_issue_codes": [KEYSURI_READER_SURFACE_BLOCKED_CODE],
            "recovery_generation_issue_codes": [
                KEYSURI_READER_SURFACE_BLOCKED_CODE,
                *("top_5_news_item_headline_missing" for _ in range(5)),
            ],
            "global_recovery_attempted": True,
            "global_recovery_reason": KEYSURI_READER_SURFACE_BLOCKED_CODE,
            "global_recovery_error_codes": [KEYSURI_READER_SURFACE_BLOCKED_CODE],
            "global_recovery_call_count": 1,
            "global_recovery_result": "failed",
            "global_generation_call_count": 2,
            "global_generation_call_budget": 2,
            "initial_reader_surface_ready_item_count": 0,
            "initial_reader_surface_unavailable_fields": [
                f"global-claim-{i}:headline" for i in range(5)
            ],
            "recovery_reader_surface_ready_item_count": 0,
            "recovery_reader_surface_unavailable_fields": [
                f"global-claim-{i}:headline" for i in range(5)
            ],
        }
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            pack_path = Path(tmp) / "source-pack.json"
            pack_path.write_text(_SOURCE_PACK.read_text(encoding="utf-8"), encoding="utf-8")
            smoke = LiveSourceSmokeResult(
                ok=False,
                program_id=PROGRAM_GLOBAL,
                source_pack_path=str(pack_path),
                html_path="",
                fetched_item_count=5,
                feed_urls_used=[],
                sample_marker_pass=False,
                placeholder_gate_pass=False,
                called_gemini=True,
                use_gemini=True,
                parse_status="parsed_invalid",
                parse_meta={
                    "parse_failure_stage": "post_enrichment_reader_surface",
                    "reader_surface_complete": False,
                },
                validation_issues=[
                    KEYSURI_READER_SURFACE_BLOCKED_CODE,
                    *("top_5_news_item_headline_missing" for _ in range(5)),
                ],
                generation_diagnostics=diagnostics,
                error=KEYSURI_READER_SURFACE_BLOCKED_CODE,
            )

            payload = run_keysuri_service_full_run(
                PROGRAM_GLOBAL,
                smoke_runner=lambda **_kwargs: smoke,
                image_canary_runner=image_runner,
                send_fn=send_fn,
            )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["run_id"], save_artifact.call_args.args[0]["run_id"])
        self.assertEqual(payload["validation_result"], "block")
        self.assertEqual(payload["error"], "validation_blocked")
        self.assertEqual(payload["issue_codes"][0], KEYSURI_READER_SURFACE_BLOCKED_CODE)
        self.assertFalse(payload["called_image_api"])
        self.assertFalse(payload["smtp_attempted"])
        self.assertFalse(payload["email_sent"])
        image_runner.assert_not_called()
        send_fn.assert_not_called()
        save_artifact.assert_called_once()
        saved = save_artifact.call_args.args[0]
        self.assertEqual(saved["generation_recovery_family"], GLOBAL_READER_SURFACE_FAILURE)
        self.assertEqual(saved["recovery_reader_surface_ready_item_count"], 0)
        self.assertEqual(saved["customer_send"], 0)

    @patch("natural_run_recovery.send_recovery_report", return_value=(False, "report"))
    @patch("natural_run_recovery.save_incident")
    @patch("natural_run_recovery.complete_recovery")
    @patch("natural_run_recovery.acquire_recovery_lease", return_value="lease-token")
    @patch("natural_run_recovery.load_incident")
    @patch("admin_store.update_run_artifact")
    def test_recovery_sees_content_failure_not_control_plane_failure(
        self,
        _update_artifact: MagicMock,
        load_incident: MagicMock,
        _lease: MagicMock,
        complete: MagicMock,
        save_incident: MagicMock,
        _report: MagicMock,
    ) -> None:
        from natural_run_recovery import execute_approved_recovery

        incident = {
            "incident_id": "2026-09-11_keysuri_global_tech_12-30",
            "program_id": PROGRAM_GLOBAL,
            "scheduled_slot": "12:30",
            "original_run_id": "original-run",
            "status": "recovery_pending",
            "first_failed_stage": "generation_validation",
        }
        updated = {**incident, "status": "recovery_failed"}
        load_incident.side_effect = [incident, updated]
        runner_payload = {
            "ok": False,
            "run_id": "20260911_123159_keysuri_global_tech_readerblocked",
            "program_id": PROGRAM_GLOBAL,
            "validation_result": "block",
            "artifact_status": "stored",
            "email_sent": False,
            "customer_send": 0,
            # Match the real service wrapper: the broad error is structural,
            # while the first issue code retains the precise reader failure.
            "error": "validation_blocked",
            "issue_codes": [KEYSURI_READER_SURFACE_BLOCKED_CODE],
        }

        result = execute_approved_recovery(
            incident["incident_id"],
            keysuri_runner=lambda *_args, **_kwargs: runner_payload,
        )

        self.assertFalse(result["ok"])
        signature = complete.call_args.kwargs["failure_signature_components"]
        self.assertIsInstance(signature, dict)
        self.assertEqual(
            signature["issue_code"],
            KEYSURI_READER_SURFACE_BLOCKED_CODE,
        )
        self.assertEqual(signature["structural_failure_class"], "validation_blocked")
        saved_incident = save_incident.call_args.args[0]
        self.assertNotIn("recovery_control_error", saved_incident)


class CustomerSendDefenseTests(unittest.TestCase):
    @staticmethod
    def _meta() -> dict:
        return {
            "mode": PROGRAM_GLOBAL,
            "program_id": PROGRAM_GLOBAL,
            "owner_review_status": "pending_review",
            "customer_delivery_status": "not_sent",
            "validation_result": "pass",
            "artifact_status": "stored",
            "customer_surface_status": "READY",
            "safety_verdict": "SAFE",
            "editorial_verdict": "READY",
            "reader_surface_enforced": True,
            "reader_surface_complete": False,
            "reader_surface_ready_item_count": 0,
        }

    def test_admin_approval_rejects_incomplete_reader_surface(self) -> None:
        ok, reason = can_approve_customer_send(self._meta(), has_email_html=True)
        self.assertFalse(ok)
        self.assertEqual(reason, "keysuri_reader_surface_incomplete")

    def test_admin_approval_rejects_unverified_reader_surface(self) -> None:
        for enforced in (None, False):
            with self.subTest(reader_surface_enforced=enforced):
                meta = self._meta()
                if enforced is None:
                    meta.pop("reader_surface_enforced")
                else:
                    meta["reader_surface_enforced"] = enforced
                ok, reason = can_approve_customer_send(meta, has_email_html=True)
                self.assertFalse(ok)
                self.assertEqual(reason, "keysuri_reader_surface_unverified")

    def test_delivery_preparation_rejects_incomplete_reader_surface(self) -> None:
        prepared = prepare_keysuri_customer_delivery(
            '<html><body><table role="presentation"></table></body></html>',
            self._meta(),
            recipients_override=["reader@example.invalid"],
        )
        self.assertFalse(prepared["ok"])
        self.assertEqual(prepared["error"], "KEYSURI_READER_SURFACE_INCOMPLETE")

    def test_delivery_preparation_rejects_unverified_reader_surface(self) -> None:
        for enforced in (None, False):
            with self.subTest(reader_surface_enforced=enforced):
                meta = self._meta()
                if enforced is None:
                    meta.pop("reader_surface_enforced")
                else:
                    meta["reader_surface_enforced"] = enforced
                prepared = prepare_keysuri_customer_delivery(
                    '<html><body><table role="presentation"></table></body></html>',
                    meta,
                    recipients_override=["reader@example.invalid"],
                )
                self.assertFalse(prepared["ok"])
                self.assertEqual(
                    prepared["error"], "KEYSURI_READER_SURFACE_UNVERIFIED"
                )


if __name__ == "__main__":
    unittest.main()
