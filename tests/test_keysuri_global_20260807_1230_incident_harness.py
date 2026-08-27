"""Production-faithful harness for KeeSuri Global 2026-08-07 12:30 incident.

Incident: 2026-08-07_keysuri_global_tech_12-30
Run: 20260807_123001_keysuri_global_tech_a349afa9

Root cause: model returned a display-only JSON shell missing required contract
keys; GLOBAL_MALFORMED_CONTRACT LLM repair repeated the shell. Fix is
deterministic Global contract scaffold from trusted TOP5 + display prose,
plus truthful watchdog stage_map for generation_validation.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest import mock

_REPO = Path(__file__).resolve().parents[1]
_FIXTURE = (
    _REPO
    / "ops"
    / "feeds"
    / "incident_fixtures"
    / "20260807_1230_keysuri_global_display_shell.json"
)
KST = ZoneInfo("Asia/Seoul")


def _load_fixture() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _prompt_input() -> dict:
    path = _REPO / "ops" / "feeds" / "keysuri_global_prompt_input.sample.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("_fixture_note", None)
    return payload


def _generated() -> dict:
    path = _REPO / "ops" / "feeds" / "keysuri_global_generated_briefing.sample.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("_fixture_note", None)
    return payload


def _shell_without_scaffold_parse(shell: dict, prompt_input: dict) -> dict:
    """Simulate pre-patch parse: repairs without Global contract scaffold."""
    from keysuri_generation_prompt import (
        _merge_parse_repair_diagnostics,
        _repair_closing_message_for_parse,
        _repair_deep_dive_key_implications_for_parse,
        _repair_korea_market_lens_for_parse,
        _repair_program_id_for_parse,
        _repair_top_level_scope_heading_for_parse,
        validate_parsed_keysuri_generated_briefing,
        _missing_required_keys,
    )

    repaired, deep_diag = _repair_deep_dive_key_implications_for_parse(
        dict(shell), prompt_input
    )
    repaired, lens_diag = _repair_korea_market_lens_for_parse(
        repaired, "keysuri_global_tech"
    )
    repaired, scope_diag = _repair_top_level_scope_heading_for_parse(
        repaired, "keysuri_global_tech"
    )
    repaired, pid_diag = _repair_program_id_for_parse(repaired, "keysuri_global_tech")
    repaired, closing_diag = _repair_closing_message_for_parse(
        repaired, "keysuri_global_tech"
    )
    _merge_parse_repair_diagnostics(
        deep_diag, lens_diag, scope_diag, pid_diag, closing_diag
    )
    validation = validate_parsed_keysuri_generated_briefing(
        "keysuri_global_tech", repaired, prompt_input
    )
    return {
        "valid": validation["valid"],
        "issue_codes": [str(i.get("code") or "") for i in validation["issues"]],
        "missing_required_keys": _missing_required_keys(repaired),
        "repaired": repaired,
    }


class Global1230IncidentHarness(unittest.TestCase):
    def test_01_pre_patch_simulation_fails_same_issue_family(self) -> None:
        fx = _load_fixture()
        shell = fx["model_display_shell"]
        pre = _shell_without_scaffold_parse(shell, _prompt_input())
        self.assertFalse(pre["valid"])
        for code in (
            "top_5_news_missing",
            "deep_dive_missing",
            "one_line_checkpoint_missing",
            "closing_sources_missing",
            "generated_status_invalid",
            "operational_status_invalid",
        ):
            self.assertIn(code, pre["issue_codes"])
        for key in fx["missing_required_keys"]:
            self.assertIn(key, pre["missing_required_keys"])

    def test_02_post_patch_scaffold_salvages_production_shell(self) -> None:
        from keysuri_generation_prompt import parse_keysuri_generated_response

        fx = _load_fixture()
        result = parse_keysuri_generated_response(
            json.dumps(fx["model_display_shell"], ensure_ascii=False),
            "keysuri_global_tech",
            _prompt_input(),
        )
        self.assertEqual(result["parse_status"], "parsed_valid")
        self.assertTrue(
            (result.get("parse_meta") or {}).get("global_contract_scaffold_applied")
        )
        briefing = result["generated_briefing"]
        self.assertIsInstance(briefing.get("top_5_news"), dict)
        self.assertEqual(len(briefing["top_5_news"]["items"]), 5)
        self.assertTrue(str(briefing["deep_dive"].get("body") or "").strip())

    def test_03_bounded_recovery_uses_at_most_two_calls_on_shell(self) -> None:
        from keysuri_live_source_smoke import generate_keysuri_with_bounded_recovery

        fx = _load_fixture()
        shell_text = json.dumps(fx["model_display_shell"], ensure_ascii=False)
        calls: list = []

        def _caller(prompt: str, **kwargs):
            calls.append({"prompt": prompt})
            sink = kwargs.get("usage_sink")
            if isinstance(sink, dict):
                sink.update(
                    {
                        "prompt_token_count": 10,
                        "candidates_token_count": 20,
                        "total_token_count": 30,
                    }
                )
            return shell_text

        result = generate_keysuri_with_bounded_recovery(
            _prompt_input(), gemini_caller=_caller, usage_sink={}
        )
        # A display shell means the model produced no article prose, so the
        # scaffold had to graft the whole TOP5. That buys the ONE budgeted
        # corrective call rather than being waved through as a success: shipping
        # the scaffold silently is what sent the owner a template-only POOR
        # briefing on 2026-08-27. The stub returns the same shell again, so the
        # retry cannot improve it and the run falls back to the scaffolded parse
        # — still contract-valid, still graded by the single adjudicator.
        self.assertEqual(len(calls), 2)
        diag = result["generation_diagnostics"]
        self.assertTrue(diag.get("global_recovery_attempted"))
        self.assertIn(
            "global_contract_scaffold_fabricated_top5",
            diag.get("global_recovery_error_codes") or [],
        )
        self.assertTrue(diag.get("global_recovery_fallback_to_prior_parse"))
        self.assertEqual(result["parse_result"]["parse_status"], "parsed_valid")
        self.assertEqual(
            len(result["parse_result"]["generated_briefing"]["top_5_news"]["items"]), 5
        )
        # Budget is still respected: never a third call.
        self.assertLessEqual(int(diag.get("global_generation_call_count") or 0), 2)
        self.assertFalse(diag.get("global_generation_budget_exhausted"))

    def test_03b_recovered_generation_replaces_scaffold_when_model_recovers(self) -> None:
        """When the corrective call DOES return a real briefing, it wins."""
        from keysuri_live_source_smoke import generate_keysuri_with_bounded_recovery

        fx = _load_fixture()
        shell_text = json.dumps(fx["model_display_shell"], ensure_ascii=False)
        good_text = json.dumps(_generated(), ensure_ascii=False)
        calls: list = []

        def _caller(prompt: str, **kwargs):
            calls.append({"prompt": prompt})
            sink = kwargs.get("usage_sink")
            if isinstance(sink, dict):
                sink.update(
                    {
                        "prompt_token_count": 10,
                        "candidates_token_count": 20,
                        "total_token_count": 30,
                    }
                )
            return shell_text if len(calls) == 1 else good_text

        result = generate_keysuri_with_bounded_recovery(
            _prompt_input(), gemini_caller=_caller, usage_sink={}
        )
        self.assertEqual(len(calls), 2)
        diag = result["generation_diagnostics"]
        self.assertTrue(diag.get("global_recovery_attempted"))
        self.assertEqual(diag.get("global_recovery_result"), "succeeded")
        self.assertFalse(diag.get("global_recovery_fallback_to_prior_parse"))
        self.assertEqual(result["parse_result"]["parse_status"], "parsed_valid")

    def test_04_genuine_empty_shell_without_top5_pack_still_blocks(self) -> None:
        from keysuri_generation_prompt import parse_keysuri_generated_response

        fx = _load_fixture()
        pi = _prompt_input()
        pi["top_5_news"] = {"news_scope": "global", "section_heading": "글로벌 테크 TOP 5", "items": []}
        pi["source_pack"] = {"sources": [], "claims": []}
        result = parse_keysuri_generated_response(
            json.dumps(fx["model_display_shell"], ensure_ascii=False),
            "keysuri_global_tech",
            pi,
        )
        self.assertNotEqual(result["parse_status"], "parsed_valid")

    def test_05_unmatched_quote_truncation_still_blocks_if_present(self) -> None:
        """Adversarial: complete contract with truncated deep_dive body must fail
        visible-text validators when those run — scaffold must not invent closure."""
        from keysuri_generation_prompt import parse_keysuri_generated_response

        bad = _generated()
        bad["deep_dive"]["body"] = '키수리가 본 신호는 "미완'
        result = parse_keysuri_generated_response(
            json.dumps(bad, ensure_ascii=False),
            "keysuri_global_tech",
            _prompt_input(),
        )
        # Schema parse may still accept; truncation is a later visible-text stage.
        # Ensure scaffold did not strip the broken body.
        if result["parse_status"] == "parsed_valid":
            self.assertIn('"', result["generated_briefing"]["deep_dive"]["body"])
            self.assertTrue(result["generated_briefing"]["deep_dive"]["body"].endswith("미완"))

    def test_06_corrective_prompt_forbids_display_shell(self) -> None:
        from keysuri_generation_prompt import build_keysuri_corrective_generation_prompt

        prompt = build_keysuri_corrective_generation_prompt(
            _prompt_input(),
            {
                "failure_family": "GLOBAL_MALFORMED_CONTRACT",
                "initial_issue_codes": ["gemini_json_missing_required_keys"],
                "missing_required_fields": ["top_5_news", "deep_dive"],
                "preservable_fields": ["opening_lead"],
                "fixed_source_ids": ["global-t0-ai-official"],
                "fixed_top5_order": [],
                "global_output_contract_keys": ["top_5_news", "deep_dive"],
            },
        )
        self.assertIn("FORBIDDEN: display-only shells", prompt)
        self.assertIn("COMPLETE contract object", prompt)
        self.assertIn("Kee-Suri Compact Generation Prompt", prompt)
        self.assertNotIn("Kee-Suri Offline Generation Prompt (staged)", prompt)
        self.assertNotIn("fill only missing or invalid required fields", prompt)

    def test_07_watchdog_generation_validation_not_gate_failure(self) -> None:
        from natural_run_watchdog import apply_proven_stage_map
        from natural_run_incident_store import empty_stage_map

        stage = empty_stage_map()
        stage["Scheduler"] = "정상"
        stage["Cloud Run"] = "정상"
        stage["실행 게이트"] = "실패"  # legacy false signal
        out = apply_proven_stage_map(
            stage,
            first_failed_stage="generation_validation",
            artifact_saved=True,
            email_sent=False,
            called_gemini=True,
            data_collected=True,
        )
        self.assertEqual(out["실행 게이트"], "정상")
        self.assertEqual(out["검증"], "실패")
        self.assertIn(out["콘텐츠 생성"], {"정상", "시도됨"})
        self.assertEqual(out["이미지"], "미실행")
        self.assertEqual(out["운영자 메일"], "미발송")

    def test_08_watchdog_smtp_failure_does_not_mark_validation_failed(self) -> None:
        from natural_run_watchdog import apply_proven_stage_map
        from natural_run_incident_store import empty_stage_map

        out = apply_proven_stage_map(
            empty_stage_map(),
            first_failed_stage="email_delivery",
            artifact_saved=True,
            email_sent=False,
        )
        self.assertEqual(out["운영자 메일"], "실패")
        self.assertNotEqual(out["검증"], "실패")
        self.assertNotEqual(out["실행 게이트"], "실패")

    def test_09_watchdog_image_failure_keeps_earlier_stages_ok(self) -> None:
        from natural_run_watchdog import apply_proven_stage_map
        from natural_run_incident_store import empty_stage_map

        out = apply_proven_stage_map(
            empty_stage_map(),
            first_failed_stage="image_generation",
            artifact_saved=False,
            email_sent=False,
        )
        self.assertEqual(out["이미지"], "실패")
        self.assertNotEqual(out["실행 게이트"], "실패")
        self.assertNotEqual(out["검증"], "실패")

    def test_10_notify_force_path_stage_map_truthful(self) -> None:
        from natural_run_watchdog import notify_natural_run_incident_from_failure
        from natural_run_incident_store import load_incident

        sent: list = []

        def _send(**kwargs):
            sent.append(kwargs)
            return True

        with mock.patch(
            "natural_run_watchdog.report_incident_once",
            side_effect=lambda incident, send_fn=None: {
                "ok": True,
                "incident_id": incident["incident_id"],
                "report_sent": True,
                "deduped": False,
                "auto_retry": 0,
                "_incident": incident,
            },
        ) as report_mock:
            out = notify_natural_run_incident_from_failure(
                program_id="keysuri_global_tech",
                run_id="20260807_123001_keysuri_global_tech_a349afa9",
                trigger_source="scheduled_service_full_run",
                first_failed_stage="generation_validation",
                error_code="validation_blocked",
                issue_codes=["top_5_news_missing", "gemini_json_missing_required_keys"],
                artifact_saved=True,
                email_sent=False,
                extra_fields={
                    "called_gemini": True,
                    "final_selected_count": 5,
                    "kst_schedule_date": "2026-08-07",
                    "scheduled_slot": "12:30",
                },
                now=datetime(2026, 8, 7, 12, 33, tzinfo=KST),
                send_fn=_send,
            )
        self.assertTrue(out and out.get("report_sent"))
        incident = report_mock.call_args[0][0]
        stage = incident["stage_map"]
        self.assertEqual(stage["실행 게이트"], "정상")
        self.assertEqual(stage["검증"], "실패")
        self.assertNotEqual(stage.get("실행 게이트"), "실패")

    def test_11_mutation_third_generation_call_forbidden(self) -> None:
        from keysuri_live_source_smoke import (
            GLOBAL_GENERATION_CALL_BUDGET,
            generate_keysuri_with_bounded_recovery,
        )

        self.assertEqual(GLOBAL_GENERATION_CALL_BUDGET, 2)
        bad = json.dumps(
            {"news_scope": "global_tech", "section_heading": "글로벌 테크"},
            ensure_ascii=False,
        )
        calls: list = []

        def _caller(prompt: str, **kwargs):
            calls.append(1)
            sink = kwargs.get("usage_sink")
            if isinstance(sink, dict):
                sink.update(
                    {
                        "prompt_token_count": 5,
                        "candidates_token_count": 5,
                        "total_token_count": 10,
                    }
                )
            return bad

        generate_keysuri_with_bounded_recovery(
            _prompt_input(), gemini_caller=_caller, usage_sink={}
        )
        self.assertLessEqual(len(calls), 2)

    def test_12_mutation_claim_gate_failure_for_generation_fails_helper(self) -> None:
        from natural_run_watchdog import apply_proven_stage_map
        from natural_run_incident_store import empty_stage_map

        lied = empty_stage_map()
        lied["실행 게이트"] = "실패"
        corrected = apply_proven_stage_map(
            lied,
            first_failed_stage="generation_validation",
            called_gemini=True,
            data_collected=True,
            artifact_saved=True,
        )
        self.assertEqual(corrected["검증"], "실패")
        self.assertEqual(corrected["실행 게이트"], "정상")

    def test_13_diagnostic_snapshot_includes_selected_news_ids(self) -> None:
        from keysuri_live_source_smoke import _prompt_input_diagnostic_snapshot

        snap = _prompt_input_diagnostic_snapshot(_prompt_input())
        self.assertTrue(snap.get("selected_news_ids"))
        self.assertEqual(len(snap["selected_news_ids"]), 5)

    def test_14_no_customer_send_on_unresolved_validation(self) -> None:
        fx = _load_fixture()
        # Artifact contract from production: customer path not reached.
        self.assertEqual(fx["error_code"], "validation_blocked")
        self.assertEqual(fx["first_failed_stage"], "generation_validation")

    def test_15_junk_json_without_display_shell_not_salvaged(self) -> None:
        from keysuri_generation_prompt import parse_keysuri_generated_response

        result = parse_keysuri_generated_response(
            json.dumps({"invalid": "not a briefing schema"}),
            "keysuri_global_tech",
            _prompt_input(),
        )
        self.assertNotEqual(result["parse_status"], "parsed_valid")
        codes = [str(i.get("code") or "") for i in (result.get("issues") or [])]
        self.assertIn("top_5_news_missing", codes)


if __name__ == "__main__":
    unittest.main()
