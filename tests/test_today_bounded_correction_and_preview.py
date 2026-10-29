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
    assert projected["risk_factors"] == []
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

