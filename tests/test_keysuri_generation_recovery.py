from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from typing import List, Optional, Tuple
from unittest.mock import MagicMock, patch

import keysuri_live_source_smoke as recovery_module
from keysuri_live_source_smoke import (
    LiveSourceSmokeResult,
    PROGRAM_KOREA,
    RECOVERY_RECONCILIATION_INSUFFICIENT,
    SEMANTIC_SCOPE_FAILURE,
    STRUCTURAL_CONTRACT_FAILURE,
    generate_keysuri_with_bounded_recovery,
)
from keysuri_service_full_run import (
    IMAGE_SOURCE_GENERATED,
    ServiceImageOutcome,
    run_keysuri_service_full_run,
)


_REPO = Path(__file__).resolve().parents[1]
_PROMPT_PATH = _REPO / "ops" / "feeds" / "keysuri_korea_prompt_input.sample.json"
_GENERATED_PATH = (
    _REPO / "ops" / "feeds" / "keysuri_korea_generated_briefing.sample.json"
)


def _prompt_input() -> dict:
    return json.loads(_PROMPT_PATH.read_text(encoding="utf-8"))


def _generated() -> dict:
    return json.loads(_GENERATED_PATH.read_text(encoding="utf-8"))


def _structural_corrective_generated() -> dict:
    payload = _generated()
    payload["deep_dive"]["source_ids"] = list(
        payload["top_5_news"]["items"][0]["source_ids"]
    )
    return payload


def _three_incomplete_fragments(marker: str = "") -> str:
    return "\n".join(
        [
            json.dumps({"program_id": "keysuri_korea_tech", "marker": marker}),
            json.dumps({"top_5_news": {"items": []}}),
            json.dumps({"deep_dive": {"body": "incomplete"}}),
        ]
    )


def _fake_caller(
    responses: List[str],
    usages: Optional[List[Tuple[int, int]]] = None,
):
    calls: list[dict] = []

    def _call(prompt: str, **kwargs):
        idx = len(calls)
        calls.append({"prompt": prompt, "kwargs": kwargs})
        if idx >= len(responses):
            raise AssertionError(
                f"Gemini caller invoked {idx + 1} times but only {len(responses)} "
                "mock response(s) were provided"
            )
        if usages:
            if idx >= len(usages):
                raise AssertionError(
                    f"Gemini caller invoked {idx + 1} times but only {len(usages)} "
                    "usage tuple(s) were provided"
                )
            input_tokens, output_tokens = usages[idx]
            sink = kwargs.get("usage_sink")
            if isinstance(sink, dict):
                sink.update(
                    {
                        "model": "fake-gemini",
                        "prompt_token_count": input_tokens,
                        "candidates_token_count": output_tokens,
                        "total_token_count": input_tokens + output_tokens,
                    }
                )
        return responses[idx]

    return _call, calls


def _add_ranked_replacement(prompt_input: dict) -> dict:
    replacement_source = {
        "source_id": "korea-replacement-source-1",
        "source_name": "전자신문",
        "source_url": "https://example.com/korea-ai-semiconductor-investment",
        "source_tier": "T2_TIER1_WIRE",
        "fetched_at": "2026-07-24T12:00:00+09:00",
        "title": "국내 AI 반도체 투자 확대",
    }
    replacement_claim = {
        "claim_id": "korea-replacement-claim-1",
        "statement": "국내 AI 반도체 투자가 확대됐다.",
        "claim_type": "company_action",
        "source_ids": [replacement_source["source_id"]],
        "confidence_label": "reported",
        "category": "korea_semiconductor",
        "headline": "국내 AI 반도체 투자 확대",
        "summary": "국내 기업이 AI 반도체 투자 계획을 확대했다.",
        "why_it_matters": "국내 반도체 공급망과 기업 투자 계획에 영향을 준다.",
        "business_implication": "국내 사업자는 공급망 기회를 점검해야 한다.",
    }
    prompt_input["source_pack"]["backfill_sources"] = [replacement_source]
    prompt_input["source_pack"]["backfill_claims"] = [replacement_claim]
    return replacement_claim


def _semantic_initial_failure() -> dict:
    payload = _generated()
    payload["top_5_news"]["items"][0]["headline"] = "미국 총격 사고로 3명 사망"
    payload["top_5_news"]["items"][0]["summary"] = "해외 범죄 사고 소식"
    return payload


def _semantic_corrective_response(prompt_input: dict, replacement_claim: dict) -> dict:
    payload = _generated()
    source_map = recovery_module._source_map_for_reconciliation(prompt_input["source_pack"])
    replacement_item = recovery_module._claim_to_news_item(
        replacement_claim, rank=1, smap=source_map
    )
    payload["top_5_news"]["items"][0] = replacement_item
    payload["deep_dive"]["source_ids"] = list(replacement_item["source_ids"])
    old_source_id = "korea-t0-policy-official"
    payload["closing_sources"]["source_list"] = [
        row
        for row in payload["closing_sources"]["source_list"]
        if row.get("source_id") != old_source_id
    ]
    payload["closing_sources"]["source_list"].append(
        {
            "source_id": replacement_item["source_ids"][0],
            "label": "전자신문",
            "url": "https://example.com/korea-ai-semiconductor-investment",
            "tier": "T2_TIER1_WIRE",
        }
    )
    return payload


class BoundedStructuralRecoveryTests(unittest.TestCase):
    def test_three_fragments_then_valid_single_json_calls_gemini_twice(self) -> None:
        prompt_input = _prompt_input()
        first_raw = _three_incomplete_fragments("FIRST_RAW_MUST_NOT_BE_REPEATED")
        caller, calls = _fake_caller(
            [first_raw, json.dumps(_structural_corrective_generated(), ensure_ascii=False)],
            usages=[(101, 41), (53, 29)],
        )
        usage: dict = {}

        result = generate_keysuri_with_bounded_recovery(
            prompt_input, gemini_caller=caller, usage_sink=usage
        )

        diagnostics = result["generation_diagnostics"]
        self.assertEqual(result["parse_result"]["parse_status"], "parsed_valid")
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            diagnostics["generation_recovery_family"], STRUCTURAL_CONTRACT_FAILURE
        )
        self.assertEqual(diagnostics["generation_recovery_result"], "succeeded")
        self.assertEqual(diagnostics["generation_attempt_count"], 2)
        self.assertNotIn("FIRST_RAW_MUST_NOT_BE_REPEATED", calls[1]["prompt"])
        self.assertIn("BOUNDED CORRECTIVE GENERATION (attempt 2 of 2)", calls[1]["prompt"])
        expected_order = [
            (item["rank"], item["news_id"], item["source_ids"])
            for item in prompt_input["top_5_news"]["items"]
        ]
        actual_order = [
            (item["rank"], item["news_id"], item["source_ids"])
            for item in result["parse_result"]["generated_briefing"]["top_5_news"]["items"]
        ]
        self.assertEqual(actual_order, expected_order)
        self.assertEqual(diagnostics["initial_input_tokens"], 101)
        self.assertEqual(diagnostics["initial_output_tokens"], 41)
        self.assertEqual(diagnostics["recovery_input_tokens"], 53)
        self.assertEqual(diagnostics["recovery_output_tokens"], 29)
        self.assertEqual(diagnostics["total_input_tokens"], 154)
        self.assertEqual(diagnostics["total_output_tokens"], 70)
        self.assertEqual(usage["prompt_token_count"], 154)
        self.assertEqual(usage["candidates_token_count"], 70)

    def test_second_structural_failure_stops_at_two_attempts(self) -> None:
        caller, calls = _fake_caller(
            [_three_incomplete_fragments("one"), _three_incomplete_fragments("two")]
        )

        result = generate_keysuri_with_bounded_recovery(
            _prompt_input(), gemini_caller=caller, usage_sink={}
        )

        self.assertEqual(result["parse_result"]["parse_status"], "parsed_invalid")
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            result["generation_diagnostics"]["generation_recovery_result"], "failed"
        )
        self.assertEqual(
            result["generation_diagnostics"]["generation_attempt_count"], 2
        )

    def test_valid_first_response_uses_one_call_and_initial_usage_only(self) -> None:
        caller, calls = _fake_caller(
            [json.dumps(_generated(), ensure_ascii=False)], usages=[(77, 31)]
        )
        result = generate_keysuri_with_bounded_recovery(
            _prompt_input(), gemini_caller=caller, usage_sink={}
        )
        diagnostics = result["generation_diagnostics"]
        self.assertEqual(result["parse_result"]["parse_status"], "parsed_valid")
        self.assertEqual(len(calls), 1)
        self.assertFalse(diagnostics["generation_recovery_attempted"])
        self.assertEqual(diagnostics["generation_attempt_count"], 1)
        self.assertEqual(diagnostics["total_input_tokens"], 77)
        self.assertEqual(diagnostics["total_output_tokens"], 31)

    def test_unknown_validation_failure_is_not_retried(self) -> None:
        unknown = _generated()
        unknown["deep_dive"]["body"] = ""
        caller, calls = _fake_caller([json.dumps(unknown, ensure_ascii=False)])

        result = generate_keysuri_with_bounded_recovery(
            _prompt_input(), gemini_caller=caller, usage_sink={}
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            result["generation_diagnostics"]["generation_recovery_result"],
            "not_attempted_unknown_failure",
        )


