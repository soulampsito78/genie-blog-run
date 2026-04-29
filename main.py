from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from prompts import (
    build_full_prompt,
    build_top3_extraction_prompt,
    today_genie_json_recovery_suffix,
    today_genie_top3_extract_recovery_suffix,
)
from today_genie_top3_assembly import (
    apply_briefing_repetition_guard,
    assemble_key_watchpoints_from_slots,
    normalize_top3_slots_payload,
)
from renderers import (
    TODAY_GENIE_LEGAL_DISCLAIMER,
    finalize_today_genie_hashtag_list,
    render_email_html,
    render_naver_body_html,
    render_web_html,
    today_genie_email_inline_cid_pair,
)
from validators import (
    NUMBER_TABLE_ACCURACY_STATUSES,
    validate_today_genie,
    validate_tomorrow_genie,
)
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
    controlled_test_mode: bool = Field(
        False,
        description="Explicit one-off controlled test gate; ignored unless true.",
    )
    controlled_test_target_date: Optional[str] = Field(
        None,
        description="YYYY-MM-DD target date for controlled tests only.",
    )


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


def _valid_iso_date(raw: str) -> bool:
    try:
        datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _controlled_test_target_date_from_env() -> Optional[str]:
    flag = os.getenv("GENIE_CONTROLLED_TEST_MODE", "").strip().lower()
    if flag not in ("1", "true", "yes"):
        return None
    target = os.getenv("GENIE_CONTROLLED_TEST_TARGET_DATE", "").strip()
    if not target or not _valid_iso_date(target):
        return None
    return target


def _controlled_test_target_date_from_request(job: JobRequest) -> Optional[str]:
    if not job.controlled_test_mode:
        return None
    target = (job.controlled_test_target_date or "").strip()
    if not target or not _valid_iso_date(target):
        raise HTTPException(
            status_code=400,
            detail="controlled_test_target_date must be YYYY-MM-DD when controlled_test_mode=true",
        )
    return target


def build_runtime_input(mode: str, controlled_test_target_date: Optional[str] = None) -> Dict[str, Any]:
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

        env_controlled_target = _controlled_test_target_date_from_env()
        today_date = controlled_test_target_date or env_controlled_target or kst_now.date().isoformat()
        controlled_active = bool(controlled_test_target_date or env_controlled_target)
        if controlled_active:
            logger.info("controlled_test_mode active target_date=%s", today_date)
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
            "controlled_test_mode": controlled_active,
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


def _normalize_json_candidate(candidate: str) -> str:
    s = candidate.lstrip("\ufeff")
    return (
        s.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )


def _strip_trailing_commas_json(candidate: str) -> str:
    s = candidate
    prev: str | None = None
    while prev != s:
        prev = s
        s = re.sub(r",(\s*[\]}])", r"\1", s)
    return s


def _json_parse_candidate_variants(raw_text: str) -> List[str]:
    base = extract_json_object(raw_text)
    seen: set[str] = set()
    out: List[str] = []

    def add(x: str) -> None:
        if x not in seen:
            seen.add(x)
            out.append(x)

    add(base)
    norm = _normalize_json_candidate(base)
    add(norm)
    add(_strip_trailing_commas_json(base))
    add(_strip_trailing_commas_json(norm))
    return out


def try_parse_model_json(raw_text: str) -> tuple[Dict[str, Any] | None, str]:
    """Try local repairs (quotes, trailing commas) before declaring parse failure."""
    errs: List[str] = []
    for i, cand in enumerate(_json_parse_candidate_variants(raw_text)):
        try:
            val = json.loads(cand)
            if isinstance(val, dict):
                logger.info("model_json_parse_ok variant_index=%s", i)
                return val, ""
            errs.append(f"v{i}:not_a_json_object")
        except json.JSONDecodeError as e:
            errs.append(f"v{i}:{e}")
    return None, "; ".join(errs[:5])


