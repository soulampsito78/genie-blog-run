from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List

from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from prompts import build_full_prompt
from renderers import render_email_html, render_naver_body_html, render_web_html
from validators import validate_today_genie, validate_tomorrow_genie

# Vertex AI SDK
# 설치 필요:
# pip install google-cloud-aiplatform vertexai fastapi uvicorn
import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel
import urllib.error
import urllib.parse
import urllib.request

app = FastAPI(title="Genie Project API")

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "global")
VERTEX_MODEL = os.getenv("VERTEX_MODEL", "gemini-2.5-flash")

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
OPENWEATHER_CITY = os.getenv("OPENWEATHER_CITY", "Seoul,KR")
OPENWEATHER_BASE_URL = os.getenv(
    "OPENWEATHER_BASE_URL", "https://api.openweathermap.org/data/2.5/forecast"
)

SUPPORTED_MODES = ["today_genie", "tomorrow_genie"]


class JobRequest(BaseModel):
    type: str = Field(..., description="today_genie or tomorrow_genie")


def init_vertex() -> None:
    if not PROJECT_ID:
        raise RuntimeError("PROJECT_ID environment variable is required.")
    vertexai.init(project=PROJECT_ID, location=VERTEX_LOCATION)


def get_model() -> GenerativeModel:
    return GenerativeModel(VERTEX_MODEL)


def _load_json_env(env_name: str, default: Any) -> Any:
    raw = os.getenv(env_name)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def fetch_seoul_weather_forecast(forecast_date: str) -> Dict[str, Any]:
    """
    Fetch OpenWeather 5-day / 3-hour forecast and extract a daily summary
    for the given forecast_date (YYYY-MM-DD) in metric units.
    """
    if not OPENWEATHER_API_KEY:
        return {}

    query = urllib.parse.urlencode(
        {
            "q": OPENWEATHER_CITY,
            "units": "metric",
            "appid": OPENWEATHER_API_KEY,
        }
    )
    url = f"{OPENWEATHER_BASE_URL}?{query}"

    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            if resp.status != 200:
                return {}
            raw = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return {}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    city_info = payload.get("city", {})
    entries = payload.get("list", [])

    day_entries: List[Dict[str, Any]] = []
    for item in entries:
        dt_txt = item.get("dt_txt")
        if isinstance(dt_txt, str) and dt_txt.startswith(forecast_date):
            day_entries.append(item)

    if not day_entries:
        return {}

    temps = []
    feels_like = []
    descriptions = set()
    precipitation_prob = []

    for item in day_entries:
        main = item.get("main", {})
        if "temp" in main:
            temps.append(main["temp"])
        if "feels_like" in main:
            feels_like.append(main["feels_like"])
        weather_list = item.get("weather", [])
        if weather_list and isinstance(weather_list, list):
            desc = weather_list[0].get("description")
            if isinstance(desc, str):
                descriptions.add(desc)
        pop = item.get("pop")
        if isinstance(pop, (int, float)):
            precipitation_prob.append(pop)

    if not temps:
        return {}

    summary: Dict[str, Any] = {
        "temp_min": min(temps),
        "temp_max": max(temps),
    }
    if feels_like:
        summary["feels_like_avg"] = sum(feels_like) / len(feels_like)
    if descriptions:
        summary["conditions"] = sorted(descriptions)
    if precipitation_prob:
        summary["precipitation_probability_max"] = max(precipitation_prob)

    return {
        "provider": "openweather",
        "city": city_info.get("name") or "Seoul",
        "country": city_info.get("country") or "KR",
        "units": "metric",
        "forecast_date": forecast_date,
        "summary": summary,
    }


def build_runtime_input(mode: str) -> Dict[str, Any]:
    kst_now = datetime.now(ZoneInfo("Asia/Seoul"))
    now_kst = kst_now.isoformat()

    if mode == "today_genie":
        overnight_us_market = _load_json_env("TODAY_GENIE_OVERNIGHT_US_MARKET_JSON", {})
        macro_indicators = _load_json_env("TODAY_GENIE_MACRO_INDICATORS_JSON", {})
        top_market_news = _load_json_env("TODAY_GENIE_TOP_MARKET_NEWS_JSON", [])
        risk_factors = _load_json_env("TODAY_GENIE_RISK_FACTORS_JSON", [])

        return {
            "target_date": kst_now.date().isoformat(),
            "briefing_time_kst": "06:30",
            "purpose": "장전 금융 브리핑",
            "overnight_us_market": overnight_us_market,
            "macro_indicators": macro_indicators,
            "top_market_news": top_market_news,
            "risk_factors": risk_factors,
            "editor_note": "사실/해석/추정 구분. 입력 부족 시 보수적으로 축약."
        }

    if mode == "tomorrow_genie":
        forecast_date = (kst_now + timedelta(days=1)).date().isoformat()
        weather_context = fetch_seoul_weather_forecast(forecast_date)

        return {
            "target_date": kst_now.date().isoformat(),
            "target_city": "서울",
            "forecast_reference_datetime_kst": now_kst,
            "weather_context": weather_context,
            "image_context": {
                "city": "서울",
                "season_hint": "auto"
            },
            "writing_goal": "다정한 마무리, 생활정보 중심, 준비형 브리핑"
        }

    raise ValueError(f"Unsupported mode: {mode}")