class DeterministicSemanticRecoveryTests(unittest.TestCase):
    @patch("keysuri_live_source_smoke.recent_sent_news_log", return_value=[])
    def test_irrelevant_item_uses_ranked_pool_replacement_only(
        self, _mock_recent: MagicMock
    ) -> None:
        prompt_input = _prompt_input()
        replacement_claim = _add_ranked_replacement(prompt_input)
        corrected = _semantic_corrective_response(prompt_input, replacement_claim)
        caller, calls = _fake_caller(
            [
                json.dumps(_semantic_initial_failure(), ensure_ascii=False),
                json.dumps(corrected, ensure_ascii=False),
            ]
        )

        result = generate_keysuri_with_bounded_recovery(
            prompt_input, gemini_caller=caller, usage_sink={}
        )
        diagnostics = result["generation_diagnostics"]

        self.assertEqual(result["parse_result"]["parse_status"], "parsed_valid")
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            diagnostics["generation_recovery_family"], SEMANTIC_SCOPE_FAILURE
        )
        self.assertTrue(diagnostics["reconciled_top5"])
        self.assertEqual(
            diagnostics["replaced_source_ids"], ["korea-t0-policy-official"]
        )
        self.assertEqual(
            diagnostics["replacement_source_ids"], ["korea-replacement-source-1"]
        )
        self.assertIn("korea-replacement-claim-1", calls[1]["prompt"])
        self.assertNotIn("korea-claim-policy-support", calls[1]["prompt"])
        self.assertNotIn("https://arbitrary.invalid", calls[1]["prompt"])
        final_items = result["parse_result"]["generated_briefing"]["top_5_news"]["items"]
        self.assertEqual(len(final_items), 5)
        self.assertEqual(final_items[0]["news_id"], "korea-replacement-claim-1")

    @patch("keysuri_live_source_smoke.recent_sent_news_log", return_value=[])
    def test_ranked_pool_skips_first_out_of_scope_candidate(
        self, _mock_recent: MagicMock
    ) -> None:
        prompt_input = _prompt_input()
        replacement_claim = _add_ranked_replacement(prompt_input)
        prompt_input["source_pack"]["backfill_sources"].insert(
            0,
            {
                "source_id": "foreign-accident-source",
                "source_name": "Foreign Crime Desk",
                "source_url": "https://example.com/foreign-accident",
                "source_tier": "T3_QUALITY_PRESS",
                "fetched_at": "2026-07-24T11:00:00+09:00",
                "title": "미국 총격 사고로 사망자 발생",
            },
        )
        prompt_input["source_pack"]["backfill_claims"].insert(
            0,
            {
                "claim_id": "foreign-accident-claim",
                "statement": "미국 총격 사고로 사망자가 발생했다.",
                "claim_type": "company_action",
                "source_ids": ["foreign-accident-source"],
                "confidence_label": "reported",
                "category": "korea_ai_enterprise",
                "headline": "미국 총격 사고로 사망자 발생",
                "summary": "해외 범죄 사고 소식이다.",
                "why_it_matters": "기술과 무관하다.",
                "business_implication": "기술 사업과 무관하다.",
            },
        )
        corrected = _semantic_corrective_response(prompt_input, replacement_claim)
        caller, calls = _fake_caller(
            [
                json.dumps(_semantic_initial_failure(), ensure_ascii=False),
                json.dumps(corrected, ensure_ascii=False),
            ]
        )

        result = generate_keysuri_with_bounded_recovery(
            prompt_input, gemini_caller=caller, usage_sink={}
        )

        self.assertEqual(result["parse_result"]["parse_status"], "parsed_valid")
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            result["generation_diagnostics"]["replacement_source_ids"],
            ["korea-replacement-source-1"],
        )
        self.assertNotIn("foreign-accident-claim", calls[1]["prompt"])

    @patch("keysuri_live_source_smoke.recent_sent_news_log", return_value=[])
    def test_insufficient_replacement_pool_skips_corrective_call(
        self, _mock_recent: MagicMock
    ) -> None:
        caller, calls = _fake_caller(
            [json.dumps(_semantic_initial_failure(), ensure_ascii=False)]
        )

        result = generate_keysuri_with_bounded_recovery(
            _prompt_input(), gemini_caller=caller, usage_sink={}
        )

        self.assertEqual(len(calls), 1)
        diagnostics = result["generation_diagnostics"]
        self.assertFalse(diagnostics["generation_recovery_attempted"])
        self.assertEqual(
            diagnostics["generation_recovery_result"],
            "not_attempted_reconciliation_failed",
        )
        self.assertIn(
            RECOVERY_RECONCILIATION_INSUFFICIENT,
            diagnostics["recovery_generation_issue_codes"],
        )

    def test_recent_sent_duplicate_replacement_is_rejected_without_retry(self) -> None:
        prompt_input = _prompt_input()
        replacement_claim = _add_ranked_replacement(prompt_input)
        caller, calls = _fake_caller(
            [json.dumps(_semantic_initial_failure(), ensure_ascii=False)]
        )
        duplicate_row = {
            "title": replacement_claim["headline"],
            "url": "https://example.com/korea-ai-semiconductor-investment",
            "source": "전자신문",
        }

        with patch(
            "keysuri_live_source_smoke.recent_sent_news_log",
            return_value=[duplicate_row],
        ):
            result = generate_keysuri_with_bounded_recovery(
                prompt_input, gemini_caller=caller, usage_sink={}
            )

        self.assertEqual(len(calls), 1)
        self.assertIn(
            RECOVERY_RECONCILIATION_INSUFFICIENT,
            result["generation_diagnostics"]["recovery_generation_issue_codes"],
        )

    @patch("keysuri_live_source_smoke.recent_sent_news_log", return_value=[])
    def test_corrective_response_cannot_invent_source_id_or_url(
        self, _mock_recent: MagicMock
    ) -> None:
        prompt_input = _prompt_input()
        replacement_claim = _add_ranked_replacement(prompt_input)
        corrected = _semantic_corrective_response(prompt_input, replacement_claim)
        corrected["top_5_news"]["items"][0]["source_ids"] = ["invented-source-id"]
        corrected["top_5_news"]["items"][0]["url"] = "https://arbitrary.invalid/story"
        caller, calls = _fake_caller(
            [
                json.dumps(_semantic_initial_failure(), ensure_ascii=False),
                json.dumps(corrected, ensure_ascii=False),
            ]
        )

        result = generate_keysuri_with_bounded_recovery(
            prompt_input, gemini_caller=caller, usage_sink={}
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(result["parse_result"]["parse_status"], "parsed_invalid")
        self.assertEqual(
            result["generation_diagnostics"]["generation_recovery_result"], "failed"
        )
        self.assertIn(
            "top_5_fixed_source_ids_mismatch",
            result["generation_diagnostics"]["recovery_generation_issue_codes"],
        )
        self.assertIn(
            "top_5_unapproved_url",
            result["generation_diagnostics"]["recovery_generation_issue_codes"],
        )


class RecoverySafetyAndObservabilityTests(unittest.TestCase):
    def test_recovery_logs_safe_info_events_once_without_raw_or_secret(self) -> None:
        marker = "RAW_SECRET_TOKEN_123"
        caller, _calls = _fake_caller(
            [
                _three_incomplete_fragments(marker),
                json.dumps(_structural_corrective_generated(), ensure_ascii=False),
            ]
        )
        with self.assertLogs("keysuri_live_source_smoke", level="INFO") as captured:
            generate_keysuri_with_bounded_recovery(
                _prompt_input(), gemini_caller=caller, usage_sink={}
            )
        text = "\n".join(captured.output)
        self.assertEqual(
            text.count('"event": "keysuri_initial_generation_validation_failure"'), 1
        )
        self.assertEqual(
            text.count('"event": "keysuri_generation_recovery_attempted"'), 1
        )
        self.assertEqual(
            text.count('"event": "keysuri_generation_recovery_succeeded"'), 1
        )
        self.assertNotIn(marker, text)
        self.assertNotIn("CORRECTIVE_CONTEXT", text)

    def test_application_logging_configuration_is_idempotent(self) -> None:
        from main import configure_application_logging

        app_logger = logging.getLogger("keysuri_live_source_smoke")
        google_logger = logging.getLogger("google")
        configure_application_logging()
        first_owned = [
            handler
            for handler in app_logger.handlers
            if getattr(handler, "_genie_application_handler", False)
        ]
        first_level = app_logger.level
        configure_application_logging()
        second_owned = [
            handler
            for handler in app_logger.handlers
            if getattr(handler, "_genie_application_handler", False)
        ]
        self.assertEqual(app_logger.level, first_level)
        self.assertEqual(app_logger.level, logging.INFO)
        self.assertEqual(google_logger.level, logging.WARNING)
        self.assertEqual(len(second_owned), len(first_owned))
        if first_owned:
            self.assertEqual(second_owned, first_owned)

    def test_successful_recovery_runs_image_and_owner_email_exactly_once(self) -> None:
        prompt_input = _prompt_input()
        caller, gemini_calls = _fake_caller(
            [
                _three_incomplete_fragments("initial"),
                json.dumps(_structural_corrective_generated(), ensure_ascii=False),
            ]
        )
        image_runner = MagicMock()
        send_fn = MagicMock(return_value=True)
        safe_html = "<html><body>주인님 국내 테크 브리핑입니다.</body></html>"
        qa_pass = type("QaPass", (), {"ok": True, "issues": [], "warnings": []})()

        with tempfile.TemporaryDirectory(dir="/tmp") as tmp_dir:
            temp_dir = Path(tmp_dir)
            pack_path = temp_dir / "pack.json"
            pack_path.write_text(
                json.dumps(prompt_input["source_pack"], ensure_ascii=False),
                encoding="utf-8",
            )
            raw_path = temp_dir / "raw.txt"
            raw_path.write_text("{}", encoding="utf-8")
            image_path = temp_dir / "top.jpg"
            image_path.write_bytes(b"\xff\xd8\xff" + b"\x00" * 128)
            image_runner.return_value = ServiceImageOutcome(
                called_image_api=True,
                image_generation_status="generated",
                image_source=IMAGE_SOURCE_GENERATED,
                generated_image_path=str(image_path),
            )

            def _smoke_runner(**kwargs):
                generated = generate_keysuri_with_bounded_recovery(
                    prompt_input,
                    gemini_caller=caller,
                    usage_sink=kwargs["usage_sink"],
                )
                return LiveSourceSmokeResult(
                    ok=True,
                    program_id=PROGRAM_KOREA,
                    source_pack_path=str(pack_path),
                    html_path="",
                    fetched_item_count=5,
                    feed_urls_used=[],
                    sample_marker_pass=True,
                    called_gemini=True,
                    use_gemini=True,
                    parse_status="parsed_valid",
                    validation_status="PASS",
                    preview_overall_status="PASS_OWNER_REVIEW_READY",
                    generated_briefing=generated["parse_result"]["generated_briefing"],
                    generation_diagnostics=generated["generation_diagnostics"],
                    raw_response_path=str(raw_path),
                    side_effects={
                        "called_gemini": True,
                        "called_image_api": False,
                    },
                )

            def _watermark(source: Path, target: Path) -> Path:
                target.write_bytes(Path(source).read_bytes())
                return target

            with ExitStack() as stack:
                stack.enter_context(patch(
                    "keysuri_service_full_run.build_keysuri_prompt_input",
                    return_value=prompt_input,
                ))
                stack.enter_context(patch(
                    "keysuri_service_full_run.apply_keysuri_mirai_on_watermark",
                    side_effect=_watermark,
                ))
                stack.enter_context(patch(
                    "keysuri_service_full_run.resolve_korea_bottom_email_image_path",
                    return_value=(None, [], {}),
                ))
                stack.enter_context(patch(
                    "keysuri_service_full_run.render_keysuri_contract_preview_html",
                    return_value=safe_html,
                ))
                stack.enter_context(patch(
                    "keysuri_service_full_run.build_keysuri_korea_gmail_owner_email_html",
                    return_value=safe_html,
                ))
                stack.enter_context(patch(
                    "keysuri_service_full_run.validate_korea_post_render_visible_quality",
                    return_value=qa_pass,
                ))
                stack.enter_context(patch("keysuri_service_full_run.save_run_artifact"))
                stack.enter_context(
                    patch("keysuri_service_full_run._maybe_write_owner_review_exposure_log")
                )
                stack.enter_context(patch(
                    "keysuri_service_full_run.save_cost_record_best_effort",
                    return_value={},
                ))
                stack.enter_context(patch.dict(
                    os.environ,
                    {
                        "GENIE_OWNER_REVIEW_SEND": "1",
                        "GENIE_ADMIN_PUBLIC_BASE_URL": "https://example.com",
                        "KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED": "off",
                    },
                    clear=False,
                ))
                result = run_keysuri_service_full_run(
                    PROGRAM_KOREA,
                    smoke_runner=_smoke_runner,
                    image_canary_runner=image_runner,
                    send_fn=send_fn,
                )

        self.assertTrue(result["ok"])
        self.assertEqual(len(gemini_calls), 2)
        self.assertEqual(result["generation_recovery_result"], "succeeded")
        image_runner.assert_called_once()
        send_fn.assert_called_once()

    @patch("keysuri_service_full_run.save_run_artifact")
    def test_failed_recovery_persists_diagnostics_before_image_or_smtp(
        self, save_artifact: MagicMock
    ) -> None:
        image_runner = MagicMock()
        send_fn = MagicMock()
        diagnostics = {
            "generation_attempt_count": 2,
            "generation_recovery_attempted": True,
            "generation_recovery_family": STRUCTURAL_CONTRACT_FAILURE,
            "generation_recovery_result": "failed",
            "initial_generation_issue_codes": [
                "parse_multiple_json_objects_unrecoverable"
            ],
            "recovery_generation_issue_codes": ["json_extract_failed"],
            "initial_input_tokens": 100,
            "initial_output_tokens": 30,
            "recovery_input_tokens": 80,
            "recovery_output_tokens": 15,
            "total_input_tokens": 180,
            "total_output_tokens": 45,
            "reconciled_top5": False,
            "replaced_source_ids": [],
            "replacement_source_ids": [],
        }
        smoke = LiveSourceSmokeResult(
            ok=False,
            program_id=PROGRAM_KOREA,
            source_pack_path="/tmp/korea-recovery-pack.json",
            html_path="",
            fetched_item_count=10,
            feed_urls_used=[],
            sample_marker_pass=False,
            placeholder_gate_pass=False,
            called_gemini=True,
            use_gemini=True,
            parse_status="parsed_invalid",
            validation_issues=["json_extract_failed"],
            generation_diagnostics=diagnostics,
            error="Gemini parse failed safely",
        )

        result = run_keysuri_service_full_run(
            PROGRAM_KOREA,
            smoke_runner=lambda **_kwargs: smoke,
            image_canary_runner=image_runner,
            send_fn=send_fn,
        )

        self.assertFalse(result["ok"])
        self.assertFalse(result["called_image_api"])
        self.assertFalse(result["smtp_attempted"])
        self.assertFalse(result["email_sent"])
        image_runner.assert_not_called()
        send_fn.assert_not_called()
        save_artifact.assert_called_once()
        meta = save_artifact.call_args.args[0]
        for key, value in diagnostics.items():
            self.assertEqual(meta[key], value)
            self.assertEqual(result[key], value)
        saved_html = save_artifact.call_args.kwargs.get("email_html")
        if saved_html is None and len(save_artifact.call_args.args) > 1:
            saved_html = save_artifact.call_args.args[1]
        self.assertEqual(saved_html, "")
        self.assertNotIn("raw_response", json.dumps(meta, ensure_ascii=False))


class NewsIdSemanticMappingTests(unittest.TestCase):
    def _shuffled_semantic_failure(self) -> tuple[dict, dict, str]:
        """Return (prompt_input, generated_payload, target_news_id).

        Generated response moves original rank-3 item to position 0 and marks it
        semantically irrelevant there.
        """
        prompt_input = _prompt_input()
        generated = _generated()
        original_items = copy.deepcopy(prompt_input["top_5_news"]["items"])
        # Rotate so original rank 3 (index 2) becomes generated index 0.
        shuffled = original_items[2:] + original_items[:2]
        for idx, item in enumerate(shuffled):
            item["rank"] = idx + 1
        generated["top_5_news"]["items"] = shuffled
        target_news_id = str(original_items[2]["news_id"])
        generated["top_5_news"]["items"][0]["headline"] = "미국 총격 사고로 3명 사망"
        generated["top_5_news"]["items"][0]["summary"] = "해외 범죄 사고 소식"
        return prompt_input, generated, target_news_id

    def test_shuffled_generated_index_maps_to_original_rank_by_news_id(self) -> None:
        prompt_input, generated, target_news_id = self._shuffled_semantic_failure()
        parse_result = {
            "parse_status": "parsed_invalid",
            "generated_briefing": generated,
            "issues": [
                {
                    "code": "korea_tech_top5_irrelevant_item",
                    "path": "top_5_news.items[0].headline",
                    "message": "irrelevant",
                }
            ],
        }
        mapped = recovery_module._original_indexes_for_semantic_item_issues(
            parse_result, prompt_input
        )
        self.assertEqual(mapped, [2])
        self.assertEqual(
            prompt_input["top_5_news"]["items"][2]["news_id"], target_news_id
        )
        self.assertNotEqual(
            prompt_input["top_5_news"]["items"][0]["news_id"], target_news_id
        )

    @patch("keysuri_live_source_smoke.recent_sent_news_log", return_value=[])
    def test_reconcile_replaces_original_rank3_not_rank1_when_shuffled(
        self, _mock_recent: MagicMock
    ) -> None:
        prompt_input, generated, target_news_id = self._shuffled_semantic_failure()
        original_rank1 = prompt_input["top_5_news"]["items"][0]["news_id"]
        replacement_claim = _add_ranked_replacement(prompt_input)
        parse_result = {
            "parse_status": "parsed_invalid",
            "generated_briefing": generated,
            "issues": [
                {
                    "code": "korea_tech_top5_irrelevant_item",
                    "path": "top_5_news.items[0]",
                    "message": "irrelevant",
                }
            ],
        }
        fixed, replaced, replacement = recovery_module._reconcile_korea_top5(
            prompt_input, parse_result
        )
        self.assertIsNotNone(fixed)
        items = fixed["top_5_news"]["items"]
        self.assertEqual(items[0]["news_id"], original_rank1)
        self.assertEqual(items[2]["news_id"], replacement_claim["claim_id"])
        self.assertNotEqual(items[2]["news_id"], target_news_id)
        self.assertEqual(replacement, ["korea-replacement-source-1"])
        self.assertTrue(replaced)

    @patch("keysuri_live_source_smoke.recent_sent_news_log", return_value=[])
    def test_multiple_semantic_items_map_independently(
        self, _mock_recent: MagicMock
    ) -> None:
        prompt_input = _prompt_input()
        generated = _generated()
        # Keep order; mark generated indexes 0 and 2 irrelevant.
        for idx in (0, 2):
            generated["top_5_news"]["items"][idx]["headline"] = f"해외 사고 {idx}"
            generated["top_5_news"]["items"][idx]["summary"] = "해외 범죄"
        # Two distinct replacements
        first = _add_ranked_replacement(prompt_input)
        second_source = {
            "source_id": "korea-replacement-source-2",
            "source_name": "디지털타임스",
            "source_url": "https://example.com/korea-cloud-expansion",
            "source_tier": "T2_TIER1_WIRE",
            "fetched_at": "2026-07-24T12:05:00+09:00",
            "title": "국내 클라우드 투자 확대",
        }
        second_claim = {
            "claim_id": "korea-replacement-claim-2",
            "statement": "국내 클라우드 투자가 확대됐다.",
            "claim_type": "company_action",
            "source_ids": [second_source["source_id"]],
            "confidence_label": "reported",
            "category": "korea_ai_enterprise",
            "headline": "국내 클라우드 투자 확대",
            "summary": "국내 기업이 클라우드 투자를 늘렸다.",
            "why_it_matters": "국내 IT 인프라 투자에 영향을 준다.",
            "business_implication": "국내 사업자는 클라우드 공급망을 점검해야 한다.",
        }
        prompt_input["source_pack"]["backfill_sources"].append(second_source)
        prompt_input["source_pack"]["backfill_claims"].append(second_claim)
        parse_result = {
            "parse_status": "parsed_invalid",
            "generated_briefing": generated,
            "issues": [
                {
                    "code": "korea_tech_top5_irrelevant_item",
                    "path": "top_5_news.items[0].headline",
                },
                {
                    "code": "korea_tech_top5_irrelevant_item",
                    "path": "top_5_news.items[2].summary",
                },
                {
                    "code": "top_5_unapproved_url",
                    "path": "top_5_news.items[0].url",
                },
            ],
        }
        mapped = recovery_module._original_indexes_for_semantic_item_issues(
            parse_result, prompt_input
        )
        self.assertEqual(mapped, [0, 2])
        fixed, _replaced, replacement_ids = recovery_module._reconcile_korea_top5(
            prompt_input, parse_result
        )
        self.assertIsNotNone(fixed)
        items = fixed["top_5_news"]["items"]
        self.assertEqual(items[0]["news_id"], first["claim_id"])
        self.assertEqual(items[2]["news_id"], second_claim["claim_id"])
        self.assertEqual(
            set(replacement_ids),
            {"korea-replacement-source-1", "korea-replacement-source-2"},
        )

    def test_unmappable_news_id_does_not_replace_arbitrary_item(self) -> None:
        prompt_input = _prompt_input()
        original_ids = [
            item["news_id"] for item in prompt_input["top_5_news"]["items"]
        ]
        generated = _generated()
        generated["top_5_news"]["items"][0]["news_id"] = "not-in-original-top5"
        generated["top_5_news"]["items"][0]["headline"] = "미국 총격 사고"
        _add_ranked_replacement(prompt_input)
        parse_result = {
            "parse_status": "parsed_invalid",
            "generated_briefing": generated,
            "issues": [
                {
                    "code": "korea_tech_top5_irrelevant_item",
                    "path": "top_5_news.items[0]",
                }
            ],
        }
        fixed, replaced, replacement = recovery_module._reconcile_korea_top5(
            prompt_input, parse_result
        )
        self.assertIsNotNone(fixed)
        self.assertEqual(replaced, [])
        self.assertEqual(replacement, [])
        self.assertEqual(
            [item["news_id"] for item in fixed["top_5_news"]["items"]],
            original_ids,
        )

    def test_out_of_range_generated_index_does_not_replace(self) -> None:
        prompt_input = _prompt_input()
        original_ids = [
            item["news_id"] for item in prompt_input["top_5_news"]["items"]
        ]
        generated = _generated()
        parse_result = {
            "parse_status": "parsed_invalid",
            "generated_briefing": generated,
            "issues": [
                {
                    "code": "korea_tech_top5_irrelevant_item",
                    "path": "top_5_news.items[9]",
                }
            ],
        }
        fixed, replaced, replacement = recovery_module._reconcile_korea_top5(
            prompt_input, parse_result
        )
        self.assertEqual(replaced, [])
        self.assertEqual(replacement, [])
        self.assertEqual(
            [item["news_id"] for item in fixed["top_5_news"]["items"]],
            original_ids,
        )

    def test_sequence_mismatch_alone_does_not_change_selection(self) -> None:
        prompt_input = _prompt_input()
        original_ids = [
            item["news_id"] for item in prompt_input["top_5_news"]["items"]
        ]
        generated = _generated()
        parse_result = {
            "parse_status": "parsed_invalid",
            "generated_briefing": generated,
            "issues": [
                {
                    "code": "top_5_sequence_mismatch",
                    "path": "top_5_news.items",
                    "message": "order changed",
                }
            ],
        }
        fixed, replaced, replacement = recovery_module._reconcile_korea_top5(
            prompt_input, parse_result
        )
        self.assertEqual(replaced, [])
        self.assertEqual(replacement, [])
        self.assertEqual(
            [item["news_id"] for item in fixed["top_5_news"]["items"]],
            original_ids,
        )


class UsageNonePreservationTests(unittest.TestCase):
    def test_both_usage_missing_totals_are_none(self) -> None:
        outer: dict = {}
        totals = recovery_module._merge_generation_usage(
            outer,
            {
                "model": "fake",
                "prompt_token_count": None,
                "candidates_token_count": None,
                "thoughts_token_count": None,
                "total_token_count": None,
            },
            {},
        )
        self.assertIsNone(totals["initial_input_tokens"])
        self.assertIsNone(totals["initial_output_tokens"])
        self.assertIsNone(totals["recovery_input_tokens"])
        self.assertIsNone(totals["total_input_tokens"])
        self.assertIsNone(totals["total_output_tokens"])
        self.assertIsNone(outer.get("prompt_token_count"))
        self.assertIsNone(outer.get("total_token_count"))

    def test_initial_only_preserves_values_and_nones(self) -> None:
        outer: dict = {"stale": 1}
        totals = recovery_module._merge_generation_usage(
            outer,
            {
                "model": "fake",
                "prompt_token_count": 77,
                "candidates_token_count": 31,
                "thoughts_token_count": None,
                "total_token_count": 108,
            },
            {},
        )
        self.assertEqual(totals["total_input_tokens"], 77)
        self.assertEqual(totals["total_output_tokens"], 31)
        self.assertIsNone(totals["recovery_input_tokens"])
        self.assertEqual(outer["prompt_token_count"], 77)
        self.assertEqual(outer["total_token_count"], 108)
        self.assertIsNone(outer["thoughts_token_count"])
        self.assertNotIn("stale", outer)

    def test_recovery_only_sums_with_none_initial(self) -> None:
        outer: dict = {}
        totals = recovery_module._merge_generation_usage(
            outer,
            {
                "prompt_token_count": None,
                "candidates_token_count": None,
                "total_token_count": None,
            },
            {
                "prompt_token_count": 50,
                "candidates_token_count": 20,
                "thoughts_token_count": 5,
                "total_token_count": 75,
            },
        )
        self.assertIsNone(totals["initial_input_tokens"])
        self.assertEqual(totals["recovery_input_tokens"], 50)
        self.assertIsNone(totals["total_input_tokens"])
        self.assertIsNone(totals["total_output_tokens"])
        self.assertEqual(totals["partial_input_tokens"], 50)
        self.assertEqual(totals["partial_output_tokens"], 20)
        self.assertFalse(totals["input_tokens_complete"])
        self.assertFalse(totals["output_tokens_complete"])
        self.assertIsNone(outer["prompt_token_count"])
        self.assertIsNone(outer["candidates_token_count"])
        self.assertEqual(outer["prompt_token_count_partial_sum"], 50)
        self.assertEqual(outer["cost_estimate_status_hint"], "partial_usage_unpriced")

    def test_both_present_sum(self) -> None:
        outer: dict = {}
        totals = recovery_module._merge_generation_usage(
            outer,
            {"prompt_token_count": 100, "candidates_token_count": 40, "total_token_count": 140},
            {"prompt_token_count": 50, "candidates_token_count": 20, "total_token_count": 70},
        )
        self.assertEqual(totals["total_input_tokens"], 150)
        self.assertEqual(totals["total_output_tokens"], 60)
        self.assertTrue(totals["input_tokens_complete"])
        self.assertTrue(totals["output_tokens_complete"])
        self.assertEqual(outer["prompt_token_count"], 150)
        self.assertEqual(outer["total_token_count"], 210)
        self.assertTrue(outer["usage_tokens_complete"])

    def test_partial_none_fields_do_not_become_zero(self) -> None:
        outer: dict = {}
        totals = recovery_module._merge_generation_usage(
            outer,
            {
                "prompt_token_count": 10,
                "candidates_token_count": None,
                "thoughts_token_count": None,
                "total_token_count": None,
            },
            {
                "prompt_token_count": None,
                "candidates_token_count": 7,
                "thoughts_token_count": None,
                "total_token_count": None,
            },
        )
        self.assertIsNone(totals["total_input_tokens"])
        self.assertIsNone(totals["total_output_tokens"])
        self.assertEqual(totals["partial_input_tokens"], 10)
        self.assertEqual(totals["partial_output_tokens"], 7)
        self.assertFalse(totals["input_tokens_complete"])
        self.assertFalse(totals["output_tokens_complete"])
        self.assertIsNone(outer["prompt_token_count"])
        self.assertIsNone(outer["candidates_token_count"])
        self.assertIsNone(outer["thoughts_token_count"])
        self.assertIsNone(outer["total_token_count"])
        self.assertEqual(outer["prompt_token_count_partial_sum"], 10)
        self.assertEqual(outer["candidates_token_count_partial_sum"], 7)
        self.assertEqual(outer["cost_estimate_status_hint"], "partial_usage_unpriced")

    def test_zero_tokens_remain_distinct_from_none(self) -> None:
        outer: dict = {}
        recovery_module._merge_generation_usage(
            outer,
            {
                "prompt_token_count": 0,
                "candidates_token_count": 0,
                "thoughts_token_count": 0,
                "total_token_count": 0,
            },
            {},
        )
        self.assertEqual(outer["prompt_token_count"], 0)
        self.assertEqual(outer["total_token_count"], 0)

    def test_cost_estimator_marks_unavailable_when_usage_none(self) -> None:
        from genie_cost_estimate import estimate_genie_generation_cost

        usage: dict = {}
        recovery_module._merge_generation_usage(
            usage,
            {
                "model": "fake",
                "prompt_token_count": None,
                "candidates_token_count": None,
                "thoughts_token_count": None,
                "total_token_count": None,
            },
            {},
        )
        estimate = estimate_genie_generation_cost(
            usage, service_family="keysuri", text_model="fake"
        )
        self.assertEqual(estimate.get("cost_estimate_status"), "unavailable")

    def test_cost_estimator_does_not_fully_price_partial_usage(self) -> None:
        from keysuri_cost_estimate import estimate_keysuri_gemini_cost

        usage: dict = {}
        recovery_module._merge_generation_usage(
            usage,
            {
                "model": "fake",
                "prompt_token_count": 100,
                "candidates_token_count": 40,
                "total_token_count": 140,
            },
            {
                "prompt_token_count": None,
                "candidates_token_count": None,
                "total_token_count": None,
            },
        )
        estimate = estimate_keysuri_gemini_cost(usage, model="fake")
        self.assertEqual(estimate.get("cost_estimate_status"), "partial_usage_unpriced")
        self.assertIsNone(estimate.get("total_cost_usd"))
        self.assertNotEqual(
            estimate.get("cost_estimate_status"), "fully_priced_ai_model_cost"
        )
    def test_global_initial_success_usage_dict_unchanged_shape(self) -> None:
        """Global path must not invent recovery usage or coerce missing fields to 0.

        Uses a pre-validated Global briefing sample when available; otherwise
        exercises the no-recovery early-return with a valid parse mock.
        """
        global_generated_path = (
            _REPO / "ops" / "feeds" / "keysuri_global_generated_briefing.sample.json"
        )
        global_prompt_path = (
            _REPO / "ops" / "feeds" / "keysuri_global_prompt_input.sample.json"
        )
        if global_prompt_path.is_file() and global_generated_path.is_file():
            prompt_input = json.loads(global_prompt_path.read_text(encoding="utf-8"))
            generated = json.loads(global_generated_path.read_text(encoding="utf-8"))
        else:
            prompt_input = _prompt_input()
            prompt_input["program_id"] = "keysuri_global_tech"
            generated = _generated()
            generated["program_id"] = "keysuri_global_tech"

        caller, calls = _fake_caller(
            [json.dumps(generated, ensure_ascii=False)], usages=[(88, 22)]
        )
        usage: dict = {}
        result = generate_keysuri_with_bounded_recovery(
            prompt_input, gemini_caller=caller, usage_sink=usage
        )
        self.assertEqual(len(calls), 1)
        self.assertFalse(result["generation_diagnostics"]["generation_recovery_attempted"])
        self.assertEqual(result["generation_diagnostics"]["generation_recovery_result"], "not_needed")
        self.assertEqual(usage["prompt_token_count"], 88)
        self.assertEqual(usage["candidates_token_count"], 22)
        self.assertEqual(usage["total_token_count"], 110)
        self.assertEqual(result["generation_diagnostics"]["total_input_tokens"], 88)
        self.assertIsNone(result["generation_diagnostics"]["recovery_input_tokens"])


class StrictDiversityReconciliationTests(unittest.TestCase):
    def _same_source_replacement(self, prompt_input: dict, source_id: str, source_name: str) -> dict:
        source = {
            "source_id": source_id,
            "source_name": source_name,
            "source_url": "https://example.com/same-source-dup",
            "source_tier": "T2_TIER1_WIRE",
            "fetched_at": "2026-07-24T12:10:00+09:00",
            "title": "국내 AI 보안 투자 확대",
        }
        claim = {
            "claim_id": "korea-same-source-claim",
            "statement": "국내 AI 보안 투자가 확대됐다.",
            "claim_type": "company_action",
            "source_ids": [source_id],
            "confidence_label": "reported",
            "category": "korea_ai_enterprise",
            "headline": "국내 AI 보안 투자 확대",
            "summary": "국내 기업이 AI 보안 투자를 늘렸다.",
            "why_it_matters": "국내 보안 시장에 영향을 준다.",
            "business_implication": "국내 사업자는 보안 공급망을 점검해야 한다.",
        }
        # Keep the colliding source identity on the original pack entry so
        # retained TOP5 items hydrate to the same diversity_source_key.
        for row in prompt_input["source_pack"]["sources"]:
            if row.get("source_id") == source_id:
                row["source_name"] = source_name
        prompt_input["source_pack"]["backfill_sources"] = [source]
        prompt_input["source_pack"]["backfill_claims"] = [claim]
        return claim

    @patch("keysuri_live_source_smoke.recent_sent_news_log", return_value=[])
    def test_same_source_cap_violation_rejects_candidate(
        self, _mock_recent: MagicMock
    ) -> None:
        prompt_input = _prompt_input()
        # Collide with retained korea-t2-procurement-wire (rank 3) by reusing it.
        self._same_source_replacement(
            prompt_input,
            source_id="korea-t2-procurement-wire",
            source_name="Example Korea Public Procurement Wire",
        )
        generated = _semantic_initial_failure()
        parse_result = {
            "parse_status": "parsed_invalid",
            "generated_briefing": generated,
            "issues": [
                {
                    "code": "korea_tech_top5_irrelevant_item",
                    "path": "top_5_news.items[0]",
                }
            ],
        }
        fixed, replaced, replacement = recovery_module._reconcile_korea_top5(
            prompt_input, parse_result
        )
        self.assertIsNone(fixed)
        self.assertEqual(replacement, [])

    @patch("keysuri_live_source_smoke.recent_sent_news_log", return_value=[])
    def test_first_diversity_violation_then_valid_candidate(
        self, _mock_recent: MagicMock
    ) -> None:
        prompt_input = _prompt_input()
        bad_source = {
            "source_id": "korea-t2-procurement-wire",
            "source_name": "Example Korea Public Procurement Wire",
            "source_url": "https://example.com/dup-procurement",
            "source_tier": "T2_TIER1_WIRE",
            "fetched_at": "2026-07-24T12:10:00+09:00",
            "title": "조달 중복 후보",
        }
        bad_claim = {
            "claim_id": "korea-dup-procurement-claim",
            "statement": "조달 중복 후보다.",
            "claim_type": "company_action",
            "source_ids": ["korea-t2-procurement-wire"],
            "confidence_label": "reported",
            "category": "korea_procurement",
            "headline": "조달 중복 후보",
            "summary": "동일 source cap을 위반한다.",
            "why_it_matters": "다양성 위반 테스트용.",
            "business_implication": "다양성 위반 테스트용.",
        }
        good = _add_ranked_replacement(prompt_input)
        prompt_input["source_pack"]["backfill_sources"].insert(0, bad_source)
        prompt_input["source_pack"]["backfill_claims"].insert(0, bad_claim)
        generated = _semantic_initial_failure()
        parse_result = {
            "parse_status": "parsed_invalid",
            "generated_briefing": generated,
            "issues": [
                {
                    "code": "korea_tech_top5_irrelevant_item",
                    "path": "top_5_news.items[0]",
                }
            ],
        }
        fixed, _replaced, replacement = recovery_module._reconcile_korea_top5(
            prompt_input, parse_result
        )
        self.assertIsNotNone(fixed)
        self.assertEqual(fixed["top_5_news"]["items"][0]["news_id"], good["claim_id"])
        self.assertEqual(replacement, ["korea-replacement-source-1"])

    def test_trial_passes_strict_diversity_false_on_relaxation(self) -> None:
        prompt_input = _prompt_input()
        items = copy.deepcopy(prompt_input["top_5_news"]["items"])
        # Force two items to share the same diversity source key.
        items[0]["source_ids"] = ["korea-t2-procurement-wire"]
        items[0]["source_name"] = "Example Korea Public Procurement Wire"
        items[2]["source_ids"] = ["korea-t2-procurement-wire"]
        items[2]["source_name"] = "Example Korea Public Procurement Wire"
        self.assertFalse(recovery_module._trial_passes_strict_diversity(items))

    @patch("keysuri_live_source_smoke.recent_sent_news_log", return_value=[])
    def test_same_entity_cap_violation_rejects_candidate(
        self, _mock_recent: MagicMock
    ) -> None:
        prompt_input = _prompt_input()
        # Retained TOP5 already mentions no NVIDIA; inject NVIDIA into rank 2
        # and propose a NVIDIA replacement for rank 1.
        prompt_input["top_5_news"]["items"][1]["headline"] = "엔비디아 GPU 공급 확대"
        prompt_input["top_5_news"]["items"][1]["summary"] = "NVIDIA가 국내 공급을 늘렸다."
        source = {
            "source_id": "korea-nvidia-entity-source",
            "source_name": "전자신문",
            "source_url": "https://example.com/nvidia-korea",
            "source_tier": "T2_TIER1_WIRE",
            "fetched_at": "2026-07-24T12:10:00+09:00",
            "title": "엔비디아 국내 파트너십",
        }
        claim = {
            "claim_id": "korea-nvidia-entity-claim",
            "statement": "엔비디아 국내 파트너십이 확대됐다.",
            "claim_type": "company_action",
            "source_ids": [source["source_id"]],
            "confidence_label": "reported",
            "category": "korea_semiconductor",
            "headline": "엔비디아 국내 파트너십",
            "summary": "NVIDIA가 국내 AI 파트너십을 발표했다.",
            "why_it_matters": "국내 AI 공급망에 영향을 준다.",
            "business_implication": "국내 사업자는 GPU 공급을 점검해야 한다.",
        }
        prompt_input["source_pack"]["backfill_sources"] = [source]
        prompt_input["source_pack"]["backfill_claims"] = [claim]
        generated = _semantic_initial_failure()
        parse_result = {
            "parse_status": "parsed_invalid",
            "generated_briefing": generated,
            "issues": [
                {
                    "code": "korea_tech_top5_irrelevant_item",
                    "path": "top_5_news.items[0]",
                }
            ],
        }
        fixed, _replaced, replacement = recovery_module._reconcile_korea_top5(
            prompt_input, parse_result
        )
        self.assertIsNone(fixed)
        self.assertEqual(replacement, [])

    @patch("keysuri_live_source_smoke.recent_sent_news_log", return_value=[])
    def test_editorial_cluster_cap_violation_rejects_candidate(
        self, _mock_recent: MagicMock
    ) -> None:
        prompt_input = _prompt_input()
        # Force retained rank-2 into cloud_infrastructure cluster; replacement
        # uses the same source name + cloud cluster keywords.
        retained = prompt_input["top_5_news"]["items"][1]
        retained["headline"] = "국내 클라우드 인프라 확장"
        retained["summary"] = "클라우드 데이터센터 투자가 확대됐다."
        retained["source_name"] = "디지털타임스"
        retained["source_ids"] = ["korea-cloud-cluster-retained"]
        source = {
            "source_id": "korea-cloud-cluster-source",
            "source_name": "디지털타임스",
            "source_url": "https://example.com/cloud-infra-2",
            "source_tier": "T2_TIER1_WIRE",
            "fetched_at": "2026-07-24T12:10:00+09:00",
            "title": "국내 GPU 클라우드 인프라",
        }
        claim = {
            "claim_id": "korea-cloud-cluster-claim",
            "statement": "국내 GPU 클라우드 인프라가 확대됐다.",
            "claim_type": "company_action",
            "source_ids": [source["source_id"]],
            "confidence_label": "reported",
            "category": "korea_platform_cloud_saas",
            "headline": "국내 GPU 클라우드 인프라",
            "summary": "클라우드 인프라 투자가 늘었다.",
            "why_it_matters": "국내 클라우드 시장에 영향을 준다.",
            "business_implication": "국내 사업자는 클라우드 공급망을 점검해야 한다.",
        }
        prompt_input["source_pack"]["backfill_sources"] = [source]
        prompt_input["source_pack"]["backfill_claims"] = [claim]
        # Also register retained source so diversity keys resolve.
        prompt_input["source_pack"]["sources"].append(
            {
                "source_id": "korea-cloud-cluster-retained",
                "source_name": "디지털타임스",
                "source_url": "https://example.com/cloud-infra-1",
                "source_tier": "T2_TIER1_WIRE",
            }
        )
        generated = _semantic_initial_failure()
        parse_result = {
            "parse_status": "parsed_invalid",
            "generated_briefing": generated,
            "issues": [
                {
                    "code": "korea_tech_top5_irrelevant_item",
                    "path": "top_5_news.items[0]",
                }
            ],
        }
        fixed, _replaced, replacement = recovery_module._reconcile_korea_top5(
            prompt_input, parse_result
        )
        self.assertIsNone(fixed)
        self.assertEqual(replacement, [])

    @patch("keysuri_live_source_smoke.recent_sent_news_log", return_value=[])
    def test_all_candidates_diversity_violations_skip_corrective_gemini(
        self, _mock_recent: MagicMock
    ) -> None:
        prompt_input = _prompt_input()
        self._same_source_replacement(
            prompt_input,
            source_id="korea-t2-procurement-wire",
            source_name="Example Korea Public Procurement Wire",
        )
        caller, calls = _fake_caller(
            [json.dumps(_semantic_initial_failure(), ensure_ascii=False)]
        )
        result = generate_keysuri_with_bounded_recovery(
            prompt_input, gemini_caller=caller, usage_sink={}
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            result["generation_diagnostics"]["generation_recovery_result"],
            "not_attempted_reconciliation_failed",
        )
        self.assertFalse(result["generation_diagnostics"]["generation_recovery_attempted"])
        self.assertEqual(result["generation_diagnostics"]["generation_attempt_count"], 1)


class CorrectiveContractAndEndpointTests(unittest.TestCase):
    @patch("keysuri_live_source_smoke.recent_sent_news_log", return_value=[])
    def test_corrective_deep_dive_rejects_unknown_source(
        self, _mock_recent: MagicMock
    ) -> None:
        prompt_input = _prompt_input()
        replacement_claim = _add_ranked_replacement(prompt_input)
        corrected = _semantic_corrective_response(prompt_input, replacement_claim)
        corrected["deep_dive"]["source_ids"] = ["invented-deep-dive-source"]
        caller, calls = _fake_caller(
            [
                json.dumps(_semantic_initial_failure(), ensure_ascii=False),
                json.dumps(corrected, ensure_ascii=False),
            ]
        )
        result = generate_keysuri_with_bounded_recovery(
            prompt_input, gemini_caller=caller, usage_sink={}
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            result["generation_diagnostics"]["generation_recovery_result"], "failed"
        )
        self.assertNotEqual(result["parse_result"]["parse_status"], "parsed_valid")
        codes = set(result["generation_diagnostics"]["recovery_generation_issue_codes"])
        self.assertTrue(
            codes
            & {
                "deep_dive_fixed_source_ids_mismatch",
                "deep_dive_source_id_invalid",
                "gemini_json_schema_validation_failed",
            },
            msg=f"expected deep-dive rejection codes, got {sorted(codes)}",
        )
    @patch("keysuri_live_source_smoke.recent_sent_news_log", return_value=[])
    def test_corrective_closing_cannot_keep_removed_source(
        self, _mock_recent: MagicMock
    ) -> None:
        prompt_input = _prompt_input()
        replacement_claim = _add_ranked_replacement(prompt_input)
        corrected = _semantic_corrective_response(prompt_input, replacement_claim)
        # Keep the removed original source in closing list.
        corrected["closing_sources"]["source_list"].append(
            {
                "source_id": "korea-t0-policy-official",
                "label": "removed",
                "url": "https://example.com/removed",
                "tier": "T0_OFFICIAL",
            }
        )
        caller, calls = _fake_caller(
            [
                json.dumps(_semantic_initial_failure(), ensure_ascii=False),
                json.dumps(corrected, ensure_ascii=False),
            ]
        )
        result = generate_keysuri_with_bounded_recovery(
            prompt_input, gemini_caller=caller, usage_sink={}
        )
        self.assertEqual(len(calls), 2)
        # Closing validation may or may not hard-fail depending on contract;
        # invented/removed source must not survive as an approved fixed source.
        briefing = result["parse_result"].get("generated_briefing") or {}
        if result["parse_result"]["parse_status"] == "parsed_valid":
            closing = briefing.get("closing_sources") or {}
            ids = {
                str(row.get("source_id"))
                for row in (closing.get("source_list") or [])
                if isinstance(row, dict)
            }
            self.assertNotIn("korea-t0-policy-official", ids)
        else:
            self.assertEqual(
                result["generation_diagnostics"]["generation_recovery_result"],
                "failed",
            )

    def test_failed_recovery_endpoint_returns_http_500_without_image_or_smtp(
        self,
    ) -> None:
        from fastapi.testclient import TestClient
        from main import app

        diagnostics = {
            "generation_attempt_count": 2,
            "generation_recovery_attempted": True,
            "generation_recovery_family": STRUCTURAL_CONTRACT_FAILURE,
            "generation_recovery_result": "failed",
            "initial_generation_issue_codes": [
                "parse_multiple_json_objects_unrecoverable"
            ],
            "recovery_generation_issue_codes": ["json_extract_failed"],
        }
        payload = {
            "ok": False,
            "program_id": PROGRAM_KOREA,
            "service_full_run": True,
            "called_image_api": False,
            "smtp_attempted": False,
            "email_sent": False,
            "generation_attempt_count": 2,
            "generation_recovery_result": "failed",
            **diagnostics,
        }
        client = TestClient(app)
        with patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "unit-test-token"}, clear=False):
            with patch(
                "internal_jobs.create_keysuri_owner_review_job",
                return_value=payload,
            ) as job:
                response = client.post(
                    "/internal/jobs/create-keysuri-owner-review",
                    json={
                        "program_id": PROGRAM_KOREA,
                        "service_full_run": True,
                        "send_owner_email": True,
                        "dry_run": False,
                    },
                    headers={"X-Genie-Internal-Job-Token": "unit-test-token"},
                )
        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["generation_attempt_count"], 2)
        self.assertFalse(body.get("called_image_api"))
        self.assertFalse(body.get("smtp_attempted"))
        job.assert_called_once()


