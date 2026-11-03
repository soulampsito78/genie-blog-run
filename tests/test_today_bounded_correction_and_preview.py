import json, os, socket, tempfile, pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from pydantic import ValidationError

_tmp = tempfile.TemporaryDirectory()
os.environ["HOME"] = _tmp.name
os.environ["TMPDIR"] = _tmp.name
os.environ["GENIE_ADMIN_SAFETY_LOCAL_DIR"] = os.path.join(_tmp.name, "safety")
os.environ["GENIE_API_URL"] = "http://fake-genie-api"
for _k in ["GEMINI_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "GCS_BUCKET_NAME", "GOOGLE_CLOUD_PROJECT"]:
    os.environ.pop(_k, None)

_orig_c, _orig_ce = socket.socket.connect, socket.socket.connect_ex
def _no_net(s, *a, **k):
    if getattr(s, "family", None) in (socket.AF_INET, getattr(socket, "AF_INET6", 30)):
        raise RuntimeError("Network disabled")
    return _orig_c(s, *a, **k)

def _no_net_ce(s, *a, **k):
    if getattr(s, "family", None) in (socket.AF_INET, getattr(socket, "AF_INET6", 30)):
        raise RuntimeError("Network disabled")
    return _orig_ce(s, *a, **k)

socket.socket.connect = _no_net
socket.socket.connect_ex = _no_net_ce
socket.getaddrinfo = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("DNS disabled"))

import admin_store
admin_store.repo_root = lambda: Path(_tmp.name)
(Path(_tmp.name) / "output" / "admin_runs").mkdir(parents=True, exist_ok=True)

from tests.test_today_genie_20260902_surgical_incident import _runtime
from main import JobRequest, _generate_impl, run_today_genie_text_pipeline
from orchestrator import run_genie_job, execute_orchestrator_run, _validate_guidance_or_fail

_RT_FIXTURE = _runtime()
_V_NEWS = _RT_FIXTURE["top_market_news"]
_V_PID = "20261027_083000_today_genie_12345678"

@pytest.mark.parametrize("m,news,pid,note", [
    ("today_genie", _V_NEWS, _V_PID, 123),
    ("today_genie", _V_NEWS, _V_PID, True),
    ("today_genie", _V_NEWS, _V_PID, ["note"]),
    ("tomorrow_genie", _V_NEWS, _V_PID, "valid note"),
    ("today_genie", _V_NEWS, _V_PID, ""),
    ("today_genie", _V_NEWS, _V_PID, "   "),
    ("today_genie", _V_NEWS, _V_PID, "x" * 1001),
    ("today_genie", None, _V_PID, "valid note"),
    ("today_genie", [], _V_PID, "valid note"),
    ("today_genie", [{}], _V_PID, "valid note"),
    ("today_genie", [{"junk": "val"}], _V_PID, "valid note"),
    ("today_genie", [{"headline": ""}], _V_PID, "valid note"),
    ("today_genie", [{"headline": "   "}], _V_PID, "valid note"),
    ("today_genie", [{"headline": 123}], _V_PID, "valid note"),
    ("today_genie", [{"headline": None}], _V_PID, "valid note"),
    ("today_genie", _V_NEWS, "", "valid note"),
    ("today_genie", _V_NEWS, "bad_id", "valid note"),
    ("today_genie", _V_NEWS, "20261027_083000_tomorrow_genie_12345678", "valid note"),
    ("today_genie", _V_NEWS, f" {_V_PID}", "valid note"),
    ("today_genie", _V_NEWS, f"{_V_PID} ", "valid note"),
    ("today_genie", _V_NEWS, f"{_V_PID}\n", "valid note"),
    ("today_genie", _V_NEWS, "20261027_083000_today_genie_1234567A", "valid note"),
])
def test_invalid_guidance_rejected(m, news, pid, note):
    with patch("urllib.request.build_opener") as mock_bo, patch("main.call_gemini") as mock_gemini:
        with pytest.raises((ValueError, ValidationError)):
            JobRequest(type=m, frozen_top_market_news=news, frozen_parent_run_id=pid, correction_guidance=note)
        with pytest.raises(ValueError):
            run_genie_job(m, frozen_top_market_news=news, frozen_parent_run_id=pid, correction_guidance=note)
        with pytest.raises(ValueError):
            execute_orchestrator_run(m, parent_run_id=pid, frozen_top_market_news=news, correction_guidance=note)
        assert mock_bo.call_count == 0
        assert mock_gemini.call_count == 0

def test_legacy_no_guidance_preserved():
    job = JobRequest(type="today_genie")
    assert job.correction_guidance is None
    assert _validate_guidance_or_fail(None, "today_genie", None, None) is None
    assert _validate_guidance_or_fail(None, "tomorrow_genie", None, None) is None

