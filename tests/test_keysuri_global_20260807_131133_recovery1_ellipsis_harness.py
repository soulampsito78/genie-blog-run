"""Harness for KeeSuri Global recovery #1 ellipsis block (2026-08-07 13:11).

Recovery #1 run 20260807_131133_keysuri_global_tech_96d921fa failed on
keysuri_korean_connector_ellipsis_blocked after a complete contract + image
generation — not the earlier display-shell defect. Root: ellipsis repair
delimiter class omitted U+201C/U+201D curly double quotes.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_FIXTURE = (
    _REPO
    / "ops"
    / "feeds"
    / "incident_fixtures"
    / "20260807_131133_keysuri_global_recovery1_ellipsis.json"
)
_PRE_PATCH_DELIM = r"(?<=[A-Za-z0-9가-힣])\s*…\s*(?=['\u2018\u2019'\"「『\(\[\u3008\u300A])"
_POST_PATCH_DELIM = (
    r"(?<=[A-Za-z0-9가-힣])\s*…\s*(?=['\u2018\u2019'\"\u201c\u201d「『\(\[\u3008\u300A])"
)


def _simulate_repair(text: str, delim_pattern: str):
    from keysuri_visible_text_quality import contains_connector_ellipsis

    original = text
    if not contains_connector_ellipsis(original):
        return False, False
    repaired = re.sub(r"\.{2,}", "…", original)
    repaired = re.sub(r"(?<=[A-Za-z0-9가-힣])\s*…\s*(?=[A-Za-z0-9가-힣])", " ", repaired)
    repaired = re.sub(delim_pattern, " ", repaired)
    repaired = re.sub(r"\s*…\s*$", "", repaired)
    repaired = re.sub(r"\s*…\s*(?=[.!?。！？])", "", repaired)
    repaired = re.sub(r"\s+([,.!?])", r"\1", repaired)
    repaired = re.sub(r"\s+", " ", repaired).strip()
    blocked = contains_connector_ellipsis(repaired)
    return (not blocked), blocked


class Recovery1EllipsisHarness(unittest.TestCase):
    def test_01_pre_patch_simulation_blocks_curly_quote_pattern(self) -> None:
        fx = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        text = fx["blocking_pattern_example"]
        _ok, blocked = _simulate_repair(text, _PRE_PATCH_DELIM)
        self.assertTrue(blocked)

    def test_02_post_patch_repairs_same_pattern(self) -> None:
        from keysuri_visible_text_quality import (
            KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED,
            repair_korean_connector_ellipsis_text,
            validate_and_repair_keysuri_visible_text_quality,
        )

        fx = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        text = fx["blocking_pattern_example"]
        result = repair_korean_connector_ellipsis_text(text)
        self.assertFalse(result.blocked)
        self.assertTrue(result.repaired)
        repaired, fields = validate_and_repair_keysuri_visible_text_quality(
            {"top_5_news": {"items": [{"what_happened": text}]}}
        )
        self.assertEqual(fields["visible_text_quality_status"], "pass")
        self.assertNotIn(
            KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED,
            fields.get("visible_text_quality_issue_codes") or [],
        )
        self.assertNotRegex(repaired["top_5_news"]["items"][0]["what_happened"], r"…|\.{2,}")

    def test_03_display_shell_fixture_still_salvages(self) -> None:
        from keysuri_generation_prompt import parse_keysuri_generated_response

        shell_fx = json.loads(
            (
                _REPO
                / "ops/feeds/incident_fixtures/20260807_1230_keysuri_global_display_shell.json"
            ).read_text(encoding="utf-8")
        )
        pi = json.loads(
            (_REPO / "ops/feeds/keysuri_global_prompt_input.sample.json").read_text(
                encoding="utf-8"
            )
        )
        pi.pop("_fixture_note", None)
        result = parse_keysuri_generated_response(
            json.dumps(shell_fx["model_display_shell"], ensure_ascii=False),
            "keysuri_global_tech",
            pi,
        )
        self.assertEqual(result["parse_status"], "parsed_valid")

    def test_04_junk_json_still_fails(self) -> None:
        from keysuri_generation_prompt import parse_keysuri_generated_response

        pi = json.loads(
            (_REPO / "ops/feeds/keysuri_global_prompt_input.sample.json").read_text(
                encoding="utf-8"
            )
        )
        pi.pop("_fixture_note", None)
        result = parse_keysuri_generated_response(
            json.dumps({"invalid": "x"}), "keysuri_global_tech", pi
        )
        self.assertNotEqual(result["parse_status"], "parsed_valid")

    def test_05_html_unrepaired_ellipsis_still_blocks(self) -> None:
        from keysuri_visible_text_quality import validate_keysuri_html_visible_text_quality

        fields = validate_keysuri_html_visible_text_quality(
            "<p>투자 계획이… 현안을 풀어낼 수 있다</p>"
        )
        self.assertEqual(fields["visible_text_quality_status"], "block")


if __name__ == "__main__":
    unittest.main()