class ObservabilityNarrowingTests(unittest.TestCase):
    def test_application_logging_configuration_is_idempotent(self) -> None:
        from main import configure_application_logging

        app_logger = logging.getLogger("keysuri_live_source_smoke")
        google_logger = logging.getLogger("google")
        # Isolate: remove owned handlers from app loggers.
        for name in (
            "keysuri_live_source_smoke",
            "keysuri_service_full_run",
            "internal_jobs",
            "main",
        ):
            log = logging.getLogger(name)
            log.handlers = [
                handler
                for handler in list(log.handlers)
                if not getattr(handler, "_genie_application_handler", False)
            ]

        root = logging.getLogger()
        had_root_handlers = bool(root.handlers)
        # Force the no-root-handler branch so we can prove handler creation.
        saved_root_handlers = list(root.handlers)
        root.handlers = []
        try:
            configure_application_logging()
            owned = [
                handler
                for handler in app_logger.handlers
                if getattr(handler, "_genie_application_handler", False)
            ]
            self.assertEqual(len(owned), 1)
            configure_application_logging()
            owned_again = [
                handler
                for handler in app_logger.handlers
                if getattr(handler, "_genie_application_handler", False)
            ]
            self.assertEqual(len(owned_again), 1)
            self.assertIs(owned_again[0], owned[0])
            self.assertEqual(app_logger.level, logging.INFO)
            self.assertEqual(google_logger.level, logging.WARNING)
            # Do not raise root to INFO; leave whatever the host configured.
            # (pytest may have set root independently — only assert we did not
            # rely on root INFO for app recovery events.)
            self.assertEqual(app_logger.level, logging.INFO)
            for third_party in ("google", "urllib3", "httpx"):
                self.assertGreaterEqual(
                    logging.getLogger(third_party).level, logging.WARNING
                )
        finally:
            root.handlers = saved_root_handlers
            if had_root_handlers:
                configure_application_logging()


