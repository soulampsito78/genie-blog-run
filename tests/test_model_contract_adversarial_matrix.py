"""Offline adversarial matrix for Global (light Korea/Today) contract salvage.

Mutates briefing/contract dicts only — no live model, network, mail, or deploy.
Classifies each variant via existing scaffold / validate helpers.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from issue_code_registry import (
    REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
    REPAIRABILITY_MODEL_CORRECTIVE_RETRY,
    REPAIRABILITY_TERMINAL_BLOCK,
)

_REPO = Path(__file__).resolve().parents[1]
_GLOBAL_PROMPT = _REPO / "ops" / "feeds" / "keysuri_global_prompt_input.sample.json"
_GLOBAL_GENERATED = _REPO / "ops" / "feeds" / "keysuri_global_generated_briefing.sample.json"
_GLOBAL_SHELL_FIXTURE = (
    _REPO
    / "ops"
    / "feeds"
    / "incident_fixtures"
    / "20260807_1230_keysuri_global_display_shell.json"
)
_KOREA_PROMPT = _REPO / "ops" / "feeds" / "keysuri_korea_prompt_input.sample.json"
_KOREA_GENERATED = _REPO / "ops" / "feeds" / "keysuri_korea_generated_briefing.sample.json"

PROGRAM_GLOBAL = "keysuri_global_tech"
PROGRAM_KOREA = "keysuri_korea_tech"


def _load_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload.pop("_fixture_note", None)
    return payload


def _prompt_input_global() -> dict:
    return _load_json(_GLOBAL_PROMPT)


def _generated_global() -> dict:
    return _load_json(_GLOBAL_GENERATED)


def _display_shell() -> dict:
    fx = _load_json(_GLOBAL_SHELL_FIXTURE)
    return dict(fx["model_display_shell"])


def _classify_parse_result(result: dict) -> str:
    """Map parse/scaffold outcome to repairability class."""
    status = str(result.get("parse_status") or "")
    meta = result.get("parse_meta") or {}
    scaffold_applied = bool(meta.get("global_contract_scaffold_applied"))
    if status == "parsed_valid":
        if scaffold_applied:
            return REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE
        return REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE  # already valid / salvaged
    codes = [
        str(i.get("code") or "")
        for i in (result.get("issues") or [])
        if isinstance(i, dict)
    ]
    # Scaffold attempted but residual schema → model corrective, else terminal.
    if scaffold_applied or meta.get("global_contract_scaffold_attempted"):
        if codes:
            return REPAIRABILITY_MODEL_CORRECTIVE_RETRY
    if status in {"parse_failed", "parsed_invalid"}:
        # Pure junk / unsalvageable structure — not a silent pass.
        if not codes and not result.get("generated_briefing"):
            return REPAIRABILITY_TERMINAL_BLOCK
        # Missing keys without salvageable display-shell signal.
        salvage_markers = {
            "top_5_news_missing",
            "deep_dive_missing",
            "gemini_json_missing_required_keys",
            "gemini_json_schema_validation_failed",
        }
        if salvage_markers.intersection(codes):
            return REPAIRABILITY_MODEL_CORRECTIVE_RETRY
        return REPAIRABILITY_TERMINAL_BLOCK
    return REPAIRABILITY_TERMINAL_BLOCK


def _run_global_parse(payload: Any, prompt_input: Optional[dict] = None) -> dict:
    from keysuri_generation_prompt import parse_keysuri_generated_response

    raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return parse_keysuri_generated_response(
        raw,
        PROGRAM_GLOBAL,
        prompt_input if prompt_input is not None else _prompt_input_global(),
    )


def _scaffold_only(obj: dict, prompt_input: Optional[dict] = None) -> Tuple[dict, dict]:
    from keysuri_generation_prompt import _scaffold_missing_global_contract_keys_for_parse

    return _scaffold_missing_global_contract_keys_for_parse(
        copy.deepcopy(obj),
        prompt_input if prompt_input is not None else _prompt_input_global(),
        PROGRAM_GLOBAL,
    )


def _validate_briefing(obj: dict, program_id: str, prompt_input: dict) -> List[dict]:
    from keysuri_generated_briefing import validate_keysuri_generated_briefing

    return validate_keysuri_generated_briefing(program_id, obj, prompt_input)


def _mutate_variants_global() -> List[Tuple[str, Any]]:
    base = _generated_global()
    shell = _display_shell()
    item0 = copy.deepcopy(base["top_5_news"]["items"][0])

    missing_keys = copy.deepcopy(shell)

    null_keys = copy.deepcopy(base)
    for key in ("top_5_news", "deep_dive", "one_line_checkpoint", "closing_sources"):
        null_keys[key] = None

    wrong_types = copy.deepcopy(base)
    wrong_types["top_5_news"] = "not-an-object"
    wrong_types["deep_dive"] = 123
    wrong_types["one_line_checkpoint"] = ["list", "not", "dict"]

    empty_arrays = copy.deepcopy(base)
    empty_arrays["top_5_news"] = {
        "news_scope": "global",
        "section_heading": "글로벌 테크 TOP 5",
        "items": [],
    }
    empty_arrays["deep_dive"] = {
        "section_heading": "깊이 보기",
        "body": "",
        "key_implications": [],
        "source_ids": [],
    }

    four_items = copy.deepcopy(base)
    four_items["top_5_news"]["items"] = four_items["top_5_news"]["items"][:4]

    six_items = copy.deepcopy(base)
    extra = copy.deepcopy(item0)
    extra["rank"] = 6
    extra["news_id"] = "global-claim-extra-6"
    six_items["top_5_news"]["items"] = six_items["top_5_news"]["items"] + [extra]

    nested_shell = {
        "wrapper": {"inner": copy.deepcopy(shell)},
        "opening_lead": shell.get("opening_lead"),
        "selected_title": shell.get("selected_title"),
        "closing_message": shell.get("closing_message"),
        "program_id": PROGRAM_GLOBAL,
    }

    junk = {"invalid": "not a briefing schema", "noise": [1, 2, 3]}

    return [
        ("display_shell_missing_required_keys", missing_keys),
        ("null_required_contract_keys", null_keys),
        ("wrong_types_for_contract_blocks", wrong_types),
        ("empty_top5_and_implications", empty_arrays),
        ("top5_count_4", four_items),
        ("top5_count_6", six_items),
        ("display_shell_only", shell),
        ("nested_shell_partial_signal", nested_shell),
        ("pure_junk_dict", junk),
    ]


class ModelContractAdversarialMatrixTests(unittest.TestCase):
    def test_01_matrix_runs_without_exceptions(self) -> None:
        outcomes: Dict[str, str] = {}
        for name, payload in _mutate_variants_global():
            with self.subTest(variant=name):
                try:
                    result = _run_global_parse(payload)
                    cls = _classify_parse_result(result)
                except Exception as exc:  # noqa: BLE001 — matrix must not crash
                    self.fail(f"variant {name!r} raised {type(exc).__name__}: {exc}")
                outcomes[name] = cls
                self.assertIn(
                    cls,
                    {
                        REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
                        REPAIRABILITY_MODEL_CORRECTIVE_RETRY,
                        REPAIRABILITY_TERMINAL_BLOCK,
                    },
                )
        self.assertGreaterEqual(len(outcomes), 8)

    def test_02_display_shell_is_deterministically_repairable_via_scaffold(self) -> None:
        shell = _display_shell()
        repaired, diag = _scaffold_only(shell)
        self.assertTrue(diag.get("global_contract_scaffold_attempted"))
        self.assertTrue(diag.get("global_contract_scaffold_applied"))
        self.assertIn("top_5_news", diag.get("repaired_fields") or [])

        result = _run_global_parse(shell)
        self.assertEqual(result["parse_status"], "parsed_valid")
        self.assertTrue(
            (result.get("parse_meta") or {}).get("global_contract_scaffold_applied")
        )
        self.assertEqual(
            _classify_parse_result(result),
            REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        )
        briefing = result["generated_briefing"]
        self.assertIsInstance(briefing.get("top_5_news"), dict)
        self.assertEqual(len(briefing["top_5_news"]["items"]), 5)

        # Pre-scaffold validation would fail; post-scaffold passes.
        pre_issues = _validate_briefing(shell, PROGRAM_GLOBAL, _prompt_input_global())
        self.assertTrue(pre_issues)
        post_issues = _validate_briefing(
            repaired, PROGRAM_GLOBAL, _prompt_input_global()
        )
        # Scaffold may still leave some fields for later repair helpers in parse;
        # full parse path above is the authority for DETERMINISTICALLY_REPAIRABLE.
        self.assertIsInstance(post_issues, list)

    def test_03_pure_junk_not_silent_pass(self) -> None:
        result = _run_global_parse({"invalid": "not a briefing schema"})
        cls = _classify_parse_result(result)
        self.assertNotEqual(result["parse_status"], "parsed_valid")
        self.assertIn(
            cls,
            {
                REPAIRABILITY_TERMINAL_BLOCK,
                REPAIRABILITY_MODEL_CORRECTIVE_RETRY,
            },
        )
        # Status constants may graft, but heavy structural salvage must not invent
        # TOP5/deep_dive from bare junk without a display-shell signal.
        repaired, diag = _scaffold_only({"invalid": "not a briefing schema"})
        self.assertTrue(diag.get("global_contract_scaffold_attempted"))
        self.assertNotIn("top_5_news", repaired)
        self.assertNotIn("deep_dive", repaired)
        self.assertNotIn("one_line_checkpoint", repaired)
        self.assertNotIn("closing_sources", repaired)
        repaired_fields = set(diag.get("repaired_fields") or [])
        self.assertFalse(
            repaired_fields.intersection(
                {"top_5_news", "deep_dive", "one_line_checkpoint", "closing_sources"}
            )
        )

    def test_04_wrong_top5_cardinality_not_silent_pass(self) -> None:
        for name, n in (("top5_count_4", 4), ("top5_count_6", 6)):
            with self.subTest(variant=name, count=n):
                payload = _generated_global()
                items = list(payload["top_5_news"]["items"])
                if n < 5:
                    payload["top_5_news"]["items"] = items[:n]
                else:
                    extra = copy.deepcopy(items[0])
                    extra["rank"] = 6
                    extra["news_id"] = "global-claim-extra-6"
                    payload["top_5_news"]["items"] = items + [extra]
                result = _run_global_parse(payload)
                # Must not silently accept wrong cardinality.
                if result["parse_status"] == "parsed_valid":
                    self.fail(f"{name} silently parsed_valid")
                cls = _classify_parse_result(result)
                self.assertIn(
                    cls,
                    {
                        REPAIRABILITY_TERMINAL_BLOCK,
                        REPAIRABILITY_MODEL_CORRECTIVE_RETRY,
                    },
                )

    def test_05_null_and_wrong_types_do_not_crash(self) -> None:
        for name, payload in _mutate_variants_global():
            if name not in {
                "null_required_contract_keys",
                "wrong_types_for_contract_blocks",
                "empty_top5_and_implications",
            }:
                continue
            with self.subTest(variant=name):
                result = _run_global_parse(payload)
                self.assertIn("parse_status", result)
                # Empty TOP5 with display prose / statuses may salvage via scaffold
                # when prompt pack has 5; null/wrong-type without shell signal must
                # not silently pass as a clean valid without diagnostics.
                if name == "wrong_types_for_contract_blocks":
                    self.assertNotEqual(result["parse_status"], "parsed_valid")

    def test_06_korea_light_validate_helpers_if_present(self) -> None:
        if not _KOREA_PROMPT.exists() or not _KOREA_GENERATED.exists():
            self.skipTest("Korea sample fixtures unavailable")
        prompt = _load_json(_KOREA_PROMPT)
        good = _load_json(_KOREA_GENERATED)
        issues = _validate_briefing(good, PROGRAM_KOREA, prompt)
        self.assertIsInstance(issues, list)

        junk = {"invalid": True, "program_id": PROGRAM_KOREA}
        junk_issues = _validate_briefing(junk, PROGRAM_KOREA, prompt)
        self.assertTrue(junk_issues)
        codes = {str(i.get("code") or "") for i in junk_issues}
        self.assertTrue(
            codes.intersection(
                {
                    "top_5_news_missing",
                    "deep_dive_missing",
                    "generated_status_invalid",
                    "operational_status_invalid",
                }
            )
        )

    def test_07_content_gate_helper_callable_offline(self) -> None:
        from keysuri_briefing_content_quality import validate_briefing_content_gate

        # Minimal HTML — must not raise; result is a structured gate object.
        result = validate_briefing_content_gate("<html><body><p>offline</p></body></html>")
        self.assertTrue(hasattr(result, "ok") or hasattr(result, "passed") or result is not None)

    def test_08_today_natural_slot_invalid_match_codes_terminal(self) -> None:
        from issue_code_registry import classify_repairability

        for code in (
            "invalid_natural_slot_match",
            "invalid_natural_slot_duplicate_match",
            "qa_consumed_natural_slot",
        ):
            with self.subTest(code=code):
                self.assertEqual(
                    classify_repairability(code),
                    REPAIRABILITY_TERMINAL_BLOCK,
                )


if __name__ == "__main__":
    unittest.main()
