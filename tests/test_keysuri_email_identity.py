from __future__ import annotations

import inspect
import unittest

import keysuri_email_identity as identity
from keysuri_email_identity import (
    PROGRAM_GLOBAL,
    PROGRAM_KOREA,
    build_keysuri_customer_subject,
    build_keysuri_editorial_subject,
    build_keysuri_owner_review_subject,
    build_keysuri_preheader,
    build_keysuri_subject_artifact_fields,
    extract_keysuri_top_headline,
    sanitize_preheader_text,
    sanitize_subject_text,
)


class KeysuriEmailIdentityTests(unittest.TestCase):
    def test_global_subject_uses_generated_top_signal_headline(self) -> None:
        briefing = {
            "top_5_news": {
                "items": [
                    {
                        "korean_title": "엔비디아 추론 칩 수요가 클라우드 증설 압력을 키움",
                        "summary": "AI 인프라 지출이 다시 확대되는 흐름입니다.",
                    }
                ]
            }
        }
        subject = build_keysuri_editorial_subject(
            PROGRAM_GLOBAL,
            briefing,
            run_id="20260624_123000_keysuri_global_tech_aabbccdd",
        )

        self.assertIn("엔비디아 추론 칩 수요", subject)
        self.assertIn("6월 24일 글로벌 테크 브리핑", subject)
        self.assertNotIn("[운영자 검토]", subject)

    def test_korea_subject_uses_generated_top_signal_headline(self) -> None:
        briefing = {
            "top_5_news": {
                "items": [
                    {
                        "headline": "국내 반도체 장비주가 HBM 투자 재개 기대를 반영",
                        "summary": "국내 공급망 쪽 기대가 커졌습니다.",
                    }
                ]
            }
        }
        subject = build_keysuri_editorial_subject(
            PROGRAM_KOREA,
            briefing,
            run_id="20260624_183000_keysuri_korea_tech_aabbccdd",
        )

        self.assertIn("국내 반도체 장비주", subject)
        self.assertIn("6월 24일 국내 테크 브리핑", subject)

    def test_fallback_subjects_are_program_specific(self) -> None:
        global_subject = build_keysuri_editorial_subject(
            PROGRAM_GLOBAL,
            {},
            run_id="20260624_123000_keysuri_global_tech_aabbccdd",
        )
        korea_subject = build_keysuri_editorial_subject(
            PROGRAM_KOREA,
            {},
            run_id="20260624_183000_keysuri_korea_tech_aabbccdd",
        )

        self.assertEqual(global_subject, "글로벌 AI·테크 신호 점검: 6월 24일 글로벌 테크 브리핑")
        self.assertEqual(korea_subject, "국내 AI·테크 신호 점검: 6월 24일 국내 테크 브리핑")

    def test_owner_and_manual_prefixes(self) -> None:
        briefing = {"top_5_news": {"items": [{"headline": "AI 데이터센터 전력 계약이 확대"}]}}
        scheduled = build_keysuri_owner_review_subject(
            PROGRAM_GLOBAL,
            briefing,
            run_id="20260624_123000_keysuri_global_tech_aabbccdd",
            trigger_source="scheduled_owner_review",
        )
        manual = build_keysuri_owner_review_subject(
            PROGRAM_GLOBAL,
            briefing,
            run_id="20260624_123000_keysuri_global_tech_aabbccdd",
            trigger_source="manual_post_deploy_owner_trace_check",
        )

        self.assertTrue(scheduled.startswith("[운영자 검토] "))
        self.assertFalse(scheduled.startswith("[운영자 검토][수동]"))
        self.assertTrue(manual.startswith("[운영자 검토][수동] "))

    def test_manual_like_trigger_tokens(self) -> None:
        briefing = {"top_5_news": {"items": [{"headline": "AI 데이터센터 전력 계약이 확대"}]}}
        for trigger_source in ("manual_run", "force_retry", "deploy_check", "canary_probe", "post_deploy_check"):
            with self.subTest(trigger_source=trigger_source):
                subject = build_keysuri_owner_review_subject(
                    PROGRAM_GLOBAL,
                    briefing,
                    run_id="20260624_130501_keysuri_global_tech_aabbccdd",
                    trigger_source=trigger_source,
                )
                self.assertTrue(subject.startswith("[운영자 검토][수동] "))

    def test_customer_subject_removes_owner_prefix(self) -> None:
        subject = build_keysuri_customer_subject(
            PROGRAM_GLOBAL,
            meta={
                "editorial_subject": "AI 데이터센터 전력 계약이 확대: 6월 24일 글로벌 테크 브리핑",
                "owner_email_subject": "[운영자 검토][수동] AI 데이터센터 전력 계약이 확대: 6월 24일 글로벌 테크 브리핑",
            },
        )

        self.assertEqual(subject, "AI 데이터센터 전력 계약이 확대: 6월 24일 글로벌 테크 브리핑")
        self.assertNotIn("[운영자 검토]", subject)
        self.assertNotIn("[수동]", subject)

    def test_customer_subject_removes_manual_prefix_from_owner_only_meta(self) -> None:
        subject = build_keysuri_customer_subject(
            PROGRAM_GLOBAL,
            meta={
                "owner_email_subject": "[운영자 검토][수동] AI 데이터센터 전력 계약이 확대: 6월 24일 글로벌 테크 브리핑",
            },
        )

        self.assertEqual(subject, "AI 데이터센터 전력 계약이 확대: 6월 24일 글로벌 테크 브리핑")
        self.assertNotIn("[운영자 검토]", subject)
        self.assertNotIn("[수동]", subject)

    def test_preheader_uses_top_headline_without_repeating_subject(self) -> None:
        briefing = {"top_5_news": {"items": [{"headline": "AI 에이전트 보안 점검 수요가 확대"}]}}
        subject = build_keysuri_owner_review_subject(
            PROGRAM_GLOBAL,
            briefing,
            run_id="20260624_123000_keysuri_global_tech_aabbccdd",
        )
        preheader = build_keysuri_preheader(
            PROGRAM_GLOBAL,
            briefing,
            run_id="20260624_123000_keysuri_global_tech_aabbccdd",
            subject=subject,
        )

        self.assertIn("글로벌 AI·테크 신호 검수 대기", preheader)
        self.assertIn("AI 에이전트 보안 점검", preheader)
        self.assertNotEqual(preheader, subject)

    def test_fallback_preheader_is_program_specific(self) -> None:
        preheader = build_keysuri_preheader(
            PROGRAM_KOREA,
            {},
            run_id="20260624_183000_keysuri_korea_tech_aabbccdd",
            trigger_source="scheduled_owner_review",
        )

        self.assertEqual(
            preheader,
            "국내 AI·테크 신호 검수 대기 · 주요 신호: 국내 AI·테크 신호 점검",
        )

    def test_manual_preheader_has_manual_run_prefix(self) -> None:
        briefing = {"top_5_news": {"items": [{"headline": "AI 에이전트 보안 점검 수요가 확대"}]}}
        preheader = build_keysuri_preheader(
            PROGRAM_GLOBAL,
            briefing,
            run_id="20260624_130501_keysuri_global_tech_aabbccdd",
            trigger_source="manual_post_deploy_check",
        )

        self.assertTrue(preheader.startswith("수동 검증 run · 글로벌 AI·테크 신호 검수 대기"))

    def test_sanitizers_remove_connector_ellipsis(self) -> None:
        subject = sanitize_subject_text("AI 생산을 위한… 흐름: 6월 24일 글로벌 테크 브리핑")
        preheader = sanitize_preheader_text("글로벌 AI·테크 신호 검수 대기 · 주요 신호: 구축… 이슈")

        self.assertNotRegex(subject, r"…|\.{2,}")
        self.assertNotRegex(preheader, r"…|\.{2,}")
        self.assertIn("AI 생산을 위한 흐름", subject)
        self.assertIn("구축 이슈", preheader)

    def test_extract_top_headline_prefers_generated_top_signal(self) -> None:
        briefing = {
            "top_5_news": {
                "items": [
                    {"headline": "AI 데이터센터 전력 계약 확대"},
                    {"headline": "두 번째 신호"},
                ]
            },
            "title": "브리핑 제목",
        }

        self.assertEqual(extract_keysuri_top_headline(briefing), "AI 데이터센터 전력 계약 확대")

    def test_artifact_fields_include_subject_identity(self) -> None:
        briefing = {"top_5_news": {"items": [{"headline": "온디바이스 AI 칩 경쟁이 재점화"}]}}
        fields = build_keysuri_subject_artifact_fields(
            PROGRAM_GLOBAL,
            briefing,
            run_id="20260624_123000_keysuri_global_tech_aabbccdd",
            trigger_source="manual_service_full_run",
        )

        self.assertEqual(fields["email_subject"], fields["editorial_subject"])
        self.assertTrue(fields["owner_email_subject"].startswith("[운영자 검토][수동] "))
        self.assertEqual(fields["subject_top_headline"], "온디바이스 AI 칩 경쟁이 재점화")
        self.assertEqual(fields["subject_source"], "generated_top_signal_headline")
        self.assertEqual(fields["subject_kst_date"], "20260624")
        self.assertEqual(fields["subject_kst_time"], "12:30")
        self.assertEqual(fields["subject_kst_label"], "6월 24일")
        self.assertEqual(fields["subject_program_label"], "글로벌 테크 브리핑")
        self.assertEqual(fields["subject_trigger_label"], "수동")
        self.assertEqual(fields["program_schedule_label"], "12:30")
        self.assertTrue(fields["owner_email_preheader"])

    def test_forbidden_fixed_narrative_is_not_hardcoded(self) -> None:
        source = inspect.getsource(identity)
        self.assertNotIn("구글·OpenAI가 같은 방향", source)


if __name__ == "__main__":
    unittest.main()
