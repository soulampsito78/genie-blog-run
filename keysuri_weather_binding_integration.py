"""Kee-Suri offline weather binding → visual context integration dry-run (no production wiring)."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from genie_runtime_weather_binding import (
    RUNTIME_BINDING_STATUS,
    build_runtime_weather_binding_report_from_canary_lock,
    load_weather_context_from_canary_lock,
)
from keysuri_visual_context import (
    FORBIDDEN_IDENTITY_EN,
    FORBIDDEN_IDENTITY_KO,
    IDENTITY_LABEL,
    build_keysuri_visual_context,
)

INTEGRATION_TYPE = "keysuri_weather_binding_visual_context_dry_run"

KEYSURI_PROGRAMS = (
    "keysuri_global_tech",
    "keysuri_korea_tech",
)

VISUAL_TIME_BY_PROGRAM = {
    "keysuri_global_tech": "seoul_daytime_1230",
    "keysuri_korea_tech": "seoul_early_evening_1830",
}

FORBIDDEN_PROGRAMS = (
    "today_geenee",
    "tomorrow_geenee",
    "tomorrow_genie",
    "Tomorrow_Geenee",
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

FORBIDDEN_SECRET_SUBSTRINGS = (
    "raw_provider_payload",
    "appid=",
    "Authorization:",
    "Bearer ",
    "WEATHER_API_KEY=",
    "OPENWEATHER_API_KEY=",
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


def _enrich_keysuri_visual_context(
    visual_context: dict,
    program_id: str,
) -> dict:
    """Attach binding dry-run metadata to Kee-Suri visual context."""
    enriched = dict(visual_context)
    enriched["visual_time_context"] = VISUAL_TIME_BY_PROGRAM[program_id]
    enriched["private_tech_secretary_identity"] = True
    enriched["identity_label"] = IDENTITY_LABEL
    return enriched


def build_keysuri_visual_contexts_from_weather_binding_report(
    binding_report: dict,
    weather_context: dict,
) -> dict:
    """Build Kee-Suri visual contexts from a pass runtime weather binding report."""
    if str(binding_report.get("binding_status") or "") != "pass":
        raise ValueError("binding_report must have binding_status pass")

    bindings = binding_report.get("consumer_bindings")
    if not isinstance(bindings, dict):
        raise ValueError("binding_report.consumer_bindings must be a dict")

    visual_contexts: Dict[str, dict] = {}
    for program_id in KEYSURI_PROGRAMS:
        if program_id not in bindings:
            raise ValueError(f"binding_report missing consumer binding for {program_id!r}")
        base = build_keysuri_visual_context(program_id, weather_context)
        visual_contexts[program_id] = _enrich_keysuri_visual_context(base, program_id)

    return visual_contexts


def build_keysuri_visual_contexts_from_canary_lock(lock_path: str) -> dict:
    """Load canary lock, build binding report, and return Kee-Suri visual contexts."""
    binding_report = build_runtime_weather_binding_report_from_canary_lock(lock_path)
    weather_context = load_weather_context_from_canary_lock(lock_path)
    return build_keysuri_visual_contexts_from_weather_binding_report(
        binding_report,
        weather_context,
    )


def validate_keysuri_weather_binding_integration_result(result: dict) -> List[dict]:
    """Validate integration dry-run result. Returns issue dicts (empty if ok)."""
    issues: List[dict] = []
    if not isinstance(result, dict):
        issues.append(_issue("result_invalid", "result must be a dict", "result"))
        return issues

    if str(result.get("integration_type") or "") != INTEGRATION_TYPE:
        issues.append(
            _issue(
                "integration_type_invalid",
                f"integration_type must be {INTEGRATION_TYPE!r}",
                "integration_type",
            )
        )

    if str(result.get("runtime_binding_status") or "") != RUNTIME_BINDING_STATUS:
        issues.append(
            _issue(
                "runtime_binding_status_invalid",
                f"runtime_binding_status must be {RUNTIME_BINDING_STATUS!r}",
                "runtime_binding_status",
            )
        )

    if str(result.get("weather_context_source") or "") != "sanitized_canary_lock":
        issues.append(
            _issue(
                "weather_context_source_invalid",
                "weather_context_source must be sanitized_canary_lock",
                "weather_context_source",
            )
        )

    if result.get("ready_for_scheduler") is not False:
        issues.append(_issue("ready_for_scheduler_invalid", "must be false", "ready_for_scheduler"))
    if result.get("ready_for_production_auto_call") is not False:
        issues.append(
            _issue(
                "ready_for_production_auto_call_invalid",
                "must be false",
                "ready_for_production_auto_call",
            )
        )

    side = result.get("side_effects")
    if not isinstance(side, dict):
        issues.append(_issue("side_effects_invalid", "side_effects must be a dict", "side_effects"))
    else:
        for key, expected in SIDE_EFFECTS_DISABLED.items():
            if side.get(key) is not expected:
                issues.append(
                    _issue(
                        "side_effect_invalid",
                        f"side_effects.{key} must be {expected!r}",
                        f"side_effects.{key}",
                    )
                )

    contexts = result.get("visual_contexts")
    if not isinstance(contexts, dict):
        issues.append(
            _issue("visual_contexts_invalid", "visual_contexts must be a dict", "visual_contexts")
        )
        return issues

    for forbidden in FORBIDDEN_PROGRAMS:
        if forbidden in contexts:
            issues.append(
                _issue(
                    "forbidden_program_present",
                    f"Must not include visual context for {forbidden!r}",
                    "visual_contexts",
                )
            )

    for program_id in KEYSURI_PROGRAMS:
        if program_id not in contexts:
            issues.append(
                _issue(
                    "visual_context_missing",
                    f"visual_contexts must include {program_id!r}",
                    "visual_contexts",
                )
            )
            continue

        ctx = contexts[program_id]
        if not isinstance(ctx, dict):
            issues.append(
                _issue("visual_context_invalid", f"{program_id} must be a dict", program_id)
            )
            continue

        if ctx.get("program_id") != program_id:
            issues.append(
                _issue(
                    "program_id_mismatch",
                    f"program_id must be {program_id!r}",
                    f"visual_contexts.{program_id}.program_id",
                )
            )
        if ctx.get("source_mode") != "sanitized_canary_lock":
            issues.append(
                _issue(
                    "source_mode_invalid",
                    "source_mode must be sanitized_canary_lock",
                    f"visual_contexts.{program_id}.source_mode",
                )
            )
        if ctx.get("visual_time_context") != VISUAL_TIME_BY_PROGRAM[program_id]:
            issues.append(
                _issue(
                    "visual_time_context_invalid",
                    f"visual_time_context must be {VISUAL_TIME_BY_PROGRAM[program_id]!r}",
                    f"visual_contexts.{program_id}.visual_time_context",
                )
            )
        if str(ctx.get("location_baseline") or ctx.get("location") or "") != "Seoul":
            issues.append(
                _issue("location_invalid", "location must be Seoul", f"visual_contexts.{program_id}")
            )
        if ctx.get("weather_condition") != "cloudy":
            issues.append(
                _issue(
                    "weather_condition_invalid",
                    "expected cloudy from canary lock fixture",
                    f"visual_contexts.{program_id}.weather_condition",
                )
            )
        if ctx.get("private_tech_secretary_identity") is not True:
            issues.append(
                _issue(
                    "identity_flag_invalid",
                    "private_tech_secretary_identity must be true",
                    f"visual_contexts.{program_id}",
                )
            )
        if ctx.get("identity_label") != IDENTITY_LABEL:
            issues.append(
                _issue(
                    "identity_label_invalid",
                    f"identity_label must be {IDENTITY_LABEL!r}",
                    f"visual_contexts.{program_id}.identity_label",
                )
            )

        positive_texts: List[str] = []
        for key in (
            "weather_visual_summary",
            "background_direction",
            "lighting_direction",
            "mood_direction",
            "program_tone",
            "must_not_feel",
        ):
            val = ctx.get(key)
            if isinstance(val, str):
                positive_texts.append(val)
        pos_blob = "\n".join(positive_texts).lower()
        for term in FORBIDDEN_IDENTITY_KO:
            if term in pos_blob:
                issues.append(
                    _issue(
                        "forbidden_identity_in_output",
                        f"Must not contain {term!r} in positive fields",
                        program_id,
                    )
                )
        for term in FORBIDDEN_IDENTITY_EN:
            if term.lower() in pos_blob:
                issues.append(
                    _issue(
                        "forbidden_identity_in_output",
                        f"Must not contain {term!r} in positive fields",
                        program_id,
                    )
                )
        if "tomorrow_geenee" in pos_blob or "tomorrow_genie" in pos_blob:
            issues.append(
                _issue("forbidden_retired_in_output", "retired product in output", program_id)
            )
        if re.search(r"\b18:00\b", pos_blob):
            issues.append(
                _issue("forbidden_scheduler_in_output", "standalone 18:00 in output", program_id)
            )

    texts: List[str] = []
    _collect_strings(result, texts)
    blob_lower = "\n".join(texts).lower()
    for forbidden in FORBIDDEN_SECRET_SUBSTRINGS:
        if forbidden.lower() in blob_lower:
            issues.append(
                _issue(
                    "forbidden_secret_or_payload",
                    f"Must not contain {forbidden!r}",
                    "result",
                )
            )

    return issues


def build_keysuri_weather_binding_integration_report(lock_path: str) -> dict:
    """Build full Kee-Suri weather binding integration dry-run report."""
    binding_report = build_runtime_weather_binding_report_from_canary_lock(lock_path)
    weather_context = load_weather_context_from_canary_lock(lock_path)

    issues: List[dict] = []
    visual_contexts: Dict[str, dict] = {}

    if binding_report.get("binding_status") != "pass":
        issues.append(
            _issue(
                "binding_report_not_pass",
                "runtime weather binding report must pass before integration",
                "binding_report",
            )
        )
    else:
        try:
            visual_contexts = build_keysuri_visual_contexts_from_weather_binding_report(
                binding_report,
                weather_context,
            )
        except ValueError as exc:
            issues.append(_issue("visual_context_build_failed", str(exc), "visual_contexts"))

    result: Dict[str, Any] = {
        "integration_status": "pass",
        "integration_type": INTEGRATION_TYPE,
        "runtime_binding_status": RUNTIME_BINDING_STATUS,
        "weather_context_source": str(weather_context.get("source_mode") or ""),
        "visual_contexts": visual_contexts,
        "ready_for_scheduler": False,
        "ready_for_production_auto_call": False,
        "side_effects": dict(SIDE_EFFECTS_DISABLED),
        "issues": issues,
    }

    validation_issues = validate_keysuri_weather_binding_integration_result(result)
    issues.extend(validation_issues)
    result["issues"] = issues
    result["integration_status"] = (
        "pass" if not issues and len(visual_contexts) == len(KEYSURI_PROGRAMS) else "blocked"
    )
    return result
