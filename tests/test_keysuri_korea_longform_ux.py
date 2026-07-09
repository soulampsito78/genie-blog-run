"""Tests for Korea 18:30 longform visible structure and evening memo."""
from __future__ import annotations

import unittest

from keysuri_briefing_content_quality import validate_briefing_content_gate
from keysuri_briefing_body_ux_normalizer import normalize_generated_briefing_visible_prose
from keysuri_korea_longform_ux import (
    KOREA_CLOSING_PARAGRAPH_MAX_CHARS,
    KOREA_DEEP_DIVE_FORBIDDEN_LABELS,
    KOREA_DEEP_DIVE_REQUIRED_LABELS,
    KOREA_DEEP_MAX_PARAGRAPH_CHARS,
    KOREA_MEMO_ACTION_MAX_CHARS,
    KOREA_WARM_FAREWELL_LINES,
    build_korea_evening_memo,
    build_korea_one_line_checkpoint,
    clamp_action_line,
    contains_truncated_headline_fragment,
    finalize_korea_visible_field,
    has_incomplete_korean_sentence_ending,
    korea_checkpoint_lacks_confirm_and_hold,
    korea_cliche_phrase_overused,
    korea_closing_paragraph_too_long,
    korea_deep_block_too_long,
    korea_deep_dive_repeats_top5_headline,
    korea_deep_dive_uses_forbidden_labels,
    korea_evening_memo_too_thin,
    korea_market_lens_axis_count,
    korea_market_lens_insufficient,
    korea_memo_action_line_too_long,
    korea_risk_lacks_hold_criteria,
    korea_warm_farewell_missing,
    remove_truncated_headline_fragments,
    repair_incomplete_korean_visible_text,
    structure_korea_deep_dive,
)
from tests.test_keysuri_contract_preview_renderer import (
    _CONTRACT_RENDERER,
    _render_contract_html,
    build_global_contract_fixture,
    build_korea_contract_fixture,
)


def _top_items() -> list[dict]:
    return [
        {
            "korean_title": "엔비디아 CEO 방한, HBM4 협력 논의",
            "what_happened": "엔비디아가 국내 반도체 파트너와 HBM4 협력을 논의했습니다.",
            "why_now": "국내 메모리 밸류체인 일정에 직접 영향을 줍니다.",
            "keysuri_judgment_label": "기회",
            "keysuri_judgment": "협력 일정이 열리면 실행 속도를 앞당길 여지가 있습니다.",
            "next_watch": "삼성전자·SK하이닉스 HBM4 후속 일정; GPU 공급 약속 대상 확인",
        },
        {
            "korean_title": "국내 AI 스타트업 투자 확대",
            "what_happened": "국내 딥테크 투자 라운드가 확대되었습니다.",
            "why_now": "정책·자본 신호가 동시에 맞물립니다.",
            "keysuri_judgment_label": "관찰",
            "keysuri_judgment": "후속 공시 전까지는 과장 없이 관찰하는 편이 안전합니다.",
            "next_watch": "정부 AI 팩토리 구체화; 국내 스타트업 투자 후속",
        },
    ]


def _korea_closing_html(memo_html: str) -> str:
    blocks = "".join(
        f"""
      <div class="korea-deep-block"><h4 class="korea-deep-label">{label}</h4>
      <div class="korea-deep-body"><p>짧은 본문입니다.</p></div></div>"""
        for label in KOREA_DEEP_DIVE_REQUIRED_LABELS
    )
    return f"""
    <html><body class="premium-briefing theme-korea">
    <section id="deep-dive-section">{blocks}
    </section>
    <section id="closing-section"><h2>퇴근 전 메모</h2>{memo_html}</section>
  </body></html>
    """


