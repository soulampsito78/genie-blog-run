"""GENIE weather runtime env binding policy and sanitized canary lock (no production wiring)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

CANONICAL_PROVIDER = "openweather"
SUPPORTED_PROVIDERS = ("openweather", "weatherapi")
IMPLEMENTED_CANARY_PROVIDERS = ("openweather", "weatherapi")

CANONICAL_KEY_ENV = "WEATHER_API_KEY"
FALLBACK_KEY_ENV = "OPENWEATHER_API_KEY"
WEATHERAPI_KEY_ENV = "WEATHERAPI_API_KEY"
CANONICAL_PROVIDER_ENV = "GENIE_WEATHER_PROVIDER"

LOCK_TYPE = "seoul_weather_live_canary"
LOCATION_SEOUL = "Seoul"
REQUIRED_OPERATIONAL_STATUS = "review_required"

ACTIVE_CONSUMERS = (
    "today_geenee",
    "keysuri_global_tech",
    "keysuri_korea_tech",
)

RETIRED_CONSUMERS = ("tomorrow_geenee", "tomorrow_genie", "Tomorrow_Geenee")

FORBIDDEN_IDENTITY_KO = ("테크 앵커", "뉴스 앵커", "아나운서")
FORBIDDEN_RETIRED = ("Tomorrow_Geenee", "tomorrow_genie", "18:00")

FORBIDDEN_LOCK_SUBSTRINGS = (
    "raw_provider_payload",
    "appid=",
    "Authorization:",
    "Bearer ",
    "api_secret",
    "private_key",
    "password=",
    ".env",
    "OPENWEATHER_API_KEY=",
    "WEATHER_API_KEY=",
    "WEATHERAPI_API_KEY=",
)

REQUIRED_SIDE_EFFECT_KEYS = (
    "called_weather_api",
    "called_gemini",
    "called_image_api",
    "fetched_live_news",
    "sent_email",
    "published_naver",
    "changed_scheduler",
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


def build_genie_weather_env_binding_policy() -> dict:
    """Return static env binding, logging, and consumer policy for weather runtime."""
    return {
        "provider": {
            "canonical_provider": CANONICAL_PROVIDER,
            "supported_providers": list(SUPPORTED_PROVIDERS),
            "implemented_canary_providers": list(IMPLEMENTED_CANARY_PROVIDERS),
        },
        "canonical_env": {
            "GENIE_WEATHER_PROVIDER": CANONICAL_PROVIDER,
            "WEATHER_API_KEY": "preferred canonical key env for OpenWeather",
            "OPENWEATHER_API_KEY": "accepted legacy/fallback key env for OpenWeather",
            "WEATHERAPI_API_KEY": "WeatherAPI provider key env",
        },
        "precedence": [
            "GENIE_WEATHER_PROVIDER determines provider",
            "openweather: WEATHER_API_KEY preferred, OPENWEATHER_API_KEY fallback",
            "weatherapi: WEATHERAPI_API_KEY required",
            "no key → blocked_missing_weather_env",
            "unknown provider → blocked_unsupported_provider",
        ],
        "local_policy": {
            "keys_may_be_exported_in_shell": True,
            "keys_must_not_be_committed": True,
            "keys_must_not_be_written_to_tracked_env_files": True,
            "dotenv_files_must_not_be_staged": True,
            "local_canary_manual_only": True,
        },
        "cloud_run_future_policy": {
            "use_secret_manager_or_secure_env_injection": True,
            "do_not_bake_key_into_image": True,
            "do_not_commit_key_into_yaml": True,
            "do_not_print_full_key_in_deployment_logs": True,
            "weather_canary_separate_from_production_scheduler_until_approved": True,
        },
        "logging_report_policy": {
            "do_not_log_full_api_key": True,
            "do_not_persist_raw_provider_payload_by_default": True,
            "sanitized_report_allowed_fields": [
                "provider",
                "request_count",
                "location",
                "weather_condition",
                "weather_date",
                "observed_or_forecast_time_kst",
                "consumer_contexts_built",
                "runtime_side_effects",
                "secrets_exposed",
                "raw_provider_payload_saved",
            ],
            "sanitized_report_forbidden_fields": [
                "full_api_key",
                "appid_query_string",
                "raw_provider_payload",
                "provider_full_response",
                "headers",
                "tokens",
                "secrets",
                "dotenv_contents",
            ],
        },
        "consumer_policy": {
            "today_geenee": (
                "weather is market/life realism layer only; must not dominate financial briefing; "
                "must not become weather-only product"
            ),
            "keysuri_global_tech": "weather is Seoul daytime (12:30) image visual context",
            "keysuri_korea_tech": "weather is Seoul early-evening (18:30) image visual context",
            "Tomorrow_Geenee": "retired; no weather usage",
        },
        "scheduler_policy": {
            "ready_for_scheduler": False,
            "ready_for_production_auto_call": False,
            "active_programs_only": [
                "Today_Geenee 06:30 KST",
                "Kee-Suri Global Tech 12:30 KST",
                "Kee-Suri Korea Tech 18:30 KST",
            ],
        },
    }


def load_genie_weather_canary_lock_fixture(path: str) -> dict:
    """Load sanitized weather canary lock JSON from disk."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Canary lock fixture must be a JSON object: {path}")
    return data


