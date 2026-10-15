import unittest
from validators import _detail_has_what_and_why_today, _split_sentences

class TodayConcreteImpactCueRegressionTests(unittest.TestCase):

    def test_concrete_market_impact_without_abstract_cue_is_not_a_false_block(self):
        detail = '이란의 공격 강화 속에 호르무즈 해협에서 컨테이너선이 침몰하는 사건이 발생하여 중동 지역의 지정학적 긴장이 고조되고 있습니다. 오늘 장전에서는 중동 지정학적 리스크 고조는 국제 유가 및 물류 비용 상승 압력으로 작용하여 시장 전반에 불안감을 조성할 수 있습니다. 이 축에서는 코스피 선물 베이시스와 대형주 호가를 먼저 확인하는 편이 좋습니다.'
        assert len(detail) > 66
        assert len(_split_sentences(detail)) >= 2
        assert _detail_has_what_and_why_today(detail)

    def test_long_today_keyword_padding_without_explained_impact_still_fails(self):
        detail = '오늘 아침 시장에서는 관련 소식과 세부 내용을 차례대로 바라봅니다. 이 문장은 충분히 긴 편이지만 어떤 내용도 구체적으로 설명하지 않고 단어만 연결합니다.'
        assert len(detail) > 66
        assert not _detail_has_what_and_why_today(detail)

    def test_repeated_bare_impact_cues_do_not_turn_keyword_padding_into_meaning(self):
        watch_padding = '오늘은 코스피 코스닥 유가 환율 금리 외국인 기관 거래대금 반도체 수급 지표를 확인하고 다시 확인합니다.'
        for repeated_phrase in ('하방 압력 하방 압력 하방 압력.', '압력으로 작용 압력으로 작용 압력으로 작용.', '불안감을 조성 불안감을 조성 불안감을 조성.'):
            detail = repeated_phrase + ' ' + watch_padding
            assert len(detail) >= 66
            assert len(_split_sentences(detail)) >= 2
            assert not _detail_has_what_and_why_today(detail), repeated_phrase
