"""Sentence-level and real pipeline boundaries for the October 28 incident."""
from copy import deepcopy
from unittest.mock import patch
import pytest
from fastapi import HTTPException

from main import (JobRequest, _generate_impl, stabilize_today_genie_vague_phrases,
                  stabilize_today_genie_validation_fields, stabilize_today_genie_market_narrative)
from prompts import build_full_prompt, build_top3_extraction_prompt
from renderers import (render_email_html, render_web_html, render_naver_body_html,
                       finalize_today_genie_hashtag_list, today_genie_email_inline_cid_pair)
from today_genie_replay_context import (CONTEXT_KEY, build_today_replay_context,
                                      replay_context_valid, replay_temporal_conflicts)
from validators import _today_replay_copy_issues, _today_genie_result_from_issues

PARENT = '20261028_063049_today_genie_5cb73e82'

def runtime(at='2026-10-28T11:21:56+09:00'):
    rt = {'target_date': '2026-10-28', 'briefing_generated_at_kst': at,
          'today_news_selection_frozen': True,
          'top_market_news': [{'headline': f'기업{i} 실적 발표', 'news_id': str(i),
                              'url': f'https://example.org/article/{i}'} for i in range(3)]}
    rt[CONTEXT_KEY] = build_today_replay_context(rt, PARENT)
    return rt

@pytest.mark.parametrize('source,expected', [
    ('기술주의 방향성을 가늠하는 지표가 될 수 있습니다.', '기술주의 흐름을 확인하는 지표가 될 수 있습니다.'),
    ('향후 방향성을 가늠하기 위해 지표를 봅니다.', '향후 흐름을 확인하기 위해 지표를 봅니다.'),
    ('지수의 방향성을 가늠할 자료입니다.', '지수의 흐름을 확인할 자료입니다.'),
    ('소비 변화를 가늠해야 합니다.', '소비 변화를 확인해야 합니다.'),
    ('소비 변화를 가늠해야 할 시점입니다.', '소비 변화를 확인해야 할 시점입니다.'),
    ('소비 변화를 확인하는 지표입니다.', '소비 변화를 확인하는 지표입니다.'),
])
def test_full_sentence_grammar_and_no_invented_variables(source, expected):
    actual = stabilize_today_genie_vague_phrases({'summary': source})
    assert actual['summary'] == expected
    assert stabilize_today_genie_vague_phrases(actual) == actual

def test_all_customer_fields_copy_without_touching_source_or_numbers():
    text = '기술주의 방향성을 가늠하는 지표가 될 수 있습니다.'
    original = dict(title=text, greeting=text, summary=text, market_setup=text, closing_message=text,
                    key_watchpoints=[dict(headline=text, detail=text, what_happened=text,
                                          news_id='fixed', source_url='https://example.org/방향성을 가늠', close=12.3)],
                    risk_check=[dict(risk='소비', detail=text, basis='fact')],
                    opportunities=[dict(theme='실적', reason=text)])
    before = deepcopy(original)
    fixed = stabilize_today_genie_vague_phrases(original)
    assert original == before
    assert fixed['key_watchpoints'][0]['source_url'] == before['key_watchpoints'][0]['source_url']
    assert fixed['key_watchpoints'][0]['close'] == 12.3
    assert fixed['key_watchpoints'][0]['news_id'] == 'fixed'
    assert fixed['risk_check'][0]['detail'] == '기술주의 흐름을 확인하는 지표가 될 수 있습니다.'
    final = stabilize_today_genie_validation_fields(fixed, {})
    assert final['risk_check'][0]['detail'] == fixed['risk_check'][0]['detail']

@pytest.mark.parametrize('at', ['2026-10-28T06:30:00+09:00', '2026-10-28T11:21:56+09:00',
                              '2026-10-28T23:59:59+09:00', '2026-10-28T02:21:56+00:00'])
def test_replay_is_neutral_at_any_same_day_preparation_time(at):
    assert replay_context_valid(runtime(at)[CONTEXT_KEY])