def test_real_run_genie_job_payload_capture():
    mock_resp = MagicMock()
    mock_resp.getcode.return_value = 200
    mock_resp.read.return_value = json.dumps({"validation_result": "pass", "workflow_status": "validated", "data": {}, "runtime_input": {}}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None
    captured = {}
    def fake_open(req, *a, **k):
        captured["d"] = json.loads(req.data.decode("utf-8"))
        return mock_resp

    with patch("urllib.request.build_opener") as mock_bo:
        mock_bo.return_value.open = fake_open
        run_genie_job(
            "today_genie",
            frozen_top_market_news=_V_NEWS,
            frozen_parent_run_id=_V_PID,
            correction_guidance="  Tighten watchpoint 2  ",
        )
    assert captured["d"]["correction_guidance"] == "Tighten watchpoint 2"
    assert captured["d"]["frozen_parent_run_id"] == _V_PID
    assert len(captured["d"]["frozen_top_market_news"]) == 3

def test_execute_orchestrator_run_forwarding():
    class Sentinel(Exception): pass
    def mock_job(mode, **kwargs):
        assert kwargs["frozen_top_market_news"] == _V_NEWS
        assert kwargs["frozen_parent_run_id"] == _V_PID
        assert kwargs["correction_guidance"] == "Tighten watchpoint 2"
        raise Sentinel("captured")

    with patch("orchestrator.run_genie_job", side_effect=mock_job):
        with pytest.raises(Sentinel):
            execute_orchestrator_run(
                "today_genie",
                parent_run_id=_V_PID,
                frozen_top_market_news=_V_NEWS,
                correction_guidance=" Tighten watchpoint 2 ",
            )

def test_generate_impl_runtime_binding():
    class SentinelPipe(Exception): pass
    job = JobRequest(
        type="today_genie",
        frozen_top_market_news=_V_NEWS,
        frozen_parent_run_id=_V_PID,
        correction_guidance="Tighten watchpoint 2",
    )
    def fake_pipe(rt, *a, **k):
        raise SentinelPipe(rt)

    with patch("main.build_runtime_input", return_value={"briefing_type": "today_genie", "target_date": "2026-10-27", "briefing_generated_at_kst": "2026-10-27T11:00:00+09:00"}), \
         patch("main.record_memory_stage", lambda *a, **k: None), \
         patch("main.run_today_genie_text_pipeline", side_effect=fake_pipe):
        with pytest.raises(SentinelPipe) as exc_info:
            _generate_impl(job)
        rt = exc_info.value.args[0]
        assert rt["correction_guidance"] == "Tighten watchpoint 2"
        assert rt["today_news_selection_frozen_parent_run_id"] == _V_PID
        assert rt["today_news_selection_frozen"] is True
        assert len(rt["top_market_news"]) == 3
        for orig, actual in zip(_V_NEWS, rt["top_market_news"]):
            assert actual["headline"] == orig["headline"]

def test_run_today_genie_text_pipeline_guidance_and_control():
    guidance_text = "Fix inflation risk detail"
    rt_guided = dict(_RT_FIXTURE, correction_guidance=guidance_text)
    rt_control = dict(_RT_FIXTURE)
    rt_control.pop("correction_guidance", None)

    def _respond(p, prompt_log):
        prompt_log.append(p)
        tag = "CORRECTED" if guidance_text in p else "BASE"
        if len(prompt_log) == 1:
            slots = [
                {
                    "slot": i,
                    "news_id": it["news_id"],
                    "headline_ko": f"제{i} 핵심 뉴스",
                    "what_happened": f"선택된 제{i} 뉴스의 사실관계가 야간 시장에서 {tag} 기준으로 확인됐습니다.",
                    "why_it_matters_today": "오늘 장전에는 위험선호와 업종별 반응을 가르는 변수입니다.",
                    "what_to_watch_in_korea": "국내에서는 코스피·코스닥과 원/달러, 외국인 수급을 확인합니다.",
                    "detail": f"선택된 제{i} 뉴스의 사실관계가 야간 시장에서 {tag} 기준으로 확인됐습니다.",
                }
                for i, it in enumerate(_RT_FIXTURE["top_market_news"], 1)
            ]
            return json.dumps({"slots": slots})
        return json.dumps({
            "summary": f"금일 시장 요약 {tag} 내용입니다.",
            "key_watchpoints": [
                {
                    "slot": i,
                    "news_id": it["news_id"],
                    "detail": f"선택된 제{i} 뉴스의 사실관계가 야간 시장에서 {tag} 기준으로 확인됐습니다.",
                    "what_happened": f"선택된 제{i} 뉴스의 사실관계가 야간 시장에서 {tag} 기준으로 확인됐습니다.",
                }
                for i, it in enumerate(_RT_FIXTURE["top_market_news"], 1)
            ],
            "risk_check": [{"risk": "물가", "detail": f"소비자물가 리스크 상세가 {tag} 기준으로 점검되었습니다."}],
        })

    guided_prompts, control_prompts = [], []
    with patch("main.call_gemini", side_effect=lambda p, *a, **k: _respond(p, guided_prompts)):
        data_g, _, _, _ = run_today_genie_text_pipeline(rt_guided)

    assert len(guided_prompts) == 2, "Guided pipeline must execute exactly two prompt phases"
    assert all(guidance_text in p for p in guided_prompts), "Correction guidance must appear in all guided prompts"
    assert len(data_g["key_watchpoints"]) == 3, "Guided run must assemble 3 key watchpoints"
    assert [kw["news_id"] for kw in data_g["key_watchpoints"]] == [it["news_id"] for it in _RT_FIXTURE["top_market_news"]], "Guided watchpoint news_id order must preserve canonical source identities"
    assert all("CORRECTED" in kw["detail"] for kw in data_g["key_watchpoints"]), "Assembled watchpoint detail must carry causal CORRECTED marker"
    assert all("CORRECTED" in rc["detail"] for rc in data_g["risk_check"]), "Risk check detail must carry causal CORRECTED marker"

    with patch("main.call_gemini", side_effect=lambda p, *a, **k: _respond(p, control_prompts)):
        data_c, _, _, _ = run_today_genie_text_pipeline(rt_control)

    assert len(control_prompts) == 2, "Control pipeline must execute exactly two prompt phases"
    assert all(guidance_text not in p for p in control_prompts), "Control prompts must not contain correction guidance"
    assert len(data_c["key_watchpoints"]) == 3, "Control run must assemble 3 key watchpoints"
    assert [kw["news_id"] for kw in data_c["key_watchpoints"]] == [it["news_id"] for it in _RT_FIXTURE["top_market_news"]], "Control watchpoint news_id order must preserve canonical source identities"
    assert all("BASE" in kw["detail"] for kw in data_c["key_watchpoints"]), "Control watchpoint detail must carry causal BASE marker"
    assert all("CORRECTED" not in kw["detail"] for kw in data_c["key_watchpoints"]), "Control watchpoint detail must not carry CORRECTED marker"
    assert all("BASE" in rc["detail"] for rc in data_c["risk_check"]), "Control risk check detail must carry causal BASE marker"
    assert all("CORRECTED" not in rc["detail"] for rc in data_c["risk_check"]), "Control risk check detail must not carry CORRECTED marker"


def test_frozen_today_replay_input_projection_blocks_unselected_narrative_and_preserves_feeds():
    import copy
    from main import _apply_frozen_today_news_selection
    from prompts import build_full_prompt, build_top3_extraction_prompt
    from today_genie_replay_context import (
        CONTEXT_KEY,
        build_today_replay_context,
        replay_context_valid,
    )

    raw_input = {
        "target_date": "2026-10-28",
        "briefing_generated_at_kst": "2026-10-28T11:00:00+09:00",
        "briefing_time_kst": "06:30",
        "purpose": "장전 금융 브리핑",
        "editor_note": "사실/해석/추정 구분. 입력 부족 시 보수적으로 축약.",
        "input_feed_status": "partial",
        "overnight_us_market": {"DJI": {"close": "42100.5", "pct_change": 0.45}},
        "macro_indicators": {"US10Y": {"value": "4.21"}},
        "korea_japan_indices": {"KOSPI": {"close": "2610.2"}},
        "current_role_evidence": {"role": "financial_editor", "as_of": "2026-10-28"},
        "image_weather_context": {"city": "서울", "condition": "clear"},
        # Safety/diagnostic feed contract fields (exact false/blocked/diagnostic values)
        "today_required_feed_contract_passed": False,
        "today_required_feed_contract_missing": ["overnight_us_market"],
        "today_required_feed_contract_stale": ["korea_japan_indices"],
        "today_genie_feed_gate_reason": "feed_contract_failed",
        "today_genie_feed_unavailable_count": 2,
        "scheduler_delivery_success": False,
        "scheduler_delivery_http_status": 500,
        "pipeline_success": False,
        "owner_review_created": True,
        "retry_recommended": True,
        "manual_action_required": True,
        "feed_json_decode_failed_envs": ["ENV_FEED_CORRUPT"],
        "today_genie_feed_gate": "block",
        "today_genie_feed_source": "cache_fallback",
        "today_genie_feed_refresh_attempted": True,
        "today_genie_feed_refresh_status": "failed",
        "today_genie_feed_fallback_used": True,
        "today_genie_feed_fallback_reason": "live_refresh_timeout",
        # Synthetic live narrative risk factors and unknown root narrative container
        "risk_factors": [
            {"risk": "UNSELECTED_SENTINEL_RISK_EVENT", "detail": "live narrative risk factor leak"}
        ],
        "unselected_root_narrative": "UNSELECTED_SENTINEL_RISK_EVENT should never enter prompts",
        "arbitrary_foreign_narrative": {"headline": "UNSELECTED_SENTINEL_RISK_EVENT"},
    }
    # Date-bound replay context
    raw_input[CONTEXT_KEY] = build_today_replay_context(
        raw_input, "20261028_063000_today_genie_12345678"
    )

    frozen_news = [
        {
            "headline": f"정착 기사 {i}",
            "news_id": f"settled_id_{i}",
            "url": f"https://example.com/news/{i}",
            "source": "언론사",
        }
        for i in range(1, 4)
    ]

    before_copy = copy.deepcopy(raw_input)

    projected = _apply_frozen_today_news_selection(
        raw_input,
        frozen_news,
        parent_run_id=_V_PID,
        correction_guidance="Tighten watchpoint 2",
    )

    # 1. Full caller-input equality against before-copy (NO mutation)
    assert raw_input == before_copy

    # 2. Projected dictionary validation
    assert projected["top_market_news"] == frozen_news
    assert len(projected["risk_factors"]) >= 1, "Projected risk_factors must not be empty []"
    assert all(
        "UNSELECTED_SENTINEL_RISK_EVENT" not in r.get("detail", "")
        and "UNSELECTED_SENTINEL_RISK_EVENT" not in r.get("risk", "")
        for r in projected["risk_factors"]
    ), "Unselected sentinel risk must not leak into projected risks"
    assert any(
        "정착 기사 1" in r.get("detail", "") for r in projected["risk_factors"]
    ), "Derived risk factors must be grounded in settled selected articles"
    assert "unselected_root_narrative" not in projected
    assert "arbitrary_foreign_narrative" not in projected
    assert projected["today_news_selection_frozen"] is True
    assert projected["today_news_selection_frozen_parent_run_id"] == _V_PID
    assert projected["correction_guidance"] == "Tighten watchpoint 2"
    assert projected["overnight_us_market"] == raw_input["overnight_us_market"]
    assert projected["macro_indicators"] == raw_input["macro_indicators"]
    assert projected["korea_japan_indices"] == raw_input["korea_japan_indices"]
    assert projected["current_role_evidence"] == raw_input["current_role_evidence"]

    # 3. Preserved safety and diagnostic fields
    assert projected["today_required_feed_contract_passed"] is False
    assert projected["today_required_feed_contract_missing"] == ["overnight_us_market"]
    assert projected["today_required_feed_contract_stale"] == ["korea_japan_indices"]
    assert projected["today_genie_feed_gate_reason"] == "feed_contract_failed"
    assert projected["today_genie_feed_unavailable_count"] == 2
    assert projected["scheduler_delivery_success"] is False
    assert projected["scheduler_delivery_http_status"] == 500
    assert projected["pipeline_success"] is False
    assert projected["owner_review_created"] is True
    assert projected["retry_recommended"] is True
    assert projected["manual_action_required"] is True
    assert projected["feed_json_decode_failed_envs"] == ["ENV_FEED_CORRUPT"]
    assert projected["today_genie_feed_gate"] == "block"
    assert projected["today_genie_feed_source"] == "cache_fallback"
    assert projected["today_genie_feed_refresh_attempted"] is True
    assert projected["today_genie_feed_refresh_status"] == "failed"
    assert projected["today_genie_feed_fallback_used"] is True
    assert projected["today_genie_feed_fallback_reason"] == "live_refresh_timeout"

    # 4. Valid date-bound replay context preserved
    assert CONTEXT_KEY in projected
    assert replay_context_valid(projected[CONTEXT_KEY])

    # 5. Prompt builders must NOT contain unselected sentinel narrative
    ext_prompt = build_top3_extraction_prompt(projected)
    main_prompt = build_full_prompt("today_genie", projected, today_genie_main_briefing=True)

    assert "UNSELECTED_SENTINEL_RISK_EVENT" not in ext_prompt
    assert "UNSELECTED_SENTINEL_RISK_EVENT" not in main_prompt
    assert "unselected_root_narrative" not in ext_prompt
    assert "unselected_root_narrative" not in main_prompt
    assert "arbitrary_foreign_narrative" not in ext_prompt
    assert "arbitrary_foreign_narrative" not in main_prompt

    # 6. Prompt builders MUST contain exact selected article IDs, URLs, and order in BOTH prompts
    for p_name, p_text in [("ext_prompt", ext_prompt), ("main_prompt", main_prompt)]:
        idx_1 = p_text.find("settled_id_1")
        idx_2 = p_text.find("settled_id_2")
        idx_3 = p_text.find("settled_id_3")
        assert idx_1 != -1 and idx_2 != -1 and idx_3 != -1, f"Missing settled IDs in {p_name}"
        assert idx_1 < idx_2 < idx_3, f"Settled IDs not in exact order in {p_name}"

        url_1 = p_text.find("https://example.com/news/1")
        url_2 = p_text.find("https://example.com/news/2")
        url_3 = p_text.find("https://example.com/news/3")
        assert url_1 != -1 and url_2 != -1 and url_3 != -1, f"Missing URLs in {p_name}"
        assert url_1 < url_2 < url_3, f"URLs not in exact order in {p_name}"

        head_1 = p_text.find("정착 기사 1")
        head_2 = p_text.find("정착 기사 2")
        head_3 = p_text.find("정착 기사 3")
        assert head_1 != -1 and head_2 != -1 and head_3 != -1, f"Missing headlines in {p_name}"
        assert head_1 < head_2 < head_3, f"Headlines not in exact order in {p_name}"

    # Quantitative feeds preserved in prompt text
    assert "42100.5" in ext_prompt
    assert "42100.5" in main_prompt
    assert "4.21" in ext_prompt
    assert "4.21" in main_prompt


def _valid_today_data_for_test(runtime_input: dict) -> dict:
    from today_genie_replay_context import CONTEXT_KEY
    wps = [
        {
            "headline": f"핵심 이슈 {i}",
            "detail": f"{item['headline'][:25]} 관련 어젯밤 확인된 수치와 오늘 시장 관점입니다.",
            "news_id": item.get("news_id", f"news_{i}"),
            "basis": "fact",
        }
        for i, item in enumerate(runtime_input.get("top_market_news", []), 1)
    ]
    data = {
        "mode": "today_genie",
        "title": "2026년 9월 2일 오늘의 지니 글로벌 금융 브리핑 시장 관점",
        "greeting": "안녕하세요.",
        "summary": "2026년 9월 2일 금융 브리핑입니다. 야간 시장 주요 지수 흐름과 환율을 종합 점검합니다. 확정 마감 세션 수치를 바탕으로 오늘 아침 운용 관점을 정리합니다.",
        "market_setup": "확정 마감 기준 상승 지수는 코스피(+0.23%)이고 하락 지수는 코스닥(-1.56%), 나스닥(-1.03%), 다우존스(-0.79%), S&P 500(-0.71%), 니케이(-0.15%)입니다. 오늘 국내 시장에서는 코스피와 코스닥의 엇갈림, 원/달러 환율과 외국인 수급을 차례로 점검하며 니케이 반응도 함께 살핍니다.",
        "market_snapshot": [
            {"label": "코스피", "value": "6835.80 (+0.23%)", "basis": "fact"},
            {"label": "코스닥", "value": "821.25 (-1.56%)", "basis": "fact"},
            {"label": "S&P 500", "value": "7631.47 (-0.71%)", "basis": "fact"},
            {"label": "나스닥", "value": "26099.77 (-1.03%)", "basis": "fact"},
            {"label": "니케이", "value": "66215.34 (-0.15%)", "basis": "fact"},
            {"label": "다우존스", "value": "52766.88 (-0.79%)", "basis": "fact"},
        ],
        "key_watchpoints": wps,
        "opportunities": [{"theme": "반도체 수급", "reason": "AI 수요 확대 지속", "basis": "interpretation"}],
        "risk_check": [{"risk": "환율 변동성", "detail": "원/달러 환율 움직임과 외국인 수급 방향을 우선 확인합니다.", "basis": "interpretation"}],
        "closing_message": "오늘은 외국인 수급을 먼저 확인하고 시장 변동성에 대한 단정은 피합니다.",
        "image_prompt_studio": "Professional female Korean news anchor presenting financial market news in a modern broadcasting studio with charts showing Nasdaq and S&P 500 data.",
        "image_prompt_outdoor": "Korean news anchor in professional attire walking near Seoul financial district on a clear morning with subtle references to Treasury yields and US equities.",
        "hashtags": ["#오늘의지니", "#장전브리핑", "#모닝브리핑", "#증시전망", "#시장점검", "#환율동향", "#투자전략"],
        "channel_drafts": {
            "email_subject": "오늘의 지니 재발행 브리핑",
            "naver_blog_title": "재발행 브리핑 - 시장 정리",
        },
    }
    if CONTEXT_KEY in runtime_input:
        data[CONTEXT_KEY] = dict(runtime_input[CONTEXT_KEY])
    return data


def test_frozen_today_replay_reconciles_risk_factors_with_validator():
    from main import _apply_frozen_today_news_selection
    from validators import validate_today_genie
    from today_genie_replay_context import CONTEXT_KEY, build_today_replay_context

    parent_id = "20260902_063000_today_genie_12345678"
    rt_known = dict(_RT_FIXTURE)
    rt_known["briefing_generated_at_kst"] = "2026-09-02T11:00:00+09:00"
    rt_known[CONTEXT_KEY] = build_today_replay_context(rt_known, parent_id)

    # Real projection
    projected = _apply_frozen_today_news_selection(
        rt_known,
        rt_known["top_market_news"],
        parent_run_id=parent_id,
    )

    # Defect assertion: projected risk_factors must not be empty []
    assert len(projected["risk_factors"]) >= 1, "Projected risk_factors must not be empty"

    # Real validation: validate_today_genie must NOT emit input_insufficient for risk_factors
    val_data = _valid_today_data_for_test(projected)
    val_res = validate_today_genie(val_data, projected)
    insufficient = [i for i in val_res.issues if i.code == "input_insufficient"]
    assert not insufficient, f"Complete frozen replay must not emit input_insufficient: {[i.message for i in insufficient]}"


def test_natural_behavior_and_fail_closed_cases():
    from main import _apply_frozen_today_news_selection
    from validators import validate_today_genie

    # 1. Natural behavior unchanged: natural input with full feeds does not emit input_insufficient
    data_natural = _valid_today_data_for_test(_RT_FIXTURE)
    val_natural = validate_today_genie(data_natural, _RT_FIXTURE)
    assert not any(i.code == "input_insufficient" for i in val_natural.issues)

    # 2. Fail closed on empty selection: risk_factors becomes [], validator emits input_insufficient
    proj_empty = _apply_frozen_today_news_selection(_RT_FIXTURE, [], parent_run_id=_V_PID)
    assert proj_empty["risk_factors"] == []
    val_empty = validate_today_genie(_valid_today_data_for_test(proj_empty), proj_empty)
    assert any(i.code == "input_insufficient" and "risk_factors" in i.message for i in val_empty.issues)

    # 3. Fail closed on malformed selection (empty headline string)
    proj_malformed = _apply_frozen_today_news_selection(_RT_FIXTURE, [{"headline": "   "}], parent_run_id=_V_PID)
    assert proj_malformed["risk_factors"] == []
    val_malformed = validate_today_genie(_valid_today_data_for_test(proj_malformed), proj_malformed)
    assert any(i.code == "input_insufficient" and "risk_factors" in i.message for i in val_malformed.issues)

    # 4. Fail closed on natural missing risks
    rt_no_risks = dict(_RT_FIXTURE, risk_factors=[])
    val_no_risks = validate_today_genie(_valid_today_data_for_test(rt_no_risks), rt_no_risks)
    assert any(i.code == "input_insufficient" and "risk_factors" in i.message for i in val_no_risks.issues)

    # 5. Fail closed on missing real macro input
    rt_no_macro = dict(_RT_FIXTURE)
    rt_no_macro.pop("macro_indicators", None)
    val_no_macro = validate_today_genie(_valid_today_data_for_test(rt_no_macro), rt_no_macro)
    assert any(i.code == "input_insufficient" and "macro_indicators" in i.message for i in val_no_macro.issues)

    # 6. Fail closed on marker spoof: setting today_news_selection_frozen=True without risk_factors
    spoof_input = dict(_RT_FIXTURE, today_news_selection_frozen=True, risk_factors=[])
    val_spoof = validate_today_genie(_valid_today_data_for_test(spoof_input), spoof_input)
    assert any(i.code == "input_insufficient" and "risk_factors" in i.message for i in val_spoof.issues)



def test_late_replay_subject_alignment_and_historical_clause_preservation():
    from main import (
        build_today_genie_email_html_for_cid_mime_send,
        stabilize_today_genie_validation_fields,
    )
    from orchestrator import OrchestrationResult, send_email_if_allowed
    from publishing_policy import PublishingDecision
    from today_genie_replay_context import (
        CONTEXT_KEY,
        build_today_replay_context,
        replay_temporal_conflicts,
    )

    rt_replay = {
        "target_date": "2026-10-28",
        "briefing_generated_at_kst": "2026-10-28T11:00:00+09:00",
    }
    rt_replay[CONTEXT_KEY] = build_today_replay_context(
        rt_replay, "20261028_063000_today_genie_12345678"
    )

    # Case A: Stale pre-open edition label is repaired to neutral late-edition
    data_stale = {
        CONTEXT_KEY: rt_replay[CONTEXT_KEY],
        "channel_drafts": {
            "email_subject": "오늘의 지니 장전 브리핑",
            "naver_blog_title": "장전 브리핑 - 시장 정리",
        },
    }
    stabilized_stale = stabilize_today_genie_validation_fields(data_stale, rt_replay)
    assert stabilized_stale["channel_drafts"]["email_subject"] == "오늘의 지니 재발행 브리핑"
    assert stabilized_stale["channel_drafts"]["naver_blog_title"] == "재발행 브리핑 - 시장 정리"
    assert replay_temporal_conflicts(stabilized_stale) == []

    # Case B: Legitimate historical subject facts must remain byte-identical
    historical_subjects = [
        "어제 장전 브리핑에서 확인된 수치",
        "지난 거래일 장전 브리핑 발표 정리",
        "전일 장전 브리핑 대비 주요 변동",
    ]
    for hist_subj in historical_subjects:
        data_hist = {
            CONTEXT_KEY: rt_replay[CONTEXT_KEY],
            "channel_drafts": {
                "email_subject": hist_subj,
                "naver_blog_title": hist_subj,
            },
        }
        stabilized_hist = stabilize_today_genie_validation_fields(data_hist, rt_replay)
        assert stabilized_hist["channel_drafts"]["email_subject"] == hist_subj
        assert stabilized_hist["channel_drafts"]["naver_blog_title"] == hist_subj
        assert replay_temporal_conflicts(stabilized_hist) == []

    # Case C: Already-neutral subjects must remain byte-identical
    data_neutral = {
        CONTEXT_KEY: rt_replay[CONTEXT_KEY],
        "channel_drafts": {
            "email_subject": "오늘 시장 브리핑",
            "naver_blog_title": "오늘 시장 브리핑",
        },
    }
    stabilized_neutral = stabilize_today_genie_validation_fields(data_neutral, rt_replay)
    assert stabilized_neutral["channel_drafts"]["email_subject"] == "오늘 시장 브리핑"
    assert stabilized_neutral["channel_drafts"]["naver_blog_title"] == "오늘 시장 브리핑"
    assert replay_temporal_conflicts(stabilized_neutral) == []

    # Case D: Natural mode (non-replay) must NOT modify pre-open edition labels
    rt_natural = {
        "target_date": "2026-10-28",
        "briefing_generated_at_kst": "2026-10-28T06:30:00+09:00",
    }
    data_natural = {
        "channel_drafts": {
            "email_subject": "오늘의 지니 장전 브리핑",
            "naver_blog_title": "장전 브리핑 - 시장 정리",
        },
    }
    stabilized_natural = stabilize_today_genie_validation_fields(data_natural, rt_natural)
    assert stabilized_natural["channel_drafts"]["email_subject"] == "오늘의 지니 장전 브리핑"
    assert stabilized_natural["channel_drafts"]["naver_blog_title"] == "장전 브리핑 - 시장 정리"

    # Case E: Actual owner MIME construction uses aligned subject and valid admin link
    from orchestrator import extract_email_html_for_artifact

    run_id = "20261028_110000_today_genie_12345678"
    orch_res = OrchestrationResult(
        decision=PublishingDecision(
            send_email=True,
            create_naver_draft=False,
            auto_publish=False,
            require_review=False,
            suppress_external=False,
        ),
        reason_summary="ok",
        response_status=200,
        mode="today_genie",
        response_data={
            "validation_result": "pass",
            "data": stabilized_stale,
            "runtime_input": rt_replay,
        },
    )
    with patch.dict(os.environ, {"GENIE_ADMIN_PUBLIC_BASE_URL": "https://admin.example.com"}):
        mime_html = extract_email_html_for_artifact(
            orch_res,
            run_id=run_id,
            today_image_result=None,
        )
        assert "운영자 검수 화면 열기" in mime_html
        assert "genie-no-image-notice" in mime_html

        sent_calls = []
        with patch("orchestrator.send_genie_email", side_effect=lambda html, subj, **k: sent_calls.append((html, subj)) or True):
            sent = send_email_if_allowed(
                orch_res,
                run_id=run_id,
                owner_email_html_snapshot=mime_html,
            )
            assert sent is True
            assert len(sent_calls) == 1
            assert sent_calls[0][1] == "[운영자 검토] 오늘의 지니 재발행 브리핑"


def test_frozen_replay_risk_and_closing_fallbacks_avoid_unstated_cpi():
    from main import stabilize_today_genie_validation_fields
    from today_genie_replay_context import CONTEXT_KEY, build_today_replay_context

    rt_replay = {
        "target_date": "2026-10-28",
        "briefing_generated_at_kst": "2026-10-28T11:00:00+09:00",
    }
    rt_replay[CONTEXT_KEY] = build_today_replay_context(
        rt_replay, "20261028_063000_today_genie_12345678"
    )

    data_missing = {
        CONTEXT_KEY: rt_replay[CONTEXT_KEY],
        "channel_drafts": {"email_subject": "오늘 시장 브리핑"},
        "risk_check": [],
        "closing_message": "",
    }

    stabilized = stabilize_today_genie_validation_fields(data_missing, rt_replay)

    # Replay fallback must NOT reintroduce unstated CPI or pre-open instructions
    assert all("CPI" not in r["detail"] for r in stabilized["risk_check"])
    assert stabilized["risk_check"][0]["detail"] == "금리와 원/달러 환율이 같은 방향으로 움직이는지 관측 기준에 맞춰 확인합니다."
    assert "CPI" not in stabilized["closing_message"]
    assert stabilized["closing_message"] == "금리·환율 반응과 외국인 수급은 입력의 관측 기준에 맞춰 함께 확인합니다."

    # Natural mode must preserve original deterministic fallback
    rt_natural = {
        "target_date": "2026-10-28",
        "briefing_generated_at_kst": "2026-10-28T06:30:00+09:00",
    }
    data_natural = {
        "channel_drafts": {"email_subject": "오늘 시장 브리핑"},
        "risk_check": [],
        "closing_message": "",
    }
    stabilized_nat = stabilize_today_genie_validation_fields(data_natural, rt_natural)
    assert "CPI" in stabilized_nat["risk_check"][0]["detail"]
    assert "CPI" in stabilized_nat["closing_message"]



# =============================================================================
# INDEPENDENT PRODUCT QA SYNTHETIC REGRESSION TEST CASES
# =============================================================================

def test_independent_qa_risk_derivation_structure_and_macro_fallback():
    from main import _apply_frozen_today_news_selection
    from validators import validate_today_genie

    # 1. Standard 3 items: derived risks must contain headline attribution for top 2 news
    news_3 = [
        {"headline": "미국 연준 금리 동결 시사", "date": "2026-09-01", "news_id": "news_1"},
        {"headline": "유럽 중앙은행 추가 긴축 경계", "date": "2026-09-01", "news_id": "news_2"},
        {"headline": "아시아 기술주 혼조세 마감", "date": "2026-09-01", "news_id": "news_3"},
    ]
    proj_3 = _apply_frozen_today_news_selection(_RT_FIXTURE, news_3, parent_run_id=_V_PID)
    assert len(proj_3["risk_factors"]) == 2
    assert proj_3["risk_factors"][0]["risk"] == "Headline / geopolitics"
    assert "Sourced from CNBC RSS (2026-09-01): 미국 연준 금리 동결 시사" in proj_3["risk_factors"][0]["detail"]
    assert proj_3["risk_factors"][1]["risk"] == "Policy / macro narrative"
    assert "Sourced from CNBC RSS (2026-09-01): 유럽 중앙은행 추가 긴축 경계" in proj_3["risk_factors"][1]["detail"]

    # 2. 1 news item + macro headline: activates macro fallback for second risk
    news_1 = [{"headline": "단일 주요 헤드라인", "date": "2026-09-01", "news_id": "news_1"}]
    rt_macro = dict(_RT_FIXTURE, macro_indicators={"headline": "거시 경제 불확실성 지속", "as_of": "2026-09-01"})
    proj_1_macro = _apply_frozen_today_news_selection(rt_macro, news_1, parent_run_id=_V_PID)
    assert len(proj_1_macro["risk_factors"]) == 2
    assert proj_1_macro["risk_factors"][0]["risk"] == "Headline / geopolitics"
    assert proj_1_macro["risk_factors"][1]["risk"] == "Macro / index tone"
    assert "거시 경제 불확실성 지속" in proj_1_macro["risk_factors"][1]["detail"]

    # 3. 1 news item + NO macro headline: produces 1 risk factor, still non-empty
    rt_no_macro_head = dict(_RT_FIXTURE, macro_indicators={"as_of": "2026-09-01"})
    proj_1_no_macro = _apply_frozen_today_news_selection(rt_no_macro_head, news_1, parent_run_id=_V_PID)
    assert len(proj_1_no_macro["risk_factors"]) == 1
    val_res = validate_today_genie(_valid_today_data_for_test(proj_1_no_macro), proj_1_no_macro)
    assert not any(i.code == "input_insufficient" for i in val_res.issues)

    # 4. Long headline is safely truncated to 240 chars
    long_news = [{"headline": "A" * 500, "date": "2026-09-01", "news_id": "news_long"}]
    proj_long = _apply_frozen_today_news_selection(_RT_FIXTURE, long_news, parent_run_id=_V_PID)
    assert len(proj_long["risk_factors"]) >= 1
    assert "A" * 240 in proj_long["risk_factors"][0]["detail"]
    assert "A" * 241 not in proj_long["risk_factors"][0]["detail"]


def test_independent_qa_source_containment_and_unrelated_sentinel_exclusion():
    import copy
    from main import _apply_frozen_today_news_selection
    from prompts import build_top3_extraction_prompt, build_full_prompt

    sentinel_str = "ATTACK_SENTINEL_LIVE_INJECTION_X77"
    raw_input = dict(_RT_FIXTURE)
    raw_input["risk_factors"] = [
        {"risk": sentinel_str, "detail": f"live leak of {sentinel_str}"}
    ]
    raw_input["unselected_root_narrative"] = f"root leak of {sentinel_str}"
    raw_input["foreign_carrier"] = {"nested": sentinel_str}
    raw_input["arbitrary_field"] = [sentinel_str]

    before = copy.deepcopy(raw_input)
    frozen_news = list(_V_NEWS)

    projected = _apply_frozen_today_news_selection(
        raw_input,
        frozen_news,
        parent_run_id=_V_PID,
        correction_guidance="Preserve tone",
    )

    # Immutability check
    assert raw_input == before, "Caller runtime_input was mutated by _apply_frozen_today_news_selection"
    assert frozen_news == _V_NEWS, "frozen_news list was mutated"

    # Sentinel containment in projected dictionary
    assert sentinel_str not in str(projected.get("risk_factors")), "Sentinel leaked into projected risk_factors"
    assert "unselected_root_narrative" not in projected
    assert "foreign_carrier" not in projected
    assert "arbitrary_field" not in projected

    # Sentinel containment in both prompt builders
    ext_prompt = build_top3_extraction_prompt(projected)
    main_prompt = build_full_prompt("today_genie", projected, today_genie_main_briefing=True)
    assert sentinel_str not in ext_prompt, f"Sentinel leaked into extraction prompt"
    assert sentinel_str not in main_prompt, f"Sentinel leaked into main prompt"


def test_independent_qa_builder_exception_fails_closed():
    from unittest.mock import patch
    from main import _apply_frozen_today_news_selection
    from validators import validate_today_genie

    # Simulate builder unexpected exception (fail closed to empty risk_factors)
    with patch("ops.probe_today_genie_feeds.build_risk_factors", side_effect=RuntimeError("simulated builder crash")):
        projected = _apply_frozen_today_news_selection(_RT_FIXTURE, _V_NEWS, parent_run_id=_V_PID)
        assert projected["risk_factors"] == [], "Risk factors must be empty list on builder exception"

        val_res = validate_today_genie(_valid_today_data_for_test(projected), projected)
        assert any(
            i.code == "input_insufficient" and "risk_factors" in i.message for i in val_res.issues
        ), "Validator must emit input_insufficient when risk builder fails"


def test_independent_qa_mixed_malformed_news_and_spoof_resilience():
    from main import _apply_frozen_today_news_selection
    from validators import validate_today_genie

    # 1. Mixed malformed: 1 valid headline and 2 invalid entries
    mixed_news = [
        {"headline": "유효한 헤드라인", "date": "2026-09-01", "news_id": "valid_1"},
        {"headline": "   ", "date": "2026-09-01"},
        {"no_headline_key": "some value"},
    ]
    proj_mixed = _apply_frozen_today_news_selection(_RT_FIXTURE, mixed_news, parent_run_id=_V_PID)
    assert len(proj_mixed["risk_factors"]) >= 1
    assert "유효한 헤드라인" in proj_mixed["risk_factors"][0]["detail"]

    # 2. All malformed news: valid_news is empty, risk_factors is [], validator emits input_insufficient
    all_malformed = [
        {"headline": ""},
        {"headline": "   "},
        {"other_key": 12345},
    ]
    proj_bad = _apply_frozen_today_news_selection(_RT_FIXTURE, all_malformed, parent_run_id=_V_PID)
    assert proj_bad["risk_factors"] == []
    val_bad = validate_today_genie(_valid_today_data_for_test(_RT_FIXTURE), proj_bad)
    assert any(
        i.code == "input_insufficient" and "risk_factors" in i.message for i in val_bad.issues
    )

    # 3. Spoofed frozen marker without required market inputs fails
    for missing_key in ["overnight_us_market", "macro_indicators", "top_market_news", "risk_factors"]:
        spoofed = dict(_RT_FIXTURE, today_news_selection_frozen=True)
        spoofed[missing_key] = {} if "market" in missing_key or "macro" in missing_key else []
        val_spoof = validate_today_genie(_valid_today_data_for_test(spoofed), spoofed)
        assert any(
            i.code == "input_insufficient" and missing_key in i.message for i in val_spoof.issues
        ), f"Spoofed input missing {missing_key} must fail validation"
