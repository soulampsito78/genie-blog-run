"""Kee-Suri weather-bound visual prompt contract integration (offline — no image API)."""
from __future__ import annotations

import re
from typing import Any, Dict, List

from genie_runtime_weather_binding import RUNTIME_BINDING_STATUS
from keysuri_visual_context import FORBIDDEN_SOURCE_MODES, IDENTITY_LABEL
from keysuri_weather_binding_integration import (
    INTEGRATION_TYPE,
    KEYSURI_PROGRAMS,
    build_keysuri_weather_binding_integration_report,
)

REPORT_TYPE = "keysuri_weather_visual_prompt_integration_report"
PROMPT_CONTRACT_TYPE = "keysuri_weather_aware_visual_prompt"
SOURCE_MODE = "sanitized_canary_lock"
LOCATION = "Seoul"

FORBIDDEN_PROGRAMS = (
    "today_geenee",
    "tomorrow_geenee",
    "tomorrow_genie",
    "Tomorrow_Geenee",
)

FORBIDDEN_POSITIVE_IDENTITY = (
    "테크 앵커",
    "뉴스 앵커",
    "아나운서",
    "공개 방송형 앵커",
    "public news anchor",
    "broadcaster",
    "tv newsroom host",
    "weathercaster",
    "news anchor",
    "announcer",
    "weather report presenter",
)

REQUIRED_NEGATIVE_PHRASES = (
    "no collage",
    "no split screen",
    "no text overlay",
    "no readable ui text",
    "no fake chart text",
    "no newsroom",
    "no broadcast desk",
    "no news anchor",
    "no announcer",
    "no weathercaster",
    "no public broadcast host",
    "no tv studio",
    "no tomorrow_geenee",
    "no weather report presenter",
    "no logo text",
    "no today_geenee wardrobe logic",
    "no newsroom outfit",
    "no weather presenter outfit",
    "no ceo power suit",
    "no casual office worker",
    "no evening dress",
    "no fashion editorial",
    "no excessive luxury styling",
    "no overly revealing outfit",
    "do not copy the reference pose",
    "do not copy the reference camera angle",
    "do not copy the reference facial expression",
    "do not copy the reference hand position",
    "do not copy the reference tablet angle",
    "do not recreate the same composition",
    "do not merely change the background",
)

IDENTITY_ONLY_REFERENCE_CLAUSE = (
    "Use the reference image for identity, hairstyle, glasses, facial impression, and "
    "wardrobe continuity only. Do not copy the reference pose, camera angle, facial "
    "expression, hand position, tablet angle, or composition. Create a new private "
    "briefing moment with a different pose and camera perspective."
)

FORBIDDEN_POSITIVE_COPY_PHRASES = (
    "same pose",
    "same composition",
    "identical pose",
    "identical composition",
    "recreate the reference pose",
    "recreate the reference composition",
    "merely change the background",
    "background-only variation",
    "background-only change",
)

REFERENCE_USAGE_POLICY = {
    "reference_role": "identity_and_wardrobe_continuity_only",
    "must_preserve": [
        "Kee-Suri facial impression",
        "sleek short bob hairstyle",
        "thin glasses",
        "refined Korean private tech secretary presence",
        "charcoal fitted suit continuity",
        "ivory blouse continuity",
        "professional pencil-skirt or refined business outfit silhouette",
        "premium private briefing mood",
    ],
    "must_not_copy": [
        "reference pose",
        "reference camera angle",
        "reference facial expression",
        "reference hand position",
        "reference tablet angle",
        "reference body orientation",
        "reference composition",
        "reference background layout",
    ],
    "variation_required": [
        "new pose",
        "new camera perspective",
        "new facial expression",
        "new private briefing gesture",
        "new tablet interaction",
        "program-specific office atmosphere",
    ],
}

