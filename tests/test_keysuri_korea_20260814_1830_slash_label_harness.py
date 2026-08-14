"""Korea 2026-08-14 18:30 incident: compact slash label reached visible prose.

Production evidence (run_id 20260814_183450_keysuri_korea_tech_76737863):
the model-authored one-line checkpoint contained the compact internal label
"AI/로봇". ``build_korea_one_line_checkpoint`` returned that text verbatim
through its "keep a substantive existing checkpoint" branch, so the Korea
customer-prose normalizer never ran, and post-render QA correctly blocked with
``korea_visible_text_customer_slash_label_artifact``.

The fix is on the producer side. These tests pin both directions:
the gate must keep blocking malformed surfaces, and the producer must stop
emitting them.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from keysuri_briefing_content_quality import _KOREA_CUSTOMER_SLASH_LABEL_RE
from keysuri_korea_longform_ux import (
    build_korea_one_line_checkpoint,
    sanitize_korea_customer_prose,
)
from keysuri_visible_text import polish_korea_checkpoint_text

# Exact visible text from the 18:34:50 failure artifact.
PRODUCTION_CHECKPOINT_20260814 = (
    "내일 SMR 및 AI/로봇 관련 국내 대기업의 구체적인 투자 계획과 정부의 정책 지원 "
    "예산안을 먼저 확인하고, 아직 규제 및 사업성 검토가 완료되지 않은 초기 단계의 "
    "발표에는 신중한 판단을 유지해야 합니다."
)


def _slash_label_hits(text: str):
    return [m.group(0) for m in _KOREA_CUSTOMER_SLASH_LABEL_RE.finditer(text)]


class KoreaSlashLabelGateStillBlocksTests(unittest.TestCase):
    """The validator must not be weakened: malformed surfaces still block."""

    def test_production_raw_text_is_a_true_positive(self) -> None:
        self.assertEqual(
            _slash_label_hits(PRODUCTION_CHECKPOINT_20260814), ["AI/로봇"]
        )

    def test_every_compact_internal_label_still_blocks(self) -> None:
        for label in (
            "협력사/소부장",
            "로봇/에이전트",
            "로봇/AI",
            "AI/로봇",
            "정책/공공",
            "투자/지원",
            "장비/소재",
            "파트너/고객/입찰",
            "일자리/지역",
        ):
            with self.subTest(label=label):
                self.assertEqual(
                    _slash_label_hits(f"내일 {label} 관련 동향을 확인하시면 됩니다."),
                    [label],
                )

    def test_legitimate_slash_expressions_are_not_blocked(self) -> None:
        """Ordinary technical slash pairs must stay valid customer prose."""
        for phrase in (
            "AI/ML 파이프라인 투자",
            "CPU/GPU 수급 상황",
            "B2B/B2C 채널 전략",
            "read/write 성능 개선",
            "hardware/software 통합",
            "https://example.com/a/b 링크",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(_slash_label_hits(phrase), [])


class KoreaOneLineCheckpointProducerTests(unittest.TestCase):
    """Producer fix: the passthrough branch must normalize before returning."""

    def test_model_checkpoint_is_normalized_not_passed_through(self) -> None:
        out = build_korea_one_line_checkpoint(
            [], existing=PRODUCTION_CHECKPOINT_20260814
        )
        self.assertEqual(_slash_label_hits(out), [])
        self.assertIn("AI와 로봇", out)
        self.assertNotIn("AI/로봇", out)

    def test_final_rendered_stage_also_clean(self) -> None:
        """Full checkpoint path: builder -> polish -> visible body."""
        rendered = polish_korea_checkpoint_text(
            build_korea_one_line_checkpoint(
                [], existing=PRODUCTION_CHECKPOINT_20260814
            )
        )
        self.assertEqual(_slash_label_hits(rendered), [])

    def test_exact_incident_text_reaches_final_gmail_visible_qa_pass(self) -> None:
        """Producer -> real Gmail renderer -> final pre-SMTP visible QA."""
        from keysuri_briefing_content_quality import (
            validate_korea_post_render_visible_quality,
        )
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            build_keysuri_korea_gmail_owner_email_html,
            prepare_contract_preview_fixture,
        )
        from tests.test_keysuri_contract_preview_renderer import (
            build_korea_contract_fixture,
        )

        fixture = build_korea_contract_fixture()
        fixture["one_line_checkpoint"] = build_korea_one_line_checkpoint(
            [], existing=PRODUCTION_CHECKPOINT_20260814
        )
        fixture["top_shot_image_src"] = "cid:keysuri_topshot_korea_aug14_lineage"
        prepare_contract_preview_fixture(
            fixture,
            repo_root=Path(__file__).resolve().parents[1],
            image_mode=IMAGE_MODE_EMAIL,
        )
        email_html = build_keysuri_korea_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Korea Tech",
            admin_url="https://example.com/admin/runs/aug14-lineage",
            run_id="aug14-lineage",
        )
        result = validate_korea_post_render_visible_quality(email_html)

        self.assertIn("AI와 로봇", email_html)
        self.assertNotIn("AI/로봇", email_html)
        self.assertTrue(result.ok, result.issues)
        self.assertNotIn(
            "korea_visible_text_customer_slash_label_artifact",
            {issue.code for issue in result.issues},
        )

    def test_substantive_checkpoint_content_is_preserved(self) -> None:
        """Normalizing must not discard the model's actual observation."""
        out = build_korea_one_line_checkpoint(
            [], existing=PRODUCTION_CHECKPOINT_20260814
        )
        for kept in ("SMR", "투자 계획", "정책 지원", "신중한 판단"):
            self.assertIn(kept, out)

    def test_every_compact_label_is_repaired_by_the_producer(self) -> None:
        for label in (
            "협력사/소부장",
            "로봇/에이전트",
            "로봇/AI",
            "AI/로봇",
            "정책/공공",
            "투자/지원",
            "장비/소재",
            "파트너/고객/입찰",
            "일자리/지역",
        ):
            with self.subTest(label=label):
                existing = (
                    f"내일 국내 {label} 관련 대기업의 구체적인 투자 계획과 정책 "
                    f"지원 예산안을 먼저 확인하시면 됩니다."
                )
                out = build_korea_one_line_checkpoint([], existing=existing)
                self.assertEqual(_slash_label_hits(out), [])

    def test_synthesized_fallback_unchanged_and_clean(self) -> None:
        """The deterministic branch must keep its exact wording."""
        items = [
            {"korean_title": "삼성전자 HBM 증설", "headline": "a"},
            {"korean_title": "SK하이닉스 신규 라인", "headline": "b"},
        ]
        out = build_korea_one_line_checkpoint(items)
        self.assertEqual(out, sanitize_korea_customer_prose(out))
        self.assertIn("글로벌·국내 TOP5를 종합하면", out)
        self.assertIn("판단을 보류하시면 됩니다", out)
        self.assertEqual(_slash_label_hits(out), [])

    def test_thin_existing_still_falls_back_to_synthesis(self) -> None:
        """Fix must not change which branch is taken."""
        out = build_korea_one_line_checkpoint(
            [{"korean_title": "삼성전자 HBM 증설", "headline": "a"}],
            existing="한 가지만 먼저 보시면 됩니다",
        )
        self.assertIn("글로벌·국내 TOP5를 종합하면", out)

    def test_short_existing_still_falls_back_to_synthesis(self) -> None:
        out = build_korea_one_line_checkpoint(
            [{"korean_title": "삼성전자 HBM 증설", "headline": "a"}],
            existing="국내 반도체",
        )
        self.assertIn("글로벌·국내 TOP5를 종합하면", out)


if __name__ == "__main__":
    unittest.main()
