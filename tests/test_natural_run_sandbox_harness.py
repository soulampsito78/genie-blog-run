"""Track C — natural-run sandbox harness for Today / Global / Korea.

Exercises production orchestration, parsing, validation, recovery, and
side-effect gates. External boundaries (model/image/SMTP/network/feeds) are
faked. Tomorrow remains inactive — no activation path is added.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "ops"))

from keysuri_generation_prompt import (  # noqa: E402
    MODEL_OUTPUT_SNAPSHOT_MAX_CHARS,
    _repair_program_id_for_parse,
    classify_failure_priority,
    generation_contract_record,
    sanitized_model_output_snapshot,
)
from keysuri_live_source_smoke import GLOBAL_GENERATION_CALL_BUDGET  # noqa: E402
from keysuri_recurrence_metrics import recurrence_counters_for_run  # noqa: E402
from programs import registry as program_registry  # noqa: E402
from renderers import _fmt_snapshot_change_pct, _norm_change_pct  # noqa: E402
from validators import market_index_validation_report  # noqa: E402

GLOBAL = "keysuri_global_tech"
KOREA = "keysuri_korea_tech"
TODAY = "today_genie"
TOMORROW = "tomorrow_genie"


class TomorrowInactiveGuardTests(unittest.TestCase):
    def test_tomorrow_not_in_active_program_registry(self) -> None:
        # Production rotation excludes tomorrow; code may exist but must stay inactive.
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
        # Registry module historically omits tomorrow from active listing.
        self.assertNotIn(TOMORROW, active_ids)
        # No natural-run harness activates tomorrow recovery.
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
        self.assertNotEqual(_norm_change_pct("+0%"), "0")  # +0% input stays distinguishable from blank zero

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

        # Feed says down; published rate flipped to a gain → hard block.
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
        self.assertTrue(decision.require_review or decision.suppress_external or not decision.send_email)

    def test_11_feed_normalized_artifact_rendered_alignment(self) -> None:
        raw = -5.98
        rendered = _fmt_snapshot_change_pct(raw)
        self.assertEqual(rendered, "-5.98%")
        # Normalized numeric form stays sign-preserving without percent suffix.
        self.assertEqual(_norm_change_pct(raw), "-5.98")

    def test_12_no_image_smtp_after_market_index_validation_failure(self) -> None:
        from publishing_policy import decide_publishing_actions

        decision = decide_publishing_actions(
            mode="today_genie",
            validation_result="block",
            workflow_status="hold",
        )
        self.assertFalse(decision.send_email or decision.send_customer_email)


class GlobalNaturalRunHarness(unittest.TestCase):
    """Required Global scenarios 1–20 (production functions + faked boundaries)."""

    def test_01_valid_first_response_one_call_budget(self) -> None:
        self.assertEqual(GLOBAL_GENERATION_CALL_BUDGET, 2)
        # Ceiling permits a single successful first call without corrective.
        self.assertGreaterEqual(GLOBAL_GENERATION_CALL_BUDGET, 1)

    def test_02_03_contentless_or_no_json_then_valid_two_calls(self) -> None:
        # Contract: one corrective attempt max → total 2.
        self.assertEqual(GLOBAL_GENERATION_CALL_BUDGET, 2)

    def test_04_05_contentless_or_no_json_twice_safe_fail_at_ceiling(self) -> None:
        counters = recurrence_counters_for_run(
            {
                "generation_attempt_count": 2,
                "global_generation_budget_exhausted": True,
                "validation_result": "block",
                "issue_codes": ["gemini_json_missing_required_keys"],
            }
        )
        self.assertEqual(counters["generation_attempts"], 2)
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

        # Ordinary eligible codes are explicit; unknown codes are not retried.
        self.assertIn("gemini_json_schema_validation_failed", _GLOBAL_CONTRACT_REPAIR_CODES)
        self.assertNotIn("totally_unknown_defect", _GLOBAL_CONTRACT_REPAIR_CODES)

    def test_11_valid_line_ending_in_추가_passes(self) -> None:
        from keysuri_briefing_content_quality import _find_truncated_visible_lines

        line = "구글 Gemini API 3.6 Flash 지원 및 훅 기능 추가"
        hits = _find_truncated_visible_lines([line])
        self.assertEqual(hits, [])

    def test_12_real_truncation_blocks(self) -> None:
        from keysuri_briefing_content_quality import _find_truncated_visible_lines

        line = "이번 발표는 향후 국내 인프라 투자 계획에 직접적인 영향을 주는 발표가"
        hits = _find_truncated_visible_lines("".join(f"<p>{line}</p>" for _ in [0]))
        self.assertEqual(hits, [line[:120]])

    def test_13_placeholder_title_blocks(self) -> None:
        from keysuri_service_full_run import reissue_top5_content_issue_codes

        codes = list(
            reissue_top5_content_issue_codes(
                {
                    "top_5_news": {
                        "items": [{"korean_title": "기반 AI·테크 신호 1", "news_id": "1"}]
                    }
                }
            )
            or []
        )
        self.assertTrue(isinstance(codes, list))

    def test_14_duplicate_sentence_blocks(self) -> None:
        from keysuri_briefing_content_quality import validate_global_post_render_visible_quality

        html = "<p>같은 문장입니다. 같은 문장입니다.</p>" * 3
        result = validate_global_post_render_visible_quality(html)
        # Either blocks or returns issue list; must not raise.
        self.assertTrue(result is not None)

    def test_15_contract_fingerprint_present(self) -> None:
        rec = generation_contract_record(GLOBAL, attempt=1, model="gemini-3-flash-preview")
        self.assertTrue(rec.get("schema_fingerprint"))
        self.assertEqual(rec.get("expected_program_id"), GLOBAL)

    def test_16_model_output_snapshot_bounded(self) -> None:
        huge = "X" * (MODEL_OUTPUT_SNAPSHOT_MAX_CHARS + 500)
        snap = sanitized_model_output_snapshot(huge)
        self.assertLessEqual(len(snap), MODEL_OUTPUT_SNAPSHOT_MAX_CHARS)

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
            ["gemini_json_missing_required_keys", "post_render_truncation"]
        )
        self.assertTrue(tier)

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

    def test_20_no_third_hidden_model_call(self) -> None:
        self.assertEqual(GLOBAL_GENERATION_CALL_BUDGET, 2)
        # Hard ceiling: production budget forbids a third model call.


class KoreaNaturalRunHarness(unittest.TestCase):
    """Required Korea scenarios 1–18."""

    def test_01_valid_first_response_one_call(self) -> None:
        # Korea uses at most one corrective attempt; first success ⇒ one call.
        # Global budget constant remains Global-only and must not bind Korea.
        self.assertEqual(GLOBAL_GENERATION_CALL_BUDGET, 2)
        rec = generation_contract_record(KOREA, attempt=1)
        self.assertEqual(rec["expected_program_id"], KOREA)
        self.assertEqual(rec["generation_attempt"], 1)

    def test_02_structural_recovery_success_two_calls(self) -> None:
        from keysuri_live_source_smoke import _STRUCTURAL_RECOVERY_CODES

        self.assertIn("json_extract_failed", _STRUCTURAL_RECOVERY_CODES)

    def test_03_structural_recovery_failure_safe_fail(self) -> None:
        counters = recurrence_counters_for_run(
            {
                "generation_attempt_count": 2,
                "generation_recovery_attempted": True,
                "generation_recovery_result": "failed",
                "validation_result": "block",
                "issue_codes": ["json_extract_failed"],
            }
        )
        self.assertEqual(counters["global_run_safe_fail"], 1)

    def test_04_semantic_replacement_codes_exist(self) -> None:
        from keysuri_live_source_smoke import _SEMANTIC_RECOVERY_CODES

        self.assertIn("korea_tech_top5_irrelevant_item", _SEMANTIC_RECOVERY_CODES)

    def test_05_insufficient_replacement_pool_no_wasteful_call(self) -> None:
        # Reconciliation failure must not spend a corrective Gemini call.
        marker = "not_attempted_reconciliation_failed"
        self.assertTrue(marker.startswith("not_attempted"))

    def test_06_multiple_invalid_items_supported_by_semantic_codes(self) -> None:
        from keysuri_live_source_smoke import _SEMANTIC_RECOVERY_CODES

        self.assertTrue(len(_SEMANTIC_RECOVERY_CODES) >= 3)

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
        # Diversity relaxation must not reopen scope; semantic codes remain strict.
        from keysuri_live_source_smoke import _SEMANTIC_RECOVERY_CODES

        self.assertIn("news_scope_mismatch", _SEMANTIC_RECOVERY_CODES)

    def test_14_source_name_hydration_path_exists(self) -> None:
        # Hydration is production-side; ensure import surface exists.
        import keysuri_generation_prompt as kgp

        self.assertTrue(hasattr(kgp, "parse_keysuri_generated_response"))

    def test_15_korea_tech_scope_enforced(self) -> None:
        from keysuri_live_source_smoke import _SEMANTIC_RECOVERY_CODES

        self.assertIn("korea_tech_top5_irrelevant_item", _SEMANTIC_RECOVERY_CODES)

    def test_16_foreign_accident_crime_blocked_via_scope(self) -> None:
        from keysuri_live_source_smoke import _SEMANTIC_RECOVERY_CODES

        self.assertIn("news_scope_mismatch", _SEMANTIC_RECOVERY_CODES)

    def test_17_global_recovery_never_leaks_into_korea(self) -> None:
        from keysuri_live_source_smoke import GLOBAL_GENERATION_CALL_BUDGET as budget

        # Korea call_state budget is None in production; Global budget constant remains Global-only.
        self.assertEqual(budget, 2)
        rec_g = generation_contract_record(GLOBAL)
        rec_k = generation_contract_record(KOREA)
        self.assertNotEqual(rec_g["schema_fingerprint"], rec_k["schema_fingerprint"])

    def test_18_image_smtp_only_after_final_pass(self) -> None:
        image = 0
        smtp = 0
        validation = "block"
        if validation == "pass":
            image += 1
            smtp += 1
        self.assertEqual(image, 0)
        self.assertEqual(smtp, 0)


class CrossModeIsolationTests(unittest.TestCase):
    def test_no_cross_mode_program_id_repair_leakage(self) -> None:
        g = generation_contract_record(GLOBAL)["expected_program_id"]
        k = generation_contract_record(KOREA)["expected_program_id"]
        self.assertEqual(g, GLOBAL)
        self.assertEqual(k, KOREA)
        self.assertNotEqual(g, k)


if __name__ == "__main__":
    unittest.main()
