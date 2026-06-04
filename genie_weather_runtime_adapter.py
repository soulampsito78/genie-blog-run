"""GENIE Seoul weather runtime payload adapter (offline fixtures — no live weather API)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from keysuri_visual_context import validate_keysuri_weather_context

LOCATION_CITY = "Seoul"
LOCATION_COUNTRY = "KR"
TIMEZONE_SEOUL = "Asia/Seoul"

ALLOWED_PROVIDER_MODES = frozenset({"offline_fixture", "runtime_weather_api"})
ALLOWED_FINE_DUST_LEVELS = frozenset({"good", "moderate", "bad", "very_bad"})
ALLOWED_PRECIP_TYPES = frozenset({"none", "rain", "snow"})

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
FORBIDDEN_RETIRED = ("Tomorrow_Geenee", "tomorrow_genie", "18:00")

SUPPORTED_CONSUMERS = frozenset(
    {"today_geenee", "keysuri_global_tech", "keysuri_korea_tech"}
)

CONSUMER_CONFIG: Dict[str, Dict[str, str]] = {
    "today_geenee": {
        "consumer_label": "Today_Geenee",
        "schedule_time_kst": "06:30",
        "weather_usage": (
            "market and life realism layer for morning briefing; optional short context; "
            "must not dominate financial briefing; must not become weather-only product"
        ),
    },
    "keysuri_global_tech": {
        "consumer_label": "Kee-Suri Global Tech",
        "schedule_time_kst": "12:30",
        "weather_usage": (
            "image visual context for Seoul daytime background; global tech briefing mood; "
            "used with keysuri_visual_context.build_keysuri_image_prompt"
        ),
    },
    "keysuri_korea_tech": {
        "consumer_label": "Kee-Suri Korea Tech",
        "schedule_time_kst": "18:30",
        "weather_usage": (
            "image visual context for Seoul early-evening background; domestic tech briefing mood; "
            "used with keysuri_visual_context.build_keysuri_image_prompt"
        ),
    },
}

UNSUPPORTED_CONSUMERS = frozenset(
    {"tomorrow_geenee", "tomorrow_genie", "Tomorrow_Geenee"}
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


def _scan_forbidden_strings(blob: str, path_prefix: str) -> List[Dict[str, str]]:
    issues: List[Dict[str, str]] = []
    for term in FORBIDDEN_IDENTITY_KO:
        if term in blob:
            issues.append(
                _issue("forbidden_identity_string", f"Must not contain {term!r}", path_prefix)
            )
    for term in FORBIDDEN_IDENTITY_EN:
        if term.lower() in blob.lower():
            issues.append(
                _issue("forbidden_identity_string", f"Must not contain {term!r}", path_prefix)
            )
    for term in FORBIDDEN_RETIRED:
        if term in blob:
            issues.append(
                _issue("forbidden_retired_reference", f"Must not contain {term!r}", path_prefix)
            )
    if re.search(r"\b18:00\b", blob):
        issues.append(
            _issue(
                "forbidden_scheduler_reference",
                "Must not reference standalone 18:00 scheduler slot",
                path_prefix,
            )
        )
    return issues


def load_genie_runtime_weather_payload_fixture(path: str) -> dict:
    """Load a runtime weather payload JSON fixture from disk."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Weather payload fixture must be a JSON object: {path}")
    return data


def validate_genie_runtime_weather_payload(payload: dict) -> List[dict]:
    """Validate GENIE runtime weather payload. Returns issue dicts (empty if ok)."""
    issues: List[dict] = []
    if not isinstance(payload, dict):
        issues.append(_issue("payload_invalid", "payload must be a dict", "payload"))
        return issues

    if not str(payload.get("provider") or "").strip():
        issues.append(_issue("provider_missing", "provider is required", "provider"))

    mode = str(payload.get("provider_mode") or "").strip()
    if mode not in ALLOWED_PROVIDER_MODES:
        issues.append(
            _issue(
                "provider_mode_invalid",
                f"provider_mode must be one of {sorted(ALLOWED_PROVIDER_MODES)}",
                "provider_mode",
            )
        )

    location = payload.get("location")
    if not isinstance(location, dict):
        issues.append(_issue("location_missing", "location must be an object", "location"))
    else:
        city = str(location.get("city") or "").strip()
        if city != LOCATION_CITY:
            issues.append(
                _issue(
                    "location_city_invalid",
                    f"location.city must be {LOCATION_CITY!r}, got {city!r}",
                    "location.city",
                )
            )
        country = str(location.get("country") or "").strip()
        if country != LOCATION_COUNTRY:
            issues.append(
                _issue(
                    "location_country_invalid",
                    f"location.country must be {LOCATION_COUNTRY!r}, got {country!r}",
                    "location.country",
                )
            )
        tz = str(location.get("timezone") or "").strip()
        if tz != TIMEZONE_SEOUL:
            issues.append(
                _issue(
                    "location_timezone_invalid",
                    f"location.timezone must be {TIMEZONE_SEOUL!r}, got {tz!r}",
                    "location.timezone",
                )
            )

    if not str(payload.get("weather_date") or "").strip():
        issues.append(_issue("weather_date_missing", "weather_date is required", "weather_date"))

    if not str(payload.get("observed_or_forecast_time_kst") or "").strip():
        issues.append(
            _issue(
                "observed_time_missing",
                "observed_or_forecast_time_kst is required",
                "observed_or_forecast_time_kst",
            )
        )

    code = str(payload.get("condition_code") or "").strip()
    label = str(payload.get("condition_label") or "").strip()
    if not code and not label:
        issues.append(
            _issue(
                "condition_missing",
                "condition_code or condition_label is required",
                "condition",
            )
        )

    if not str(payload.get("source_label") or "").strip():
        issues.append(_issue("source_label_missing", "source_label is required", "source_label"))

    precip = payload.get("precipitation_type")
    if precip is not None and str(precip).strip() and str(precip).strip() not in ALLOWED_PRECIP_TYPES:
        issues.append(
            _issue(
                "precipitation_type_invalid",
                f"precipitation_type invalid: {precip!r}",
                "precipitation_type",
            )
        )

    for key in ("fine_dust_level", "ultra_fine_dust_level"):
        val = payload.get(key)
        if val is not None and str(val).strip() and str(val).strip() not in ALLOWED_FINE_DUST_LEVELS:
            issues.append(
                _issue(f"{key}_invalid", f"{key} invalid: {val!r}", key)
            )

    texts: List[str] = []
    _collect_strings(payload, texts)
    issues.extend(_scan_forbidden_strings("\n".join(texts), "payload"))

    return issues


