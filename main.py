from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from prompts import build_full_prompt
from renderers import (
    TODAY_GENIE_LEGAL_DISCLAIMER,
    finalize_today_genie_hashtag_list,
    render_email_html,
    render_naver_body_html,
    render_web_html,
)
from validators import validate_today_genie, validate_tomorrow_genie
from weather_image_context import build_image_weather_context_for_today

# Vertex AI SDK
# 설치 필요:
# pip install google-cloud-aiplatform vertexai fastapi uvicorn
import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel
import urllib.error
import urllib.parse
import urllib.request

app = FastAPI(title="Genie Project API")

_static_dir = Path(__file__).resolve().parent / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "global")
VERTEX_MODEL = os.getenv("VERTEX_MODEL", "gemini-2.5-flash")

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
OPENWEATHER_CITY = os.getenv("OPENWEATHER_CITY", "Seoul,KR")
OPENWEATHER_BASE_URL = os.getenv(
    "OPENWEATHER_BASE_URL", "https://api.openweathermap.org/data/2.5/forecast"
)


def _openweather_app_id() -> str:
    """Same OpenWeather provider as tomorrow_genie; WEATHER_API_KEY overrides OPENWEATHER_API_KEY."""
    return (os.getenv("WEATHER_API_KEY") or OPENWEATHER_API_KEY or "").strip()


def _openweather_query_q() -> str:
    city = os.getenv("TARGET_CITY", "").strip()
    country = os.getenv("TARGET_COUNTRY", "").strip()
    if city and country:
        return f"{city},{country}"
    return OPENWEATHER_CITY.strip() or "Seoul,KR"

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


def _load_json_env_with_retries(env_name: str, default: Any, attempts: int = 3) -> tuple[Any, str]:
    """
    Read JSON from env with parse retries (transient / race on env injection).
    Returns (value, status): status is ok | missing | decode_failed_after_retries
    """
    for _ in range(max(1, attempts)):
        raw = os.getenv(env_name)
        if raw is None or not str(raw).strip():
            return default, "missing"
        try:
            return json.loads(raw), "ok"
        except json.JSONDecodeError:
            time.sleep(0.08)
    return default, "decode_failed_after_retries"


def _load_today_genie_feed_bundle(max_rounds: int = 3) -> Dict[str, Any]:
    """
    Load core today_genie market JSON envs; up to `max_rounds` full reload rounds
    if any decode fails (handles late env population).
    """
    specs = [
        ("TODAY_GENIE_OVERNIGHT_US_MARKET_JSON", "overnight_us_market", {}),
        ("TODAY_GENIE_MACRO_INDICATORS_JSON", "macro_indicators", {}),
        ("TODAY_GENIE_TOP_MARKET_NEWS_JSON", "top_market_news", []),
        ("TODAY_GENIE_RISK_FACTORS_JSON", "risk_factors", []),
        (
            "TODAY_GENIE_KOREA_JAPAN_INDICES_JSON",
            "korea_japan_indices",
            {"as_of": "", "session": "", "indices": {}, "summary": ""},
        ),
    ]
    decode_failed: List[str] = []
    bundle: Dict[str, Any] = {}
    for _ in range(max(1, max_rounds)):
        decode_failed = []
        bundle = {}
        all_ok = True
        for env_key, field, default in specs:
            val, st = _load_json_env_with_retries(env_key, default, attempts=3)
            bundle[field] = val
            if st == "decode_failed_after_retries":
                decode_failed.append(env_key)
                all_ok = False
        if all_ok:
            break
        time.sleep(0.1)
    bundle["feed_json_decode_failed_envs"] = decode_failed
    return bundle


