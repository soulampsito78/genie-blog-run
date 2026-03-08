# main.py
from __future__ import annotations

import json
import os
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from prompts import build_full_prompt
from validators import validate_today_genie, validate_tomorrow_genie

app = FastAPI()

PROJECT_ID = os.getenv("PROJECT_ID", "gen-lang-client-0667098249")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "global")
VERTEX_MODEL = os.getenv("VERTEX_MODEL", "gemini-2.5-flash")

SUPPORTED_MODES = ["today_genie", "tomorrow_genie"]

class JobRequest(BaseModel):
    type: str

def build_runtime_input(mode: str) -> Dict[str, Any]:
    # 실제 구현에서는 market_service.py / weather_service.py에서 가져와야 함
    # 여기서는 스키마 틀만 제시
    if mode == "today_genie":
        return {
            "target_date": "2026-03-08",
            "briefing_time_kst": "06:30",
            "purpose": "장전 금융 브리핑",
            "overnight_us_market": {},
            "macro_indicators": {},
            "top_market_news": [],
            "risk_factors": [],
            "editor_note": "사실/해석/추정 구분. 입력 부족 시 보수적으로 축약."
        }

    if mode == "tomorrow_genie":
        return {
            "target_date": "2026-03-09",
            "target_city": "서울",
            "forecast_reference_datetime_kst": "2026-03-09T06:00:00+09:00",
            "weather_context": {},
            "image_context": {},
            "writing_goal": "다정한 마무리, 생활정보 중심, 준비형 브리핑"
        }

    raise ValueError(f"Unsupported mode: {mode}")

def call_gemini(prompt: str) -> str:
    # 실제 Vertex AI 호출부로 교체
    raise NotImplementedError

def parse_model_json(raw_text: str) -> Dict[str, Any]:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "status": "failed",
                "reason": "json_parse_error",
                "message": str(e),
                "raw_preview": raw_text[:1000],
            },
        )

def render_web_html(mode: str, data: Dict[str, Any]) -> str:
    if mode == "today_genie":
        return f"""
        <html><body>
        <h1>{data['title']}</h1>
        <p>{data['summary']}</p>
        <h2>시장 셋업</h2><p>{data['market_setup']}</p>
        </body></html>
        """.strip()

    return f"""
    <html><body>
    <h1>{data['title']}</h1>
    <p>{data['summary']}</p>
    <h2>내일 날씨</h2><p>{data['weather_briefing']}</p>
    </body></html>
    """.strip()

def render_email_html(mode: str, data: Dict[str, Any]) -> str:
    # 웹 HTML을 재사용하지 않고 단순 구조로 별도 생성
    return f"""
    <div>
      <h1>{data['title']}</h1>
      <p>{data['summary']}</p>
      <p>{data['closing_message']}</p>
    </div>
    """.strip()

def render_naver_body_html(mode: str, data: Dict[str, Any]) -> str:
    if mode == "today_genie":
        return f"""
        <h2>{data['title']}</h2>
        <p>{data['summary']}</p>
        <h3>오늘 장 셋업</h3>
        <p>{data['market_setup']}</p>
        """.strip()

    return f"""
    <h2>{data['title']}</h2>
    <p>{data['summary']}</p>
    <h3>내일 날씨</h3>
    <p>{data['weather_briefing']}</p>
    """.strip()

@app.get("/health")
def health():
    return {
        "status": "ok",
        "project_id": PROJECT_ID,
        "location": VERTEX_LOCATION,
        "model": VERTEX_MODEL,
        "supported_modes": SUPPORTED_MODES,
    }

@app.post("/")
def generate(job: JobRequest):
    mode = job.type
    if mode not in SUPPORTED_MODES:
        raise HTTPException(status_code=400, detail=f"Unsupported type: {mode}")

    runtime_input = build_runtime_input(mode)
    prompt = build_full_prompt(mode, runtime_input)
    raw_text = call_gemini(prompt)
    data = parse_model_json(raw_text)

    if mode == "today_genie":
        validation = validate_today_genie(data, runtime_input)
    else:
        validation = validate_tomorrow_genie(data, runtime_input)

    if validation.result == "block":
        raise HTTPException(
            status_code=500,
            detail={
                "status": "review_required" if mode == "tomorrow_genie" else "failed",
                "reason": "validation_block",
                "issues": [issue.__dict__ for issue in validation.issues],
                "raw_preview": raw_text[:1000],
            },
        )

    web_html = render_web_html(mode, data)
    email_html = render_email_html(mode, data)
    naver_body_html = render_naver_body_html(mode, data)

    response_data = {
        **data,
        "rendered_channels": {
            "html_page": web_html,
            "email_body_html": email_html,
            "naver_blog_body_html": naver_body_html,
        },
    }

    return {
        "status": "ok",
        "type": mode,
        "workflow_status": "validated" if validation.result == "pass" else "review_required",
        "validation_result": validation.result,
        "issues": [issue.__dict__ for issue in validation.issues],
        "data": response_data,
    }