def extract_json_object(raw_text: str) -> str:
    raw_text = raw_text.strip()

    if raw_text.startswith("{") and raw_text.endswith("}"):
        return raw_text

    codeblock_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw_text, re.DOTALL)
    if codeblock_match:
        return codeblock_match.group(1).strip()

    first_brace = raw_text.find("{")
    last_brace = raw_text.rfind("}")
    if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
        return raw_text[first_brace:last_brace + 1]

    return raw_text


def parse_model_json(raw_text: str, mode: str) -> Dict[str, Any]:
    candidate = extract_json_object(raw_text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        logger.error(
            "genie_api failure mode=%s reason=json_parse_error message=%s",
            mode,
            str(e),
        )
        raise HTTPException(
            status_code=500,
            detail={
                "status": "failed",
                "reason": "json_parse_error",
                "message": str(e),
                "raw_preview": raw_text[:1200],
            },
        )


def call_gemini(prompt: str, mode: str) -> str:
    try:
        init_vertex()
        model = get_model()

        generation_config = GenerationConfig(
            temperature=0.3,
            top_p=0.9,
            max_output_tokens=8192,
            response_mime_type="application/json",
        )

        response = model.generate_content(
            prompt,
            generation_config=generation_config,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "genie_api failure mode=%s internal_reason=vertex_path_unhandled exc_type=%s message=%s",
            mode,
            type(e).__name__,
            str(e),
            exc_info=True,
        )
        raise

    text = getattr(response, "text", None)
    if not text:
        logger.error(
            "genie_api failure mode=%s reason=empty_model_response",
            mode,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "status": "failed",
                "reason": "empty_model_response",
                "message": "Gemini returned empty text response.",
            },
        )
    return text


def response_issues(issues: List[Any]) -> List[Dict[str, Any]]:
    return [
        {
            "code": issue.code,
            "message": issue.message,
            "severity": issue.severity,
        }
        for issue in issues
    ]


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "project_id": PROJECT_ID,
        "location": VERTEX_LOCATION,
        "model": VERTEX_MODEL,
        "supported_modes": SUPPORTED_MODES,
    }


@app.post("/")
def generate(job: JobRequest) -> Dict[str, Any]:
    mode = job.type
    if mode not in SUPPORTED_MODES:
        raise HTTPException(status_code=400, detail=f"Unsupported type: {mode}")

    runtime_input = build_runtime_input(mode)
    prompt = build_full_prompt(mode, runtime_input)
    raw_text = call_gemini(prompt, mode)
    data = parse_model_json(raw_text, mode)

    if mode == "today_genie":
        validation = validate_today_genie(data, runtime_input)
    else:
        validation = validate_tomorrow_genie(data, runtime_input)

    if validation.result == "block":
        issue_codes = [i.code for i in validation.issues[:8]]
        logger.error(
            "genie_api failure mode=%s reason=validation_block issue_count=%s issue_codes=%s",
            mode,
            len(validation.issues),
            issue_codes,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "status": "failed" if mode == "today_genie" else "review_required",
                "reason": "validation_block",
                "issues": response_issues(validation.issues),
                "raw_preview": raw_text[:1200],
            },
        )

    web_html = render_web_html(mode, data)
    email_html = render_email_html(mode, data)
    naver_body_html = render_naver_body_html(mode, data)

    rendered = {
        "html_page": web_html,
        "email_body_html": email_html,
        "naver_blog_body_html": naver_body_html,
    }

    workflow_status = "validated" if validation.result == "pass" else "review_required"

    return {
        "status": "ok",
        "type": mode,
        "workflow_status": workflow_status,
        "validation_result": validation.result,
        "issues": response_issues(validation.issues),
        "runtime_input": runtime_input,
        "data": {
            **data,
            "rendered_channels": rendered,
        },
    }
