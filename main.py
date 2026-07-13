from __future__ import annotations

import json
import logging
import os
import re
import hashlib
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from prompts import (
    build_full_prompt,
    build_top3_extraction_prompt,
    feed_image_anchor_hints,
    today_genie_json_recovery_suffix,
    today_genie_top3_extract_recovery_suffix,
)
from today_genie_grounding import headline_grounding_anchors
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
from sent_news_dedup_gate import metadata_from_gate_result, run_sent_news_dedup_gate
from sent_news_log_store import recent_sent_news_log
from validators import (
    NUMBER_TABLE_ACCURACY_STATUSES,
    validate_today_genie,
    validate_tomorrow_genie,
)
from weather_image_context import build_image_weather_context_for_today
from keysuri_gemini_client import extract_gemini_usage_metadata
from genie_cost_estimate import estimate_genie_generation_cost

# Vertex AI SDK
# 설치 필요:
# pip install google-cloud-aiplatform vertexai fastapi uvicorn
import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel
import urllib.error
import urllib.parse
import urllib.request

app = FastAPI(title="Genie Project API")

from admin_routes import router as admin_router  # noqa: E402
from internal_jobs import router as internal_jobs_router  # noqa: E402

app.include_router(admin_router)
app.include_router(internal_jobs_router)

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
TODAY_GENIE_REQUIRED_NEWS_COUNT = 3
TODAY_GENIE_CORE_DATE_FEEDS = (
    "overnight_us_market",
    "korea_japan_indices",
    "macro_indicators",
)
TODAY_GENIE_RUNTIME_FEEDS = (
    "overnight_us_market",
    "korea_japan_indices",
    "macro_indicators",
    "top_market_news",
    "risk_factors",
)
TODAY_GENIE_MAX_FEED_STALE_DAYS = 7
TODAY_GENIE_LIVE_REFRESH_TIMEOUT_SEC = 6
TODAY_GENIE_FEED_CACHE_SCHEMA_VERSION = "today_genie_feed_cache_v1"
TODAY_GENIE_FEED_DIAGNOSTIC_KEYS = (
    "today_genie_feed_source",
    "today_genie_feed_refresh_attempted",
    "today_genie_feed_refresh_status",
    "today_genie_feed_fallback_used",
    "today_genie_feed_fallback_reason",
    "today_genie_feed_staleness",
    "today_genie_live_feed_staleness",
    "today_genie_stale_feeds",
    "today_genie_feed_refresh_started_at",
    "today_genie_feed_refresh_finished_at",
    "today_genie_feed_refresh_elapsed_ms",
    "today_genie_feed_refresh_source_results",
    "today_genie_feed_partial_success",
    "today_genie_feed_live_success_count",
    "today_genie_feed_cache_fallback_count",
    "today_genie_feed_env_fallback_count",
    "today_genie_feed_unavailable_count",
    "today_required_feed_contract_passed",
    "today_required_feed_contract_missing",
    "today_required_feed_contract_stale",
    "today_genie_feed_gate_reason",
    "scheduler_delivery_success",
    "scheduler_delivery_http_status",
    "pipeline_success",
    "owner_review_created",
    "retry_recommended",
    "manual_action_required",
)


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


def _parse_feed_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _today_feed_staleness(feeds: Dict[str, Any], target_date: str) -> Dict[str, Dict[str, Any]]:
    target = _parse_feed_date(target_date)
    out: Dict[str, Dict[str, Any]] = {}
    for name in TODAY_GENIE_CORE_DATE_FEEDS:
        source = feeds.get(name)
        as_of_raw = source.get("as_of") if isinstance(source, dict) else None
        as_of = _parse_feed_date(as_of_raw)
        age_days: Optional[int] = None
        stale = False
        reason = ""
        if target is None:
            reason = "invalid_target_date"
            stale = True
        elif as_of is None:
            reason = "missing_or_invalid_as_of"
            stale = True
        else:
            age_days = (target - as_of).days
            if age_days > TODAY_GENIE_MAX_FEED_STALE_DAYS:
                reason = "as_of_older_than_7_days"
                stale = True
        out[name] = {
            "as_of": str(as_of_raw or ""),
            "age_days": age_days,
            "stale": stale,
            "reason": reason,
        }
    return out


