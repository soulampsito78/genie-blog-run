from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from admin_store import _normalize_run_memory_evidence
from keysuri_briefing_content_enricher import _build_what_happened
from keysuri_live_source_smoke import LiveSourceSmokeResult, PROGRAM_KOREA
from keysuri_service_full_run import run_keysuri_service_full_run
from keysuri_visible_text import (
    contains_dangling_quoted_title_fragment,
    normalize_visible_text,
    normalize_visible_title,
)
from keysuri_visible_text_quality import (
    KEYSURI_DANGLING_QUOTED_TITLE_BLOCKED,
    validate_and_repair_keysuri_visible_text_quality,
    validate_keysuri_html_visible_text_quality,
)
from service_full_run_contract import IMAGE_SOURCE_GENERATED, ServiceImageOutcome


FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "keysuri_korea_20260814_233109_dangling_title.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class KoreaProductionDanglingTitleTests(unittest.TestCase):
    def test_01_legacy_producer_reproduces_exact_terminal_fragment(self) -> None:
        fx = _fixture()
        canonical = fx["canonical_source_headline"]
        legacy = normalize_visible_text(canonical, style="inline")
        self.assertEqual(legacy, fx["legacy_generated_title"])
        sentence = f'{fx["source_name"]} 공개 요약에 따르면 「{legacy}」 관련 변화가 보고되었습니다.'
        self.assertEqual(sentence, fx["exact_offending_sentence"])
        self.assertTrue(contains_dangling_quoted_title_fragment(sentence))

        payload = {"top_5_news": {"items": [{}, {"what_happened": sentence}]}}
        _repaired, fields = validate_and_repair_keysuri_visible_text_quality(payload)
        self.assertEqual(fields["terminal_issue_codes"], [KEYSURI_DANGLING_QUOTED_TITLE_BLOCKED])
        self.assertEqual(fields["visible_text_quality_status"], "block")
        terminal = [
            row
            for row in fields["visible_text_quality_samples"]
            if row.get("validator_result") == "block"
        ]
        self.assertEqual(terminal[0]["path"], fx["field_paths"][0])
        self.assertIn("「美 투자 압박'", terminal[0]["sample"])

    def test_02_quote_preserving_title_producer_restores_grounded_surface(self) -> None:
        fx = _fixture()
        canonical = fx["canonical_source_headline"]
        self.assertEqual(normalize_visible_title(canonical), canonical)

        item = {
            "rank": 2,
            "news_id": fx["source_id"],
            "korean_title": canonical,
            "what_happened": (
                "미국 상무부 관련 보도에 대해 청와대가 통상 현안에 수시로 대응하고 "
                "있다고 밝혔습니다. 후속 공식 발표를 확인해야 합니다."
            ),
        }
        meta = {
            "statement": canonical,
            "source_name": fx["source_name"],
            "primary_category": fx["primary_category"],
            "category_display_label": fx["category_display_label"],
        }
        visible, _thin = _build_what_happened(item, meta)
        # The invariant is the grounded surface, not the padding wording: the
        # attribution sentence must quote the whole canonical headline and must
        # never reproduce the truncated fragment. The phrasing itself rotates by
        # rank so five TOP5 cards do not share one sentence skeleton.
        self.assertIn(f"「{canonical}」", visible)
        self.assertIn(fx["source_name"], visible)
        self.assertNotIn(fx["exact_offending_sentence"], visible)
        self.assertFalse(contains_dangling_quoted_title_fragment(visible))

        repaired, fields = validate_and_repair_keysuri_visible_text_quality(
            {"top_5_news": {"items": [{}, {"what_happened": visible}]}}
        )
        self.assertEqual(fields["visible_text_quality_status"], "pass")
        self.assertEqual(fields["terminal_issue_codes"], [])
        html_fields = validate_keysuri_html_visible_text_quality(
            f"<p>{repaired['top_5_news']['items'][1]['what_happened']}</p>"
        )
        self.assertEqual(html_fields["visible_text_quality_status"], "pass")

    def test_03_unsafe_model_title_uses_only_safe_canonical_source_title(self) -> None:
        fx = _fixture()
        item = {
            "korean_title": fx["legacy_generated_title"],
            "what_happened": "첫 문장입니다. 둘째 문장입니다.",
        }
        meta = {
            "statement": fx["canonical_source_headline"],
            "source_name": fx["source_name"],
        }
        visible, _thin = _build_what_happened(item, meta)
        self.assertIn(f'「{fx["canonical_source_headline"]}」', visible)
        self.assertNotIn(f'「{fx["legacy_generated_title"]}」', visible)

    def test_04_balanced_quote_and_apostrophe_controls_pass(self) -> None:
        controls = (
            "「균형 잡힌 ‘한국어 제목’」",
            "「균형 잡힌 “한국어 제목”」",
            "「보고서 『세부 제목』 안내」",
            "「OpenAI's mixed 한국어 product title」",
            "「The builder’s guide」",
        )
        for text in controls:
            with self.subTest(text=text):
                self.assertFalse(contains_dangling_quoted_title_fragment(text))

    def test_05_genuinely_dangling_controls_still_block(self) -> None:
        controls = (
            "「열린 제목만 남았습니다",
            "닫는 제목만 남았습니다」",
            "「OpenAI introduces ‘Ultrafast」 확인 포인트는",
            "「잘린 제목과」 후속입니다.",
        )
        for text in controls:
            with self.subTest(text=text):
                self.assertTrue(contains_dangling_quoted_title_fragment(text))

    def test_06_memory_sidecar_distinguishes_reached_and_not_reached(self) -> None:
        normalized = _normalize_run_memory_evidence(
            {
                "source": "proc_status",
                "configured_limit_kib": 786_432,
                "stages": {
                    "after_image_generation": {
                        "reached": True,
                        "rss_kib": 300_000,
                        "hwm_kib": 301_000,
                        "image_status": "generated",
                    },
                    "before_owner_smtp": {
                        "reached": False,
                        "reason": "not_reached_due_to_validation_block",
                    },
                },
            }
        )
        image = normalized["stages"]["after_image_generation"]
        smtp = normalized["stages"]["before_owner_smtp"]
        self.assertEqual(
            image,
            {
                "rss_kib": 300_000,
                "hwm_kib": 301_000,
                "reached": True,
                "image_status": "generated",
            },
        )
        self.assertEqual(
            smtp,
            {
                "reached": False,
                "reason": "not_reached_due_to_validation_block",
            },
        )
        self.assertEqual(normalized["peak_hwm_kib"], 301_000)

    def test_07_service_validation_block_persists_image_and_smtp_stage_states(self) -> None:
        fx = _fixture()
        with tempfile.TemporaryDirectory() as td:
            generated_image = Path(td) / "generated.jpg"
            generated_image.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
            pack_path = Path(td) / "source_pack.json"
            pack_path.write_text(
                json.dumps({"program_id": PROGRAM_KOREA, "sources": [], "claims": []}),
                encoding="utf-8",
            )
            generated = {
                "top_5_news": {
                    "items": [
                        {},
                        {
                            "what_happened": fx["exact_offending_sentence"],
                            "briefing_item": {
                                "what_happened": fx["exact_offending_sentence"]
                            },
                        },
                    ]
                }
            }
            smoke = LiveSourceSmokeResult(
                ok=True,
                program_id=PROGRAM_KOREA,
                source_pack_path=str(pack_path),
                html_path=str(Path(td) / "smoke.html"),
                fetched_item_count=5,
                feed_urls_used=[],
                sample_marker_pass=True,
                called_gemini=True,
                use_gemini=True,
                parse_status="parsed_valid",
                generated_briefing=generated,
                validation_status="PASS",
                side_effects={"called_gemini": True, "called_image_api": False},
            )
            image = ServiceImageOutcome(
                called_image_api=True,
                image_generation_status="generated",
                image_source=IMAGE_SOURCE_GENERATED,
                generated_image_path=str(generated_image),
            )
            saved_memory: dict = {}

            def _capture_memory(_run_id: str, evidence: dict) -> dict:
                saved_memory.update(_normalize_run_memory_evidence(evidence))
                return saved_memory

            with (
                patch("keysuri_service_full_run.generate_run_id", return_value=fx["run_id"]),
                patch("keysuri_service_full_run.save_run_artifact"),
                patch("keysuri_service_full_run.save_run_memory_evidence", side_effect=_capture_memory),
                patch(
                    "keysuri_service_full_run._watermarked_top_shot_path",
                    return_value=generated_image,
                ),
                patch(
                    "keysuri_service_full_run.build_keysuri_prompt_input",
                    return_value={
                        "program_id": PROGRAM_KOREA,
                        "prompt_status": "ready_for_generation",
                        "source_pack": {"sources": [], "claims": []},
                    },
                ),
                patch.dict(os.environ, {"GENIE_OWNER_REVIEW_SEND": "1"}, clear=False),
            ):
                result = run_keysuri_service_full_run(
                    PROGRAM_KOREA,
                    trigger_source="manual_service_full_run",
                    send_owner_email=True,
                    smoke_runner=lambda **_kwargs: smoke,
                    image_canary_runner=lambda *_args, **_kwargs: image,
                    send_fn=lambda *_args, **_kwargs: True,
                )

        # A grounded punctuation defect is now an editorial REVIEW, not a
        # content kill-switch.  The owner surface remains available with a
        # truthful warning, while this test still performs no SMTP call.
        self.assertEqual(result["validation_result"], "pass")
        self.assertEqual(result["safety_verdict"], "SAFE")
        self.assertEqual(result["editorial_verdict"], "REVIEW")
        self.assertTrue(result["email_sent"])
        image_stage = saved_memory["stages"]["after_image_generation"]
        smtp_stage = saved_memory["stages"]["before_owner_smtp"]
        self.assertTrue(image_stage["reached"])
        self.assertEqual(image_stage["image_status"], "generated")
        self.assertGreater(image_stage["rss_kib"], 0)
        self.assertGreaterEqual(image_stage["hwm_kib"], image_stage["rss_kib"])
        self.assertTrue(smtp_stage["reached"])


if __name__ == "__main__":
    unittest.main()
