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

    def test_unrecoverable_trailing_ellipsis_blocks_with_sample(self) -> None:
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

        self.assertEqual(fields["visible_text_quality_status"], "block")
        self.assertTrue(fields["visible_text_ellipsis_found"])
        self.assertTrue(fields["visible_text_ellipsis_blocked"])
        self.assertIn(KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED, fields["visible_text_quality_issue_codes"])
        self.assertLessEqual(len(fields["visible_text_quality_samples"][0]["sample"]), 120)
        self.assertEqual(repaired["top_5_news"]["items"][0]["source_url"], "https://example.com/a...b")

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