@pytest.mark.parametrize('changes', [
    {'briefing_generated_at_kst': None}, {'briefing_generated_at_kst': '2026-10-28T11:21:56'},
    {'briefing_generated_at_kst': '2026-10-29T00:00:00+09:00'}, {'target_date': '2026-10-27'},
    {'target_date': '2026-10-28garbage'}, {'target_date': True},
])
def test_unknown_or_cross_day_replay_does_not_gain_a_context(changes):
    rt = dict(runtime(), **changes)
    with pytest.raises(ValueError): build_today_replay_context(rt, PARENT)

def test_outside_calendar_and_holiday_are_unavailable():
    for day, parent in [('2099-10-28', '20991028_063000_today_genie_12345678'),
                        ('2026-10-31', '20261031_063000_today_genie_12345678')]:
        with pytest.raises(ValueError):
            build_today_replay_context({'target_date': day, 'briefing_generated_at_kst': day+'T11:00:00+09:00'}, parent)

def test_both_model_phases_get_last_priority_replay_rule():
    rt = runtime()
    for prompt in (build_top3_extraction_prompt(rt), build_full_prompt('today_genie', rt, today_genie_main_briefing=True)):
        assert '[TODAY_REPLAY_TIME_CONTEXT' in prompt
        assert '2026-10-28T11:21:56+09:00' in prompt
        assert 'closing_message' in prompt
        assert '실시간' in prompt
    assert '[TODAY_REPLAY_TIME_CONTEXT' not in build_full_prompt('tomorrow_genie', rt)
    assert '[TODAY_REPLAY_TIME_CONTEXT' not in build_full_prompt('today_genie', {})

@pytest.mark.parametrize('collection,key', [(None, 'title'), (None, 'greeting'), (None, 'summary'),
    (None, 'market_setup'), (None, 'closing_message'), ('key_watchpoints','detail'),
    ('risk_check','detail'), ('opportunities','reason')])
def test_every_rendered_copy_surface_with_stale_instruction_cannot_pass(collection, key):
    rt = runtime()
    payload = {CONTEXT_KEY: rt[CONTEXT_KEY]}
    text = '오늘 장전에는 수급을 확인하며 장을 시작해야 합니다.'
    if collection: payload[collection] = [{key: text}]
    else: payload[key] = text
    issues = _today_replay_copy_issues(payload, rt)
    assert {i.code for i in issues} == {'today_replay_temporal_conflict'}
    assert _today_genie_result_from_issues(issues) != 'pass'

def test_historical_first_thirty_minutes_is_preserved_but_future_advice_is_flagged():
    past = {'summary': '전일 개장 후 첫 30분 거래대금은 원문에 명시돼 있습니다.'}
    assert replay_temporal_conflicts(past) == []
    future = {'summary': '첫 30분 변동성만으로도 우선순위를 재정렬할 수 있습니다.'}
    assert replay_temporal_conflicts(future) == ['summary']

@pytest.mark.parametrize('key', ['email_subject', 'naver_blog_title'])
def test_channel_titles_are_customer_copy_too(key):
    rt = runtime()
    data = {CONTEXT_KEY:rt[CONTEXT_KEY], 'channel_drafts':{key:'오늘 장전에는 환율을 확인해야 합니다.'}}
    assert _today_replay_copy_issues(data, rt)[0].code == 'today_replay_temporal_conflict'
    source = {'channel_drafts':{key:'기술주의 방향성을 가늠하는 지표'}}
    fixed = stabilize_today_genie_vague_phrases(source)
    assert fixed['channel_drafts'][key] == '기술주의 흐름을 확인하는 지표'
    assert source['channel_drafts'][key] == '기술주의 방향성을 가늠하는 지표'

def test_missing_forged_or_unbound_context_is_a_hard_failure():
    rt = runtime()
    for data, source in [({}, rt), ({CONTEXT_KEY: rt[CONTEXT_KEY]}, {}), ({}, {'today_news_selection_frozen': True})]:
        assert _today_genie_result_from_issues(_today_replay_copy_issues(data, source)) == 'block'