WARDROBE_LOCK = {
    "wardrobe_role": "premium_private_tech_secretary_professional",
    "allowed": [
        "charcoal fitted suit",
        "ivory blouse",
        "pencil skirt",
        "refined business dress",
        "thin glasses",
        "tablet or briefing folder",
        "premium but not flashy styling",
        "glamorous but professional silhouette",
    ],
    "forbidden": [
        "news anchor outfit",
        "weathercaster outfit",
        "CEO power suit dominance",
        "casual office worker look",
        "evening dress",
        "fashion editorial styling",
        "excessive luxury styling",
        "overly revealing outfit",
        "seasonal wardrobe drift",
        "Tomorrow_Geenee weather presenter styling",
        "Today_Geenee wardrobe logic",
    ],
    "must_remain": [
        "private tech secretary",
        "professional briefing assistant",
        "premium office presence",
    ],
}

POSE_VARIATION_POLICY = {
    "variation_role": "required_non_reference_composition",
    "global_tech_allowed_variations": [
        "three-quarter angle beside the desk",
        "seated or half-standing near a briefing table",
        "leaning slightly toward the viewer as if giving a private briefing",
        "tablet angled toward the viewer",
        "one hand making a subtle briefing gesture",
        "calm confident expression with slight warmth",
        "over-the-shoulder office monitor depth",
        "premium daylight office with global tech briefing atmosphere",
    ],
    "korea_tech_allowed_variations": [
        "early-evening private office briefing",
        "slightly closer conversational angle",
        "tablet lowered while explaining a key signal",
        "subtle after-work briefing posture",
        "soft confident expression",
        "city-light window atmosphere",
        "premium Korean tech/startup briefing mood",
    ],
    "must_not": [
        "same front-facing standing pose",
        "same tablet held at same angle",
        "same neutral facial expression",
        "same centered camera composition",
        "same body crop as reference",
        "background-only variation",
    ],
}

SAFETY_CONSTRAINTS = {
    "no_collage": True,
    "no_split_screen": True,
    "no_text_overlay": True,
    "no_readable_ui_text": True,
    "no_fake_chart_text": True,
    "no_news_studio": True,
    "no_broadcast_desk": True,
    "no_weathercaster": True,
    "no_public_anchor": True,
}

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

VISUAL_TIME_BY_PROGRAM = {
    "keysuri_global_tech": "seoul_daytime_1230",
    "keysuri_korea_tech": "seoul_early_evening_1830",
}

IDENTITY_BLOCK = {
    "persona_name": "테크 비서 키수리",
    "role": "private_tech_secretary",
    "audience": (
        "Korean executives, founders, professionals, investors, freelancers, "
        "and business-minded users"
    ),
    "must_feel": [
        "private executive briefing",
        "premium office",
        "quietly intelligent",
        "competent",
        "personal technology insight assistant",
    ],
    "must_not_feel": [
        "news anchor",
        "announcer",
        "weathercaster",
        "public broadcast host",
        "TV newsroom",
    ],
}

WEATHER_VISUAL_USAGE = {
    "usage_type": "visual_realism_only",
    "must_affect": [
        "window light",
        "city atmosphere",
        "office lighting",
        "reflections",
        "wardrobe or props when relevant",
    ],
    "must_not_affect": [
        "persona identity",
        "product category",
        "news anchor framing",
        "weathercaster framing",
    ],
}


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


def _program_is_forbidden(program_id: str) -> bool:
    pid = (program_id or "").strip()
    if not pid:
        return True
    lower = pid.lower()
    return lower in {p.lower() for p in FORBIDDEN_PROGRAMS} or lower in (
        "tomorrow_geenee",
        "tomorrow_genie",
        "tomorrow",
    )


