from __future__ import annotations

import unittest

from keysuri_visible_text_quality import (
    KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED,
    KEYSURI_KOREAN_REPEATED_TOKEN_REPAIRED,
    repair_korean_connector_ellipsis_text,
    validate_and_repair_keysuri_visible_text_quality,
    validate_keysuri_html_visible_text_quality,
)


class KeysuriVisibleTextQualityTests(unittest.TestCase):
    def test_problem_sentence_repairs_to_complete_korean_prose(self) -> None:
        broken = (
            "오늘 눈에 띄는 점은 엔비디아와 AWS, 대규모 AI 생산을 위한… 흐름과 "
            "기업들이 신뢰할 수 있는 특화된 AI를 구축… 이슈가 동시에 보인다는 것입니다."
        )
        result = repair_korean_connector_ellipsis_text(broken)

        self.assertTrue(result.found)
        self.assertTrue(result.repaired)
        self.assertFalse(result.blocked)
        self.assertNotRegex(result.text, r"…|\.{2,}")
        self.assertIn("대규모 AI 생산 인프라", result.text)
        self.assertIn("기업 맞춤형 AI 구축 흐름", result.text)
        self.assertIn("동시에 두드러졌습니다.", result.text)

    def test_simple_modifier_connection_repairs_without_blank_deletion(self) -> None:
        result = repair_korean_connector_ellipsis_text(
            "AI 생산을 위한… 흐름과 기업 특화 AI를 구축… 이슈가 함께 보입니다."
        )

        self.assertFalse(result.blocked)
        self.assertNotRegex(result.text, r"…|\.{2,}")
        self.assertIn("AI 생산을 위한 흐름", result.text)
        self.assertIn("구축 이슈", result.text)

    def test_object_marked_construct_ellipsis_drops_stray_particle(self) -> None:
        result = repair_korean_connector_ellipsis_text(
            "특화된 AI를 구축… 이슈가 있습니다"
        )

        self.assertTrue(result.found)
        self.assertTrue(result.repaired)
        self.assertFalse(result.blocked)
        self.assertNotRegex(result.text, r"…|\.{2,}|\.{2}")
        self.assertNotIn("를 구축 이슈", result.text)
        self.assertNotIn("을 구축 이슈", result.text)
        self.assertNotEqual(result.text, "특화된 AI를 구축 이슈가 있습니다")
        self.assertIn("AI 구축 이슈", result.text)

    def test_object_marked_construct_ellipsis_in_longer_sentence(self) -> None:
        result = repair_korean_connector_ellipsis_text(
            "기업들이 신뢰할 수 있는 특화된 AI를 구축… 이슈가 있습니다"
        )

        self.assertTrue(result.found)
        self.assertTrue(result.repaired)
        self.assertFalse(result.blocked)
        self.assertNotRegex(result.text, r"…|\.{2,}|\.{2}")
        self.assertNotIn("를 구축 이슈", result.text)
        self.assertNotIn("을 구축 이슈", result.text)

    def test_trailing_ellipsis_repaired_not_blocked(self) -> None:
        """Terminal trailing ellipsis is now repaired by stripping."""
        payload = {
            "top_5_news": {
                "items": [
                    {
                        "korean_title": "확인 불가…",
                        "source_url": "https://example.com/a...b",
                    }
                ]
            }
        }

        repaired, fields = validate_and_repair_keysuri_visible_text_quality(payload)

        self.assertEqual(fields["visible_text_quality_status"], "pass")
        self.assertTrue(fields["visible_text_ellipsis_found"])
        self.assertTrue(fields["visible_text_ellipsis_repaired"])
        self.assertFalse(fields["visible_text_ellipsis_blocked"])
        self.assertEqual(repaired["top_5_news"]["items"][0]["korean_title"], "확인 불가")
        # URL fields are not checked/repaired
        self.assertEqual(repaired["top_5_news"]["items"][0]["source_url"], "https://example.com/a...b")

    def test_live_korea_connector_ellipsis_repaired(self) -> None:
        """Reproduce the bec8c744 live failure pattern: mid-sentence '..' connectors."""
        text = (
            "현재 글로벌 반도체 수요가 급증하는 상황에서.. "
            "삼성의 이번 투자는 기흥.. 화성.. 평택에 이은 새로운 반도체 생산 거점 확보를 "
            "의미합니다. 이는 국내 반도체 산업의 경쟁력을 강화하고.. AI 시대에 필요한 인프라"
        )
        result = repair_korean_connector_ellipsis_text(text)

        self.assertTrue(result.found)
        self.assertTrue(result.repaired)
        self.assertFalse(result.blocked)
        self.assertNotRegex(result.text, r"…|\.{2,}")
        self.assertIn("상황에서 삼성의", result.text)
        self.assertIn("강화하고 AI", result.text)

    def test_headline_ellipsis_before_quote_repaired(self) -> None:
        """Source headline with '…' before quote: should repair, not block."""
        text = "박관호 위메이드 의장, 9200억원 메가딜… '미르' IP 중국계 자본 품으로"
        result = repair_korean_connector_ellipsis_text(text)

        self.assertTrue(result.found)
        self.assertTrue(result.repaired)
        self.assertFalse(result.blocked)
        self.assertNotRegex(result.text, r"…|\.{2,}")
        self.assertIn("메가딜", result.text)
        self.assertIn("미르", result.text)

    def test_summary_trailing_dots_repaired(self) -> None:
        """Source summary ending with '...': should repair by stripping."""
        text = "삼성전자와 SK하이닉스 등의 반도체 투자 계획이 전남광주의 해묵은 현안을 풀어낼 수 있다..."
        result = repair_korean_connector_ellipsis_text(text)

        self.assertTrue(result.found)
        self.assertTrue(result.repaired)
        self.assertFalse(result.blocked)
        self.assertNotRegex(result.text, r"…|\.{2,}")
        self.assertTrue(result.text.endswith("있다"))

    def test_full_payload_live_pattern_passes_after_repair(self) -> None:
        """Full payload mimicking the bec8c744 live failure: should pass after repair."""
        payload = {
            "top_5_news": {
                "items": [
                    {
                        "headline": "철강 문턱 높인 EU…무관세 물량 반토막",
                        "why_it_matters": (
                            "EU의 이번 조치는 글로벌 철강 공급 과잉에 대응하기 위한 것으로.. "
                            "국내 철강 기업들의 EU 수출 전략에 즉각적인 영향을 미칠 것입니다."
                        ),
                        "summary": "삼성전자와 SK하이닉스 등의 투자 계획이 현안을 풀어낼 수 있다...",
                    }
                ]
            }
        }

        repaired, fields = validate_and_repair_keysuri_visible_text_quality(payload)

        self.assertEqual(fields["visible_text_quality_status"], "pass")
        self.assertTrue(fields["visible_text_ellipsis_found"])
        self.assertTrue(fields["visible_text_ellipsis_repaired"])
        self.assertFalse(fields["visible_text_ellipsis_blocked"])
        # Verify no ellipsis remains in repaired text
        self.assertNotRegex(repaired["top_5_news"]["items"][0]["headline"], r"…|\.{2,}")
        self.assertNotRegex(repaired["top_5_news"]["items"][0]["why_it_matters"], r"…|\.{2,}")
        self.assertNotRegex(repaired["top_5_news"]["items"][0]["summary"], r"…|\.{2,}")

    def test_genuinely_unrecoverable_ellipsis_still_blocks(self) -> None:
        """Ellipsis in final rendered HTML always blocks regardless of repair."""
        # The HTML validator is the strict final gate: any ellipsis found = block
        fields = validate_keysuri_html_visible_text_quality(
            "<p>투자 계획이… 현안을 풀어낼 수 있다</p>"
        )

        self.assertTrue(fields["visible_text_ellipsis_found"])
        self.assertTrue(fields["visible_text_ellipsis_blocked"])
        self.assertEqual(fields["visible_text_quality_status"], "block")

    def test_recursive_payload_repair_fields(self) -> None:
        payload = {"deep_dive": {"body": "대규모 AI를 위한… 흐름이 관찰됐습니다."}}

        repaired, fields = validate_and_repair_keysuri_visible_text_quality(payload)

        self.assertEqual(fields["visible_text_quality_status"], "pass")
        self.assertTrue(fields["visible_text_ellipsis_found"])
        self.assertTrue(fields["visible_text_ellipsis_repaired"])
        self.assertFalse(fields["visible_text_ellipsis_blocked"])
        self.assertNotRegex(repaired["deep_dive"]["body"], r"…|\.{2,}")

    def test_repeated_korean_token_repaired_in_payload(self) -> None:
        payload = {
            "one_line_checkpoint": {
                "body": "이 흐름은 국내 산업에 어떤 영향을 미 미칠 것인가?"
            }
        }

        repaired, fields = validate_and_repair_keysuri_visible_text_quality(payload)

        self.assertEqual(fields["visible_text_quality_status"], "pass")
        self.assertTrue(fields["visible_text_repeated_token_found"])
        self.assertTrue(fields["visible_text_repeated_token_repaired"])
        self.assertIn(KEYSURI_KOREAN_REPEATED_TOKEN_REPAIRED, fields["visible_text_quality_issue_codes"])
        self.assertEqual(
            repaired["one_line_checkpoint"]["body"],
            "이 흐름은 국내 산업에 어떤 영향을 미칠 것인가?",
        )

    def test_html_visible_text_validator_blocks_renderer_leftovers(self) -> None:
        fields = validate_keysuri_html_visible_text_quality(
            "<html><body><p>공급망 변화... 확인 중입니다.</p></body></html>"
        )

        self.assertEqual(fields["visible_text_quality_status"], "block")
        self.assertTrue(fields["visible_text_ellipsis_blocked"])


if __name__ == "__main__":
    unittest.main()