class KeysuriKoreaLongformUxTests(unittest.TestCase):
    def test_structure_uses_five_contract_blocks(self) -> None:
        wall = (
            "오늘 눈에 띄는 점은 H… 이슈가 동시에 보인다는 것입니다. "
            "한쪽은 산업·인프라 쪽이고, 다른 쪽은 소프트웨어·운영 쪽입니다."
        )
        sections = structure_korea_deep_dive(wall, _top_items())
        labels = [section["label"] for section in sections]
        self.assertEqual(labels, list(KOREA_DEEP_DIVE_REQUIRED_LABELS))
        for forbidden in KOREA_DEEP_DIVE_FORBIDDEN_LABELS:
            self.assertNotIn(forbidden, labels)
        blob = " ".join(section["body"] for section in sections)
        self.assertNotIn("H…", blob)
        self.assertNotIn("한쪽은 산업·인프라", blob)
        global_block = next(section for section in sections if section["label"] == "글로벌 영향")
        self.assertIn("글로벌 AI 인프라", global_block["body"])
        self.assertIn("한국 기업", global_block["body"])
        self.assertNotIn("?", next(section for section in sections if section["label"] == "위험 요인")["body"])
        judgment_block = next(section for section in sections if section["label"] == "키수리 판단")
        self.assertNotRegex(judgment_block["body"], r"^키수리\s*판단\s*[:：]")

    def test_truncated_fixture_is_repaired(self) -> None:
        broken = "국내 로봇 산업에서 핵심 부품 역할을 조명합"
        repaired = repair_incomplete_korean_visible_text(
            broken,
            fallback="국내 로봇 산업 핵심 부품 역할이 강화되는 신호입니다.",
        )
        self.assertFalse(has_incomplete_korean_sentence_ending(repaired))
        self.assertNotIn("조명합", repaired)

    def test_finalize_clamps_selection_reason_without_midword_cut(self) -> None:
        long_reason = (
            "국내 기업 언급이 명확하며, 미래 성장 동력인 로봇 산업에서 국내 부품 기업의 역할을 조명합니다. "
            "글로벌→한국 번역 신호로 선정했습니다."
        )
        finalized = finalize_korea_visible_field(long_reason)
        self.assertFalse(has_incomplete_korean_sentence_ending(finalized))
        broken = finalize_korea_visible_field(
            "국내 기업 언급이 명확하며 로봇 산업에서 국내 부품 기업의 역할을 조명합",
            fallback="국내 로봇 산업 핵심 부품 역할이 강화되는 신호입니다.",
        )
        self.assertFalse(has_incomplete_korean_sentence_ending(broken))
        self.assertNotRegex(broken, r"조명합(?:\s|<|$)")

    def test_real_owner_review_broken_endings_are_detected(self) -> None:
        for broken in (
            "이 뉴스는 국내 기술 혁신과 자본 흐름에 직접적인 영향을 미칠 수 있어 국내 스타트업/투",
            "새만금 사업과 AI 건설·로봇 혁신센터 설립 논의는 국내 산업 전반에 미칠 파급력이 커 국내 대기업 테크 전략",
            "글로벌 로봇 트렌드가 국내 기업에 미치는 영향을 분석하는 데 중요하여 글로벌",
            "관련 정책 변화는 국내 스타트업 생태계 전반에 큰 영향을 미 미칩니다.",
        ):
            with self.subTest(broken=broken):
                self.assertTrue(has_incomplete_korean_sentence_ending(broken))

    def test_normalizer_removes_real_owner_review_failures(self) -> None:
        generated = {
            "program_id": "keysuri_korea_tech",
            "top_5_news": {
                "items": [
                    {
                        "rank": 1,
                        "korean_title": "삼성전자, 'C랩 아웃사이드' 9기 스타트업 모집 시작",
                        "selection_reason": "이 뉴스는 삼성전자의 국내 스타트업 생태계 지원 의지를 보여주는 중요한 신호입니다. 특히 AI, 로봇 등 미래 기술 분야 스타트업 발굴은 국내 기술 혁신과 자본 흐름에 직접적인 영향을 미칠 수 있어 국내 스타트업/투",
                        "what_happened": "삼성전자가 유망 스타트업 발굴 프로그램을 시작했습니다.",
                        "why_now": "국내 스타트업 지원 프로그램은 기술 혁신과 일자리 창출에 영향을 줍니다.",
                        "owner_angle": "내일 협력 가능성이 있는 스타트업 분야를 점검하시면 됩니다.",
                        "keysuri_judgment_label": "기회",
                        "keysuri_judgment": "대기업과 스타트업 협력 기회가 열리는 신호입니다.",
                    },
                    {
                        "rank": 2,
                        "korean_title": "전기공사협회 전북도회, 국토부 장관과 건설산업 활성화 간담회 참석",
                        "selection_reason": "새만금 사업과 AI 건설·로봇 혁신센터 설립 논의는 국내 산업 전반에 미칠 파급력이 커 국내 대기업 테크 전략",
                        "what_happened": "국토부 장관과 건설산업 활성화 방안이 논의됐습니다.",
                        "why_now": "정부 정책과 대기업 투자가 맞물려 산업 생태계에 영향을 줍니다.",
                        "owner_angle": "내일 새만금 투자와 AI 건설 후속 일정을 보시면 됩니다.",
                        "keysuri_judgment_label": "사업 신호",
                        "keysuri_judgment": "정책과 대기업 투자가 결합된 사업 신호입니다.",
                    },
                    {
                        "rank": 3,
                        "korean_title": "벤처업계, 자본시장 개편에 코스닥 보완책 5가지 제안",
                        "selection_reason": "자본시장 개편은 벤처 투자 회수 시장에 영향을 줍니다.",
                        "what_happened": "벤처업계가 정부에 보완책을 제안했습니다.",
                        "why_now": "코스닥 시장은 국내 벤처기업의 주요 자금 조달 및 회수 통로이므로, 관련 정책 변화는 국내 스타트업 생태계 전반에 큰 영향을 미 미칩니다.",
                        "owner_angle": "내일 자본시장 정책 후속 논의를 점검하시면 됩니다.",
                        "keysuri_judgment_label": "리스크 신호",
                        "keysuri_judgment": "벤처 자금 조달 환경에 부담이 생길 수 있습니다.",
                    },
                ]
            },
            "deep_dive": {
                "body": "오늘 국내 테크 신호는 정책·투자·로봇 공급망이 겹친 흐름입니다.",
                "uncertainty": "삼성전자 C랩 아웃사이드 9기 선정 기업들이 실제 어떤 혁신을 이끌어낼지, 그리고 이들이 국내 산업 생태계에 미칠 구체적인 영향은 무엇일까요?",
            },
            "one_line_checkpoint": {"body": "국내 시장의 기회와 리스크를 함께 보겠습니다."},
            "closing_sources": {},
        }
        normalized = normalize_generated_briefing_visible_prose(
            generated,
            "keysuri_korea_tech",
            {"program_id": "keysuri_korea_tech"},
        )
        blob = str(normalized)
        for forbidden in (
            "국내 스타트업/투",
            "국내 대기업 테크 전략",
            "무엇일까요",
            "영향을 미 미칩니다",
        ):
            self.assertNotIn(forbidden, blob)

    def test_risk_block_converts_questions_to_declarative(self) -> None:
        sections = structure_korea_deep_dive(
            "",
            _top_items(),
            uncertainty="삼성 C랩 선정 스타트업의 구체적 기술 방향은 무엇인가?",
        )
        risk = next(section for section in sections if section["label"] == "위험 요인")
        self.assertNotIn("?", risk["body"])
        self.assertIn("불확실", risk["body"])

    def test_risk_block_converts_what_would_it_be_questions(self) -> None:
        sections = structure_korea_deep_dive(
            "",
            _top_items(),
            uncertainty="삼성전자 C랩 선정 기업들이 국내 산업 생태계에 미칠 구체적인 영향은 무엇일까요?",
        )
        risk = next(section for section in sections if section["label"] == "위험 요인")
        self.assertNotIn("?", risk["body"])
        self.assertNotIn("무엇일까요", risk["body"])
        self.assertIn("불확실", risk["body"])

    def test_global_impact_block_bridges_without_concatenating_titles(self) -> None:
        items = [
            {"korean_title": "삼성전자, 'C랩 아웃사이드' 9기 스타트업 모집 시작"},
            {"korean_title": "전기공사협회 전북도회, 국토부 장관과 건설산업 활성화 간담회 참석"},
            {"korean_title": "KH바텍, 휴머노이드 로봇 감속기 공급 협력 논의 중"},
        ]
        sections = structure_korea_deep_dive("", items)
        global_block = next(section for section in sections if section["label"] == "글로벌 영향")
        self.assertIn("글로벌 AI 인프라", global_block["body"])
        self.assertIn("한국 기업", global_block["body"])
        self.assertNotIn("삼성전자, 'C랩 아웃사이드'", global_block["body"])
        self.assertNotIn("전기공사협회 전북도회", global_block["body"])

    def test_forbidden_label_detector(self) -> None:
        retired = [{"label": "오늘의 핵심 흐름", "body": "본문"}]
        self.assertTrue(korea_deep_dive_uses_forbidden_labels(retired))

    def test_checkpoint_synthesizes_market_observation(self) -> None:
        checkpoint = build_korea_one_line_checkpoint(
            _top_items(),
            existing="오늘은 인프라·조달 일정 변동을 먼저 보시면 됩니다.",
        )
        self.assertIn("글로벌·국내 TOP5", checkpoint)
        self.assertIn("한국 시장", checkpoint)
        self.assertNotIn("먼저 보시면 됩니다", checkpoint)
        self.assertNotIn("내일 영향을 줄", checkpoint)

    def test_wall_text_gate_flags_unnormalized_paragraph(self) -> None:
        sections = [{"label": "글로벌 영향", "body": "가" * (KOREA_DEEP_MAX_PARAGRAPH_CHARS + 5)}]
        self.assertTrue(korea_deep_block_too_long(sections))

    def test_remove_truncated_headline_fragments(self) -> None:
        cleaned = remove_truncated_headline_fragments("H… 만… 후속 일정")
        self.assertFalse(contains_truncated_headline_fragment(cleaned))

    def test_evening_memo_has_actions_and_warm_farewell(self) -> None:
        memo = build_korea_evening_memo(_top_items())
        self.assertGreaterEqual(len(memo["action_lines"]), 2)
        self.assertFalse(korea_evening_memo_too_thin(memo))
        self.assertEqual(memo["warm_lines"], list(KOREA_WARM_FAREWELL_LINES))

    def test_action_lines_split_from_semicolon_chain(self) -> None:
        memo = build_korea_evening_memo(_top_items())
        self.assertGreaterEqual(len(memo["action_lines"]), 2)
        for line in memo["action_lines"]:
            self.assertNotIn(";", line)
            self.assertLessEqual(len(line), KOREA_MEMO_ACTION_MAX_CHARS)

    def test_thin_closing_without_warm_farewell_fails_gate(self) -> None:
        html = _korea_closing_html(
            '<div class="evening-memo-body"><p>오늘도 수고하셨습니다. 내일 다시 뵙겠습니다.</p></div>'
        )
        result = validate_briefing_content_gate(html)
        codes = {issue.code for issue in result.issues}
        self.assertIn("korea_closing_warm_farewell_missing", codes)

    def test_gate_fails_when_closing_paragraph_too_long(self) -> None:
        long_para = "가" * (KOREA_CLOSING_PARAGRAPH_MAX_CHARS + 1)
        self.assertTrue(korea_closing_paragraph_too_long(f"<p>{long_para}</p>"))

    def test_gate_fails_when_action_line_too_long(self) -> None:
        long_line = "가" * (KOREA_MEMO_ACTION_MAX_CHARS + 1)
        self.assertTrue(korea_memo_action_line_too_long([long_line]))
        self.assertLessEqual(len(clamp_action_line(long_line)), KOREA_MEMO_ACTION_MAX_CHARS)

    def test_renderer_includes_warm_farewell_after_memo(self) -> None:
        if _CONTRACT_RENDERER is None:
            raise unittest.SkipTest("keysuri_contract_preview_renderer not implemented yet")
        html = _render_contract_html(_CONTRACT_RENDERER, build_korea_contract_fixture())
        self.assertNotIn("국내 18:30 따뜻한 마무리", html)
        self.assertIn("퇴근 전 메모", html)
        self.assertIn("오늘도 수고 많으셨습니다.", html)
        self.assertIn("내일 아침에 다시 볼 흐름만 남겨두겠습니다.", html)
        self.assertFalse(korea_warm_farewell_missing(html))

    def test_global_rendering_unchanged(self) -> None:
        if _CONTRACT_RENDERER is None:
            raise unittest.SkipTest("keysuri_contract_preview_renderer not implemented yet")
        html = _render_contract_html(_CONTRACT_RENDERER, build_global_contract_fixture())
        self.assertNotRegex(html, r'class="korea-deep-block"')
        self.assertNotIn("퇴근 전 메모", html)
        self.assertNotIn("오늘도 수고 많으셨습니다.", html)
        self.assertIn("deep-dive-prose", html)