def _build_positive_prompt(program_id: str, visual_context: dict) -> str:
    """Build positive image prompt from weather-bound visual context."""
    bg = str(visual_context.get("background_direction") or "").strip()
    light = str(visual_context.get("lighting_direction") or "").strip()
    mood = str(visual_context.get("mood_direction") or "").strip()
    summary = str(visual_context.get("weather_visual_summary") or "").strip()
    props = str(visual_context.get("prop_direction") or "").strip()

    identity = (
        "Photorealistic premium Korean private tech secretary 테크 비서 키수리, sleek short bob hair, "
        "thin metal glasses, refined Korean facial impression, charcoal fitted suit, ivory blouse, "
        "professional pencil-skirt or refined business silhouette, premium private briefing mood, "
        "quietly intelligent competent private executive tech secretary, no public studio feeling, "
        "no public broadcast anchor or newsroom studio feeling"
    )

    if program_id == "keysuri_global_tech":
        program_bits = (
            "Daytime global tech private executive briefing, three-quarter or conversational "
            "private briefing angle beside the desk, new pose and camera perspective different "
            "from reference, tablet interaction angled toward the viewer with a subtle briefing "
            "gesture, calm confident expression with slight warmth, Seoul daytime cloudy window "
            "light affects daylight and window realism only, global tech big tech startup platform "
            "policy signal briefing mood, international business executive office atmosphere"
        )
    else:
        program_bits = (
            "Early-evening Korean tech startup private briefing, conversational after-work briefing "
            "angle slightly closer to the viewer, new pose and camera perspective different from "
            "reference, tablet lowered or briefing folder interaction different from reference, "
            "soft confident expression, Seoul early evening cloudy city tone affects city and window "
            "realism only, personal after-work premium office atmosphere"
        )

    parts = [
        identity,
        IDENTITY_ONLY_REFERENCE_CLAUSE,
        program_bits,
        summary,
        bg,
        light,
        mood,
        props,
    ]
    return ". ".join(p for p in parts if p)


def _build_negative_prompt() -> str:
    return ", ".join(REQUIRED_NEGATIVE_PHRASES)


def build_keysuri_weather_visual_prompt_contract(
    program_id: str,
    visual_context: dict,
) -> dict:
    """Build weather-aware image prompt contract for one Kee-Suri program."""
    pid = (program_id or "").strip()
    if _program_is_forbidden(pid):
        raise ValueError(f"Forbidden program for visual prompt contract: {program_id!r}")
    if pid not in KEYSURI_PROGRAMS:
        raise ValueError(f"Unknown program for visual prompt contract: {program_id!r}")
    if not isinstance(visual_context, dict):
        raise ValueError("visual_context must be a dict")

    source_mode = str(visual_context.get("source_mode") or "").strip()
    if source_mode != SOURCE_MODE:
        raise ValueError(f"visual_context.source_mode must be {SOURCE_MODE!r}")

    condition = str(visual_context.get("weather_condition") or "").strip()
    visual_time = str(
        visual_context.get("visual_time_context") or VISUAL_TIME_BY_PROGRAM[pid]
    ).strip()

    return {
        "program_id": pid,
        "prompt_contract_type": PROMPT_CONTRACT_TYPE,
        "source_mode": SOURCE_MODE,
        "runtime_binding_status": RUNTIME_BINDING_STATUS,
        "visual_time_context": visual_time,
        "weather_condition": condition,
        "location": LOCATION,
        "identity": dict(IDENTITY_BLOCK),
        "weather_visual_usage": dict(WEATHER_VISUAL_USAGE),
        "reference_usage_policy": dict(REFERENCE_USAGE_POLICY),
        "wardrobe_lock": dict(WARDROBE_LOCK),
        "pose_variation_policy": dict(POSE_VARIATION_POLICY),
        "positive_prompt": _build_positive_prompt(pid, visual_context),
        "negative_prompt": _build_negative_prompt(),
        "safety_constraints": dict(SAFETY_CONSTRAINTS),
        "side_effects": dict(SIDE_EFFECTS_DISABLED),
    }


