"""GENIE Seoul weather provider client — controlled manual canary only (one request per run)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from genie_weather_runtime_adapter import (
    build_genie_weather_consumer_context,
    normalize_genie_runtime_weather_payload,
    validate_genie_runtime_weather_payload,
)
from keysuri_visual_context import validate_keysuri_weather_context

SEOUL_QUERY = "Seoul,KR"
LOCATION_LABEL = "Seoul"
CANARY_TIMEOUT_SECONDS = 8

PROVIDER_REGISTRY: Dict[str, Dict[str, Any]] = {
    "openweather": {
        "api_key_envs": ("WEATHER_API_KEY", "OPENWEATHER_API_KEY"),
        "base_url": "https://api.openweathermap.org/data/2.5/weather",
        "city_query": SEOUL_QUERY,
    },
    "weatherapi": {
        "api_key_envs": ("WEATHERAPI_API_KEY",),
        "base_url": "https://api.weatherapi.com/v1/current.json",
        "city_query": "Seoul",
    },
}

SUPPORTED_PROVIDERS = frozenset(PROVIDER_REGISTRY.keys())
CONSUMER_IDS = ("today_geenee", "keysuri_global_tech", "keysuri_korea_tech")

FORBIDDEN_REPORT_TERMS = (
    "테크 앵커",
    "뉴스 앵커",
    "아나운서",
    "Tomorrow_Geenee",
    "tomorrow_genie",
)

RUNTIME_SIDE_EFFECTS_TEMPLATE: Dict[str, bool] = {
    "called_weather_api": False,
    "called_gemini": False,
    "called_image_api": False,
    "fetched_live_news": False,
    "sent_email": False,
    "published_naver": False,
    "changed_scheduler": False,
}

# Injectable for tests (must perform at most one HTTP call when set).
_urlopen_fn: Optional[Callable[..., Any]] = None


def _issue(code: str, message: str, path: str) -> Dict[str, str]:
    return {"code": code, "message": message, "path": path}


def _kst_now_parts() -> tuple[str, str]:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    return now.strftime("%Y-%m-%d"), now.strftime("%H:%M")


def mask_secret(value: str | None) -> str:
    """Return a safe masked representation; never return the full secret."""
    if value is None or not str(value).strip():
        return "(missing)"
    text = str(value).strip()
    if len(text) <= 4:
        return "****"
    return f"****{text[-4:]}"


def _resolve_api_key(env_names: tuple[str, ...]) -> tuple[Optional[str], Optional[str]]:
    for name in env_names:
        val = os.getenv(name)
        if val and str(val).strip():
            return str(val).strip(), name
    return None, env_names[0] if env_names else None


def get_weather_provider_config_from_env() -> dict:
    """Build provider config from environment without exposing full secrets."""
    issues: List[Dict[str, str]] = []
    provider = (os.getenv("GENIE_WEATHER_PROVIDER") or "").strip().lower()

    if not provider:
        issues.append(
            _issue(
                "provider_env_missing",
                "GENIE_WEATHER_PROVIDER is required for weather canary",
                "GENIE_WEATHER_PROVIDER",
            )
        )
        return {
            "provider": "",
            "provider_mode": "runtime_weather_api",
            "api_key_env": "",
            "api_key_present": False,
            "api_key_masked": mask_secret(None),
            "base_url": "",
            "can_call": False,
            "issues": issues,
        }

    if provider not in SUPPORTED_PROVIDERS:
        issues.append(
            _issue(
                "provider_unsupported",
                f"Unsupported GENIE_WEATHER_PROVIDER: {provider!r}",
                "GENIE_WEATHER_PROVIDER",
            )
        )
        return {
            "provider": provider,
            "provider_mode": "runtime_weather_api",
            "api_key_env": "",
            "api_key_present": False,
            "api_key_masked": mask_secret(None),
            "base_url": "",
            "can_call": False,
            "issues": issues,
        }

    reg = PROVIDER_REGISTRY[provider]
    api_key, api_key_env = _resolve_api_key(reg["api_key_envs"])
    base_url = str(reg["base_url"])

    if not api_key:
        issues.append(
            _issue(
                "api_key_missing",
                f"API key not set for provider {provider!r} (checked: {', '.join(reg['api_key_envs'])})",
                api_key_env or "api_key",
            )
        )

    return {
        "provider": provider,
        "provider_mode": "runtime_weather_api",
        "api_key_env": api_key_env or reg["api_key_envs"][0],
        "api_key_present": bool(api_key),
        "api_key_masked": mask_secret(api_key),
        "base_url": base_url,
        "can_call": bool(api_key),
        "issues": issues,
        "_api_key": api_key,
        "_city_query": reg.get("city_query", SEOUL_QUERY),
    }


def _http_get_json(url: str, timeout: int = CANARY_TIMEOUT_SECONDS) -> Dict[str, Any]:
    opener = _urlopen_fn or urllib.request.urlopen
    try:
        with opener(url, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or getattr(resp, "code", 200)
            raw = resp.read()
            if int(status) != 200:
                return {
                    "success": False,
                    "status_code": int(status),
                    "error": f"HTTP {status}",
                    "data": None,
                }
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                return {
                    "success": False,
                    "status_code": int(status),
                    "error": "Response is not a JSON object",
                    "data": None,
                }
            return {"success": True, "status_code": int(status), "error": None, "data": data}
    except urllib.error.HTTPError as exc:
        return {
            "success": False,
            "status_code": exc.code,
            "error": f"HTTP {exc.code}: {exc.reason}",
            "data": None,
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"success": False, "status_code": None, "error": str(exc), "data": None}


def _build_openweather_url(config: dict) -> str:
    api_key = config.get("_api_key") or ""
    query = urllib.parse.urlencode(
        {
            "q": config.get("_city_query", SEOUL_QUERY),
            "units": "metric",
            "appid": api_key,
        }
    )
    return f"{config['base_url']}?{query}"


def _build_weatherapi_url(config: dict) -> str:
    api_key = config.get("_api_key") or ""
    query = urllib.parse.urlencode(
        {
            "key": api_key,
            "q": config.get("_city_query", "Seoul"),
            "aqi": "no",
        }
    )
    return f"{config['base_url']}?{query}"


def fetch_seoul_weather_once(config: dict) -> dict:
    """Perform exactly one Seoul weather HTTP request when config.can_call is true."""
    if not config.get("can_call"):
        return {
            "success": False,
            "status_code": None,
            "error": "Provider not configured for API call",
            "data": None,
        }

    provider = config.get("provider")
    if provider == "openweather":
        url = _build_openweather_url(config)
    elif provider == "weatherapi":
        url = _build_weatherapi_url(config)
    else:
        return {
            "success": False,
            "status_code": None,
            "error": f"Unsupported provider: {provider!r}",
            "data": None,
        }

    return _http_get_json(url)


def convert_provider_response_to_runtime_weather_payload(
    provider: str,
    provider_response: dict,
) -> dict:
    """Map provider JSON to GENIE runtime weather payload (no raw_provider_payload field)."""
    weather_date, observed_kst = _kst_now_parts()
    source_label = f"GENIE weather canary ({provider})"

    if provider == "openweather":
        weather_list = provider_response.get("weather") or []
        w0 = weather_list[0] if weather_list and isinstance(weather_list[0], dict) else {}
        main = provider_response.get("main") if isinstance(provider_response.get("main"), dict) else {}
        wind = provider_response.get("wind") if isinstance(provider_response.get("wind"), dict) else {}
        condition_code = str(w0.get("main") or "unknown").strip().lower()
        condition_label = str(w0.get("description") or condition_code).strip()
        payload: Dict[str, Any] = {
            "provider": provider,
            "provider_mode": "runtime_weather_api",
            "location": {
                "city": LOCATION_LABEL,
                "country": "KR",
                "timezone": "Asia/Seoul",
            },
            "weather_date": weather_date,
            "observed_or_forecast_time_kst": observed_kst,
            "condition_code": condition_code,
            "condition_label": condition_label,
            "temperature_c": main.get("temp"),
            "feels_like_c": main.get("feels_like"),
            "humidity_percent": main.get("humidity"),
            "wind_speed_mps": wind.get("speed"),
            "precipitation_type": "none",
            "source_label": source_label,
            "notes": "Converted from OpenWeather current weather canary response (sanitized).",
        }
        return payload

    if provider == "weatherapi":
        current = provider_response.get("current")
        if not isinstance(current, dict):
            raise ValueError("WeatherAPI response missing current object")
        cond = current.get("condition") if isinstance(current.get("condition"), dict) else {}
        condition_label = str(cond.get("text") or "unknown").strip()
        condition_code = str(cond.get("code") or condition_label).strip().lower()
        precip = current.get("precip_mm")
        precip_type = "rain" if isinstance(precip, (int, float)) and precip > 0 else "none"
        wind_kph = current.get("wind_kph")
        wind_mps = None
        if isinstance(wind_kph, (int, float)):
            wind_mps = round(float(wind_kph) / 3.6, 2)
        payload = {
            "provider": provider,
            "provider_mode": "runtime_weather_api",
            "location": {
                "city": LOCATION_LABEL,
                "country": "KR",
                "timezone": "Asia/Seoul",
            },
            "weather_date": weather_date,
            "observed_or_forecast_time_kst": observed_kst,
            "condition_code": condition_code,
            "condition_label": condition_label,
            "temperature_c": current.get("temp_c"),
            "feels_like_c": current.get("feelslike_c"),
            "humidity_percent": current.get("humidity"),
            "wind_speed_mps": wind_mps,
            "precipitation_type": precip_type,
            "source_label": source_label,
            "notes": "Converted from WeatherAPI current weather canary response (sanitized).",
        }
        return payload

    raise ValueError(f"Unsupported provider for conversion: {provider!r}")


def _blocked_result(
    *,
    canary_status: str,
    config: dict,
    request_count: int = 0,
    issues: Optional[List[Dict[str, str]]] = None,
    called_weather_api: bool = False,
) -> dict:
    side = dict(RUNTIME_SIDE_EFFECTS_TEMPLATE)
    side["called_weather_api"] = called_weather_api
    return {
        "canary_status": canary_status,
        "provider": config.get("provider") or "",
        "request_count": request_count,
        "location": LOCATION_LABEL,
        "runtime_weather_payload": None,
        "normalized_weather_context": None,
        "consumer_contexts": {cid: None for cid in CONSUMER_IDS},
        "issues": issues or list(config.get("issues") or []),
        "secrets_exposed": False,
        "raw_provider_payload_saved": False,
        "provider_config_summary": _public_config_summary(config),
        "runtime_side_effects": side,
    }


def _public_config_summary(config: dict) -> dict:
    return {
        "provider": config.get("provider"),
        "provider_mode": config.get("provider_mode"),
        "api_key_env": config.get("api_key_env"),
        "api_key_present": config.get("api_key_present"),
        "api_key_masked": config.get("api_key_masked"),
        "base_url": config.get("base_url"),
        "can_call": config.get("can_call"),
    }


def sanitize_canary_report_for_output(report: dict) -> dict:
    """Return a JSON-safe report without secrets or raw provider payloads."""
    out = json.loads(json.dumps(report, default=str))
    out.pop("_api_key", None)
    if isinstance(out.get("provider_config_summary"), dict):
        out["provider_config_summary"].pop("_api_key", None)
    for key in list(out.keys()):
        if key in ("raw_provider_payload", "_api_key") or key.endswith("_api_key"):
            out.pop(key, None)
    text = json.dumps(out, ensure_ascii=False)
    for term in FORBIDDEN_REPORT_TERMS:
        if term in text:
            raise ValueError(f"Canary report contains forbidden term: {term!r}")
    if "****" not in text and out.get("provider_config_summary", {}).get("api_key_present"):
        pass
    return out


def run_seoul_weather_controlled_canary() -> dict:
    """Run a single-request Seoul weather canary when env and provider are configured."""
    config = get_weather_provider_config_from_env()
    provider = config.get("provider") or ""

    if not provider:
        return _blocked_result(
            canary_status="blocked_missing_weather_env",
            config=config,
        )

    if provider not in SUPPORTED_PROVIDERS:
        return _blocked_result(
            canary_status="blocked_unsupported_provider",
            config=config,
        )

    if not config.get("can_call"):
        status = (
            "blocked_missing_weather_env"
            if any(i.get("code") == "api_key_missing" for i in config.get("issues") or [])
            else "blocked_missing_weather_env"
        )
        return _blocked_result(canary_status=status, config=config)

    fetch_result = fetch_seoul_weather_once(config)
    side = dict(RUNTIME_SIDE_EFFECTS_TEMPLATE)
    side["called_weather_api"] = True

    if not fetch_result.get("success"):
        return {
            "canary_status": "api_error",
            "provider": provider,
            "request_count": 1,
            "location": LOCATION_LABEL,
            "runtime_weather_payload": None,
            "normalized_weather_context": None,
            "consumer_contexts": {cid: None for cid in CONSUMER_IDS},
            "issues": [
                _issue(
                    "weather_api_error",
                    str(fetch_result.get("error") or "Weather API request failed"),
                    "fetch_seoul_weather_once",
                )
            ],
            "secrets_exposed": False,
            "raw_provider_payload_saved": False,
            "provider_config_summary": _public_config_summary(config),
            "runtime_side_effects": side,
        }

    provider_data = fetch_result.get("data") or {}
    issues: List[Dict[str, str]] = []

    try:
        runtime_payload = convert_provider_response_to_runtime_weather_payload(
            provider, provider_data
        )
    except ValueError as exc:
        return {
            "canary_status": "normalization_failed",
            "provider": provider,
            "request_count": 1,
            "location": LOCATION_LABEL,
            "runtime_weather_payload": None,
            "normalized_weather_context": None,
            "consumer_contexts": {cid: None for cid in CONSUMER_IDS},
            "issues": [_issue("conversion_failed", str(exc), "convert_provider_response")],
            "secrets_exposed": False,
            "raw_provider_payload_saved": False,
            "provider_config_summary": _public_config_summary(config),
            "runtime_side_effects": side,
        }

    val_issues = validate_genie_runtime_weather_payload(runtime_payload)
    if val_issues:
        return {
            "canary_status": "normalization_failed",
            "provider": provider,
            "request_count": 1,
            "location": LOCATION_LABEL,
            "runtime_weather_payload": runtime_payload,
            "normalized_weather_context": None,
            "consumer_contexts": {cid: None for cid in CONSUMER_IDS},
            "issues": val_issues,
            "secrets_exposed": False,
            "raw_provider_payload_saved": False,
            "provider_config_summary": _public_config_summary(config),
            "runtime_side_effects": side,
        }

    try:
        normalized = normalize_genie_runtime_weather_payload(runtime_payload)
    except ValueError as exc:
        return {
            "canary_status": "normalization_failed",
            "provider": provider,
            "request_count": 1,
            "location": LOCATION_LABEL,
            "runtime_weather_payload": runtime_payload,
            "normalized_weather_context": None,
            "consumer_contexts": {cid: None for cid in CONSUMER_IDS},
            "issues": [_issue("normalize_failed", str(exc), "normalize")],
            "secrets_exposed": False,
            "raw_provider_payload_saved": False,
            "provider_config_summary": _public_config_summary(config),
            "runtime_side_effects": side,
        }

    w_ctx_issues = validate_keysuri_weather_context(normalized)
    if w_ctx_issues:
        return {
            "canary_status": "normalization_failed",
            "provider": provider,
            "request_count": 1,
            "location": LOCATION_LABEL,
            "runtime_weather_payload": runtime_payload,
            "normalized_weather_context": normalized,
            "consumer_contexts": {cid: None for cid in CONSUMER_IDS},
            "issues": w_ctx_issues,
            "secrets_exposed": False,
            "raw_provider_payload_saved": False,
            "provider_config_summary": _public_config_summary(config),
            "runtime_side_effects": side,
        }

    consumer_contexts: Dict[str, Optional[dict]] = {}
    for cid in CONSUMER_IDS:
        try:
            consumer_contexts[cid] = build_genie_weather_consumer_context(cid, normalized)
        except ValueError as exc:
            issues.append(_issue("consumer_context_failed", str(exc), cid))
            consumer_contexts[cid] = None

    status = "pass" if not issues else "normalization_failed"
    return {
        "canary_status": status,
        "provider": provider,
        "request_count": 1,
        "location": LOCATION_LABEL,
        "runtime_weather_payload": runtime_payload,
        "normalized_weather_context": normalized,
        "consumer_contexts": consumer_contexts,
        "issues": issues,
        "secrets_exposed": False,
        "raw_provider_payload_saved": False,
        "provider_config_summary": _public_config_summary(config),
        "runtime_side_effects": side,
    }
