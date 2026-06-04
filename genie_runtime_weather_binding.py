"""GENIE runtime weather binding design (offline — no live API, scheduler, or production wiring)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from genie_weather_runtime_policy import (
    CANONICAL_PROVIDER,
    load_genie_weather_canary_lock_fixture,
    validate_genie_weather_canary_lock,
)

BINDING_TYPE = "runtime_weather_context_binding_design"
RUNTIME_BINDING_STATUS = "design_ready_not_wired"
TIMEZONE_SEOUL = "Asia/Seoul"
LOCATION_SEOUL = "Seoul"

ALLOWED_CONSUMERS = (
    "today_geenee",
    "keysuri_global_tech",
    "keysuri_korea_tech",
)

FORBIDDEN_CONSUMERS = (
    "tomorrow_geenee",
    "tomorrow_genie",
    "Tomorrow_Geenee",
    "tomorrow",
    "standalone_18_00_product",
    "weather_only_product",
)

SOURCE_MODES_ALLOWED = (
    "sample_fixture",
    "sanitized_canary_lock",
    "future_manual_canary_result",
)

SOURCE_MODES_FORBIDDEN = (
    "automatic_live_weather_api_call",
    "scheduler_invoked_weather_call",
    "production_auto_call",
)

ALLOWED_WEATHER_CONDITIONS = frozenset(
    {
        "sunny",
        "clear",
        "cloudy",
        "overcast",
        "rainy",
        "snow",
        "cold",
        "fine_dust",
        "haze",
    }
)

FORBIDDEN_IDENTITY_KO = ("테크 앵커", "뉴스 앵커", "아나운서")
FORBIDDEN_IDENTITY_EN = (
    "public news anchor",
    "broadcaster",
    "TV newsroom host",
    "weathercaster",
    "tech anchor",
    "news anchor",
    "announcer",
)
FORBIDDEN_RETIRED = ("Tomorrow_Geenee", "tomorrow_genie")
FORBIDDEN_SECRET_SUBSTRINGS = (
    "raw_provider_payload",
    "appid=",
    "Authorization:",
    "Bearer ",
    "WEATHER_API_KEY=",
    "OPENWEATHER_API_KEY=",
    "WEATHERAPI_API_KEY=",
)

SIDE_EFFECTS_DISABLED = {
    "called_weather_api": False,
    "called_gemini": False,
    "called_image_api": False,
    "fetched_live_news": False,
    "sent_email": False,
    "published_naver": False,
    "changed_scheduler": False,
}

WEATHER_ONLY_FORBIDDEN_PHRASES = (
    "weather-only product",
    "weather only product",
    "dedicated weather service",
    "long-range forecast",
    "7-day forecast",
    "extended forecast",
)

ANCHOR_FORBIDDEN_PHRASES = (
    "public news anchor",
    "news anchor",
    "broadcaster",
    "weathercaster",
    "TV newsroom host",
    "tech anchor",
    "announcer",
)


def _issue(code: str, message: str, path: str) -> Dict[str, str]:
    return {"code": code, "message": message, "path": path}


def _collect_strings(value: Any, out: List[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            _collect_strings(v, out)
    elif isinstance(value, list):
        for item in value:
            _collect_strings(item, out)


def get_allowed_weather_consumers() -> List[str]:
    """Return active GENIE consumers allowed to receive runtime weather binding."""
    return list(ALLOWED_CONSUMERS)


def build_runtime_weather_binding_contract() -> dict:
    """Return static runtime weather binding design contract (not production-wired)."""
    return {
        "binding_type": BINDING_TYPE,
        "runtime_binding_status": RUNTIME_BINDING_STATUS,
        "allowed_consumers": list(ALLOWED_CONSUMERS),
        "forbidden_consumers": list(FORBIDDEN_CONSUMERS),
        "source_modes_allowed": list(SOURCE_MODES_ALLOWED),
        "source_modes_forbidden": list(SOURCE_MODES_FORBIDDEN),
        "ready_for_runtime_binding_plan": True,
        "ready_for_scheduler": False,
        "ready_for_production_auto_call": False,
        "side_effects": dict(SIDE_EFFECTS_DISABLED),
    }


def _normalize_consumer_id(consumer: str) -> str:
    return (consumer or "").strip()


def _consumer_is_forbidden(consumer: str) -> bool:
    cid = _normalize_consumer_id(consumer)
    if not cid:
        return True
    lower = cid.lower()
    if lower in {c.lower() for c in FORBIDDEN_CONSUMERS}:
        return True
    if lower in ("tomorrow_geenee", "tomorrow_genie", "tomorrow"):
        return True
    if "weather_only" in lower or lower == "weather_only_product":
        return True
    if "standalone" in lower and "18" in lower:
        return True
    return False


def _scan_weather_context_guards(weather_context: dict) -> List[dict]:
    issues: List[dict] = []
    texts: List[str] = []
    _collect_strings(weather_context, texts)
    blob = "\n".join(texts)
    blob_lower = blob.lower()

    for term in FORBIDDEN_IDENTITY_KO:
        if term in blob:
            issues.append(
                _issue("forbidden_identity", f"Must not contain {term!r}", "weather_context")
            )
    for term in FORBIDDEN_IDENTITY_EN:
        if term.lower() in blob_lower:
            issues.append(
                _issue("forbidden_identity", f"Must not contain {term!r}", "weather_context")
            )
    for term in FORBIDDEN_RETIRED:
        if term in blob:
            issues.append(
                _issue("forbidden_retired", f"Must not contain {term!r}", "weather_context")
            )
    if re.search(r"\b18:00\b", blob_lower):
        issues.append(
            _issue(
                "forbidden_scheduler_reference",
                "Must not reference standalone 18:00 scheduler slot",
                "weather_context",
            )
        )
    for forbidden in FORBIDDEN_SECRET_SUBSTRINGS:
        if forbidden.lower() in blob_lower:
            issues.append(
                _issue(
                    "forbidden_secret_or_payload",
                    f"Must not contain forbidden substring {forbidden!r}",
                    "weather_context",
                )
            )
    return issues


def _validate_weather_context(weather_context: dict) -> List[dict]:
    issues: List[dict] = []
    if not isinstance(weather_context, dict):
        issues.append(_issue("weather_context_invalid", "weather_context must be a dict", "weather_context"))
        return issues

    source_mode = str(weather_context.get("source_mode") or "").strip()
    if not source_mode:
        issues.append(_issue("source_mode_missing", "source_mode is required", "source_mode"))
    elif source_mode in SOURCE_MODES_FORBIDDEN:
        issues.append(
            _issue(
                "source_mode_forbidden",
                f"source_mode {source_mode!r} is not allowed for binding design",
                "source_mode",
            )
        )
    elif source_mode not in SOURCE_MODES_ALLOWED:
        issues.append(
            _issue(
                "source_mode_invalid",
                f"source_mode must be one of {sorted(SOURCE_MODES_ALLOWED)}",
                "source_mode",
            )
        )

    if str(weather_context.get("location") or "").strip() != LOCATION_SEOUL:
        issues.append(
            _issue(
                "location_invalid",
                f"location must be {LOCATION_SEOUL!r}",
                "location",
            )
        )
    if str(weather_context.get("timezone") or "").strip() != TIMEZONE_SEOUL:
        issues.append(
            _issue(
                "timezone_invalid",
                f"timezone must be {TIMEZONE_SEOUL!r}",
                "timezone",
            )
        )

    for key in ("weather_date", "observed_or_forecast_time_kst", "source_label"):
        if not str(weather_context.get(key) or "").strip():
            issues.append(_issue(f"{key}_missing", f"{key} is required", key))

    condition = str(weather_context.get("weather_condition") or "").strip()
    if condition not in ALLOWED_WEATHER_CONDITIONS:
        issues.append(
            _issue(
                "weather_condition_invalid",
                f"weather_condition must be one of {sorted(ALLOWED_WEATHER_CONDITIONS)}",
                "weather_condition",
            )
        )

    provider = str(weather_context.get("provider") or "").strip()
    if provider and provider != CANONICAL_PROVIDER:
        issues.append(
            _issue(
                "provider_not_canonical",
                f"provider must be {CANONICAL_PROVIDER!r} when set",
                "provider",
            )
        )

    issues.extend(_scan_weather_context_guards(weather_context))
    return issues


def _brief_life_context_hint(weather_context: dict) -> str:
    condition = str(weather_context.get("weather_condition") or "cloudy")
    time_kst = str(weather_context.get("observed_or_forecast_time_kst") or "")
    hints = {
        "cloudy": "light overcast Seoul morning mood; keep market briefing primary",
        "overcast": "muted Seoul sky; brief life realism only",
        "rainy": "umbrella commute cue; avoid weather-dominated briefing",
        "sunny": "clear Seoul morning; short outdoor realism cue only",
        "clear": "clear Seoul air; minimal weather mention",
        "snow": "cold commute awareness; financial briefing stays primary",
        "cold": "layered commute cue; no extended forecast",
        "fine_dust": "air-quality awareness; keep briefing financial-first",
        "haze": "soft haze atmosphere; no weather-product framing",
    }
    base = hints.get(condition, "Seoul life realism cue only; financial briefing primary")
    if time_kst:
        return f"{base} (observed {time_kst} KST)"
    return base


def _keysuri_visual_reflects(visual_time_context: str, weather_context: dict) -> List[str]:
    condition = str(weather_context.get("weather_condition") or "")
    if visual_time_context == "seoul_daytime_1230":
        reflects = ["office_window_light", "city_atmosphere"]
        if condition in ("rainy", "overcast", "cloudy"):
            reflects.append("wardrobe_props_if_relevant")
        return reflects
    reflects = ["evening_window_tone", "city_reflections", "office_lighting"]
    if condition in ("rainy", "cloudy", "overcast"):
        reflects.append("subtle_commute_lifestyle_cues")
    return reflects


def build_weather_context_for_consumer(consumer: str, weather_context: dict) -> dict:
    """Build consumer-specific weather binding payload from normalized weather_context."""
    cid = _normalize_consumer_id(consumer)
    if _consumer_is_forbidden(cid):
        raise ValueError(f"Forbidden weather consumer: {consumer!r}")
    if cid not in ALLOWED_CONSUMERS:
        raise ValueError(f"Unknown weather consumer: {consumer!r}")

    ctx_issues = _validate_weather_context(weather_context)
    if ctx_issues:
        messages = "; ".join(f"{i['code']}: {i['message']}" for i in ctx_issues[:3])
        raise ValueError(f"Invalid weather_context: {messages}")

    location = str(weather_context.get("location") or LOCATION_SEOUL)
    condition = str(weather_context.get("weather_condition") or "")
    time_kst = str(weather_context.get("observed_or_forecast_time_kst") or "")

    if cid == "today_geenee":
        return {
            "consumer": cid,
            "role": "market_life_realism_layer",
            "emphasis": "light",
            "must_not_become_weather_only": True,
            "weather_cues": {
                "location": location,
                "weather_condition": condition,
                "observed_or_forecast_time_kst": time_kst,
                "brief_life_context_hint": _brief_life_context_hint(weather_context),
            },
            "forbidden_framing": list(WEATHER_ONLY_FORBIDDEN_PHRASES),
            "binding_status": "pass",
        }

    visual_time = (
        "seoul_daytime_1230" if cid == "keysuri_global_tech" else "seoul_early_evening_1830"
    )
    binding = {
        "consumer": cid,
        "role": "visual_realism_layer",
        "visual_time_context": visual_time,
        "must_not_change_persona": True,
        "visual_reflects": _keysuri_visual_reflects(visual_time, weather_context),
        "forbidden_framing": list(ANCHOR_FORBIDDEN_PHRASES),
        "weather_context_summary": {
            "location": location,
            "weather_condition": condition,
            "observed_or_forecast_time_kst": time_kst,
            "source_mode": weather_context.get("source_mode"),
            "source_label": weather_context.get("source_label"),
        },
        "binding_status": "pass",
    }
    return binding


def load_weather_context_from_canary_lock(lock_path: str) -> dict:
    """Load sanitized canary lock, validate, and convert to minimal weather_context."""
    lock = load_genie_weather_canary_lock_fixture(lock_path)
    lock_issues = validate_genie_weather_canary_lock(lock)
    if lock_issues:
        messages = "; ".join(f"{i['code']}: {i['message']}" for i in lock_issues[:3])
        raise ValueError(f"Invalid canary lock: {messages}")

    condition = str(lock.get("weather_condition") or "").strip().lower()
    if condition not in ALLOWED_WEATHER_CONDITIONS:
        raise ValueError(f"Cannot map canary weather_condition: {condition!r}")

    return {
        "source_mode": "sanitized_canary_lock",
        "provider": str(lock.get("provider") or CANONICAL_PROVIDER).strip(),
        "location": LOCATION_SEOUL,
        "timezone": TIMEZONE_SEOUL,
        "weather_condition": condition,
        "weather_date": str(lock.get("weather_date") or "").strip(),
        "observed_or_forecast_time_kst": str(
            lock.get("observed_or_forecast_time_kst") or ""
        ).strip(),
        "source_label": "OpenWeather live canary lock",
        "canary_lock_status": str(lock.get("canary_status") or "pass").strip(),
    }


def build_runtime_weather_binding_report(weather_context: dict) -> dict:
    """Build runtime weather binding report for all allowed consumers."""
    issues: List[dict] = list(_validate_weather_context(weather_context))

    forbidden_present = False
    for key in weather_context:
        if isinstance(key, str) and _consumer_is_forbidden(key):
            forbidden_present = True
            issues.append(
                _issue(
                    "forbidden_consumer_key",
                    f"weather_context must not include forbidden consumer key {key!r}",
                    "weather_context",
                )
            )

    consumer_bindings: Dict[str, Any] = {}
    if not issues:
        for consumer in ALLOWED_CONSUMERS:
            try:
                consumer_bindings[consumer] = build_weather_context_for_consumer(
                    consumer, weather_context
                )
            except ValueError as exc:
                issues.append(
                    _issue(
                        "consumer_binding_failed",
                        str(exc),
                        consumer,
                    )
                )

    binding_status = "pass" if not issues and len(consumer_bindings) == len(ALLOWED_CONSUMERS) else "blocked"

    return {
        "binding_status": binding_status,
        "runtime_binding_status": RUNTIME_BINDING_STATUS,
        "weather_context_source": str(weather_context.get("source_mode") or ""),
        "consumer_bindings": consumer_bindings,
        "forbidden_consumers_present": forbidden_present,
        "ready_for_scheduler": False,
        "ready_for_production_auto_call": False,
        "side_effects": dict(SIDE_EFFECTS_DISABLED),
        "issues": issues,
    }


def build_runtime_weather_binding_report_from_canary_lock(lock_path: str) -> dict:
    """Load canary lock, build weather_context, and emit binding report."""
    weather_context = load_weather_context_from_canary_lock(lock_path)
    return build_runtime_weather_binding_report(weather_context)