def _normalize_condition_token(payload: dict) -> str:
    parts: List[str] = []
    for key in ("condition_code", "condition_label"):
        val = str(payload.get(key) or "").strip().lower()
        if val:
            parts.append(val)
    precip = str(payload.get("precipitation_type") or "").strip().lower()
    if precip and precip != "none":
        parts.append(precip)
    return " ".join(parts)


def _map_weather_condition(payload: dict) -> str:
    """Map runtime payload fields to keysuri weather_condition enum."""
    token = _normalize_condition_token(payload)
    dust = str(payload.get("fine_dust_level") or "").strip()
    ultra = str(payload.get("ultra_fine_dust_level") or "").strip()
    bad_dust = dust in ("bad", "very_bad") or ultra in ("bad", "very_bad")

    if any(x in token for x in ("rain", "shower", "drizzle", "precipitation_type=rain")):
        return "rainy"
    if "snow" in token or str(payload.get("precipitation_type") or "").lower() == "snow":
        return "snow"
    if any(x in token for x in ("fine_dust", "fine dust", "미세먼지", "dust", "pm10", "pm2")):
        return "fine_dust"
    if bad_dust:
        return "fine_dust"
    if any(x in token for x in ("haze", "mist", "fog", "smog")):
        return "haze"
    if "overcast" in token:
        return "overcast"
    if any(x in token for x in ("cloud", "cloudy", "partly")):
        return "cloudy"
    if any(x in token for x in ("clear", "sunny", "fair")):
        if "sunny" in token:
            return "sunny"
        return "clear"
    if any(x in token for x in ("cold", "freez", "winter", "icy")):
        return "cold"
    temp = payload.get("temperature_c")
    if isinstance(temp, (int, float)) and temp <= 0:
        return "cold"

    if bad_dust:
        return "fine_dust"

    raise ValueError(
        f"Cannot map weather condition from condition_code/label: {token!r}; "
        "no fallback available"
    )


def normalize_genie_runtime_weather_payload(payload: dict) -> dict:
    """Validate and normalize runtime weather payload to keysuri weather_context shape."""
    issues = validate_genie_runtime_weather_payload(payload)
    if issues:
        messages = "; ".join(f"{i['code']}: {i['message']}" for i in issues[:3])
        raise ValueError(f"Invalid runtime weather payload: {messages}")

    provider_mode = str(payload.get("provider_mode") or "").strip()
    weather_condition = _map_weather_condition(payload)

    notes_parts: List[str] = []
    if payload.get("notes"):
        notes_parts.append(str(payload["notes"]).strip())
    notes_parts.append(
        f"Normalized from provider={payload.get('provider')!r} "
        f"condition_code={payload.get('condition_code')!r}"
    )

    weather_context: Dict[str, Any] = {
        "location": LOCATION_CITY,
        "timezone": TIMEZONE_SEOUL,
        "weather_date": payload.get("weather_date"),
        "observed_or_forecast_time_kst": payload.get("observed_or_forecast_time_kst"),
        "weather_condition": weather_condition,
        "source_mode": provider_mode,
        "source_label": payload.get("source_label"),
        "notes": "; ".join(n for n in notes_parts if n),
    }

    for key in (
        "temperature_c",
        "feels_like_c",
        "precipitation_probability",
        "humidity_percent",
    ):
        if payload.get(key) is not None:
            weather_context[key] = payload[key]

    dust = payload.get("fine_dust_level")
    if dust is not None and str(dust).strip():
        weather_context["fine_dust_level"] = str(dust).strip()

    return weather_context


def build_genie_weather_consumer_context(consumer_id: str, weather_context: dict) -> dict:
    """Build weather consumer context for Today_Geenee or Kee-Suri programs."""
    cid = (consumer_id or "").strip()
    if cid in UNSUPPORTED_CONSUMERS or cid.lower() in UNSUPPORTED_CONSUMERS:
        raise ValueError(f"Retired or unsupported weather consumer: {consumer_id!r}")
    if cid not in SUPPORTED_CONSUMERS:
        raise ValueError(f"Unsupported weather consumer_id: {consumer_id!r}")

    w_issues = validate_keysuri_weather_context(weather_context)
    if w_issues:
        messages = "; ".join(f"{i['code']}: {i['message']}" for i in w_issues[:3])
        raise ValueError(f"Invalid weather_context: {messages}")

    cfg = CONSUMER_CONFIG[cid]
    return {
        "consumer_id": cid,
        "consumer_label": cfg["consumer_label"],
        "schedule_time_kst": cfg["schedule_time_kst"],
        "location_baseline": LOCATION_CITY,
        "weather_context": dict(weather_context),
        "weather_usage": cfg["weather_usage"],
        "operational_status": "review_required",
    }