def fetch_seoul_weather_forecast(forecast_date: str) -> Dict[str, Any]:
    """
    Fetch OpenWeather 5-day / 3-hour forecast and extract a daily summary
    for the given forecast_date (YYYY-MM-DD) in metric units.
    """
    app_id = _openweather_app_id()
    if not app_id:
        return {}

    query = urllib.parse.urlencode(
        {
            "q": _openweather_query_q(),
            "units": "metric",
            "appid": app_id,
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
    wind_speeds: List[float] = []
    humidities: List[float] = []

    for item in day_entries:
        main = item.get("main", {})
        if "temp" in main:
            temps.append(main["temp"])
        if "feels_like" in main:
            feels_like.append(main["feels_like"])
        if isinstance(main.get("humidity"), (int, float)):
            humidities.append(float(main["humidity"]))
        weather_list = item.get("weather", [])
        if weather_list and isinstance(weather_list, list):
            desc = weather_list[0].get("description")
            if isinstance(desc, str):
                descriptions.add(desc)
        pop = item.get("pop")
        if isinstance(pop, (int, float)):
            precipitation_prob.append(pop)
        wind = item.get("wind") if isinstance(item.get("wind"), dict) else {}
        ws = wind.get("speed")
        if isinstance(ws, (int, float)):
            wind_speeds.append(float(ws))

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
    if wind_speeds:
        summary["wind_speed_max"] = max(wind_speeds)
    if humidities:
        summary["humidity_avg"] = sum(humidities) / len(humidities)

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
        feeds = _load_today_genie_feed_bundle(max_rounds=3)
        overnight_us_market = feeds["overnight_us_market"]
        macro_indicators = feeds["macro_indicators"]
        top_market_news = feeds["top_market_news"]
        risk_factors = feeds["risk_factors"]
        korea_japan_indices = feeds["korea_japan_indices"]
        decode_failed_envs = list(feeds.get("feed_json_decode_failed_envs") or [])

        def _feed_nonempty(val: Any) -> bool:
            if val is None:
                return False
            if isinstance(val, dict):
                return len(val) > 0
            if isinstance(val, list):
                return len(val) > 0
            return True

        feed_pairs = [
            ("overnight_us_market", overnight_us_market),
            ("macro_indicators", macro_indicators),
            ("top_market_news", top_market_news),
            ("risk_factors", risk_factors),
            ("korea_japan_indices", korea_japan_indices),
        ]
        missing_feeds = [name for name, v in feed_pairs if not _feed_nonempty(v)]
        if not missing_feeds:
            input_feed_status = "full"
        elif len(missing_feeds) == len(feed_pairs):
            input_feed_status = "none"
        else:
            input_feed_status = "partial"

        if decode_failed_envs:
            today_genie_feed_gate = "block"
        elif input_feed_status == "none":
            today_genie_feed_gate = "block"
        else:
            today_genie_feed_gate = "ok"

        today_date = kst_now.date().isoformat()
        weather_raw = fetch_seoul_weather_forecast(today_date)
        if not isinstance(weather_raw, dict):
            weather_raw = {}
        image_weather_context = build_image_weather_context_for_today(weather_raw, kst_now)

        return {
            "target_date": today_date,
            "briefing_time_kst": "06:30",
            "purpose": "장전 금융 브리핑",
            "overnight_us_market": overnight_us_market,
            "macro_indicators": macro_indicators,
            "top_market_news": top_market_news,
            "risk_factors": risk_factors,
            "korea_japan_indices": korea_japan_indices,
            "input_feed_status": input_feed_status,
            "editor_note": "사실/해석/추정 구분. 입력 부족 시 보수적으로 축약.",
            "image_weather_context": image_weather_context,
            "feed_json_decode_failed_envs": decode_failed_envs,
            "today_genie_feed_gate": today_genie_feed_gate,
        }

    if mode == "tomorrow_genie":
        forecast_date = (kst_now + timedelta(days=1)).date().isoformat()
        weather_context = fetch_seoul_weather_forecast(forecast_date)
        # When OpenWeather is unset or returns no rows, keep a non-empty object so
        # the model is not blocked on weather_input_missing and can write conservatively.
        if not weather_context:
            weather_context = {
                "provider": "unavailable",
                "forecast_date": forecast_date,
                "summary": {},
                "note": "OpenWeather 미구성 또는 해당 일자 데이터 없음. 수치·지역 특화 예보를 만들지 말고 보수적으로 서술.",
            }

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


def _email_operational_handoff_meta(
    mode: str,
    validation_result: str,
) -> Dict[str, Any]:
    """
    Server-owned, customer-facing labels for the email 운영 안내 block only.
    No raw internal state strings (e.g. draft_only, validated) are exposed here.
    """
    kst_now = datetime.now(ZoneInfo("Asia/Seoul"))
    exec_ts = kst_now.strftime("%Y-%m-%d %H:%M:%S KST")

    if mode == "today_genie":
        mode_label = "오늘의 지니 장전 브리핑"
    elif mode == "tomorrow_genie":
        mode_label = "내일의 지니 브리핑"
    else:
        mode_label = "지니 브리핑"

    if validation_result == "pass":
        status_label = "기본 검수 통과"
        result_summary = "초안 생성과 기본 검수를 통과했습니다."
        email_delivery_label = "이메일 발송 완료"
    elif validation_result == "draft_only":
        status_label = "운영 검토 필요"
        result_summary = (
            "초안은 생성되었지만, 운영 검토 후 전달하는 편이 안전합니다."
        )
        email_delivery_label = "이메일 미발송"
    else:
        status_label = "자동 진행 불가"
        result_summary = "이번 실행은 자동 진행보다 확인이 우선입니다."
        email_delivery_label = "이메일 미발송"

    raw_href = os.getenv("GENIE_REREQUEST_URL", "").strip()
    rerequest_url = raw_href if raw_href else "#"

    # revision_request: policy-gated / review-first (today_genie); not immediate rerun.
    # Placeholder POST target — bind GENIE_REVISION_REQUEST_POST_URL to your API when ready.
    revision_post = os.getenv("GENIE_REVISION_REQUEST_POST_URL", "").strip()
    if not revision_post:
        revision_post = "https://placeholder.genie-revision.bind-later.invalid/v1/revision-request"

    return {
        "mode_label": mode_label,
        "status_label": status_label,
        "execution_time_kst": exec_ts,
        "result_summary": result_summary,
        "email_delivery_label": email_delivery_label,
        "rerequest_url": rerequest_url,
        "mode_code": mode,
        "revision_request_post_url": revision_post,
    }


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
    if (
        mode == "today_genie"
        and runtime_input.get("today_genie_feed_gate") == "block"
    ):
        detail = {
            "status": "review_required",
            "reason": "today_genie_feed_unavailable",
            "message": (
                "핵심 시장 피드가 비어 있거나(JSON 미설정) 연속 로드에 실패했습니다. "
                "피드를 확인한 뒤 다시 실행하세요."
            ),
            "feed_json_decode_failed_envs": runtime_input.get(
                "feed_json_decode_failed_envs", []
            ),
            "input_feed_status": runtime_input.get("input_feed_status"),
        }
        raise HTTPException(status_code=422, detail=detail)

    prompt = build_full_prompt(mode, runtime_input)
    raw_text = call_gemini(prompt, mode)
    data = parse_model_json(raw_text, mode)
    if mode == "today_genie":
        data["hashtags"] = finalize_today_genie_hashtag_list(data, runtime_input)
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

    if mode == "today_genie":
        data = {**data, "legal_disclaimer": TODAY_GENIE_LEGAL_DISCLAIMER}

    web_html = render_web_html(mode, data)
    workflow_status = "validated" if validation.result == "pass" else "review_required"
    op_meta = _email_operational_handoff_meta(mode, validation.result)
    email_base = os.getenv("GENIE_PUBLIC_BASE_URL", "").strip().rstrip("/")
    email_html = render_email_html(
        mode, data, op_meta, email_asset_base_url=email_base
    )
    naver_body_html = render_naver_body_html(mode, data)

    rendered = {
        "html_page": web_html,
        "email_body_html": email_html,
        "naver_blog_body_html": naver_body_html,
    }

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