def build_keysuri_weather_visual_prompt_contracts_from_integration_result(
    integration_result: dict,
) -> dict:
    """Build prompt contracts from Batch 8.15 weather binding integration result."""
    if str(integration_result.get("integration_status") or "") != "pass":
        raise ValueError("integration_result must have integration_status pass")

    contexts = integration_result.get("visual_contexts")
    if not isinstance(contexts, dict):
        raise ValueError("integration_result.visual_contexts must be a dict")

    contracts: Dict[str, dict] = {}
    for program_id in KEYSURI_PROGRAMS:
        if program_id not in contexts:
            raise ValueError(f"integration_result missing visual context for {program_id!r}")
        contracts[program_id] = build_keysuri_weather_visual_prompt_contract(
            program_id,
            contexts[program_id],
        )
    return contracts


def validate_keysuri_weather_visual_prompt_contract(contract: dict) -> List[dict]:
    """Validate a single prompt contract. Returns issue dicts (empty if ok)."""
    issues: List[dict] = []
    if not isinstance(contract, dict):
        issues.append(_issue("contract_invalid", "contract must be a dict", "contract"))
        return issues

    pid = str(contract.get("program_id") or "").strip()
    if pid not in KEYSURI_PROGRAMS:
        issues.append(_issue("program_id_invalid", f"program_id must be in {KEYSURI_PROGRAMS}", "program_id"))

    if contract.get("prompt_contract_type") != PROMPT_CONTRACT_TYPE:
        issues.append(
            _issue(
                "prompt_contract_type_invalid",
                f"prompt_contract_type must be {PROMPT_CONTRACT_TYPE!r}",
                "prompt_contract_type",
            )
        )

    if contract.get("source_mode") != SOURCE_MODE:
        issues.append(_issue("source_mode_invalid", f"source_mode must be {SOURCE_MODE!r}", "source_mode"))

    if contract.get("runtime_binding_status") != RUNTIME_BINDING_STATUS:
        issues.append(
            _issue(
                "runtime_binding_status_invalid",
                f"runtime_binding_status must be {RUNTIME_BINDING_STATUS!r}",
                "runtime_binding_status",
            )
        )

    if contract.get("location") != LOCATION:
        issues.append(_issue("location_invalid", f"location must be {LOCATION!r}", "location"))

    if str(contract.get("weather_condition") or "").strip() != "cloudy":
        issues.append(
            _issue(
                "weather_condition_invalid",
                "expected cloudy from canary lock fixture",
                "weather_condition",
            )
        )

    expected_vt = VISUAL_TIME_BY_PROGRAM.get(pid)
    if expected_vt and contract.get("visual_time_context") != expected_vt:
        issues.append(
            _issue(
                "visual_time_context_invalid",
                f"visual_time_context must be {expected_vt!r}",
                "visual_time_context",
            )
        )

    identity = contract.get("identity")
    if not isinstance(identity, dict):
        issues.append(_issue("identity_invalid", "identity must be a dict", "identity"))
    elif identity.get("persona_name") != IDENTITY_BLOCK["persona_name"]:
        issues.append(_issue("persona_name_invalid", "persona_name must be 테크 비서 키수리", "identity.persona_name"))
    elif identity.get("role") != "private_tech_secretary":
        issues.append(_issue("role_invalid", "role must be private_tech_secretary", "identity.role"))

    pos = str(contract.get("positive_prompt") or "")
    pos_lower = pos.lower()
    for term in FORBIDDEN_POSITIVE_IDENTITY:
        if term.lower() in pos_lower:
            issues.append(
                _issue(
                    "forbidden_identity_in_positive",
                    f"positive_prompt must not contain {term!r}",
                    "positive_prompt",
                )
            )

    neg = str(contract.get("negative_prompt") or "").lower()
    for phrase in REQUIRED_NEGATIVE_PHRASES:
        if phrase not in neg:
            issues.append(
                _issue(
                    "negative_prompt_missing_phrase",
                    f"negative_prompt must include {phrase!r}",
                    "negative_prompt",
                )
            )

    ref_policy = contract.get("reference_usage_policy")
    if not isinstance(ref_policy, dict):
        issues.append(
            _issue(
                "reference_usage_policy_missing",
                "reference_usage_policy must be a dict",
                "reference_usage_policy",
            )
        )
    elif ref_policy.get("reference_role") != "identity_and_wardrobe_continuity_only":
        issues.append(
            _issue(
                "reference_role_invalid",
                "reference_role must be identity_and_wardrobe_continuity_only",
                "reference_usage_policy.reference_role",
            )
        )
    else:
        for key in ("must_preserve", "must_not_copy", "variation_required"):
            if not isinstance(ref_policy.get(key), list) or not ref_policy.get(key):
                issues.append(
                    _issue(
                        "reference_usage_policy_list_invalid",
                        f"reference_usage_policy.{key} must be a non-empty list",
                        f"reference_usage_policy.{key}",
                    )
                )
        must_not_copy = {str(x).lower() for x in (ref_policy.get("must_not_copy") or [])}
        for required in (
            "reference pose",
            "reference camera angle",
            "reference facial expression",
            "reference hand position",
            "reference tablet angle",
            "reference composition",
        ):
            if required not in must_not_copy:
                issues.append(
                    _issue(
                        "must_not_copy_missing",
                        f"must_not_copy must include {required!r}",
                        "reference_usage_policy.must_not_copy",
                    )
                )

    wardrobe = contract.get("wardrobe_lock")
    if not isinstance(wardrobe, dict):
        issues.append(
            _issue(
                "wardrobe_lock_missing",
                "wardrobe_lock must be a dict",
                "wardrobe_lock",
            )
        )
    elif wardrobe.get("wardrobe_role") != "premium_private_tech_secretary_professional":
        issues.append(
            _issue(
                "wardrobe_role_invalid",
                "wardrobe_role must be premium_private_tech_secretary_professional",
                "wardrobe_lock.wardrobe_role",
            )
        )
    else:
        forbidden_wardrobe = " ".join(str(x).lower() for x in (wardrobe.get("forbidden") or []))
        for term in (
            "today_geenee wardrobe logic",
            "weathercaster outfit",
            "news anchor outfit",
        ):
            if term not in forbidden_wardrobe:
                issues.append(
                    _issue(
                        "wardrobe_forbidden_missing",
                        f"wardrobe_lock.forbidden must include {term!r}",
                        "wardrobe_lock.forbidden",
                    )
                )

    pose_policy = contract.get("pose_variation_policy")
    if not isinstance(pose_policy, dict):
        issues.append(
            _issue(
                "pose_variation_policy_missing",
                "pose_variation_policy must be a dict",
                "pose_variation_policy",
            )
        )
    elif pose_policy.get("variation_role") != "required_non_reference_composition":
        issues.append(
            _issue(
                "pose_variation_role_invalid",
                "variation_role must be required_non_reference_composition",
                "pose_variation_policy.variation_role",
            )
        )
    else:
        if pid == "keysuri_global_tech":
            global_vars = " ".join(
                str(x).lower() for x in (pose_policy.get("global_tech_allowed_variations") or [])
            )
            if "three-quarter" not in global_vars and "conversational" not in global_vars:
                issues.append(
                    _issue(
                        "global_variation_missing",
                        "global_tech_allowed_variations must include three-quarter or conversational angle",
                        "pose_variation_policy.global_tech_allowed_variations",
                    )
                )
        if pid == "keysuri_korea_tech":
            korea_vars = " ".join(
                str(x).lower() for x in (pose_policy.get("korea_tech_allowed_variations") or [])
            )
            if "early-evening" not in korea_vars and "conversational" not in korea_vars:
                issues.append(
                    _issue(
                        "korea_variation_missing",
                        "korea_tech_allowed_variations must include early-evening or conversational briefing",
                        "pose_variation_policy.korea_tech_allowed_variations",
                    )
                )
        must_not_pose = " ".join(str(x).lower() for x in (pose_policy.get("must_not") or []))
        if "background-only variation" not in must_not_pose:
            issues.append(
                _issue(
                    "pose_must_not_missing",
                    "must_not must include background-only variation",
                    "pose_variation_policy.must_not",
                )
            )

    if IDENTITY_ONLY_REFERENCE_CLAUSE.lower() not in pos_lower:
        issues.append(
            _issue(
                "identity_only_reference_clause_missing",
                "positive_prompt must include identity-only reference usage clause",
                "positive_prompt",
            )
        )
    if "do not copy the reference pose" not in pos_lower and "do not copy" not in pos_lower:
        issues.append(
            _issue(
                "no_copy_pose_clause_missing",
                "positive_prompt must forbid copying reference pose/composition",
                "positive_prompt",
            )
        )
    if "private tech secretary" not in pos_lower and "테크 비서" not in pos:
        issues.append(
            _issue(
                "private_secretary_identity_missing",
                "positive_prompt must include private tech secretary identity",
                "positive_prompt",
            )
        )
    for forbidden_phrase in FORBIDDEN_POSITIVE_COPY_PHRASES:
        if forbidden_phrase.lower() in pos_lower:
            issues.append(
                _issue(
                    "forbidden_copy_language_in_positive",
                    f"positive_prompt must not contain {forbidden_phrase!r}",
                    "positive_prompt",
                )
            )

    safety = contract.get("safety_constraints")
    if not isinstance(safety, dict):
        issues.append(_issue("safety_constraints_invalid", "safety_constraints must be a dict", "safety_constraints"))
    else:
        for key, expected in SAFETY_CONSTRAINTS.items():
            if safety.get(key) is not expected:
                issues.append(
                    _issue(
                        "safety_constraint_invalid",
                        f"safety_constraints.{key} must be {expected!r}",
                        f"safety_constraints.{key}",
                    )
                )

    side = contract.get("side_effects")
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

    if contract.get("ready_for_image_api_call") is True:
        issues.append(
            _issue(
                "ready_for_image_api_call_invalid",
                "contract must not set ready_for_image_api_call true",
                "ready_for_image_api_call",
            )
        )

    source_mode_val = str(contract.get("source_mode") or "")
    if source_mode_val in FORBIDDEN_SOURCE_MODES:
        issues.append(_issue("source_mode_forbidden", "forbidden source_mode", "source_mode"))

    texts: List[str] = []
    _collect_strings(contract, texts)
    blob_lower = "\n".join(texts).lower()
    for forbidden in FORBIDDEN_SECRET_SUBSTRINGS:
        if forbidden.lower() in blob_lower:
            issues.append(
                _issue(
                    "forbidden_secret_or_payload",
                    f"Must not contain {forbidden!r}",
                    "contract",
                )
            )

    return issues