class FixedSelectionCanonicalUrlContractTests(unittest.TestCase):
    def _briefing_with_item0_urls(
        self, *, raw_url: str, canonical_url: str, source_ids: Optional[List[str]] = None
    ) -> dict:
        payload = _generated()
        item = payload["top_5_news"]["items"][0]
        if source_ids is not None:
            item["source_ids"] = list(source_ids)
        item["url"] = raw_url
        item["canonical_url"] = canonical_url
        item["source_url"] = raw_url
        return payload

    def test_canonical_url_form_of_approved_source_is_allowed(self) -> None:
        from sent_news_dedup_gate import canonicalize_url

        prompt_input = _prompt_input()
        source_id = "korea-t0-policy-official"
        raw_url = "https://www.zdnet.co.kr/view/?no=123&utm_source=rss"
        for source in prompt_input["source_pack"]["sources"]:
            if source.get("source_id") == source_id:
                source["source_url"] = raw_url
                source["url"] = raw_url
                break
        canonical = canonicalize_url(raw_url)
        self.assertEqual(canonical, "https://www.zdnet.co.kr/view?no=123")
        generated = self._briefing_with_item0_urls(
            raw_url=raw_url,
            canonical_url=canonical,
            source_ids=[source_id],
        )
        parse_result = {
            "parse_status": "parsed_valid",
            "program_id": PROGRAM_KOREA,
            "generated_briefing": generated,
            "issues": [],
            "parse_meta": {},
        }
        contracted = recovery_module._apply_fixed_selection_contract(
            parse_result, prompt_input
        )
        self.assertEqual(contracted["parse_status"], "parsed_valid")
        codes = [
            issue.get("code")
            for issue in (contracted.get("issues") or [])
            if isinstance(issue, dict)
        ]
        self.assertNotIn("top_5_unapproved_url", codes)

    def test_same_domain_different_article_is_blocked(self) -> None:
        from sent_news_dedup_gate import canonicalize_url

        prompt_input = _prompt_input()
        source_id = "korea-t0-policy-official"
        raw_url = "https://www.zdnet.co.kr/view/?no=123&utm_source=rss"
        for source in prompt_input["source_pack"]["sources"]:
            if source.get("source_id") == source_id:
                source["source_url"] = raw_url
                source["url"] = raw_url
                break
        approved_canonical = canonicalize_url(raw_url)
        other_url = "https://www.zdnet.co.kr/view?no=999"
        self.assertNotEqual(approved_canonical, canonicalize_url(other_url))
        generated = self._briefing_with_item0_urls(
            raw_url=other_url,
            canonical_url=canonicalize_url(other_url),
            source_ids=[source_id],
        )
        parse_result = {
            "parse_status": "parsed_valid",
            "program_id": PROGRAM_KOREA,
            "generated_briefing": generated,
            "issues": [],
            "parse_meta": {},
        }
        contracted = recovery_module._apply_fixed_selection_contract(
            parse_result, prompt_input
        )
        self.assertEqual(contracted["parse_status"], "parsed_invalid")
        codes = [
            issue.get("code")
            for issue in (contracted.get("issues") or [])
            if isinstance(issue, dict)
        ]
        self.assertIn("top_5_unapproved_url", codes)