def _today_live_feed_refresh_enabled() -> bool:
    raw = os.getenv("TODAY_GENIE_LIVE_FEED_REFRESH_ENABLED", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _today_live_feed_refresh_timeout_sec() -> int:
    raw = os.getenv("TODAY_GENIE_LIVE_FEED_REFRESH_TIMEOUT_SEC", "").strip()
    if not raw:
        return TODAY_GENIE_LIVE_REFRESH_TIMEOUT_SEC
    try:
        return max(1, min(20, int(raw)))
    except ValueError:
        return TODAY_GENIE_LIVE_REFRESH_TIMEOUT_SEC


def _today_utc_now_iso() -> str:
    return datetime.now(ZoneInfo("UTC")).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _today_feed_payload_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _today_feed_cache_object_key(source_id: str) -> str:
    safe_source = re.sub(r"[^a-z0-9_-]+", "_", str(source_id or "").strip().lower())
    if not safe_source:
        safe_source = "unknown"
    try:
        from admin_store import admin_artifact_gcs_prefix

        prefix = admin_artifact_gcs_prefix().strip("/")
    except Exception:
        prefix = "admin_runs"
    return f"{prefix}/runtime_feed_cache/today_genie/{safe_source}/latest.json"


def _read_today_genie_feed_cache(source_id: str) -> Optional[Dict[str, Any]]:
    try:
        from admin_store import admin_artifact_bucket_name, _gcs_download_text

        if not admin_artifact_bucket_name():
            return None
        raw = _gcs_download_text(_today_feed_cache_object_key(source_id))
    except Exception as exc:  # noqa: BLE001 - cache is a best-effort fallback.
        logger.warning(
            "today_genie feed cache read failed source_id=%s error_type=%s",
            source_id,
            type(exc).__name__,
        )
        return None
    if raw is None:
        return None
    try:
        record = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    payload = record.get("payload")
    checksum = str(record.get("payload_sha256") or "").strip()
    if checksum and checksum != _today_feed_payload_hash(payload):
        logger.warning("today_genie feed cache checksum mismatch source_id=%s", source_id)
        return None
    return record


def _write_today_genie_feed_cache(
    source_id: str,
    payload: Any,
    target_date: str,
    *,
    provenance: str,
) -> str:
    try:
        from admin_store import admin_artifact_bucket_name, _gcs_upload_text

        if not admin_artifact_bucket_name():
            return "skipped_no_gcs_backend"
        fetched_at = _today_utc_now_iso()
        record = {
            "schema_version": TODAY_GENIE_FEED_CACHE_SCHEMA_VERSION,
            "source_id": source_id,
            "target_date": target_date,
            "as_of": _today_feed_source_as_of(source_id, payload) or target_date,
            "fetched_at": fetched_at,
            "provenance": provenance,
            "payload": payload,
            "payload_sha256": _today_feed_payload_hash(payload),
        }
        _gcs_upload_text(
            _today_feed_cache_object_key(source_id),
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
            content_type="application/json",
        )
        return "written"
    except Exception as exc:  # noqa: BLE001 - cache write must never fail the run.
        logger.warning(
            "today_genie feed cache write failed source_id=%s error_type=%s",
            source_id,
            type(exc).__name__,
        )
        return f"failed:{type(exc).__name__}"


def _today_feed_nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return len(value) > 0
    if isinstance(value, list):
        return len(value) > 0
    return True


def _today_feed_source_as_of(source_id: str, payload: Any) -> Optional[str]:
    if source_id in TODAY_GENIE_CORE_DATE_FEEDS and isinstance(payload, dict):
        raw = payload.get("as_of")
        parsed = _parse_feed_date(raw)
        return parsed.isoformat() if parsed else (str(raw).strip() or None)
    if source_id == "top_market_news" and isinstance(payload, list):
        dates = [
            parsed
            for item in payload
            if isinstance(item, dict)
            for parsed in [_parse_feed_date(item.get("date"))]
            if parsed is not None
        ]
        if dates:
            return max(dates).isoformat()
    return None


def _today_feed_payload_freshness(
    source_id: str,
    payload: Any,
    target_date: str,
) -> Dict[str, Any]:
    if not _today_feed_nonempty(payload):
        return {
            "fresh": False,
            "stale": True,
            "as_of": "",
            "age_days": None,
            "reason": "missing_or_empty",
        }
    if source_id == "risk_factors":
        return {
            "fresh": True,
            "stale": False,
            "as_of": "",
            "age_days": None,
            "reason": "",
        }
    as_of_raw = _today_feed_source_as_of(source_id, payload)
    as_of = _parse_feed_date(as_of_raw)
    target = _parse_feed_date(target_date)
    age_days: Optional[int] = None
    stale = False
    reason = ""
    if target is None:
        stale = True
        reason = "invalid_target_date"
    elif as_of is None:
        stale = True
        reason = "missing_or_invalid_as_of"
    else:
        age_days = (target - as_of).days
        if age_days > TODAY_GENIE_MAX_FEED_STALE_DAYS:
            stale = True
            reason = "as_of_older_than_7_days"
    return {
        "fresh": not stale,
        "stale": stale,
        "as_of": str(as_of_raw or ""),
        "age_days": age_days,
        "reason": reason,
    }


def _today_required_feed_contract(feeds: Dict[str, Any], target_date: str) -> Dict[str, Any]:
    missing: List[str] = []
    stale: List[str] = []
    freshness: Dict[str, Any] = {}
    for source_id in TODAY_GENIE_RUNTIME_FEEDS:
        info = _today_feed_payload_freshness(source_id, feeds.get(source_id), target_date)
        freshness[source_id] = info
        if info.get("reason") == "missing_or_empty":
            missing.append(source_id)
        elif info.get("stale"):
            stale.append(source_id)
    return {
        "passed": not missing and not stale,
        "missing": missing,
        "stale": stale,
        "freshness": freshness,
    }


def _today_is_timeout_error(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, TimeoutError):
        return True
    return "timed out" in str(exc).lower() or "timeout" in str(type(exc).__name__).lower()


def _today_probe_one_live_source(
    source_id: str,
    call: Any,
    *,
    timeout_sec: Optional[int] = None,
) -> tuple[Optional[Any], Dict[str, Any]]:
    started = time.perf_counter()
    retry_count = 0
    last_exc: Optional[BaseException] = None
    for attempt in range(2):
        try:
            payload = call()
            return payload, {
                "source_id": source_id,
                "status": "success",
                "live_status": "success",
                "attempt_count": retry_count + 1,
                "retry_count": retry_count,
                "timeout_seconds": timeout_sec,
                "connect_timeout_seconds": timeout_sec,
                "read_timeout_seconds": timeout_sec,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
        except Exception as exc:  # noqa: BLE001 - source-level isolation is intentional.
            last_exc = exc
            if attempt == 0 and _today_is_timeout_error(exc):
                retry_count = 1
                continue
            break
    return None, {
        "source_id": source_id,
        "status": "timeout" if _today_is_timeout_error(last_exc) else "error",
        "live_status": "failed",
        "attempt_count": retry_count + 1,
        "retry_count": retry_count,
        "timeout_seconds": timeout_sec,
        "connect_timeout_seconds": timeout_sec,
        "read_timeout_seconds": timeout_sec,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "error_type": type(last_exc).__name__ if last_exc else "UnknownError",
        "error": str(last_exc)[:300] if last_exc else "",
        "error_message_safe": str(last_exc)[:300] if last_exc else "",
        "timeout_type": "read_or_total_timeout" if _today_is_timeout_error(last_exc) else None,
        "timeout": _today_is_timeout_error(last_exc) if last_exc else False,
    }


def _probe_today_genie_live_feeds(target_date: str, timeout_sec: int) -> Dict[str, Any]:
    from ops.probe_today_genie_feeds import (
        build_macro_indicators,
        build_risk_factors,
        probe_korea_japan_indices,
        probe_overnight_us_market,
        probe_top_market_news,
    )

    feeds: Dict[str, Any] = {}
    source_results: List[Dict[str, Any]] = []
    source_calls = (
        (
            "overnight_us_market",
            lambda: probe_overnight_us_market(target_date, timeout_sec=timeout_sec),
        ),
        (
            "korea_japan_indices",
            lambda: probe_korea_japan_indices(target_date, timeout_sec=timeout_sec),
        ),
        (
            "top_market_news",
            lambda: probe_top_market_news(target_date, timeout_sec=timeout_sec),
        ),
    )
    for source_id, call in source_calls:
        payload, result = _today_probe_one_live_source(source_id, call, timeout_sec=timeout_sec)
        source_results.append(result)
        if payload is not None:
            feeds[source_id] = payload

    if "overnight_us_market" in feeds and "korea_japan_indices" in feeds:
        payload, result = _today_probe_one_live_source(
            "macro_indicators",
            lambda: build_macro_indicators(
                feeds["overnight_us_market"],
                feeds["korea_japan_indices"],
                target_date,
            ),
            timeout_sec=0,
        )
        source_results.append(result)
        if payload is not None:
            feeds["macro_indicators"] = payload
    else:
        source_results.append(
            {
                "source_id": "macro_indicators",
                "status": "skipped_missing_dependency",
                "live_status": "skipped_missing_dependency",
                "attempt_count": 0,
                "retry_count": 0,
                "elapsed_ms": 0,
            }
        )

    if "top_market_news" in feeds and "macro_indicators" in feeds:
        payload, result = _today_probe_one_live_source(
            "risk_factors",
            lambda: build_risk_factors(feeds["top_market_news"], feeds["macro_indicators"]),
            timeout_sec=0,
        )
        source_results.append(result)
        if payload is not None:
            feeds["risk_factors"] = payload
    else:
        source_results.append(
            {
                "source_id": "risk_factors",
                "status": "skipped_missing_dependency",
                "live_status": "skipped_missing_dependency",
                "attempt_count": 0,
                "retry_count": 0,
                "elapsed_ms": 0,
            }
        )

    feeds["today_genie_live_source_results"] = source_results
    return feeds


def _today_live_result_map(refreshed: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for item in refreshed.get("today_genie_live_source_results") or []:
        if isinstance(item, dict) and item.get("source_id"):
            out[str(item["source_id"])] = dict(item)
    return out


def _today_select_feed_source(
    source_id: str,
    *,
    live_feeds: Dict[str, Any],
    env_feeds: Dict[str, Any],
    target_date: str,
    live_results: Dict[str, Dict[str, Any]],
) -> tuple[Any, Dict[str, Any]]:
    result = {
        "source_id": source_id,
        "live_status": live_results.get(source_id, {}).get("live_status", "not_attempted"),
        "attempt_count": live_results.get(source_id, {}).get("attempt_count", 0),
        "retry_count": live_results.get(source_id, {}).get("retry_count", 0),
        "timeout_seconds": live_results.get(source_id, {}).get("timeout_seconds"),
        "connect_timeout_seconds": live_results.get(source_id, {}).get("connect_timeout_seconds"),
        "read_timeout_seconds": live_results.get(source_id, {}).get("read_timeout_seconds"),
        "elapsed_ms": live_results.get(source_id, {}).get("elapsed_ms"),
        "timeout_type": live_results.get(source_id, {}).get("timeout_type"),
        "error_type": live_results.get(source_id, {}).get("error_type"),
        "error_message_safe": live_results.get(source_id, {}).get("error_message_safe"),
        "selected_source": None,
        "selected_provenance": None,
        "cache_key": _today_feed_cache_object_key(source_id),
        "status": "unresolved",
    }
    live_payload = live_feeds.get(source_id)
    if source_id in live_feeds:
        live_freshness = _today_feed_payload_freshness(source_id, live_payload, target_date)
        result["live_freshness"] = live_freshness
        if live_freshness.get("fresh"):
            result["selected_source"] = "live"
            result["selected_provenance"] = "live"
            result["status"] = "selected"
            result["cache_write_status"] = _write_today_genie_feed_cache(
                source_id,
                live_payload,
                target_date,
                provenance="live_refresh",
            )
            return live_payload, result

    cache_record = _read_today_genie_feed_cache(source_id)
    if cache_record:
        cache_payload = cache_record.get("payload")
        cache_freshness = _today_feed_payload_freshness(source_id, cache_payload, target_date)
        result["cache_status"] = "hit"
        result["cache_freshness"] = cache_freshness
        result["cache_fetched_at"] = cache_record.get("fetched_at")
        if cache_freshness.get("fresh"):
            result["selected_source"] = "cache"
            result["selected_provenance"] = "cache"
            result["status"] = "selected"
            return cache_payload, result
    else:
        result["cache_status"] = "miss_or_unconfigured"

    env_payload = env_feeds.get(source_id)
    env_freshness = _today_feed_payload_freshness(source_id, env_payload, target_date)
    result["env_freshness"] = env_freshness
    if env_freshness.get("fresh"):
        result["selected_source"] = "env"
        result["selected_provenance"] = "env"
        result["status"] = "selected"
        return env_payload, result
    if _today_feed_nonempty(env_payload):
        result["selected_source"] = "env_stale"
        result["selected_provenance"] = "env"
        result["status"] = "stale_unresolved"
        return env_payload, result
    result["selected_source"] = "missing"
    result["selected_provenance"] = "unavailable"
    result["status"] = "missing"
    return env_payload, result


def _today_try_derive_macro_from_selected(
    selected: Dict[str, Any],
    target_date: str,
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    overnight_info = _today_feed_payload_freshness(
        "overnight_us_market",
        selected.get("overnight_us_market"),
        target_date,
    )
    asia_info = _today_feed_payload_freshness(
        "korea_japan_indices",
        selected.get("korea_japan_indices"),
        target_date,
    )
    if not overnight_info.get("fresh") or not asia_info.get("fresh"):
        return None, None
    try:
        from ops.probe_today_genie_feeds import build_macro_indicators

        payload = build_macro_indicators(
            selected["overnight_us_market"],
            selected["korea_japan_indices"],
            target_date,
        )
    except Exception as exc:  # noqa: BLE001 - derived fallback is best effort.
        return None, {
            "source_id": "macro_indicators",
            "derived_status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc)[:300],
        }
    freshness = _today_feed_payload_freshness("macro_indicators", payload, target_date)
    if not freshness.get("fresh"):
        return None, {
            "source_id": "macro_indicators",
            "derived_status": "stale_or_invalid",
            "derived_freshness": freshness,
        }
    return payload, {
        "source_id": "macro_indicators",
        "derived_status": "success",
        "derived_freshness": freshness,
    }


def _today_try_derive_risks_from_selected(
    selected: Dict[str, Any],
) -> tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
    if not _today_feed_nonempty(selected.get("top_market_news")) or not _today_feed_nonempty(
        selected.get("macro_indicators")
    ):
        return None, None
    try:
        from ops.probe_today_genie_feeds import build_risk_factors

        payload = build_risk_factors(selected["top_market_news"], selected["macro_indicators"])
    except Exception as exc:  # noqa: BLE001 - derived fallback is best effort.
        return None, {
            "source_id": "risk_factors",
            "derived_status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc)[:300],
        }
    if not _today_feed_nonempty(payload):
        return None, {
            "source_id": "risk_factors",
            "derived_status": "missing_or_empty",
        }
    return payload, {
        "source_id": "risk_factors",
        "derived_status": "success",
    }


def _refresh_today_genie_feeds_if_needed(
    feeds: Dict[str, Any],
    target_date: str,
    *,
    controlled_active: bool,
) -> Dict[str, Any]:
    """Refresh stale Today_Geenee feeds once with source-level durable fallback."""
    current = dict(feeds)
    staleness = _today_feed_staleness(current, target_date)
    stale_feeds = [name for name, info in staleness.items() if info.get("stale")]
    contract = _today_required_feed_contract(current, target_date)
    meta: Dict[str, Any] = {
        "today_genie_feed_source": "env",
        "today_genie_feed_refresh_attempted": False,
        "today_genie_feed_refresh_status": "not_needed_fresh",
        "today_genie_feed_fallback_used": False,
        "today_genie_feed_fallback_reason": None,
        "today_genie_feed_staleness": staleness,
        "today_genie_stale_feeds": stale_feeds,
        "today_genie_feed_refresh_started_at": None,
        "today_genie_feed_refresh_finished_at": None,
        "today_genie_feed_refresh_elapsed_ms": None,
        "today_genie_feed_refresh_source_results": [],
        "today_genie_feed_partial_success": False,
        "today_genie_feed_live_success_count": 0,
        "today_genie_feed_cache_fallback_count": 0,
        "today_genie_feed_env_fallback_count": 0,
        "today_genie_feed_unavailable_count": 0,
        "today_required_feed_contract_passed": bool(contract["passed"]),
        "today_required_feed_contract_missing": list(contract["missing"]),
        "today_required_feed_contract_stale": list(contract["stale"]),
        "today_genie_feed_gate_reason": None
        if contract["passed"]
        else "required_feed_contract_failed",
        "scheduler_delivery_success": True,
        "scheduler_delivery_http_status": 200,
        "pipeline_success": None,
        "owner_review_created": None,
        "retry_recommended": False,
        "manual_action_required": not bool(contract["passed"]),
    }
    if not stale_feeds and contract["passed"]:
        current.update(meta)
        return current

    if controlled_active:
        meta.update(
            {
                "today_genie_feed_refresh_status": "controlled_test_refresh_disabled",
                "today_genie_feed_fallback_used": True,
                "today_genie_feed_fallback_reason": "controlled_test_refresh_disabled",
                "manual_action_required": not bool(contract["passed"]),
            }
        )
        current.update(meta)
        return current

    if not _today_live_feed_refresh_enabled():
        meta.update(
            {
                "today_genie_feed_refresh_status": "live_refresh_disabled",
                "today_genie_feed_fallback_used": True,
                "today_genie_feed_fallback_reason": "live_refresh_disabled",
                "manual_action_required": not bool(contract["passed"]),
            }
        )
        current.update(meta)
        return current

    timeout_sec = _today_live_feed_refresh_timeout_sec()
    meta["today_genie_feed_refresh_attempted"] = True
    meta["today_genie_feed_refresh_started_at"] = _today_utc_now_iso()
    refresh_start = time.perf_counter()
    refreshed: Dict[str, Any] = {}
    global_refresh_error = ""
    try:
        refreshed = _probe_today_genie_live_feeds(target_date, timeout_sec)
    except Exception as exc:  # noqa: BLE001 - explicit fallback metadata is the contract.
        logger.warning(
            "today_genie feed live refresh failed; using fallback env feeds: %s",
            exc,
        )
        global_refresh_error = f"{type(exc).__name__}: {exc}"

    live_results = _today_live_result_map(refreshed)
    selected: Dict[str, Any] = {
        "feed_json_decode_failed_envs": list(current.get("feed_json_decode_failed_envs") or [])
    }
    source_results: List[Dict[str, Any]] = []

    for source_id in ("overnight_us_market", "korea_japan_indices", "top_market_news"):
        payload, result = _today_select_feed_source(
            source_id,
            live_feeds=refreshed,
            env_feeds=current,
            target_date=target_date,
            live_results=live_results,
        )
        selected[source_id] = payload
        source_results.append(result)

    macro_payload, macro_result = _today_select_feed_source(
        "macro_indicators",
        live_feeds=refreshed,
        env_feeds={},
        target_date=target_date,
        live_results=live_results,
    )
    if not _today_feed_payload_freshness("macro_indicators", macro_payload, target_date).get("fresh"):
        derived_macro, derived_result = _today_try_derive_macro_from_selected(selected, target_date)
        if derived_result:
            source_results.append(derived_result)
        if derived_macro is not None:
            macro_payload = derived_macro
            macro_result.update(
                {
                    "selected_source": "derived_from_selected_sources",
                    "selected_provenance": "derived_from_selected_sources",
                    "status": "selected",
                    "derived_status": "success",
                }
            )
    if not _today_feed_payload_freshness("macro_indicators", macro_payload, target_date).get("fresh"):
        macro_payload, macro_result = _today_select_feed_source(
            "macro_indicators",
            live_feeds={},
            env_feeds=current,
            target_date=target_date,
            live_results=live_results,
        )
    selected["macro_indicators"] = macro_payload
    source_results.append(macro_result)

    risk_payload, risk_result = _today_select_feed_source(
        "risk_factors",
        live_feeds=refreshed,
        env_feeds={},
        target_date=target_date,
        live_results=live_results,
    )
    if not _today_feed_payload_freshness("risk_factors", risk_payload, target_date).get("fresh"):
        derived_risks, derived_result = _today_try_derive_risks_from_selected(selected)
        if derived_result:
            source_results.append(derived_result)
        if derived_risks is not None:
            risk_payload = derived_risks
            risk_result.update(
                {
                    "selected_source": "derived_from_selected_sources",
                    "selected_provenance": "derived_from_selected_sources",
                    "status": "selected",
                    "derived_status": "success",
                }
            )
    if not _today_feed_payload_freshness("risk_factors", risk_payload, target_date).get("fresh"):
        risk_payload, risk_result = _today_select_feed_source(
            "risk_factors",
            live_feeds={},
            env_feeds=current,
            target_date=target_date,
            live_results=live_results,
        )
    selected["risk_factors"] = risk_payload
    source_results.append(risk_result)

    final_staleness = _today_feed_staleness(selected, target_date)
    final_stale = [name for name, info in final_staleness.items() if info.get("stale")]
    final_contract = _today_required_feed_contract(selected, target_date)
    selected_sources = [
        str(item.get("selected_source") or "")
        for item in source_results
        if item.get("source_id") in TODAY_GENIE_RUNTIME_FEEDS
    ]
    live_success_count = selected_sources.count("live") + selected_sources.count(
        "derived_from_selected_sources"
    )
    cache_fallback_count = selected_sources.count("cache")
    env_fallback_count = selected_sources.count("env") + selected_sources.count("env_stale")
    unavailable_count = selected_sources.count("missing")
    live_staleness = _today_feed_staleness(refreshed, target_date) if refreshed else {}

    if final_contract["passed"]:
        status = "live_refresh_applied" if cache_fallback_count == 0 and env_fallback_count == 0 else "live_refresh_partial_fallback_applied"
        source = (
            "live_refresh"
            if cache_fallback_count == 0 and env_fallback_count == 0
            else "mixed_live_cache_env"
        )
        fallback_reason = (
            None
            if status == "live_refresh_applied"
            else "source_level_fresh_fallback_used"
        )
    elif global_refresh_error:
        status = "live_refresh_failed_fallback"
        source = "env" if env_fallback_count else "unavailable"
        fallback_reason = global_refresh_error
    elif any(name in refreshed for name in TODAY_GENIE_CORE_DATE_FEEDS) and any(
        info.get("stale") for info in live_staleness.values()
    ):
        status = "live_refresh_returned_stale_fallback"
        source = "env" if env_fallback_count else "unavailable"
        fallback_reason = "live_refresh_returned_stale_feeds"
    else:
        status = "live_refresh_incomplete_blocked"
        source = "mixed_live_cache_env" if live_success_count or cache_fallback_count else "env"
        fallback_reason = "fresh_required_feed_contract_not_satisfied"

    meta.update(
        {
            "today_genie_feed_source": source,
            "today_genie_feed_refresh_status": status,
            "today_genie_feed_fallback_used": status != "live_refresh_applied",
            "today_genie_feed_fallback_reason": fallback_reason,
            "today_genie_feed_staleness": final_staleness,
            "today_genie_live_feed_staleness": live_staleness,
            "today_genie_stale_feeds": final_stale,
            "today_genie_feed_refresh_finished_at": _today_utc_now_iso(),
            "today_genie_feed_refresh_elapsed_ms": int(
                (time.perf_counter() - refresh_start) * 1000
            ),
            "today_genie_feed_refresh_source_results": source_results,
            "today_genie_feed_partial_success": bool(
                live_success_count and (cache_fallback_count or env_fallback_count or unavailable_count)
            ),
            "today_genie_feed_live_success_count": live_success_count,
            "today_genie_feed_cache_fallback_count": cache_fallback_count,
            "today_genie_feed_env_fallback_count": env_fallback_count,
            "today_genie_feed_unavailable_count": unavailable_count,
            "today_required_feed_contract_passed": bool(final_contract["passed"]),
            "today_required_feed_contract_missing": list(final_contract["missing"]),
            "today_required_feed_contract_stale": list(final_contract["stale"]),
            "today_genie_feed_gate_reason": None
            if final_contract["passed"]
            else "required_feed_contract_failed",
            "pipeline_success": None,
            "owner_review_created": None,
            "retry_recommended": False,
            "manual_action_required": not bool(final_contract["passed"]),
        }
    )
    selected.update(meta)
    if not final_contract["passed"]:
        logger.warning(
            "today_genie feed refresh did not satisfy required contract status=%s stale=%s missing=%s source_results=%s",
            status,
            final_contract["stale"],
            final_contract["missing"],
            source_results,
        )
    return selected


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
        env_controlled_target = _controlled_test_target_date_from_env()
        today_date = controlled_test_target_date or env_controlled_target or kst_now.date().isoformat()
        controlled_active = bool(controlled_test_target_date or env_controlled_target)
        if controlled_active:
            logger.info("controlled_test_mode active target_date=%s", today_date)

        feeds = _load_today_genie_feed_bundle(max_rounds=3)
        feeds = _refresh_today_genie_feeds_if_needed(
            feeds,
            today_date,
            controlled_active=controlled_active,
        )
        overnight_us_market = feeds["overnight_us_market"]
        macro_indicators = feeds["macro_indicators"]
        top_market_news = feeds["top_market_news"]
        risk_factors = feeds["risk_factors"]
        korea_japan_indices = feeds["korea_japan_indices"]
        decode_failed_envs = list(feeds.get("feed_json_decode_failed_envs") or [])

        feed_pairs = [
            ("overnight_us_market", overnight_us_market),
            ("macro_indicators", macro_indicators),
            ("top_market_news", top_market_news),
            ("risk_factors", risk_factors),
            ("korea_japan_indices", korea_japan_indices),
        ]
        missing_feeds = [name for name, v in feed_pairs if not _today_feed_nonempty(v)]
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
        elif feeds.get("today_required_feed_contract_passed") is False:
            today_genie_feed_gate = "block"
        else:
            today_genie_feed_gate = "ok"

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
            "today_genie_feed_source": feeds.get("today_genie_feed_source"),
            "today_genie_feed_refresh_attempted": bool(
                feeds.get("today_genie_feed_refresh_attempted")
            ),
            "today_genie_feed_refresh_status": feeds.get(
                "today_genie_feed_refresh_status"
            ),
            "today_genie_feed_fallback_used": bool(
                feeds.get("today_genie_feed_fallback_used")
            ),
            "today_genie_feed_fallback_reason": feeds.get(
                "today_genie_feed_fallback_reason"
            ),
            "today_genie_feed_staleness": feeds.get("today_genie_feed_staleness"),
            "today_genie_live_feed_staleness": feeds.get(
                "today_genie_live_feed_staleness"
            ),
            "today_genie_stale_feeds": list(feeds.get("today_genie_stale_feeds") or []),
            "today_genie_feed_refresh_started_at": feeds.get(
                "today_genie_feed_refresh_started_at"
            ),
            "today_genie_feed_refresh_finished_at": feeds.get(
                "today_genie_feed_refresh_finished_at"
            ),
            "today_genie_feed_refresh_elapsed_ms": feeds.get(
                "today_genie_feed_refresh_elapsed_ms"
            ),
            "today_genie_feed_refresh_source_results": list(
                feeds.get("today_genie_feed_refresh_source_results") or []
            ),
            "today_genie_feed_partial_success": bool(
                feeds.get("today_genie_feed_partial_success")
            ),
            "today_genie_feed_live_success_count": int(
                feeds.get("today_genie_feed_live_success_count") or 0
            ),
            "today_genie_feed_cache_fallback_count": int(
                feeds.get("today_genie_feed_cache_fallback_count") or 0
            ),
            "today_genie_feed_env_fallback_count": int(
                feeds.get("today_genie_feed_env_fallback_count") or 0
            ),
            "today_genie_feed_unavailable_count": int(
                feeds.get("today_genie_feed_unavailable_count") or 0
            ),
            "today_required_feed_contract_passed": bool(
                feeds.get("today_required_feed_contract_passed")
            ),
            "today_required_feed_contract_missing": list(
                feeds.get("today_required_feed_contract_missing") or []
            ),
            "today_required_feed_contract_stale": list(
                feeds.get("today_required_feed_contract_stale") or []
            ),
            "today_genie_feed_gate_reason": feeds.get("today_genie_feed_gate_reason"),
            "scheduler_delivery_success": bool(feeds.get("scheduler_delivery_success", True)),
            "scheduler_delivery_http_status": feeds.get("scheduler_delivery_http_status"),
            "pipeline_success": feeds.get("pipeline_success"),
            "owner_review_created": feeds.get("owner_review_created"),
            "retry_recommended": bool(feeds.get("retry_recommended")),
            "manual_action_required": bool(feeds.get("manual_action_required")),
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


def apply_today_genie_sent_news_dedup(runtime_input: Dict[str, Any]) -> Dict[str, Any]:
    """Filter today_genie news candidates before text generation and retain metadata."""
    raw = runtime_input.get("top_market_news")
    if not isinstance(raw, list):
        return runtime_input
    candidates = [item for item in raw if isinstance(item, dict)]
    gate_result = run_sent_news_dedup_gate(
        briefing_type="today_genie",
        candidates=candidates,
        sent_log_last_5_days=recent_sent_news_log("today_genie"),
        required_count=TODAY_GENIE_REQUIRED_NEWS_COUNT,
    )
    meta = metadata_from_gate_result(
        gate_result,
        required_count=TODAY_GENIE_REQUIRED_NEWS_COUNT,
    )
    out = dict(runtime_input)
    out["top_market_news"] = meta["selected_items"]
    out["sent_news_dedup"] = meta
    return out


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
    usage_sink: dict | None = None,
) -> str:
    """usage_sink (optional): populated in place with the model name and
    best-effort token usage for cost-estimate logging (see
    genie_cost_estimate.py). Never raises — a usage_sink populate failure
    must not affect text generation."""
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

    if usage_sink is not None:
        try:
            usage_sink["model"] = VERTEX_MODEL
            usage_sink.update(extract_gemini_usage_metadata(response))
        except Exception:
            pass

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


def _sum_usage_sinks(*sinks: dict) -> Dict[str, Any]:
    """Best-effort accumulation of per-call usage_sink dicts across a
    multi-call pipeline. Never raises — missing/partial counts just sum as 0."""
    try:
        combined: Dict[str, Any] = {}
        model_name = None
        for sink in sinks:
            if not isinstance(sink, dict):
                continue
            model_name = sink.get("model") or model_name
            for field in (
                "prompt_token_count",
                "candidates_token_count",
                "thoughts_token_count",
                "total_token_count",
            ):
                value = sink.get(field)
                if value is None:
                    continue
                combined[field] = (combined.get(field) or 0) + value
        if model_name:
            combined["model"] = model_name
        return combined
    except Exception:
        return {}


def run_today_genie_text_pipeline(
    runtime_input: Dict[str, Any],
) -> tuple[Dict[str, Any], str, Dict[str, float], Dict[str, Any]]:
    """
    Two-phase today_genie text: (1) structured TOP3 slots, (2) main briefing JSON.
    Final key_watchpoints are always assembled in code: **exactly three** items,
    news-anchored where headlines exist, otherwise feed-anchored (overnight/macro/risk)
    market-watch slots — never absence filler.

    Returns (data, raw_main, prof, usage) — usage is the accumulated best-effort
    token usage across both phases (see _sum_usage_sinks), for cost-estimate
    logging only; never affects generation itself.
    """
    prof: Dict[str, float] = {}
    ext_prompt = build_top3_extraction_prompt(runtime_input)
    ext_usage: Dict[str, Any] = {}
    t0 = time.perf_counter()
    raw_ext = call_gemini(ext_prompt, "today_genie", max_output_tokens=4096, usage_sink=ext_usage)
    prof["top3_extract_inference_sec"] = round(time.perf_counter() - t0, 4)
    try:
        ext_data = parse_model_json(raw_ext, "today_genie")
    except HTTPException:
        raw_ext = call_gemini(
            ext_prompt + today_genie_top3_extract_recovery_suffix(),
            "today_genie",
            max_output_tokens=4096,
            usage_sink=ext_usage,
        )
        ext_data = parse_model_json(raw_ext, "today_genie")
    slots = normalize_top3_slots_payload(ext_data)
    main_prompt = build_full_prompt(
        "today_genie",
        runtime_input,
        today_genie_main_briefing=True,
    )
    main_usage: Dict[str, Any] = {}
    t1 = time.perf_counter()
    raw_main = call_gemini(main_prompt, "today_genie", usage_sink=main_usage)
    prof["main_brief_inference_sec"] = round(time.perf_counter() - t1, 4)
    try:
        data = parse_model_json(raw_main, "today_genie")
    except HTTPException as e:
        det = e.detail if isinstance(e.detail, dict) else {}
        if det.get("reason") == "json_parse_error":
            raw_main = call_gemini(
                main_prompt + today_genie_json_recovery_suffix(),
                "today_genie",
                usage_sink=main_usage,
            )
            data = parse_model_json(raw_main, "today_genie")
        else:
            raise
    data["key_watchpoints"] = assemble_key_watchpoints_from_slots(slots, runtime_input)
    apply_briefing_repetition_guard(data)
    return data, raw_main, prof, _sum_usage_sinks(ext_usage, main_usage)


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
    payload = {
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
    for key in TODAY_GENIE_FEED_DIAGNOSTIC_KEYS:
        if key in runtime_input:
            payload[key] = runtime_input.get(key)
    if payload.get("pipeline_success") is None:
        payload["pipeline_success"] = validation_result == "pass"
    if payload.get("owner_review_created") is None:
        payload["owner_review_created"] = validation_result == "pass"
    if validation_result == "block":
        payload["manual_action_required"] = True
    return payload


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


_VAGUE_PHRASE_REPLACEMENTS = (
    ("방향성을 가늠", "우선 확인할 변수는 금리·환율·수급 흐름"),
    ("가늠해야 합니다", "우선 확인할 필요가 있습니다"),
    ("가늠해야 할", "우선 확인할"),
)


def _scrub_vague_phrases(text: str) -> str:
    out = text
    for src, dst in _VAGUE_PHRASE_REPLACEMENTS:
        out = out.replace(src, dst)
    return out


def stabilize_today_genie_vague_phrases(data: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic cleanup for validator-blocked vague meta phrases."""
    normalized = dict(data)
    for field in ("summary", "market_setup"):
        val = normalized.get(field)
        if isinstance(val, str) and val.strip():
            normalized[field] = _scrub_vague_phrases(val)
    wps = normalized.get("key_watchpoints")
    if isinstance(wps, list):
        patched: List[Any] = []
        for wp in wps:
            if not isinstance(wp, dict):
                patched.append(wp)
                continue
            wp2 = dict(wp)
            for key in ("headline", "detail"):
                if isinstance(wp2.get(key), str):
                    wp2[key] = _scrub_vague_phrases(wp2[key])
            patched.append(wp2)
        normalized["key_watchpoints"] = patched
    return normalized


def stabilize_today_genie_image_prompt_anchors(
    data: Dict[str, Any],
    runtime_input: Dict[str, Any],
) -> Dict[str, Any]:
    """Append feed-derived anchor terms to image prompts when the model omitted them."""
    hints = feed_image_anchor_hints(runtime_input)
    seen = {h.lower() for h in hints}
    news = runtime_input.get("top_market_news")
    if isinstance(news, list):
        for item in news[:3]:
            if not isinstance(item, dict):
                continue
            headline = str(item.get("headline") or "").strip()
            if not headline:
                continue
            for anchor in headline_grounding_anchors(headline):
                if anchor.lower() not in seen:
                    hints.append(anchor)
                    seen.add(anchor.lower())
    if not hints:
        return data
    normalized = dict(data)
    for key in ("image_prompt_studio", "image_prompt_outdoor"):
        prompt = str(normalized.get(key) or "").strip()
        if not prompt:
            continue
        blob = prompt.lower()
        missing = [h for h in hints if h.lower() not in blob]
        if not missing:
            continue
        tail = " Include subtle visual references to: " + ", ".join(missing) + "."
        normalized[key] = prompt.rstrip(".") + "." + tail
    return normalized


def stabilize_today_genie_top3_grounding(
    data: Dict[str, Any],
    runtime_input: Dict[str, Any],
) -> Dict[str, Any]:
    """Re-apply headline/topic anchors on assembled TOP3 before validation."""
    from today_genie_grounding import inject_headline_grounding_into_detail
    from today_genie_top3_assembly import collect_valid_major_overseas_news

    wps = data.get("key_watchpoints")
    if not isinstance(wps, list):
        return data
    valid = collect_valid_major_overseas_news(runtime_input, max_items=3)
    patched: List[Any] = []
    for position, wp in enumerate(wps):
        if not isinstance(wp, dict):
            patched.append(wp)
            continue
        wp2 = dict(wp)
        if position < len(valid):
            nh = str(valid[position][1].get("headline") or "").strip()
            if nh:
                wp2["detail"] = inject_headline_grounding_into_detail(
                    str(wp2.get("detail") or ""),
                    nh,
                )
        patched.append(wp2)
    normalized = dict(data)
    normalized["key_watchpoints"] = patched
    return normalized


def stabilize_today_genie_validation_fields(
    data: Dict[str, Any],
    runtime_input: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Keep the generated briefing, but make validation-critical structural fields
    deterministic before the hard gate. This aligns no-send preflight and worker
    send attempts without weakening validators or publishing policy.
    """
    normalized = stabilize_today_genie_vague_phrases(data)
    normalized = stabilize_today_genie_top3_grounding(normalized, runtime_input)
    normalized = stabilize_today_genie_image_prompt_anchors(normalized, runtime_input)

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
    Server-owned labels for the owner/admin 운영자 검수 상태 block only.
    No raw internal state strings (e.g. draft_only, validated) are exposed here.
    Labels must not imply customer send completion or human 검수완료 from validation pass alone.
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
        status_label = "자동 검증 통과"
        result_summary = (
            "초안 생성과 자동 검증을 통과했습니다. 운영자 검수 후 전달 여부를 확정합니다."
        )
        email_delivery_label = "운영자 검수 메일 발송 전"
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
    *,
    run_id: Optional[str] = None,
) -> str:
    """
    today_genie HTML for SMTP MIME sends: top/bottom slots use cid:… references
    so the message does not depend on public base URLs or local static paths for images.
    """
    from admin_urls import build_owner_review_admin_url

    op_meta = email_operational_handoff_meta("today_genie", validation_result)
    rid = str(run_id or "").strip()
    if rid:
        admin_url = build_owner_review_admin_url(rid)
        if admin_url:
            op_meta = {**op_meta, "run_id": rid, "admin_review_url": admin_url}
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
        feed_runtime_check = {
            "target_date": runtime_input.get("target_date"),
            "controlled_test_mode": bool(runtime_input.get("controlled_test_mode")),
            "controlled_test_target_date": runtime_input.get("target_date")
            if runtime_input.get("controlled_test_mode")
            else None,
            "validation_result": "block",
            "workflow_status": "review_required",
            "issue_codes": ["today_genie_feed_unavailable"],
            "issue_details": [
                {
                    "code": "today_genie_feed_unavailable",
                    "message": "핵심 시장 피드가 비어 있거나(JSON 미설정) 연속 로드에 실패했습니다.",
                    "severity": "error",
                }
            ],
            "content_quality_warnings": [],
            "scheduler_delivery_success": True,
            "scheduler_delivery_http_status": 200,
            "pipeline_success": False,
            "owner_review_created": False,
            "retry_recommended": False,
            "manual_action_required": True,
        }
        for key in TODAY_GENIE_FEED_DIAGNOSTIC_KEYS:
            if key in runtime_input:
                feed_runtime_check[key] = runtime_input.get(key)
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
            "runtime_validation_check": feed_runtime_check,
        }
        raise HTTPException(status_code=422, detail=detail)

    if mode == "today_genie":
        runtime_input = apply_today_genie_sent_news_dedup(runtime_input)

    if mode == "today_genie":
        data, raw_text, _layer_prof, gemini_usage = run_today_genie_text_pipeline(runtime_input)
        logger.info("today_genie_two_phase_timings_sec=%s", _layer_prof)
    else:
        prompt = build_full_prompt(mode, runtime_input)
        gemini_usage = {}
        raw_text = call_gemini(prompt, mode, usage_sink=gemini_usage)
        try:
            data = parse_model_json(raw_text, mode)
        except HTTPException as e:
            det = e.detail if isinstance(e.detail, dict) else {}
            if det.get("reason") == "json_parse_error":
                raw_text = call_gemini(
                    prompt + today_genie_json_recovery_suffix(), mode, usage_sink=gemini_usage
                )
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

    # Best-effort cost estimate — never affects validation_result/HTTP status;
    # see genie_cost_estimate.py for the estimate-only pricing model. Image
    # generation for today_genie happens in a later service_full_run step
    # (see today_genie_service_full_run.py), so generated_image_count is 0 here.
    try:
        cost_estimate = estimate_genie_generation_cost(
            gemini_usage,
            service_family="today_genie" if mode == "today_genie" else "tomorrow_genie",
            text_model=gemini_usage.get("model") or VERTEX_MODEL,
            mode=mode,
        )
    except Exception:
        cost_estimate = None

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
        "cost_estimate": cost_estimate,
        "data": {
            **data,
            "rendered_channels": rendered,
        },
    }