def validate_keysuri_weather_visual_prompt_report(report: dict) -> List[dict]:
    """Validate full visual prompt integration report."""
    issues: List[dict] = []
    if not isinstance(report, dict):
        issues.append(_issue("report_invalid", "report must be a dict", "report"))
        return issues

    if report.get("report_type") != REPORT_TYPE:
        issues.append(
            _issue(
                "report_type_invalid",
                f"report_type must be {REPORT_TYPE!r}",
                "report_type",
            )
        )

    if str(report.get("integration_type") or "") != INTEGRATION_TYPE:
        issues.append(
            _issue(
                "integration_type_invalid",
                f"integration_type must be {INTEGRATION_TYPE!r}",
                "integration_type",
            )
        )

    if report.get("runtime_binding_status") != RUNTIME_BINDING_STATUS:
        issues.append(
            _issue(
                "runtime_binding_status_invalid",
                f"runtime_binding_status must be {RUNTIME_BINDING_STATUS!r}",
                "runtime_binding_status",
            )
        )

    if report.get("weather_context_source") != SOURCE_MODE:
        issues.append(
            _issue(
                "weather_context_source_invalid",
                f"weather_context_source must be {SOURCE_MODE!r}",
                "weather_context_source",
            )
        )

    if report.get("ready_for_image_api_call") is not False:
        issues.append(
            _issue(
                "ready_for_image_api_call_invalid",
                "ready_for_image_api_call must be false",
                "ready_for_image_api_call",
            )
        )
    if report.get("ready_for_scheduler") is not False:
        issues.append(_issue("ready_for_scheduler_invalid", "must be false", "ready_for_scheduler"))
    if report.get("ready_for_production_auto_call") is not False:
        issues.append(
            _issue(
                "ready_for_production_auto_call_invalid",
                "must be false",
                "ready_for_production_auto_call",
            )
        )

    side = report.get("side_effects")
    if isinstance(side, dict):
        for key, expected in SIDE_EFFECTS_DISABLED.items():
            if side.get(key) is not expected:
                issues.append(
                    _issue(
                        "side_effect_invalid",
                        f"side_effects.{key} must be {expected!r}",
                        f"side_effects.{key}",
                    )
                )

    contracts = report.get("prompt_contracts")
    if not isinstance(contracts, dict):
        issues.append(
            _issue("prompt_contracts_invalid", "prompt_contracts must be a dict", "prompt_contracts")
        )
        return issues

    for forbidden in FORBIDDEN_PROGRAMS:
        if forbidden in contracts:
            issues.append(
                _issue(
                    "forbidden_program_present",
                    f"Must not include prompt for {forbidden!r}",
                    "prompt_contracts",
                )
            )

    for program_id in KEYSURI_PROGRAMS:
        if program_id not in contracts:
            issues.append(
                _issue(
                    "prompt_contract_missing",
                    f"prompt_contracts must include {program_id!r}",
                    "prompt_contracts",
                )
            )
        else:
            issues.extend(
                validate_keysuri_weather_visual_prompt_contract(contracts[program_id])
            )

    texts: List[str] = []
    _collect_strings(report, texts)
    blob_lower = "\n".join(texts).lower()
    for forbidden in FORBIDDEN_SECRET_SUBSTRINGS:
        if forbidden.lower() in blob_lower:
            issues.append(
                _issue(
                    "forbidden_secret_or_payload",
                    f"Must not contain {forbidden!r}",
                    "report",
                )
            )
    if "tomorrow_geenee" in blob_lower and "no tomorrow_geenee" not in blob_lower:
        issues.append(_issue("forbidden_retired", "Tomorrow_Geenee in report", "report"))
    if re.search(r"\b18:00\b", blob_lower):
        issues.append(_issue("forbidden_scheduler", "standalone 18:00 in report", "report"))

    return issues


