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

    with patch("main.build_runtime_input", return_value={"briefing_type": "today_genie"}), \
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