def parse_model_json(raw_text: str, mode: str) -> Dict[str, Any]:
    data, err = try_parse_model_json(raw_text)
    if data is not None:
        return data
    logger.error(
        "genie_api failure mode=%s reason=json_parse_error repairs_exhausted detail=%s",
        mode,
        err[:800],
    )
    raise HTTPException(
        status_code=500,
        detail={
            "status": "failed",
            "reason": "json_parse_error",
            "message": err[:1200],
            "raw_preview": raw_text[:1200],
        },
    )


def call_gemini(
    prompt: str,
    mode: str,
    *,
    max_output_tokens: int | None = None,
) -> str:
    try:
        init_vertex()
        model = get_model()
        max_out = (
            max_output_tokens
            if max_output_tokens is not None
            else int(os.getenv("GENIE_MAX_OUTPUT_TOKENS", "12288"))
        )

        generation_config = GenerationConfig(
            temperature=0.3,
            top_p=0.9,
            max_output_tokens=max_out,
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


call_gemini_text = call_gemini


def run_today_genie_text_pipeline(
    runtime_input: Dict[str, Any],
) -> tuple[Dict[str, Any], str, Dict[str, float]]:
    """
    Two-phase today_genie text: (1) structured TOP3 slots, (2) main briefing JSON.
    Final key_watchpoints are always assembled in code: **exactly three** items,
    news-anchored where headlines exist, otherwise feed-anchored (overnight/macro/risk)
    market-watch slots — never absence filler.
    """
    prof: Dict[str, float] = {}
    ext_prompt = build_top3_extraction_prompt(runtime_input)
    t0 = time.perf_counter()
    raw_ext = call_gemini(ext_prompt, "today_genie", max_output_tokens=4096)
    prof["top3_extract_inference_sec"] = round(time.perf_counter() - t0, 4)
    try:
        ext_data = parse_model_json(raw_ext, "today_genie")
    except HTTPException:
        raw_ext = call_gemini(
            ext_prompt + today_genie_top3_extract_recovery_suffix(),
            "today_genie",
            max_output_tokens=4096,
        )
        ext_data = parse_model_json(raw_ext, "today_genie")
    slots = normalize_top3_slots_payload(ext_data)
    main_prompt = build_full_prompt(
        "today_genie",
        runtime_input,
        today_genie_main_briefing=True,
    )
    t1 = time.perf_counter()
    raw_main = call_gemini(main_prompt, "today_genie")
    prof["main_brief_inference_sec"] = round(time.perf_counter() - t1, 4)
    try:
        data = parse_model_json(raw_main, "today_genie")
    except HTTPException as e:
        det = e.detail if isinstance(e.detail, dict) else {}
        if det.get("reason") == "json_parse_error":
            raw_main = call_gemini(
                main_prompt + today_genie_json_recovery_suffix(),
                "today_genie",
            )
            data = parse_model_json(raw_main, "today_genie")
        else:
            raise
    data["key_watchpoints"] = assemble_key_watchpoints_from_slots(slots, runtime_input)
    apply_briefing_repetition_guard(data)
    return data, raw_main, prof


def response_issues(issues: List[Any]) -> List[Dict[str, Any]]:
    return [
        {
            "code": issue.code,
            "message": issue.message,
            "severity": issue.severity,
        }
        for issue in issues
    ]


def _runtime_validation_check_payload(
    *,
    runtime_input: Dict[str, Any],
    validation_result: str,
    workflow_status: str,
    issues: List[Any],
    content_quality_warnings: List[Any],
) -> Dict[str, Any]:
    issue_details = response_issues(issues)
    return {
        "target_date": runtime_input.get("target_date"),
        "controlled_test_mode": bool(runtime_input.get("controlled_test_mode")),
        "controlled_test_target_date": runtime_input.get("target_date")
        if runtime_input.get("controlled_test_mode")
        else None,
        "validation_result": validation_result,
        "workflow_status": workflow_status,
        "issue_codes": [item.get("code") for item in issue_details if isinstance(item, dict)],
        "issue_details": issue_details,
        "content_quality_warnings": list(content_quality_warnings),
    }


def _fmt_signed_pct(value: Any) -> str:
    if isinstance(value, (int, float)):
        sign = "+" if value > 0 else ""
        return f"{sign}{value:g}%"
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.endswith("%"):
        if raw.startswith(("+", "-")):
            return raw
        try:
            num = float(raw[:-1])
        except ValueError:
            return raw
        sign = "+" if num > 0 else ""
        return f"{sign}{raw}"
    return raw


def _fmt_close(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value or "").strip()


def _coerce_index_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    txt = str(value or "").strip().replace(",", "")
    if txt.endswith("%"):
        txt = txt[:-1]
    try:
        return float(txt)
    except ValueError:
        return None


def _provenance_field(slot: Any, feed: Dict[str, Any], key: str) -> str:
    if isinstance(slot, dict):
        v = slot.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    v = feed.get(key)
    if v is not None and str(v).strip():
        return str(v).strip()
    return ""


def _resolve_row_accuracy_status(slot: Any, feed: Dict[str, Any], has_proof: bool) -> str:
    for obj in (slot, feed):
        if not isinstance(obj, dict):
            continue
        raw = str(obj.get("accuracy_status") or "").strip().lower()
        if raw in NUMBER_TABLE_ACCURACY_STATUSES:
            return raw
    if has_proof:
        return "unverified"
    return "source_missing"


def _feed_index_row(
    indices: Any,
    feed: Any,
    source_keys: tuple[str, ...],
    label: str,
) -> Optional[Dict[str, Any]]:
    if not isinstance(indices, dict):
        return None
    feed_dict = feed if isinstance(feed, dict) else {}
    slot: Optional[Dict[str, Any]] = None
    symbol = ""
    for key in source_keys:
        candidate = indices.get(key)
        if isinstance(candidate, dict):
            slot = candidate
            symbol = key
            break
    if not slot:
        return None
    close_disp = _fmt_close(slot.get("close"))
    pct = _fmt_signed_pct(slot.get("change_pct"))
    if not close_disp or not pct:
        return None
    close_num = _coerce_index_float(slot.get("close"))
    pct_num = _coerce_index_float(slot.get("change_pct"))
    if close_num is None or pct_num is None:
        return None

    as_of = ""
    raw_as_of = feed_dict.get("as_of")
    if isinstance(raw_as_of, str) and len(raw_as_of.strip()) >= 10:
        as_of = raw_as_of.strip()[:10]

    source_name = _provenance_field(slot, feed_dict, "source_name")
    source_url = _provenance_field(slot, feed_dict, "source_url")
    source_id = _provenance_field(slot, feed_dict, "source_id")
    fetched_at = _provenance_field(slot, feed_dict, "fetched_at")
    verified_at = _provenance_field(slot, feed_dict, "verified_at")
    has_proof = bool(source_name) and (bool(source_url) or bool(source_id)) and bool(verified_at)
    accuracy_status = _resolve_row_accuracy_status(slot, feed_dict, has_proof)

    return {
        "label": label,
        "value": f"{close_disp} ({pct})",
        "basis": "fact",
        "symbol": symbol,
        "display_name": label,
        "close": float(close_num),
        "change_pct": float(pct_num),
        "as_of": as_of,
        "source_name": source_name,
        "source_url": source_url,
        "source_id": source_id,
        "fetched_at": fetched_at,
        "verified_at": verified_at,
        "accuracy_status": accuracy_status,
    }


def enforce_today_genie_market_snapshot_from_feeds(
    data: Dict[str, Any],
    runtime_input: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Preserve model content, but make the customer number table deterministic
    when feed values exist. Missing required feed values remain validation errors.
    """
    kj = runtime_input.get("korea_japan_indices")
    ov = runtime_input.get("overnight_us_market")
    kj_indices = kj.get("indices") if isinstance(kj, dict) else {}
    ov_indices = ov.get("indices") if isinstance(ov, dict) else {}
    kj_d = kj if isinstance(kj, dict) else {}
    ov_d = ov if isinstance(ov, dict) else {}
    required = [
        (kj_indices, kj_d, ("KOSPI",), "코스피"),
        (kj_indices, kj_d, ("KOSDAQ",), "코스닥"),
        (ov_indices, ov_d, ("SPX", "S&P 500", "SP500"), "S&P 500"),
        (ov_indices, ov_d, ("NASDAQ", "IXIC"), "나스닥"),
        (kj_indices, kj_d, ("NIKKEI", "N225", "NI225"), "니케이"),
        (ov_indices, ov_d, ("DJI", "DOW", "DOWJONES"), "다우존스"),
    ]
    rows = [_feed_index_row(indices, fd, keys, label) for indices, fd, keys, label in required]
    complete = [r for r in rows if r is not None]
    if complete:
        return {**data, "market_snapshot": complete}
    return data


def _today_genie_risk_fallbacks_from_feeds(runtime_input: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Build review-safe risk rows from supplied risk feeds when model output is
    structurally unusable. This does not add new market facts; it only restates
    the provided risk feed in the required customer-facing shape.
    """
    risks = runtime_input.get("risk_factors")
    if not isinstance(risks, list):
        risks = []

    fallback: List[Dict[str, str]] = []
    for item in risks[:4]:
        if not isinstance(item, dict):
            continue
        raw_risk = str(item.get("risk") or "").strip()
        raw_detail = str(item.get("detail") or "").strip()
        if not raw_risk or not raw_detail:
            continue
        low = raw_risk.lower()
        if "inflation" in low or "cpi" in low:
            risk = "인플레이션 경로"
            detail = "CPI와 금리 재평가가 이어질 수 있어 장 초반 금리·환율 반응을 먼저 확인합니다."
        elif "geopolitic" in low or "iran" in raw_detail.lower():
            risk = "지정학 변수"
            detail = "중동 휴전 관련 뉴스가 위험선호를 흔들 수 있어 헤드라인과 유가 반응을 함께 봅니다."
        else:
            risk = raw_risk
            detail = raw_detail
        fallback.append({"risk": risk, "detail": detail, "basis": "interpretation"})

    if fallback:
        return fallback

    return [
        {
            "risk": "금리·환율 반응",
            "detail": "CPI 이후 금리와 원/달러 환율이 같은 방향으로 움직이는지 먼저 확인합니다.",
            "basis": "interpretation",
        }
    ]


def stabilize_today_genie_validation_fields(
    data: Dict[str, Any],
    runtime_input: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Keep the generated briefing, but make validation-critical structural fields
    deterministic before the hard gate. This aligns no-send preflight and worker
    send attempts without weakening validators or publishing policy.
    """
    normalized = dict(data)

    risk_rows: List[Dict[str, str]] = []
    source_risks = data.get("risk_check")
    if isinstance(source_risks, list):
        for item in source_risks[:4]:
            if not isinstance(item, dict):
                continue
            risk = str(item.get("risk") or "").strip()
            detail = str(item.get("detail") or "").strip()
            if not risk or not detail:
                continue
            basis = str(item.get("basis") or "").strip()
            if basis not in ("fact", "interpretation", "speculation"):
                basis = "interpretation"
            risk_rows.append({"risk": risk, "detail": detail, "basis": basis})

    if not risk_rows:
        risk_rows = _today_genie_risk_fallbacks_from_feeds(runtime_input)
    normalized["risk_check"] = risk_rows

    closing = str(data.get("closing_message") or "").strip()
    lecture_tails = (
        "신중한 접근",
        "민감한 대응",
        "주의가 필요",
        "면밀히 지켜",
        "주시할 필요",
        "리스크 관리",
    )
    if not closing or any(phrase in closing for phrase in lecture_tails):
        normalized["closing_message"] = (
            "오늘은 CPI 이후 금리·환율 반응과 외국인 수급이 같은 방향인지 먼저 확인하겠습니다."
        )

    return normalized


def email_operational_handoff_meta(
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


def build_today_genie_email_html_for_cid_mime_send(
    data: Dict[str, Any],
    validation_result: str = "pass",
) -> str:
    """
    today_genie HTML for SMTP MIME sends: top/bottom slots use cid:… references
    so the message does not depend on public base URLs or local static paths for images.
    """
    op_meta = email_operational_handoff_meta("today_genie", validation_result)
    return render_email_html(
        "today_genie",
        data,
        op_meta,
        email_asset_base_url="",
        email_inline_cid_pair=today_genie_email_inline_cid_pair(),
    )


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

    controlled_test_target_date = _controlled_test_target_date_from_request(job)
    runtime_input = build_runtime_input(mode, controlled_test_target_date=controlled_test_target_date)
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

    if mode == "today_genie":
        data, raw_text, _layer_prof = run_today_genie_text_pipeline(runtime_input)
        logger.info("today_genie_two_phase_timings_sec=%s", _layer_prof)
    else:
        prompt = build_full_prompt(mode, runtime_input)
        raw_text = call_gemini(prompt, mode)
        try:
            data = parse_model_json(raw_text, mode)
        except HTTPException as e:
            det = e.detail if isinstance(e.detail, dict) else {}
            if det.get("reason") == "json_parse_error":
                raw_text = call_gemini(prompt + today_genie_json_recovery_suffix(), mode)
                data = parse_model_json(raw_text, mode)
            else:
                raise
    if mode == "today_genie":
        data["hashtags"] = finalize_today_genie_hashtag_list(data, runtime_input)
        data = enforce_today_genie_market_snapshot_from_feeds(data, runtime_input)
        data = stabilize_today_genie_validation_fields(data, runtime_input)
        validation = validate_today_genie(data, runtime_input)
        if any(i.code == "number_table_accuracy_not_verified" for i in validation.issues):
            logger.warning(
                "today_genie number_table: accuracy_not_externally_verified "
                "(issue code number_table_accuracy_not_verified)"
            )
    else:
        validation = validate_tomorrow_genie(data, runtime_input)

    if validation.result == "block":
        issue_codes = [i.code for i in validation.issues[:8]]
        runtime_check = _runtime_validation_check_payload(
            runtime_input=runtime_input,
            validation_result=validation.result,
            workflow_status="review_required",
            issues=validation.issues,
            content_quality_warnings=list(validation.content_quality_warnings),
        )
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
                "issue_codes": runtime_check["issue_codes"],
                "issue_details": runtime_check["issue_details"],
                "content_quality_warnings": runtime_check["content_quality_warnings"],
                "runtime_validation_check": runtime_check,
                "raw_preview": raw_text[:1200],
            },
        )

    if mode == "today_genie":
        data = {**data, "legal_disclaimer": TODAY_GENIE_LEGAL_DISCLAIMER}

    web_html = render_web_html(mode, data)
    workflow_status = "validated" if validation.result == "pass" else "review_required"
    op_meta = email_operational_handoff_meta(mode, validation.result)
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

    runtime_check = _runtime_validation_check_payload(
        runtime_input=runtime_input,
        validation_result=validation.result,
        workflow_status=workflow_status,
        issues=validation.issues,
        content_quality_warnings=list(validation.content_quality_warnings),
    )
    return {
        "status": "ok",
        "type": mode,
        "workflow_status": workflow_status,
        "validation_result": validation.result,
        "issues": response_issues(validation.issues),
        "issue_codes": runtime_check["issue_codes"],
        "issue_details": runtime_check["issue_details"],
        "content_quality_warnings": list(validation.content_quality_warnings),
        "runtime_validation_check": runtime_check,
        "runtime_input": runtime_input,
        "data": {
            **data,
            "rendered_channels": rendered,
        },
    }