def build_keysuri_weather_visual_prompt_report_from_canary_lock(lock_path: str) -> dict:
    """Build full visual prompt integration report from sanitized canary lock."""
    integration_result = build_keysuri_weather_binding_integration_report(lock_path)
    issues: List[dict] = []

    if integration_result.get("integration_status") != "pass":
        issues.append(
            _issue(
                "integration_not_pass",
                "weather binding integration must pass before prompt integration",
                "integration_result",
            )
        )
        prompt_contracts: Dict[str, dict] = {}
    else:
        try:
            prompt_contracts = build_keysuri_weather_visual_prompt_contracts_from_integration_result(
                integration_result
            )
        except ValueError as exc:
            issues.append(_issue("prompt_contract_build_failed", str(exc), "prompt_contracts"))
            prompt_contracts = {}

    report: Dict[str, Any] = {
        "report_type": REPORT_TYPE,
        "report_status": "pass",
        "integration_type": INTEGRATION_TYPE,
        "runtime_binding_status": RUNTIME_BINDING_STATUS,
        "weather_context_source": SOURCE_MODE,
        "prompt_contracts": prompt_contracts,
        "ready_for_image_api_call": False,
        "ready_for_scheduler": False,
        "ready_for_production_auto_call": False,
        "side_effects": dict(SIDE_EFFECTS_DISABLED),
        "issues": issues,
    }

    validation_issues = validate_keysuri_weather_visual_prompt_report(report)
    issues.extend(validation_issues)
    report["issues"] = issues
    report["report_status"] = (
        "pass"
        if not issues and len(prompt_contracts) == len(KEYSURI_PROGRAMS)
        else "blocked"
    )
    return report