class KeysuriKoreaMarketSignalBriefingTests(unittest.TestCase):
    """Korea Tech reposition: market-signal briefing checks, not news-summary checks."""

    def test_market_lens_axis_count_recognizes_multiple_axes(self) -> None:
        text = (
            "오늘은 코스피 반응과 함께 원달러 환율, 기준금리 발표가 겹쳤습니다. "
            "대기업 투자 일정도 함께 살펴야 합니다."
        )
        self.assertGreaterEqual(korea_market_lens_axis_count(text), 3)
        self.assertFalse(korea_market_lens_insufficient(text))

    def test_market_lens_insufficient_when_only_tech_recap(self) -> None:
        text = "오늘 국내에서 AI 모델이 새로 출시되었다는 소식이 있었습니다."
        self.assertTrue(korea_market_lens_insufficient(text))

    def test_cliche_phrase_overuse_requires_repetition_not_single_use(self) -> None:
        single_use = "이 흐름은 구조 변화를 구분해 보는 것이 중요합니다."
        self.assertFalse(korea_cliche_phrase_overused(single_use))
        repeated = "오늘 뉴스는 중요합니다. 저 뉴스도 중요합니다. 이 흐름도 중요합니다."
        self.assertTrue(korea_cliche_phrase_overused(repeated))

    def test_risk_lacks_hold_criteria_flags_abstract_warning(self) -> None:
        abstract = "이 뉴스는 위험할 수 있습니다."
        self.assertTrue(korea_risk_lacks_hold_criteria(abstract))
        concrete = "실제 발주 일정이 확정되기 전까지는 판단을 보류하시는 편이 안전합니다."
        self.assertFalse(korea_risk_lacks_hold_criteria(concrete))

    def test_default_risk_fallback_satisfies_hold_criteria(self) -> None:
        sections = structure_korea_deep_dive("", _top_items())
        risk = next(section for section in sections if section["label"] == "위험 요인")
        self.assertFalse(korea_risk_lacks_hold_criteria(risk["body"]))

    def test_checkpoint_lacks_confirm_and_hold_flags_bare_recap(self) -> None:
        bare = "오늘 신호는 기회와 리스크가 동시에 이동하고 있습니다."
        self.assertTrue(korea_checkpoint_lacks_confirm_and_hold(bare))
        actionable = "내일은 발주 일정을 먼저 확인하고, 숫자가 확정되기 전까지는 판단을 보류하시면 됩니다."
        self.assertFalse(korea_checkpoint_lacks_confirm_and_hold(actionable))

    def test_default_checkpoint_synthesis_satisfies_confirm_and_hold(self) -> None:
        checkpoint = build_korea_one_line_checkpoint(_top_items(), existing="")
        self.assertFalse(korea_checkpoint_lacks_confirm_and_hold(checkpoint))

    def test_deep_dive_repeats_top5_headline_detects_verbatim_recap(self) -> None:
        items = [{"korean_title": "엔비디아 CEO 방한, HBM4 협력 논의"}]
        recap_sections = [
            {"label": "글로벌 영향", "body": "엔비디아 CEO 방한, HBM4 협력 논의가 있었습니다."}
        ]
        self.assertTrue(korea_deep_dive_repeats_top5_headline(recap_sections, items))

    def test_deep_dive_synthesis_does_not_flag_as_recap(self) -> None:
        sections = structure_korea_deep_dive("", _top_items())
        self.assertFalse(korea_deep_dive_repeats_top5_headline(sections, _top_items()))