class FixedDeepDiveSubsetContractTests(unittest.TestCase):
    def _valid_parse(self, source_ids: List[str]) -> dict:
        generated = _generated()
        generated["deep_dive"]["source_ids"] = list(source_ids)
        return {
            "parse_status": "parsed_valid",
            "program_id": PROGRAM_KOREA,
            "generated_briefing": generated,
            "issues": [],
            "parse_meta": {},
        }

    def test_approved_subset_passes(self) -> None:
        approved = [
            "s1",
            "s2",
            "s3",
            "s4",
            "s5",
        ]
        result = recovery_module._apply_fixed_deep_dive_contract(
            self._valid_parse(["s1", "s3"]), approved
        )
        self.assertEqual(result["parse_status"], "parsed_valid")

    def test_unknown_id_fails(self) -> None:
        approved = ["s1", "s2", "s3", "s4", "s5"]
        result = recovery_module._apply_fixed_deep_dive_contract(
            self._valid_parse(["s1", "s9"]), approved
        )
        self.assertEqual(result["parse_status"], "parsed_invalid")
        self.assertEqual(
            result["issues"][0]["code"], "deep_dive_fixed_source_ids_mismatch"
        )

    def test_empty_source_ids_fail(self) -> None:
        approved = ["s1", "s2", "s3", "s4", "s5"]
        result = recovery_module._apply_fixed_deep_dive_contract(
            self._valid_parse([]), approved
        )
        self.assertEqual(result["parse_status"], "parsed_invalid")

    @patch("keysuri_live_source_smoke.recent_sent_news_log", return_value=[])
    def test_recovery_accepts_approved_non_top1_subset(
        self, _mock_recent: MagicMock
    ) -> None:
        prompt_input = _prompt_input()
        replacement_claim = _add_ranked_replacement(prompt_input)
        corrected = _semantic_corrective_response(prompt_input, replacement_claim)
        # After reconciliation TOP5 includes the replacement plus remaining items.
        # A non-empty approved subset that is not exact TOP1 equality must pass.
        corrected["deep_dive"]["source_ids"] = [
            "korea-replacement-source-1",
            "korea-t2-support-wire",
        ]
        caller, calls = _fake_caller(
            [
                json.dumps(_semantic_initial_failure(), ensure_ascii=False),
                json.dumps(corrected, ensure_ascii=False),
            ]
        )
        result = generate_keysuri_with_bounded_recovery(
            prompt_input, gemini_caller=caller, usage_sink={}
        )
        self.assertEqual(len(calls), 2)
        self.assertNotIn(
            "deep_dive_fixed_source_ids_mismatch",
            result["generation_diagnostics"]["recovery_generation_issue_codes"],
        )


class LiveSourceSmokeResultTokenOptionalTests(unittest.TestCase):
    def test_none_token_diagnostics_are_not_coerced_to_zero(self) -> None:
        smoke = LiveSourceSmokeResult(
            ok=False,
            program_id=PROGRAM_KOREA,
            source_pack_path="/tmp/pack.json",
            html_path="/tmp/out.html",
            fetched_item_count=0,
            feed_urls_used=[],
            sample_marker_pass=False,
            initial_input_tokens=_optional_or_none_probe(),
            total_input_tokens=None,
            recovery_input_tokens=None,
        )
        self.assertIsNone(smoke.initial_input_tokens)
        self.assertIsNone(smoke.total_input_tokens)
        self.assertIsNone(smoke.to_dict()["total_input_tokens"])


def _optional_or_none_probe() -> Optional[int]:
    return recovery_module._optional_diag_int(
        {"initial_input_tokens": None}, "initial_input_tokens"
    )


if __name__ == "__main__":
    unittest.main()