def validate_genie_weather_canary_lock(canary_lock: dict) -> List[dict]:
    """Validate sanitized canary lock fixture. Returns issue dicts (empty if ok)."""
    issues: List[dict] = []
    if not isinstance(canary_lock, dict):
        issues.append(_issue("canary_lock_invalid", "canary_lock must be a dict", "canary_lock"))
        return issues

    lock_type = str(canary_lock.get("lock_type") or "").strip()
    if lock_type != LOCK_TYPE:
        issues.append(
            _issue(
                "lock_type_invalid",
                f"lock_type must be {LOCK_TYPE!r}",
                "lock_type",
            )
        )

    provider = str(canary_lock.get("provider") or "").strip()
    if not provider:
        issues.append(_issue("provider_missing", "provider is required", "provider"))
    elif provider != CANONICAL_PROVIDER:
        issues.append(
            _issue(
                "provider_not_canonical",
                f"provider must be {CANONICAL_PROVIDER!r} for this lock, got {provider!r}",
                "provider",
            )
        )

    status = str(canary_lock.get("canary_status") or "").strip()
    if status != "pass":
        issues.append(
            _issue(
                "canary_status_invalid",
                "canary_status must be pass for canary lock",
                "canary_status",
            )
        )

    request_count = canary_lock.get("request_count")
    if request_count != 1:
        issues.append(
            _issue(
                "request_count_invalid",
                "request_count must be 1 for successful live canary lock",
                "request_count",
            )
        )

    location = str(canary_lock.get("location") or "").strip()
    if location != LOCATION_SEOUL:
        issues.append(
            _issue(
                "location_invalid",
                f"location must be {LOCATION_SEOUL!r}",
                "location",
            )
        )

    if not str(canary_lock.get("weather_date") or "").strip():
        issues.append(_issue("weather_date_missing", "weather_date is required", "weather_date"))

    if not str(canary_lock.get("observed_or_forecast_time_kst") or "").strip():
        issues.append(
            _issue(
                "observed_time_missing",
                "observed_or_forecast_time_kst is required",
                "observed_or_forecast_time_kst",
            )
        )

    if not str(canary_lock.get("weather_condition") or "").strip():
        issues.append(
            _issue("weather_condition_missing", "weather_condition is required", "weather_condition")
        )

    consumers = canary_lock.get("consumer_contexts_built")
    if not isinstance(consumers, list):
        issues.append(
            _issue(
                "consumer_contexts_invalid",
                "consumer_contexts_built must be a list",
                "consumer_contexts_built",
            )
        )
    else:
        built = [str(c).strip() for c in consumers]
        for required in ACTIVE_CONSUMERS:
            if required not in built:
                issues.append(
                    _issue(
                        "consumer_missing",
                        f"consumer_contexts_built must include {required!r}",
                        "consumer_contexts_built",
                    )
                )
        for retired in RETIRED_CONSUMERS:
            if retired in built:
                issues.append(
                    _issue(
                        "retired_consumer_present",
                        f"Must not include retired consumer {retired!r}",
                        "consumer_contexts_built",
                    )
                )

    if canary_lock.get("secrets_exposed") is not False:
        issues.append(
            _issue(
                "secrets_exposed_invalid",
                "secrets_exposed must be false",
                "secrets_exposed",
            )
        )

    if canary_lock.get("raw_provider_payload_saved") is not False:
        issues.append(
            _issue(
                "raw_payload_saved_invalid",
                "raw_provider_payload_saved must be false",
                "raw_provider_payload_saved",
            )
        )

    op_status = str(canary_lock.get("operational_status") or "").strip()
    if op_status != REQUIRED_OPERATIONAL_STATUS:
        issues.append(
            _issue(
                "operational_status_invalid",
                f"operational_status must be {REQUIRED_OPERATIONAL_STATUS!r}",
                "operational_status",
            )
        )

    side = canary_lock.get("runtime_side_effects")
    if not isinstance(side, dict):
        issues.append(
            _issue(
                "runtime_side_effects_invalid",
                "runtime_side_effects must be an object",
                "runtime_side_effects",
            )
        )
    else:
        for key in REQUIRED_SIDE_EFFECT_KEYS:
            if key not in side:
                issues.append(
                    _issue(
                        "runtime_side_effect_missing",
                        f"runtime_side_effects.{key} is required",
                        f"runtime_side_effects.{key}",
                    )
                )
        if side.get("called_weather_api") is not True:
            issues.append(
                _issue(
                    "called_weather_api_invalid",
                    "runtime_side_effects.called_weather_api must be true",
                    "runtime_side_effects.called_weather_api",
                )
            )
        for key in REQUIRED_SIDE_EFFECT_KEYS:
            if key != "called_weather_api" and side.get(key) is not False:
                issues.append(
                    _issue(
                        "runtime_side_effect_must_be_false",
                        f"runtime_side_effects.{key} must be false",
                        f"runtime_side_effects.{key}",
                    )
                )

    texts: List[str] = []
    _collect_strings(canary_lock, texts)
    blob = "\n".join(texts).lower()
    for term in FORBIDDEN_IDENTITY_KO:
        if term in blob:
            issues.append(
                _issue("forbidden_identity", f"Must not contain {term!r}", "canary_lock")
            )
    for term in FORBIDDEN_RETIRED:
        if term in blob:
            issues.append(
                _issue("forbidden_retired", f"Must not contain {term!r}", "canary_lock")
            )
    if re.search(r"\b18:00\b", blob):
        issues.append(
            _issue(
                "forbidden_scheduler_reference",
                "Must not reference standalone 18:00 scheduler slot",
                "canary_lock",
            )
        )
    for forbidden in FORBIDDEN_LOCK_SUBSTRINGS:
        if forbidden.lower() in blob:
            issues.append(
                _issue(
                    "forbidden_secret_or_raw_payload",
                    f"Must not contain forbidden substring {forbidden!r}",
                    "canary_lock",
                )
            )

    return issues