class KeysuriKoreaMarketRendererHelpersTests(unittest.TestCase):
    """Helpers backing the Korea market-briefing renderer UX (Phase 2)."""

    def test_lens_inference_from_item_text(self) -> None:
        from keysuri_korea_longform_ux import infer_korea_market_lenses

        item = {
            "korean_title": "정부, AI 데이터센터 전력·인허가 가이드라인 개정",
            "why_now": "국내 정책·공급망 변화가 겹치는 시점입니다.",
        }
        lenses = infer_korea_market_lenses(item)
        self.assertIn("정책", lenses)
        self.assertLessEqual(len(lenses), 3)

    def test_lens_explicit_field_takes_priority(self) -> None:
        from keysuri_korea_longform_ux import infer_korea_market_lenses

        item = {"market_lens": "주식 · 환율", "korean_title": "정부 정책 발표"}
        self.assertEqual(infer_korea_market_lenses(item), ["주식", "환율"])

    def test_lens_fallback_never_empty(self) -> None:
        from keysuri_korea_longform_ux import KOREA_MARKET_LENS_FALLBACK, infer_korea_market_lenses

        self.assertEqual(infer_korea_market_lenses({"korean_title": "짧은 소식"}), [KOREA_MARKET_LENS_FALLBACK])

    def test_empty_explicit_lens_falls_back_to_inference(self) -> None:
        from keysuri_korea_longform_ux import infer_korea_market_lenses

        item = {
            "market_lens": [""],
            "korean_title": "정부, AI 데이터센터 전력·인허가 가이드라인 개정",
            "why_now": "국내 정책·공급망 변화가 겹치는 시점입니다.",
        }
        lenses = infer_korea_market_lenses(item)
        self.assertIn("정책", lenses)

    def test_market_impact_line_explicit_field_wins(self) -> None:
        from keysuri_korea_longform_ux import build_korea_market_impact_line

        item = {"market_impact": "주식시장에서는 2차 반응을 먼저 봐야 합니다.", "korean_title": "삼성 투자"}
        self.assertEqual(
            build_korea_market_impact_line(item), "주식시장에서는 2차 반응을 먼저 봐야 합니다."
        )

    def test_empty_market_impact_line_uses_fallback(self) -> None:
        from keysuri_korea_longform_ux import build_korea_market_impact_line

        item = {"market_impact": "   ", "market_lens": ["AI"], "korean_title": "AI 도입 확대"}
        line = build_korea_market_impact_line(item, rank=1)
        self.assertIn("AI 뉴스", line)

    def test_market_impact_line_fallback_not_empty_and_varies_by_rank(self) -> None:
        from keysuri_korea_longform_ux import build_korea_market_impact_line

        item = {"korean_title": "정부, AI 예산·조달 정책 발표", "why_now": "정책 일정이 겹칩니다."}
        lines = {build_korea_market_impact_line(item, rank=r) for r in (1, 2, 3)}
        self.assertTrue(all(lines))
        self.assertGreaterEqual(len(lines), 2)

    def test_market_impact_lines_avoid_news_summary_cliches(self) -> None:
        from keysuri_korea_longform_ux import (
            _KOREA_MARKET_IMPACT_POOLS,
            KOREA_NEWS_SUMMARY_CLICHE_PHRASES,
        )

        for pool in _KOREA_MARKET_IMPACT_POOLS.values():
            for sentence in pool:
                for cliche in KOREA_NEWS_SUMMARY_CLICHE_PHRASES:
                    self.assertNotIn(cliche, sentence)
                for directive in ("매수", "매도"):
                    self.assertNotIn(directive, sentence)

    def test_market_impact_fallback_translates_to_everyday_impact(self) -> None:
        from keysuri_korea_longform_ux import build_korea_market_impact_line

        cases = [
            {"market_lens": ["산업"], "korean_title": "반도체 패키징 투자 확대"},
            {"market_lens": ["AI"], "korean_title": "AI 업무 자동화 서비스 출시"},
            {"market_lens": ["인프라"], "korean_title": "데이터센터 전력 투자"},
        ]
        lines = [
            build_korea_market_impact_line(item, rank=rank)
            for item, rank in zip(cases, (1, 1, 2))
        ]
        joined = " ".join(lines)
        for term in ("장비", "소재", "부품", "교육", "비용", "데이터센터", "지역", "채용"):
            with self.subTest(term=term):
                self.assertIn(term, joined)
        self.assertNotIn("직접 영향은 제한적", joined)

    def test_tomorrow_checkpoint_parts_have_confirm_and_hold(self) -> None:
        from keysuri_korea_longform_ux import build_korea_tomorrow_checkpoint_parts

        confirm, hold = build_korea_tomorrow_checkpoint_parts(_top_items()[0])
        self.assertTrue(confirm)
        self.assertTrue(hold)
        confirm_empty, hold_empty = build_korea_tomorrow_checkpoint_parts({"korean_title": "신호"})
        self.assertTrue(confirm_empty)
        self.assertTrue(hold_empty)

    def test_market_impact_summary_min_three_axes(self) -> None:
        from keysuri_korea_longform_ux import (
            KOREA_MARKET_SUMMARY_HEADING,
            build_korea_market_impact_summary,
        )

        rows = build_korea_market_impact_summary(_top_items())
        self.assertGreaterEqual(len(rows), 3)
        axes = {row["axis"] for row in rows}
        self.assertEqual(KOREA_MARKET_SUMMARY_HEADING, "오늘 신호가 내려오는 곳")
        for axis in ("관련 업종", "소부장 협력사", "개인 투자자"):
            with self.subTest(axis=axis):
                self.assertIn(axis, axes)
        for row in rows:
            self.assertTrue(row["body"])
            self.assertNotIn("협력사/소부장", row["axis"])
            self.assertNotIn("협력사/소부장", row["body"])
            self.assertNotIn("매수", row["body"])
            self.assertNotIn("매도", row["body"])
            self.assertNotIn("직접 영향은 제한적", row["body"])

    def test_market_impact_summary_is_day_specific_not_static_lesson(self) -> None:
        """Rows must be anchored to today's actual items, and the legacy fixed
        daily-lesson sentences must never be emitted again."""
        from keysuri_briefing_content_quality import KOREA_STATIC_LESSON_LEGACY_SENTENCES
        from keysuri_korea_longform_ux import build_korea_market_impact_summary

        rows = build_korea_market_impact_summary(_top_items())
        bodies = " ".join(row["body"] for row in rows)
        for legacy in KOREA_STATIC_LESSON_LEGACY_SENTENCES:
            self.assertNotIn(legacy, bodies)

        semis = build_korea_market_impact_summary(
            [{"korean_title": "SK하이닉스 HBM 공급 계약", "primary_category": "domestic_semiconductor"}]
        )
        startups = build_korea_market_impact_summary(
            [{"korean_title": "스타트업 투자 유치", "primary_category": "domestic_startup_investment"}]
        )
        self.assertNotEqual(
            [r["body"] for r in semis],
            [r["body"] for r in startups],
            "market summary must change with the day's items",
        )

    def test_everyday_impact_quality_helpers_flag_finance_only_copy(self) -> None:
        from keysuri_korea_longform_ux import (
            korea_defensive_market_phrase_overused,
            korea_everyday_impact_lens_insufficient,
            korea_upper_layer_only_without_everyday_lens,
        )

        finance_only = (
            "M&A와 투자유치, 정책금융, 외국인 자금, 조달, 발주, 수혜주를 봅니다. "
            "직접 영향은 제한적입니다. 원달러 흐름은 참고 축입니다."
        )
        translated = (
            "M&A와 조달 신호를 보되 협력사, 소부장, 장비, 소재, 부품, 지역 채용, "
            "유지보수, 교육, 프리랜서 외주로 내려오는지 확인합니다."
        )
        self.assertTrue(korea_everyday_impact_lens_insufficient(finance_only))
        self.assertTrue(korea_upper_layer_only_without_everyday_lens(finance_only))
        self.assertTrue(korea_defensive_market_phrase_overused(finance_only))
        self.assertFalse(korea_everyday_impact_lens_insufficient(translated))
        self.assertFalse(korea_upper_layer_only_without_everyday_lens(translated))

    def test_follow_hold_blocks_have_min_entries(self) -> None:
        from keysuri_korea_longform_ux import build_korea_follow_hold_blocks

        blocks = build_korea_follow_hold_blocks(_top_items())
        self.assertGreaterEqual(len(blocks["follow"]), 1)
        self.assertGreaterEqual(len(blocks["hold"]), 2)
        blocks_empty = build_korea_follow_hold_blocks([])
        self.assertGreaterEqual(len(blocks_empty["follow"]), 1)
        self.assertGreaterEqual(len(blocks_empty["hold"]), 2)

    def test_market_frame_line_synthesizes_structure_not_recap(self) -> None:
        from keysuri_korea_longform_ux import build_korea_market_frame_line

        frame = build_korea_market_frame_line(_top_items())
        self.assertIn("오늘 다섯 신호를 하나로 보면", frame)
        self.assertIn("시장 구조", frame)
        self.assertNotIn("엔비디아 CEO 방한, HBM4 협력 논의", frame)
        self.assertLess(len(frame), 220)


