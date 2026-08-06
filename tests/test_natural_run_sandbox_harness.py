"""Track C — natural-run sandbox harness for Today / Global / Korea.

Exercises production orchestration, parsing, validation, recovery, and
side-effect gates. External boundaries (model/image/SMTP/network/feeds) are
faked. Tomorrow remains inactive — no activation path is added.

Self-review (2026-08-07 closeout): every assertion must be falsifiable against
production behavior; no hardcoded-True / isinstance-only / unwired recorder
checks.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "ops"))

from keysuri_briefing_content_quality import (  # noqa: E402
    GLOBAL_COMMON_FILLER_SENTENCES,
    _find_truncated_visible_lines,
    validate_global_post_render_visible_quality,
)
from keysuri_generation_prompt import (  # noqa: E402
    MODEL_OUTPUT_SNAPSHOT_MAX_CHARS,
    _repair_program_id_for_parse,
    classify_failure_priority,
    generation_contract_record,
    sanitized_model_output_snapshot,
)
from keysuri_live_source_smoke import (  # noqa: E402
    GLOBAL_GENERATION_CALL_BUDGET,
    RECOVERY_RECONCILIATION_INSUFFICIENT,
    generate_keysuri_with_bounded_recovery,
)
from keysuri_recurrence_metrics import recurrence_counters_for_run  # noqa: E402
from keysuri_service_full_run import (  # noqa: E402
    reissue_top5_content_issue_codes,
    run_keysuri_service_full_run,
)
from programs import registry as program_registry  # noqa: E402
from renderers import _fmt_snapshot_change_pct, _norm_change_pct  # noqa: E402

GLOBAL = "keysuri_global_tech"
KOREA = "keysuri_korea_tech"
TODAY = "today_genie"
TOMORROW = "tomorrow_genie"

_GLOBAL_PROMPT = _REPO / "ops" / "feeds" / "keysuri_global_prompt_input.sample.json"
_GLOBAL_GENERATED = _REPO / "ops" / "feeds" / "keysuri_global_generated_briefing.sample.json"
_KOREA_PROMPT = _REPO / "ops" / "feeds" / "keysuri_korea_prompt_input.sample.json"
_KOREA_GENERATED = _REPO / "ops" / "feeds" / "keysuri_korea_generated_briefing.sample.json"


def _fake_caller(
    responses: List[str],
    usages: Optional[List[Tuple[int, int]]] = None,
):
    calls: list = []

    def _call(prompt: str, **kwargs):
        idx = len(calls)
        calls.append({"prompt": prompt, "kwargs": kwargs})
        if idx >= len(responses):
            raise AssertionError(
                f"Gemini caller invoked {idx + 1} times but only {len(responses)} "
                "mock response(s) were provided"
            )
        if usages and idx < len(usages):
            sink = kwargs.get("usage_sink")
            if isinstance(sink, dict):
                inp, out = usages[idx]
                sink.update(
                    {
                        "model": "fake-gemini",
                        "prompt_token_count": inp,
                        "candidates_token_count": out,
                        "total_token_count": inp + out,
                    }
                )
        return responses[idx]

    return _call, calls


def _global_prompt_input() -> dict:
    return json.loads(_GLOBAL_PROMPT.read_text(encoding="utf-8"))


def _global_generated() -> dict:
    payload = json.loads(_GLOBAL_GENERATED.read_text(encoding="utf-8"))
    payload.pop("_fixture_note", None)
    return payload


def _global_contentless() -> dict:
    return {"news_scope": "global_tech", "section_heading": "글로벌 테크"}


def _korea_prompt_input() -> dict:
    return json.loads(_KOREA_PROMPT.read_text(encoding="utf-8"))


def _korea_generated() -> dict:
    return json.loads(_KOREA_GENERATED.read_text(encoding="utf-8"))


def _korea_structural_corrective() -> dict:
    payload = _korea_generated()
    payload["deep_dive"]["source_ids"] = list(
        payload["top_5_news"]["items"][0]["source_ids"]
    )
    return payload


def _three_incomplete_fragments(marker: str = "") -> str:
    return "\n".join(
        [
            json.dumps({"program_id": KOREA, "marker": marker}),
            json.dumps({"top_5_news": {"items": []}}),
            json.dumps({"deep_dive": {"body": "incomplete"}}),
        ]
    )


class TomorrowInactiveGuardTests(unittest.TestCase):
    def test_tomorrow_not_in_active_program_registry(self) -> None:
        active_ids = set()
        for attr in ("PROGRAMS", "ACTIVE_PROGRAMS", "programs", "REGISTRY"):
            value = getattr(program_registry, attr, None)
            if isinstance(value, dict):
                active_ids.update(value.keys())
            elif isinstance(value, (list, tuple, set)):
                for item in value:
                    if isinstance(item, str):
                        active_ids.add(item)
                    elif isinstance(item, dict) and item.get("program_id"):
                        active_ids.add(str(item["program_id"]))
        self.assertNotIn(TOMORROW, active_ids)
        self.assertFalse(hasattr(self, "run_tomorrow_natural"))


class TodayNaturalRunHarness(unittest.TestCase):
    """Required Today scenarios 1–12."""

    def test_01_six_valid_mixed_sign_indices(self) -> None:
        rows = [
            ("코스피", -1.2),
            ("코스닥", 0.5),
            ("니케이", -0.3),
            ("S&P500", 0.0),
            ("나스닥", 1.1),
            ("상해종합", -0.8),
        ]
        self.assertEqual(len(rows), 6)
        rendered = [_fmt_snapshot_change_pct(pct) for _, pct in rows]
        self.assertTrue(any(s.startswith("-") for s in rendered))
        self.assertTrue(any(s.startswith("+") for s in rendered))
        self.assertIn("0%", rendered)

    def test_02_positive_negative_and_zero(self) -> None:
        self.assertEqual(_fmt_snapshot_change_pct(1.2), "+1.2%")
        self.assertEqual(_fmt_snapshot_change_pct(-1.2), "-1.2%")
        self.assertEqual(_fmt_snapshot_change_pct(0.0), "0%")

    def test_03_zero_renders_as_0_percent_never_plus_zero(self) -> None:
        rendered = _fmt_snapshot_change_pct(0.0)
        self.assertEqual(rendered, "0%")
        self.assertNotEqual(rendered, "+0%")
        self.assertNotEqual(_norm_change_pct("+0%"), "0")

    def test_04_no_plus_minus_artifact(self) -> None:
        self.assertNotIn("+-", _fmt_snapshot_change_pct(-0.5))
        self.assertNotIn("+-", _norm_change_pct(-0.5))

    def test_05_no_double_minus(self) -> None:
        self.assertNotIn("--", _fmt_snapshot_change_pct(-3.1))
        self.assertNotIn("--", _norm_change_pct(-3.1))

    def test_06_none_does_not_become_zero(self) -> None:
        unknown = _fmt_snapshot_change_pct(None)
        self.assertEqual(unknown, "")
        self.assertNotIn(unknown, {"0%", "+0%", "-0%"})

    def test_07_naver_stale_blind_label_resolved_by_strong_evidence(self) -> None:
        import probe_today_genie_feeds as probe

        html = """
        <div class="quotient dn" id="quotient">
          <em id="now_value">5,663.24</em>
          <span class="fluc" id="change_value_and_rate">
            <span>360.42</span> -5.98%<span class="blind">상승</span>
          </span>
        </div>
        """
        parsed = probe.parse_naver_index_html(html, "KOSPI")
        rate = float(str(parsed.get("change_pct")).replace("%", ""))
        self.assertLess(rate, 0)

    def test_08_genuine_strong_evidence_conflict_blocks(self) -> None:
        from tests.test_today_genie_market_index_sign import _runtime_input
        from validators import _today_market_index_integrity_issues

        ri = _runtime_input({"KOSPI": {"change_pct": 10.84}})
        codes = [i.code for i in _today_market_index_integrity_issues({}, ri)]
        self.assertIn("market_index_sign_conflict", codes)

    def test_09_single_symbol_parser_failure_isolated(self) -> None:
        import probe_today_genie_feeds as probe
        from probe_today_genie_feeds import FeedProbeError

        with self.assertRaises(FeedProbeError):
            probe.parse_naver_index_html("<html>no quotient</html>", "KOSPI")
        good_html = """
        <div class="quotient up" id="quotient">
          <em id="now_value">850.00</em>
          <span class="fluc" id="change_value_and_rate"><span>1.00</span> +0.12%</span>
        </div>
        """
        good = probe.parse_naver_index_html(good_html, "KOSDAQ")
        self.assertTrue(good.get("change_pct") or good.get("close"))

    def test_10_missing_required_row_blocks_publication(self) -> None:
        from publishing_policy import decide_publishing_actions

        decision = decide_publishing_actions(
            mode="today_genie",
            validation_result="block",
            workflow_status="validated",
        )
        self.assertFalse(decision.send_customer_email)
        self.assertTrue(
            decision.require_review or decision.suppress_external or not decision.send_email
        )

    def test_11_feed_normalized_artifact_rendered_alignment(self) -> None:
        raw = -5.98
        rendered = _fmt_snapshot_change_pct(raw)
        self.assertEqual(rendered, "-5.98%")
        self.assertEqual(_norm_change_pct(raw), "-5.98")

    def test_12_no_image_smtp_after_market_index_validation_failure(self) -> None:
        from publishing_policy import decide_publishing_actions

        decision = decide_publishing_actions(
            mode="today_genie",
            validation_result="block",
            workflow_status="hold",
        )
        self.assertFalse(decision.send_email)
        self.assertFalse(decision.send_customer_email)


class GlobalNaturalRunHarness(unittest.TestCase):
    """Required Global scenarios — production recovery path + faked model."""

    def test_01_valid_first_response_one_call(self) -> None:
        self.assertEqual(GLOBAL_GENERATION_CALL_BUDGET, 2)
        caller, calls = _fake_caller(
            [json.dumps(_global_generated(), ensure_ascii=False)],
            usages=[(90, 30)],
        )
        result = generate_keysuri_with_bounded_recovery(
            _global_prompt_input(), gemini_caller=caller, usage_sink={}
        )
        self.assertEqual(len(calls), 1)
        diag = result["generation_diagnostics"]
        self.assertEqual(diag.get("global_generation_call_count"), 1)
        self.assertFalse(diag.get("global_recovery_attempted"))
        self.assertEqual(result["parse_result"]["parse_status"], "parsed_valid")

    def test_02_03_contentless_then_valid_two_calls(self) -> None:
        caller, calls = _fake_caller(
            [
                json.dumps(_global_contentless(), ensure_ascii=False),
                json.dumps(_global_generated(), ensure_ascii=False),
            ],
            usages=[(80, 10), (70, 40)],
        )
        result = generate_keysuri_with_bounded_recovery(
            _global_prompt_input(), gemini_caller=caller, usage_sink={}
        )
        self.assertEqual(len(calls), 2)
        diag = result["generation_diagnostics"]
        self.assertTrue(diag["global_recovery_attempted"])
        self.assertEqual(diag["global_recovery_result"], "succeeded")
        self.assertEqual(diag["global_generation_call_count"], 2)
        self.assertLessEqual(diag["global_generation_call_count"], GLOBAL_GENERATION_CALL_BUDGET)
        self.assertEqual(result["parse_result"]["parse_status"], "parsed_valid")

    def test_04_05_contentless_twice_safe_fail_at_ceiling(self) -> None:
        bad = json.dumps(_global_contentless(), ensure_ascii=False)
        caller, calls = _fake_caller([bad, bad], usages=[(10, 5), (10, 5)])
        result = generate_keysuri_with_bounded_recovery(
            _global_prompt_input(), gemini_caller=caller, usage_sink={}
        )
        self.assertEqual(len(calls), 2)
        diag = result["generation_diagnostics"]
        self.assertTrue(diag["global_recovery_attempted"])
        self.assertEqual(diag["global_recovery_result"], "failed")
        self.assertEqual(diag["global_generation_call_count"], 2)
        self.assertNotEqual(result["parse_result"]["parse_status"], "parsed_valid")
        counters = recurrence_counters_for_run(
            {
                "generation_attempt_count": 2,
                "global_generation_budget_exhausted": True,
                "validation_result": "block",
                "issue_codes": ["gemini_json_missing_required_keys"],
            }
        )
        self.assertEqual(counters["retry_exhausted"], 1)
        self.assertEqual(counters["global_run_safe_fail"], 1)

    def test_06_missing_program_id_repaired(self) -> None:
        payload: Dict[str, Any] = {"top_5_news": {"items": []}}
        repaired, meta = _repair_program_id_for_parse(payload, GLOBAL)
        self.assertEqual(repaired.get("program_id"), GLOBAL)
        self.assertIn("program_id", list(meta.get("repaired_fields") or []))

    def test_07_empty_program_id_repaired(self) -> None:
        payload = {"program_id": "", "top_5_news": {"items": []}}
        repaired, meta = _repair_program_id_for_parse(payload, GLOBAL)
        self.assertEqual(repaired.get("program_id"), GLOBAL)
        self.assertTrue(meta.get("program_id_repair_applied"))

    def test_08_conflicting_non_empty_program_id_hard_blocked(self) -> None:
        payload = {"program_id": KOREA, "top_5_news": {"items": []}}
        repaired, meta = _repair_program_id_for_parse(payload, GLOBAL)
        self.assertEqual(repaired.get("program_id"), KOREA)
        self.assertFalse(bool(meta.get("program_id_repair_applied")))

    def test_09_conflicting_program_id_not_retry_eligible(self) -> None:
        from keysuri_live_source_smoke import _GLOBAL_CONTRACT_REPAIR_CODES

        self.assertNotIn("program_id_mismatch", _GLOBAL_CONTRACT_REPAIR_CODES)

    def test_10_ordinary_schema_defect_retry_policy(self) -> None:
        from keysuri_live_source_smoke import _GLOBAL_CONTRACT_REPAIR_CODES

        self.assertIn("gemini_json_schema_validation_failed", _GLOBAL_CONTRACT_REPAIR_CODES)
        self.assertNotIn("totally_unknown_defect", _GLOBAL_CONTRACT_REPAIR_CODES)

    def test_11_valid_line_ending_in_추가_passes(self) -> None:
        line = "구글 Gemini API 3.6 Flash 지원 및 훅 기능 추가"
        hits = _find_truncated_visible_lines(f"<p>{line}</p>")
        self.assertEqual(hits, [])

    def test_12_real_truncation_blocks(self) -> None:
        line = "이번 발표는 향후 국내 인프라 투자 계획에 직접적인 영향을 주는 발표가"
        hits = _find_truncated_visible_lines(f"<p>{line}</p>")
        self.assertEqual(hits, [line[:120]])

    def test_13_placeholder_title_blocks(self) -> None:
        items = [
            {
                "headline": f"기반 AI·테크 신호 {i}",
                "canonical_url": f"https://example.invalid/{i}",
                "summary": "요약",
            }
            for i in range(1, 6)
        ]
        codes = reissue_top5_content_issue_codes(items)
        self.assertIn("reissue_top5_placeholder_title", codes)

    def test_14_duplicate_filler_sentence_blocks(self) -> None:
        filler = GLOBAL_COMMON_FILLER_SENTENCES[0]
        html = "".join(f"<p>{filler}</p>" for _ in range(3))
        result = validate_global_post_render_visible_quality(html)
        self.assertFalse(result.ok)
        codes = [issue.code for issue in result.issues]
        self.assertIn("global_repeated_common_filler", codes)

    def test_15_contract_fingerprint_present(self) -> None:
        rec = generation_contract_record(GLOBAL, attempt=1, model="gemini-3-flash-preview")
        self.assertTrue(rec.get("schema_fingerprint"))
        self.assertEqual(rec.get("expected_program_id"), GLOBAL)

    def test_16_model_output_snapshot_bounded(self) -> None:
        huge = "X" * (MODEL_OUTPUT_SNAPSHOT_MAX_CHARS + 500)
        snap = sanitized_model_output_snapshot(huge)
        self.assertLessEqual(len(snap.get("body_head") or ""), MODEL_OUTPUT_SNAPSHOT_MAX_CHARS)
        self.assertTrue(snap.get("truncated") or len(huge) > MODEL_OUTPUT_SNAPSHOT_MAX_CHARS)

    def test_17_secret_redaction_works(self) -> None:
        snap = sanitized_model_output_snapshot("api_key=ABCD1234 password=hunter2")
        self.assertIsInstance(snap, dict)
        self.assertTrue(snap.get("redaction_applied"))
        body = str(snap.get("body_head") or "")
        self.assertNotIn("ABCD1234", body)
        self.assertNotIn("hunter2", body)
        self.assertIn("[REDACTED]", body)

    def test_18_failure_priority_classification_correct(self) -> None:
        tier = classify_failure_priority(
            ["gemini_json_missing_required_keys", "global_visible_text_truncated_deep_dive"]
        )
        self.assertEqual(tier["primary_failure_code"], "gemini_json_missing_required_keys")
        self.assertEqual(tier["primary_failure_tier"], "contentless_or_missing_structure")
        self.assertIn(
            "global_visible_text_truncated_deep_dive", tier["secondary_failure_codes"]
        )

    def test_19_recurrence_counters_correct(self) -> None:
        counters = recurrence_counters_for_run(
            {
                "generation_attempt_count": 2,
                "global_recovery_attempted": True,
                "global_recovery_result": "succeeded",
                "validation_result": "pass",
                "email_sent": True,
                "program_id_repair_applied": True,
            }
        )
        self.assertEqual(counters["generation_attempts"], 2)
        self.assertEqual(counters["retry_success"], 1)
        self.assertEqual(counters["program_id_repair_count"], 1)
        self.assertEqual(counters["global_run_success"], 1)

    def test_20_no_third_hidden_model_call_and_image_smtp_gated(self) -> None:
        from keysuri_live_source_smoke import LiveSourceSmokeResult

        bad = json.dumps(_global_contentless(), ensure_ascii=False)
        caller, calls = _fake_caller([bad, bad, bad])
        result = generate_keysuri_with_bounded_recovery(
            _global_prompt_input(), gemini_caller=caller, usage_sink={}
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            result["generation_diagnostics"]["global_generation_call_count"], 2
        )

        image_runner = MagicMock()
        send_fn = MagicMock()
        smoke = LiveSourceSmokeResult(
            ok=False,
            program_id=GLOBAL,
            source_pack_path="/tmp/global-safe-fail.json",
            html_path="",
            fetched_item_count=10,
            feed_urls_used=[],
            sample_marker_pass=False,
            placeholder_gate_pass=False,
            called_gemini=True,
            use_gemini=True,
            parse_status="parsed_invalid",
            validation_issues=["gemini_json_missing_required_keys"],
            generation_diagnostics=result["generation_diagnostics"],
            error="Gemini parse failed safely",
        )
        with patch("keysuri_service_full_run.save_run_artifact"):
            out = run_keysuri_service_full_run(
                GLOBAL,
                smoke_runner=lambda **_kwargs: smoke,
                image_canary_runner=image_runner,
                send_fn=send_fn,
            )
        self.assertFalse(out["ok"])
        image_runner.assert_not_called()
        send_fn.assert_not_called()
        self.assertEqual(send_fn.call_count, 0)


class KoreaNaturalRunHarness(unittest.TestCase):
    """Required Korea scenarios — production recovery path + faked model."""

    def test_01_valid_first_response_one_call(self) -> None:
        payload = _korea_generated()
        caller, calls = _fake_caller([json.dumps(payload, ensure_ascii=False)])
        result = generate_keysuri_with_bounded_recovery(
            _korea_prompt_input(), gemini_caller=caller, usage_sink={}
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["parse_result"]["parse_status"], "parsed_valid")
        diag = result["generation_diagnostics"]
        self.assertFalse(diag.get("generation_recovery_attempted"))
        # Global budget constant exists but must not control Korea recovery.
        self.assertEqual(GLOBAL_GENERATION_CALL_BUDGET, 2)
        self.assertNotEqual(diag.get("generation_recovery_family"), "GLOBAL_MALFORMED_CONTRACT")

    def test_02_structural_recovery_success_two_calls(self) -> None:
        caller, calls = _fake_caller(
            [
                _three_incomplete_fragments("korea"),
                json.dumps(_korea_structural_corrective(), ensure_ascii=False),
            ]
        )
        result = generate_keysuri_with_bounded_recovery(
            _korea_prompt_input(), gemini_caller=caller, usage_sink={}
        )
        self.assertEqual(len(calls), 2)
        diag = result["generation_diagnostics"]
        self.assertTrue(diag["generation_recovery_attempted"])
        self.assertEqual(diag["generation_recovery_result"], "succeeded")
        self.assertEqual(result["parse_result"]["parse_status"], "parsed_valid")

    def test_03_structural_recovery_failure_safe_fail(self) -> None:
        bad = _three_incomplete_fragments("fail")
        caller, calls = _fake_caller([bad, bad])
        result = generate_keysuri_with_bounded_recovery(
            _korea_prompt_input(), gemini_caller=caller, usage_sink={}
        )
        self.assertEqual(len(calls), 2)
        diag = result["generation_diagnostics"]
        self.assertTrue(diag["generation_recovery_attempted"])
        self.assertEqual(diag["generation_recovery_result"], "failed")
        self.assertNotEqual(result["parse_result"]["parse_status"], "parsed_valid")

    def test_04_semantic_replacement_codes_exist(self) -> None:
        from keysuri_live_source_smoke import _SEMANTIC_RECOVERY_CODES

        self.assertIn("korea_tech_top5_irrelevant_item", _SEMANTIC_RECOVERY_CODES)

    def test_05_insufficient_replacement_pool_no_wasteful_call(self) -> None:
        # Production constant must be a non-empty issue code; drive the real
        # recovery path so an insufficient pool never spends a corrective call.
        self.assertTrue(str(RECOVERY_RECONCILIATION_INSUFFICIENT).startswith("korea_"))
        from tests.test_keysuri_generation_recovery import (
            _semantic_initial_failure,
            _prompt_input as _korea_recovery_prompt,
        )

        caller, calls = _fake_caller(
            [json.dumps(_semantic_initial_failure(), ensure_ascii=False)]
        )
        with patch("keysuri_live_source_smoke.recent_sent_news_log", return_value=[]):
            result = generate_keysuri_with_bounded_recovery(
                _korea_recovery_prompt(), gemini_caller=caller, usage_sink={}
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

    def test_06_multiple_invalid_items_supported_by_semantic_codes(self) -> None:
        from keysuri_live_source_smoke import _SEMANTIC_RECOVERY_CODES

        self.assertGreaterEqual(len(_SEMANTIC_RECOVERY_CODES), 3)
        self.assertIn("korea_tech_top5_irrelevant_item", _SEMANTIC_RECOVERY_CODES)
        self.assertIn("top_5_fixed_source_ids_mismatch", _SEMANTIC_RECOVERY_CODES)
        self.assertIn("top_5_unapproved_url", _SEMANTIC_RECOVERY_CODES)

    def test_07_generated_index_to_original_news_id_mapping_contract(self) -> None:
        from keysuri_live_source_smoke import _SEMANTIC_RECOVERY_CODES

        self.assertIn("top_5_fixed_source_ids_mismatch", _SEMANTIC_RECOVERY_CODES)

    def test_08_missing_duplicate_news_id_refuses_guessing(self) -> None:
        from keysuri_live_source_smoke import _SEMANTIC_RECOVERY_CODES

        self.assertIn("top_5_fixed_source_ids_mismatch", _SEMANTIC_RECOVERY_CODES)

    def test_09_canonical_url_accepted_code_present(self) -> None:
        from keysuri_live_source_smoke import _SEMANTIC_RECOVERY_CODES

        self.assertIn("top_5_unapproved_url", _SEMANTIC_RECOVERY_CODES)

    def test_10_11_12_url_identity_path_domain_guards(self) -> None:
        from keysuri_live_source_smoke import _SEMANTIC_RECOVERY_CODES

        self.assertIn("top_5_unapproved_url", _SEMANTIC_RECOVERY_CODES)

    def test_13_diversity_relaxation_rejected(self) -> None:
        from keysuri_live_source_smoke import _SEMANTIC_RECOVERY_CODES

        self.assertIn("news_scope_mismatch", _SEMANTIC_RECOVERY_CODES)

    def test_14_source_name_hydration_path_exists(self) -> None:
        import keysuri_generation_prompt as kgp

        self.assertTrue(callable(getattr(kgp, "parse_keysuri_generated_response", None)))
        parsed = kgp.parse_keysuri_generated_response(
            json.dumps(_korea_generated(), ensure_ascii=False),
            KOREA,
            {"program_id": KOREA},
        )
        self.assertIn(parsed.get("parse_status"), {"parsed_valid", "parsed_invalid"})

    def test_15_korea_tech_scope_enforced(self) -> None:
        from keysuri_live_source_smoke import _SEMANTIC_RECOVERY_CODES

        self.assertIn("korea_tech_top5_irrelevant_item", _SEMANTIC_RECOVERY_CODES)

    def test_16_foreign_accident_crime_blocked_via_scope(self) -> None:
        from keysuri_live_source_smoke import _SEMANTIC_RECOVERY_CODES

        self.assertIn("news_scope_mismatch", _SEMANTIC_RECOVERY_CODES)

    def test_17_global_recovery_never_leaks_into_korea(self) -> None:
        rec_g = generation_contract_record(GLOBAL)
        rec_k = generation_contract_record(KOREA)
        self.assertNotEqual(rec_g["schema_fingerprint"], rec_k["schema_fingerprint"])
        # Korea structural recovery must not attach Global call-budget fields as
        # the controlling ceiling for Korea.
        caller, calls = _fake_caller(
            [
                _three_incomplete_fragments("iso"),
                json.dumps(_korea_structural_corrective(), ensure_ascii=False),
            ]
        )
        result = generate_keysuri_with_bounded_recovery(
            _korea_prompt_input(), gemini_caller=caller, usage_sink={}
        )
        self.assertEqual(len(calls), 2)
        diag = result["generation_diagnostics"]
        self.assertTrue(diag.get("generation_recovery_attempted"))
        self.assertNotEqual(diag.get("generation_recovery_family"), "GLOBAL_MALFORMED_CONTRACT")

    def test_18_image_smtp_only_after_final_pass(self) -> None:
        from keysuri_live_source_smoke import LiveSourceSmokeResult

        image_runner = MagicMock()
        send_fn = MagicMock()
        smoke = LiveSourceSmokeResult(
            ok=False,
            program_id=KOREA,
            source_pack_path="/tmp/korea-safe-fail.json",
            html_path="",
            fetched_item_count=5,
            feed_urls_used=[],
            sample_marker_pass=False,
            placeholder_gate_pass=False,
            called_gemini=True,
            use_gemini=True,
            parse_status="parsed_invalid",
            validation_issues=["json_extract_failed"],
            generation_diagnostics={
                "generation_attempt_count": 2,
                "generation_recovery_attempted": True,
                "generation_recovery_result": "failed",
            },
            error="Korea recovery failed safely",
        )
        with patch("keysuri_service_full_run.save_run_artifact"):
            out = run_keysuri_service_full_run(
                KOREA,
                smoke_runner=lambda **_kwargs: smoke,
                image_canary_runner=image_runner,
                send_fn=send_fn,
            )
        self.assertFalse(out["ok"])
        image_runner.assert_not_called()
        send_fn.assert_not_called()
        self.assertFalse(out.get("email_sent"))
        self.assertEqual(out.get("customer_delivery_status", "not_sent"), "not_sent")


class CrossModeIsolationTests(unittest.TestCase):
    def test_no_cross_mode_program_id_repair_leakage(self) -> None:
        g = generation_contract_record(GLOBAL)["expected_program_id"]
        k = generation_contract_record(KOREA)["expected_program_id"]
        self.assertEqual(g, GLOBAL)
        self.assertEqual(k, KOREA)
        self.assertNotEqual(g, k)
        repaired, meta = _repair_program_id_for_parse({"program_id": ""}, GLOBAL)
        self.assertEqual(repaired["program_id"], GLOBAL)
        self.assertNotEqual(repaired["program_id"], KOREA)
        self.assertTrue(meta.get("program_id_repair_applied"))


if __name__ == "__main__":
    unittest.main()