def test_numeric_repair_cannot_reinsert_preopen_tail_in_a_replay():
    rt = runtime()
    data = {'summary': '잘못된 방향', 'market_setup': ''}
    obs = {'SPX': {'observation_status': 'settled', 'pct_change': 0.6, 'market_date': '2026-10-27'}}
    with patch('main.canonical_market_observations', return_value=obs), \
         patch('market_observation.prose_fact_conflicts', side_effect=lambda text,*a: text == '잘못된 방향'):
        fixed = stabilize_today_genie_market_narrative(data, rt)
    assert '장전' not in fixed['summary']
    assert '+0.60%' in fixed['summary'] and '2026-10-27' in fixed['summary']

def test_real_api_rejects_bad_time_before_a_model_call():
    rt = runtime()
    rt['briefing_generated_at_kst'] = '2026-10-29T00:00:00+09:00'
    with patch('main.build_runtime_input', return_value=rt), patch('main.record_memory_stage'), \
         patch('main.run_today_genie_text_pipeline') as pipeline, patch('main.call_gemini') as gemini:
        with pytest.raises(HTTPException) as exc:
            _generate_impl(JobRequest(type='today_genie', frozen_top_market_news=rt['top_market_news'], frozen_parent_run_id=PARENT))
    assert exc.value.status_code == 422
    pipeline.assert_not_called(); gemini.assert_not_called()

@pytest.mark.parametrize('replay', [True, False])
def test_real_api_overwrites_model_context_with_server_binding(replay):
    rt = runtime()
    if not replay:
        rt.pop(CONTEXT_KEY); rt.pop('today_news_selection_frozen')
    data = {CONTEXT_KEY: {'schema':'forged'}, 'summary': '마감 기준 내용입니다.'}
    class Stop(Exception): pass
    captured = {}
    def capture(payload, source):
        captured.update(payload=deepcopy(payload),source=deepcopy(source)); raise Stop()
    kwargs = {'frozen_top_market_news': rt['top_market_news'], 'frozen_parent_run_id': PARENT} if replay else {}
    with patch('main.build_runtime_input', return_value=rt), patch('main.record_memory_stage'), \
         patch('main.apply_today_genie_sent_news_dedup', side_effect=lambda r:r), \
         patch('main.run_today_genie_text_pipeline', return_value=(data,'',{},{})), \
         patch('main.validate_today_genie', side_effect=capture):
        with pytest.raises(Stop): _generate_impl(JobRequest(type='today_genie', **kwargs))
    if replay: assert captured['payload'][CONTEXT_KEY] == captured['source'][CONTEXT_KEY]
    else: assert CONTEXT_KEY not in captured['payload']

def test_final_customer_render_has_neutral_label_tags_cue_and_both_images():
    rt = runtime()
    data = {CONTEXT_KEY: rt[CONTEXT_KEY], 'title':'미국 실적과 AI 이슈', 'summary':'전일 마감 기준으로 정리합니다.',
            'closing_message':'입력의 마감 세션을 함께 확인합니다.',
            'hashtags':['#오늘의지니','#장전브리핑','#미국증시','#실적','#인공지능','#리스크','#오늘증시체크']}
    original = deepcopy(data)
    html = render_email_html('today_genie', data, {}, email_inline_cid_pair=today_genie_email_inline_cid_pair())
    assert '[재발행 브리핑]' in html and '작성 기준 2026.10.28 11:21 KST' in html
    assert '장전' not in html and '오늘 아침 시장을 움직일' not in html
    assert html.count('<img ') == 2 and html.count('src="cid:') == 2
    assert len(finalize_today_genie_hashtag_list(data, rt)) == 7
    for render in (render_web_html, render_naver_body_html):
        other = render('today_genie',data)
        assert '장전' not in other and '[재발행 브리핑]' in other
    assert data == original

def test_natural_edition_keeps_its_existing_label_and_cue():
    html = render_email_html('today_genie', {'title':'정상 장전 본문'}, {})
    assert '[장전 브리핑]' in html
    assert '오늘 아침 시장을 움직일' in html
    assert '[재발행 브리핑]' not in html