class KeysuriKoreaMarketContractHardeningTests(unittest.TestCase):
    """Phase 3: explicit-field priority, lens label integrity, follow/memo dedupe."""

    def test_explicit_bond_rate_lens_label_not_split(self) -> None:
        from keysuri_korea_longform_ux import infer_korea_market_lenses

        item = {"market_lens": "채권/금리 · 환율", "korean_title": "금리 뉴스"}
        self.assertEqual(infer_korea_market_lenses(item), ["채권/금리", "환율"])

    def test_explicit_bond_rate_lens_maps_to_impact_pool(self) -> None:
        from keysuri_korea_longform_ux import build_korea_market_impact_line

        item = {"market_lens": ["채권/금리"], "korean_title": "기준금리 발표"}
        line = build_korea_market_impact_line(item, rank=1)
        self.assertIn("금리", line)

    def test_compress_follow_check_item_shortens_memo_sentence(self) -> None:
        """Follow items are noun/observation phrases — the imperative tail is
        dropped and nothing (especially not '확인') is glued onto the stem."""
        from keysuri_korea_longform_ux import compress_to_follow_check_item

        memo_line = "항목 1 관련 공식 발표·가격·일정 공개 여부를 확인하세요"
        short = compress_to_follow_check_item(memo_line)
        self.assertNotEqual(short, memo_line)
        self.assertEqual(short, "항목 1 관련 공식 발표·가격·일정 공개 여부")
        self.assertNotIn("하세요", short)

    def test_compress_follow_check_item_handles_any_imperative_verb(self) -> None:
        """Generic '…하세요' endings (분석하세요/주시하세요/…) must compress into
        bare observation phrases — no imperative remnant, nothing glued on
        (the '…비교 분석하세요 확인' production artifact)."""
        from keysuri_korea_longform_ux import compress_to_follow_check_item

        for memo_line in (
            "국내 다른 대기업들의 AI 전략 발표와 방향성 변화를 비교 분석하세요",
            "개인화된 AI 솔루션 개발 스타트업에 대한 투자 동향을 주시하세요",
            "관련 공시 일정을 점검하십시오",
        ):
            with self.subTest(memo_line=memo_line):
                short = compress_to_follow_check_item(memo_line)
                self.assertTrue(short, memo_line)
                self.assertNotIn("하세요", short)
                self.assertNotIn("하십시오", short)
                self.assertNotIn("하세요 확인", short)
                self.assertNotIn("하십시오 확인", short)

    def test_compress_follow_strips_declarative_hamnida_tails(self) -> None:
        """'…해야 합니다 / …필요합니다' must compress to observation stems —
        never survive to become '합니다 여부' glue."""
        from keysuri_korea_longform_ux import compress_to_follow_check_item

        cases = (
            ("SK하이닉스의 투자 계획 발표를 확인해야 합니다", "SK하이닉스의 투자 계획 발표"),
            ("관련 정책 일정을 점검해야 합니다", "관련 정책 일정"),
            ("수주 동향을 주시해야 합니다", "수주 동향"),
            ("후속 확인이 필요합니다", "후속 확인"),
            ("후속 가격·API 조건을 확인해야 합니다.", "후속 가격·API 조건"),
        )
        for memo_line, expected in cases:
            with self.subTest(memo_line=memo_line):
                short = compress_to_follow_check_item(memo_line)
                self.assertEqual(short, expected)
                self.assertNotIn("합니다", short)
                self.assertNotIn("여부", short)

    def test_follow_blocks_never_glue_hamnida_yeobu(self) -> None:
        from keysuri_korea_longform_ux import build_korea_follow_hold_blocks

        items = [
            {
                "korean_title": "투자 계획 신호",
                "next_watch": "SK하이닉스의 투자 계획 발표를 확인해야 합니다",
            },
            {
                "korean_title": "수주 동향 신호",
                "next_watch": "수주 동향을 주시해야 합니다",
            },
            {
                "korean_title": "정책 일정 신호",
                "next_watch": "관련 정책 일정을 점검해야 합니다",
            },
            {
                "korean_title": "후속 확인 신호",
                "next_watch": "후속 확인이 필요합니다",
            },
        ]
        follow = build_korea_follow_hold_blocks(items)["follow"]
        self.assertTrue(follow)
        blob = "\n".join(follow)
        for forbidden in (
            "합니다 여부",
            "해야 합니다 여부",
            "확인해야 합니다 여부",
            "주시해야 합니다 여부",
            "점검해야 합니다 여부",
            "필요합니다 여부",
            "중요합니다 여부",
            "입니다 여부",
            "됩니다 여부",
        ):
            self.assertNotIn(forbidden, blob)
        for line in follow:
            with self.subTest(line=line):
                self.assertNotRegex(line, r"합니다\s+여부")
                self.assertNotIn("하세요", line)

    def test_finalize_follow_strips_finished_sentence_yeobu_glue(self) -> None:
        from keysuri_korea_longform_ux import (
            _finalize_follow_check_item,
            compress_to_follow_check_item,
        )

        cases = (
            (
                "정부의 구체적인 '전기국가' 실현 계획 및 예산 배정 현황이 다음 확인 지점입니다 여부",
                "다음 확인 지점입니다.",
            ),
            (
                "전력 효율화 기술 및 청정 에너지 솔루션 관련 기업들의 동향만 이어서 보면 됩니다 여부",
                "보면 됩니다.",
            ),
        )
        for raw, expected_tail in cases:
            with self.subTest(raw=raw):
                out = _finalize_follow_check_item(
                    compress_to_follow_check_item(raw),
                    memo_lines=set(),
                )
                self.assertTrue(out.endswith(expected_tail), out)
                self.assertNotIn("여부", out)

    def test_finalize_follow_completes_truncated_continuously_tail(self) -> None:
        from keysuri_korea_longform_ux import (
            _finalize_follow_check_item,
            compress_to_follow_check_item,
        )

        raw = (
            "AI 데이터센터 및 반도체 팹 증설에 따른 전력 수요 증가와 "
            "공급망 변화를 지속적으로"
        )
        out = _finalize_follow_check_item(
            compress_to_follow_check_item(raw),
            memo_lines=set(),
        )
        self.assertFalse(out.rstrip(".!").endswith("지속적으로"), out)
        self.assertIn("이어서 보면 됩니다", out)
        self.assertTrue(out.endswith("."), out)

    def test_finalize_follow_preserves_noun_phrase_yeobu(self) -> None:
        from keysuri_korea_longform_ux import _finalize_follow_check_item

        for stem in ("예산 배정 여부", "후속 발표 여부", "실제 계약 여부"):
            with self.subTest(stem=stem):
                out = _finalize_follow_check_item(stem, memo_lines={stem})
                self.assertEqual(out, stem)

    def test_follow_blocks_reject_production_yeobu_and_truncation(self) -> None:
        from keysuri_korea_longform_ux import (
            build_korea_evening_memo,
            build_korea_follow_hold_blocks,
        )

        items = [
            {
                "korean_title": "전기국가 전략",
                "next_watch": (
                    "정부의 구체적인 '전기국가' 실현 계획 및 예산 배정 현황이 "
                    "다음 확인 지점입니다"
                ),
            },
            {
                "korean_title": "전력 수요",
                "next_watch": (
                    "AI 데이터센터 및 반도체 팹 증설에 따른 전력 수요 증가와 "
                    "공급망 변화를 지속적으로 관찰해야 합니다"
                ),
            },
            {
                "korean_title": "전력 효율",
                "next_watch": (
                    "전력 효율화 기술 및 청정 에너지 솔루션 관련 기업들의 "
                    "동향만 이어서 보면 됩니다"
                ),
            },
        ]
        follow = build_korea_follow_hold_blocks(items)["follow"]
        memo = build_korea_evening_memo(items)["action_lines"]
        for lines in (follow, memo):
            blob = "\n".join(lines)
            with self.subTest(blob=blob):
                self.assertNotIn("됩니다 여부", blob)
                self.assertNotIn("입니다 여부", blob)
                self.assertNotIn("합니다 여부", blob)
                for line in lines:
                    self.assertFalse(
                        line.rstrip(".!").endswith("지속적으로"),
                        line,
                    )

    def test_longform_industry_labels_never_expose_slash_taxonomy(self) -> None:
        from keysuri_korea_longform_ux import (
            _memo_summary_line,
            build_korea_market_frame_line,
        )

        items = [
            {
                "korean_title": "정책 조달 신호",
                "category_label_ko": "국내 정책 / 규제 / 공공",
            },
            {
                "korean_title": "반도체 장비 신호",
                "category_label_ko": "국내 반도체 / 장비 / 소재",
            },
            {
                "korean_title": "기업 AI 도입 신호",
                "category_label_ko": "국내 AI / 기업 AI 도입",
            },
        ]
        summary = _memo_summary_line(items, "정책·반도체")
        frame = build_korea_market_frame_line(items)
        for text in (summary, frame):
            with self.subTest(text=text):
                self.assertNotIn("정책 / 규제", text)
                self.assertNotIn("반도체 / 장비", text)
                self.assertNotIn("공공·국내", text)
                self.assertNotIn(" / ", text)

    def test_sanitize_korea_customer_prose_strips_slash_and_softens_imperatives(self) -> None:
        from keysuri_korea_longform_ux import (
            finalize_korea_visible_field,
            sanitize_korea_customer_prose,
        )

        cases = (
            (
                "국내 AI / 기업 AI 도입 관점에서 오늘 한국에서 의미 있는 신호로 선정했습니다.",
                "기업 AI 도입",
            ),
            (
                "내일 국내 로보틱스 / 스마트팩토리 관련 파트너·고객·입찰·정책 일정을 점검하세요.",
                "로봇 자동화",
            ),
            (
                "관련 SaaS 시장의 성장과 경쟁 구도를 주시하십시오.",
                "이어서 보면 됩니다",
            ),
            (
                "내일 먼저 볼 것: 현대차그룹의 로봇 관련 투자 및 협력사 발표 일정을 확인해야 합니다",
                "다음 확인 지점입니다",
            ),
            (
                "협력사/소부장 물량으로 번지는지",
                "소부장 협력사",
            ),
            (
                "반도체 공급망·로봇/에이전트 AI 축",
                "로봇과 AI 에이전트",
            ),
        )
        for raw, expected_fragment in cases:
            with self.subTest(raw=raw):
                out = sanitize_korea_customer_prose(raw)
                self.assertNotIn(" / ", out)
                self.assertNotIn("협력사/소부장", out)
                self.assertNotIn("로봇/에이전트", out)
                self.assertNotIn("점검하세요", out)
                self.assertNotIn("확인해야 합니다", out)
                self.assertNotIn("주시하십시오", out)
                self.assertIn(expected_fragment, out)
                finalized = finalize_korea_visible_field(raw)
                self.assertNotIn(" / ", finalized)
                self.assertNotIn("점검하세요", finalized)

    def test_sanitize_preserves_https_urls(self) -> None:
        from keysuri_korea_longform_ux import sanitize_korea_customer_prose

        raw = "출처 https://www.etnews.com/news/articleView.html?idxno=1 협력사/소부장"
        out = sanitize_korea_customer_prose(raw)
        self.assertIn("https://www.etnews.com/news/articleView.html?idxno=1", out)
        self.assertNotIn("협력사/소부장", out)
        self.assertIn("소부장 협력사", out)

    def test_weak_startup_support_prose_is_observational(self) -> None:
        from keysuri_korea_longform_ux import (
            is_weak_startup_support_item,
            polish_weak_startup_support_item_fields,
            soften_weak_startup_support_prose,
        )

        title = "B-스타트업 챌린지, 5개 팀에 3억 원 지분투자 및 참가기업 모집"
        self.assertTrue(is_weak_startup_support_item(title))
        over = (
            "지역 기반 스타트업 생태계 활성화와 투자 기회 발굴에 긍정적인 신호입니다. "
            "유망 기술 및 사업 모델을 가진 스타트업과의 협력 기회를 모색할 수 있습니다."
        )
        soft = soften_weak_startup_support_prose(title + " " + over)
        self.assertNotIn("협력 기회를 모색할 수 있습니다", soft)
        self.assertTrue(
            "참고 신호" in soft or "모집 요건" in soft or "선정 분야" in soft,
            soft,
        )
        polished = polish_weak_startup_support_item_fields(
            {
                "korean_title": title,
                "keysuri_judgment_label": "사업 신호",
                "keysuri_judgment_text": over,
            }
        )
        self.assertEqual(polished["keysuri_judgment_label"], "관찰")
        self.assertNotIn("사업 신호", polished.get("keysuri_judgment_text") or "")

    def test_theme_phrase_avoids_deeptech_bleed_for_generic_startup(self) -> None:
        from keysuri_korea_longform_ux import _theme_phrase

        items = [{"korean_title": "부산시 주최 B-스타트업 챌린지, 5개 팀에 3억 원 지분투자 지원"}]
        theme = _theme_phrase(items)
        self.assertNotIn("원자력", theme)
        self.assertNotIn("딥테크", theme)
        self.assertIn("투자", theme)

    def test_follow_blocks_never_contain_double_ending(self) -> None:
        from keysuri_korea_longform_ux import build_korea_follow_hold_blocks

        items = [
            {
                "korean_title": "국내 AI 전략 신호",
                "next_watch": "국내 다른 대기업들의 AI 전략 발표와 방향성 변화를 비교 분석하세요",
            },
            {
                "korean_title": "국내 투자 신호",
                "next_watch": "개인화된 AI 솔루션 개발 스타트업에 대한 투자 동향을 주시하세요",
            },
        ]
        follow = build_korea_follow_hold_blocks(items)["follow"]
        self.assertTrue(follow)
        for line in follow:
            with self.subTest(line=line):
                self.assertNotIn("하세요 확인", line)
                self.assertNotIn("하십시오 확인", line)

    def test_theme_phrase_never_names_ungrounded_events(self) -> None:
        """A keyword hit (엔비디아/삼성) says the TOPIC moved — it must never
        become a fabricated EVENT claim like 방한(visit) or 협력(partnership)."""
        from keysuri_korea_longform_ux import _theme_phrase

        nvidia_items = [{"korean_title": "엔비디아, 신형 GPU 아키텍처 공개"}]
        samsung_items = [{"korean_title": "삼성전자, '나를 아는 AI'가 가장 중요하다고 강조"}]
        robot_items = [{"korean_title": "나우로보틱스, K-뷰티 로봇 자동화 설비 공급"}]
        for items in (nvidia_items, samsung_items, robot_items):
            with self.subTest(items=items):
                theme = _theme_phrase(items)
                self.assertNotIn("방한", theme)
                self.assertNotIn("협력", theme)
        # No NVIDIA in today's items → the word must not appear at all.
        self.assertNotIn("엔비디아", _theme_phrase(robot_items))

    def test_evening_memo_summary_anchored_to_todays_industries(self) -> None:
        """The 퇴근 전 메모 opener must reflect today's actual items — never the
        fixed 'HBM·파운드리·국내 AI 투자' recitation from the old template."""
        from keysuri_korea_longform_ux import build_korea_evening_memo

        robot_items = [
            {"korean_title": "나우로보틱스, K-뷰티 로봇 자동화 설비 공급",
             "primary_category": "domestic_robotics"},
        ]
        memo = build_korea_evening_memo(robot_items)
        self.assertNotIn("HBM·파운드리·국내 AI 투자", memo["summary"])
        self.assertNotIn("방한", memo["summary"])
        self.assertIn("흐름을 한 번에 묶었습니다", memo["summary"])

    def test_hold_list_never_copies_risk_judgment_verbatim(self) -> None:
        """보류할 것 entries must state what is not yet confirmed — not repeat
        the card's risk judgment sentence a third time."""
        from keysuri_korea_longform_ux import build_korea_follow_hold_blocks

        risk_sentence = (
            "국내 주요 대기업의 노사 갈등이 장기화되며 생산 차질 및 공급망 불안정성으로 "
            "이어질 수 있는 명확한 리스크 신호입니다."
        )
        items = [
            {
                "korean_title": "현대차 노사, 임단협 난항 2년 연속 파업 위기 고조",
                "keysuri_judgment_label": "리스크 신호",
                "keysuri_judgment_text": risk_sentence,
            }
        ]
        hold = build_korea_follow_hold_blocks(items)["hold"]
        self.assertTrue(hold)
        for line in hold:
            with self.subTest(line=line):
                self.assertNotEqual(line, risk_sentence)
                self.assertNotIn("명확한 리스크 신호입니다", line)
        self.assertTrue(any("확인되지 않" in line for line in hold), hold)

    def test_market_impact_summary_tone_is_observational_not_recitation(self) -> None:
        """Rows are judgment/observation statements, at most 3, without the
        daily '확인하겠습니다/보겠습니다' recitation endings."""
        from keysuri_korea_longform_ux import build_korea_market_impact_summary

        rows = build_korea_market_impact_summary(_top_items())
        self.assertLessEqual(len(rows), 3)
        for row in rows:
            with self.subTest(axis=row["axis"]):
                self.assertNotIn("확인하겠습니다", row["body"])
                self.assertNotIn("보겠습니다", row["body"])
                self.assertNotIn("하세요", row["body"])

    def test_tomorrow_checkpoint_hold_never_copies_risk_judgment(self) -> None:
        """The hold field must state an unconfirmed assumption — not repeat the
        card's '키수리 판단' risk explanation verbatim (production defect)."""
        from keysuri_korea_longform_ux import build_korea_tomorrow_checkpoint_parts

        risk_explanation = (
            "국내 주요 대기업의 노사 갈등이 장기화되며 생산 차질 및 공급망 불안정성으로 "
            "이어질 수 있는 명확한 리스크 신호입니다."
        )
        item = {
            "korean_title": "현대차 노사, 임단협 난항 2년 연속 파업 위기 고조",
            "keysuri_judgment_label": "리스크 신호",
            "keysuri_judgment_text": risk_explanation,
            "next_watch": "현대차 노사 간 추가 교섭 일정 및 합의 여부를 확인하세요",
        }
        confirm, hold = build_korea_tomorrow_checkpoint_parts(item)
        self.assertTrue(confirm)
        self.assertTrue(hold)
        self.assertNotEqual(hold, risk_explanation)
        self.assertNotIn("리스크 신호입니다", hold)

    def test_follow_lines_never_verbatim_repeat_memo_action_lines(self) -> None:
        """Noun-style watch items: follow may add '여부', memo keeps the stem.

        Finished observational sentences may legitimately appear in both blocks
        after finalize — that is preferred over gluing '여부' onto them.
        """
        from keysuri_korea_longform_ux import (
            build_korea_evening_memo,
            build_korea_follow_hold_blocks,
        )

        items = [
            {
                "korean_title": "국내 반도체 공급망 신호",
                "next_watch": "삼성전자 HBM4 후속 일정; 국내 팹 투자 발표",
            }
        ]
        follow = build_korea_follow_hold_blocks(items)["follow"]
        memo_lines = build_korea_evening_memo(items)["action_lines"]
        overlap = set(follow) & set(memo_lines)
        self.assertEqual(overlap, set(), overlap)
        self.assertGreaterEqual(len(follow), 1)
        for line in follow + memo_lines:
            with self.subTest(line=line):
                self.assertNotRegex(line, r"(?:입니다|됩니다|합니다)\s+여부")
                self.assertFalse(line.rstrip(".!").endswith("지속적으로"))

    def test_follow_lines_differ_even_for_noun_style_watch_items(self) -> None:
        from keysuri_korea_longform_ux import (
            build_korea_evening_memo,
            build_korea_follow_hold_blocks,
        )

        items = [
            {
                "korean_title": "국내 반도체 공급망 신호",
                "next_watch": "삼성전자 HBM4 후속 일정; 국내 팹 투자 발표",
            }
        ]
        follow = build_korea_follow_hold_blocks(items)["follow"]
        memo_lines = build_korea_evening_memo(items)["action_lines"]
        self.assertEqual(set(follow) & set(memo_lines), set())
        self.assertTrue(any(line.endswith("여부") for line in follow), follow)

    def test_fixture_mapper_passes_market_fields_for_korea_only(self) -> None:
        from keysuri_contract_preview_fixture import _map_top_item

        item = {
            "korean_title": "국내 클라우드 GPU 조달 일정",
            "market_lens": ["주식", "채권/금리"],
            "market_impact": "개인 투자자는 GPU 협력사와 데이터센터 비용 구조 변화를 먼저 봐야 합니다.",
            "source_ids": ["s1"],
        }
        korea_out = _map_top_item(
            item, src={}, source_pack={}, rank=1, program_id="keysuri_korea_tech"
        )
        self.assertEqual(korea_out.get("market_lens"), ["주식", "채권/금리"])
        self.assertIn("데이터센터 비용 구조", korea_out.get("market_impact") or "")
        global_out = _map_top_item(
            item, src={}, source_pack={}, rank=1, program_id="keysuri_global_tech"
        )
        self.assertNotIn("market_lens", global_out)
        self.assertNotIn("market_impact", global_out)


if __name__ == "__main__":
    unittest.main()