def build_genie_weather_runtime_readiness_summary(
    canary_lock: dict | None = None,
) -> dict:
    """Build runtime readiness summary from optional sanitized canary lock."""
    policy = build_genie_weather_env_binding_policy()
    issues: List[dict] = []

    if canary_lock is None:
        return {
            "weather_runtime_status": "canary_not_run",
            "canonical_provider": CANONICAL_PROVIDER,
            "canonical_provider_confirmed": False,
            "canonical_key_env": CANONICAL_KEY_ENV,
            "fallback_key_env": FALLBACK_KEY_ENV,
            "weather_canary_passed": False,
            "consumer_contexts_confirmed": [],
            "ready_for_runtime_binding_plan": False,
            "ready_for_scheduler": False,
            "ready_for_production_auto_call": False,
            "issues": [
                _issue("canary_lock_missing", "No canary lock supplied", "canary_lock")
            ],
        }

    issues = validate_genie_weather_canary_lock(canary_lock)
    provider = str(canary_lock.get("provider") or "").strip()
    canonical_confirmed = provider == CANONICAL_PROVIDER and not issues
    canary_passed = (
        str(canary_lock.get("canary_status") or "").strip() == "pass"
        and canary_lock.get("request_count") == 1
        and not issues
    )

    consumers_raw = canary_lock.get("consumer_contexts_built")
    consumers_confirmed: List[str] = []
    if isinstance(consumers_raw, list) and canary_passed:
        consumers_confirmed = [c for c in consumers_raw if c in ACTIVE_CONSUMERS]

    ready_plan = (
        canary_passed
        and canonical_confirmed
        and len(consumers_confirmed) == len(ACTIVE_CONSUMERS)
        and not issues
    )

    status = "blocked"
    if canary_passed and ready_plan:
        status = "canary_passed"
    elif not canary_passed and not issues:
        status = "canary_not_run"
    elif issues:
        status = "blocked"

    if canary_passed and issues:
        status = "blocked"

    return {
        "weather_runtime_status": status,
        "canonical_provider": CANONICAL_PROVIDER,
        "canonical_provider_confirmed": canonical_confirmed,
        "canonical_key_env": CANONICAL_KEY_ENV,
        "fallback_key_env": FALLBACK_KEY_ENV,
        "weather_canary_passed": canary_passed,
        "consumer_contexts_confirmed": consumers_confirmed,
        "ready_for_runtime_binding_plan": ready_plan,
        "ready_for_scheduler": policy["scheduler_policy"]["ready_for_scheduler"],
        "ready_for_production_auto_call": policy["scheduler_policy"][
            "ready_for_production_auto_call"
        ],
        "issues": issues,
    }
