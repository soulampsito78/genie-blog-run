"""Kee-Suri R5D manual canary-only failure-history (v2 — NOT_ACCEPTED, not production resolver)."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Dict, List

from keysuri_weather_binding_integration import build_keysuri_weather_binding_integration_report
from keysuri_weather_visual_prompt_integration import (
    _GLOBAL_SCENE_WEATHER_STEM,
    build_keysuri_weather_visual_prompt_contract,
)

VISUAL_QA_STATUS = "NOT_ACCEPTED"

R5D_APPROVED_MANUAL_OVERRIDE_PASS = "R5D_APPROVED_MANUAL_OVERRIDE_PASS"
ENV_R5D_CREATIVE_VARIATION = "GENIE_KEYSURI_R5D_CREATIVE_VARIATION"
R5D_PALETTE_VERSION = "v2"
R5D_PROFILE_V2_01 = "profile_v2_01_deep_navy_cream_silver"

R5D_WARDROBE_CLAUSE_V2_01 = (
    "Deep navy tailored suit with warm cream silk blouse and a small silver brooch, "
    "pencil skirt, fitted premium private tech secretary silhouette."
)

R5D_CANARY_PROFILES: Dict[str, dict] = {
    R5D_PROFILE_V2_01: {
        "wardrobe_profile_id": R5D_PROFILE_V2_01,
        "wardrobe_clause": R5D_WARDROBE_CLAUSE_V2_01,
        "wardrobe_palette_version": R5D_PALETTE_VERSION,
        "visual_qa_status": "NOT_ACCEPTED",
        "visual_qa_reason": (
            "Deep navy / cream / brooch still rendered as dark blazer + pale blouse; "
            "structure delta failed."
        ),
    },
}

R5D_IDENTITY_VARIATION_BLOCK = (
    "Same Kee-Suri identity, not same image. Clear wardrobe variation from the previous "
    "charcoal suit look."
)
R5D_REFERENCE_IDENTITY_ONLY = (
    "Use reference image for face, hair, and glasses identity continuity only — "
    "not outfit copy, not pose copy, not composition copy."
)
R5D_POSE_VARIATION_BLOCK = (
    "Natural variation in pose and angle is allowed within a premium private briefing. "
    "Tablet may be held, lowered, or resting near her hands. Hands must remain natural "
    "and simple."
)
R5D_EXPRESSION_BLOCK = (
    "Calm intelligent expression with subtle life, not blank or stiff."
)
R5D_MOOD_BLOCK = (
    "Premium office briefing composition, not fashion editorial. Private AI tech secretary — "
    "not public news anchor, not CEO portrait, not weathercaster, not lounge or glamour shoot."
)

R5D_NEGATIVE_PHRASES = (
    "not a public news anchor",
    "not a weathercaster",
    "not a ceo portrait",
    "not fashion editorial",
    "not a glamour shoot",
    "not a lounge shoot",
    "no collage",
    "no split screen",
    "no readable text overlay",
    "no pointing finger",
    "no tapping tablet",
    "no distorted hands",
    "no extra fingers",
    "no identity drift",
    "not a different woman with similar clothes only",
)

R5D_FORBIDDEN_CONTINUITY_PHRASES = (
    "charcoal fitted suit continuity",
    "ivory or soft cream blouse continuity",
    "charcoal fitted suit, ivory or soft cream blouse",
    "do not require large pose or composition change",
    "minimal_micro",
    "wardrobe continuity only",
)


@dataclass(frozen=True)
class R5DCanaryTarget:
    wardrobe_date_kst: str
    program_id: str
    wardrobe_profile_id: str
    daily_wardrobe_seed: str
    wardrobe_clause: str
    wardrobe_palette_version: str
    visual_qa_status: str
    visual_qa_reason: str


def is_r5d_v2_profile_id(profile_id: str) -> bool:
    pid = (profile_id or "").strip()
    return pid.startswith("profile_v2_")


def build_r5d_daily_wardrobe_seed(wardrobe_date_kst: str, wardrobe_profile_id: str) -> str:
    return f"keysuri_daily|{wardrobe_date_kst}|{R5D_PALETTE_VERSION}|{wardrobe_profile_id}"


def resolve_r5d_canary_target(
    *,
    wardrobe_date_kst: str,
    program_id: str,
    wardrobe_profile_id: str,
    expected_daily_wardrobe_seed: str,
) -> tuple[R5DCanaryTarget | None, List[str]]:
    issues: List[str] = []
    profile_id = (wardrobe_profile_id or "").strip()
    if profile_id not in R5D_CANARY_PROFILES:
        issues.append(f"[blocked_unknown_r5d_profile] profile {profile_id!r} is not in R5D canary catalog")
        return None, issues

    expected_seed = build_r5d_daily_wardrobe_seed(wardrobe_date_kst, profile_id)
    if (expected_daily_wardrobe_seed or "").strip() != expected_seed:
        issues.append(
            "[blocked_r5d_seed_mismatch] expected_daily_wardrobe_seed must match R5D canary seed format"
        )
        return None, issues

    profile = R5D_CANARY_PROFILES[profile_id]
    return R5DCanaryTarget(
        wardrobe_date_kst=wardrobe_date_kst,
        program_id=program_id,
        wardrobe_profile_id=profile_id,
        daily_wardrobe_seed=expected_seed,
        wardrobe_clause=str(profile["wardrobe_clause"]),
        wardrobe_palette_version=str(profile["wardrobe_palette_version"]),
        visual_qa_status=str(profile["visual_qa_status"]),
        visual_qa_reason=str(profile["visual_qa_reason"]),
    ), []


def build_r5d_positive_prompt(
    program_id: str,
    visual_context: dict,
    *,
    wardrobe_clause: str,
) -> str:
    if program_id != "keysuri_global_tech":
        raise ValueError("R5D manual canary MVP supports keysuri_global_tech only")

    summary = str(visual_context.get("weather_visual_summary") or "").strip()
    bg = str(visual_context.get("background_direction") or "").strip()
    light = str(visual_context.get("lighting_direction") or "").strip()
    mood = str(visual_context.get("mood_direction") or "").strip()
    props = str(visual_context.get("prop_direction") or "").strip()

    identity_prefix = (
        "Photorealistic premium Korean private tech secretary Kee-Suri (테크 비서 키수리). "
        "Refined Korean facial impression, sleek short bob, thin metal glasses, "
        "mature professional age, mid-to-late 30s professional impression. "
    )
    parts = [
        identity_prefix,
        R5D_REFERENCE_IDENTITY_ONLY,
        R5D_IDENTITY_VARIATION_BLOCK,
        wardrobe_clause.strip(),
        R5D_EXPRESSION_BLOCK,
        R5D_POSE_VARIATION_BLOCK,
        R5D_MOOD_BLOCK,
        _GLOBAL_SCENE_WEATHER_STEM,
        summary,
        bg,
        light,
        mood,
        props,
    ]
    return ". ".join(p for p in parts if p)


def build_r5d_negative_prompt() -> str:
    return ", ".join(R5D_NEGATIVE_PHRASES)


def build_r5d_opt_in_prompt_source(
    *,
    lock_path: str,
    program_id: str,
    wardrobe_date_kst: str,
    wardrobe_profile_id: str,
    daily_wardrobe_seed: str,
) -> dict:
    target, issues = resolve_r5d_canary_target(
        wardrobe_date_kst=wardrobe_date_kst,
        program_id=program_id,
        wardrobe_profile_id=wardrobe_profile_id,
        expected_daily_wardrobe_seed=daily_wardrobe_seed,
    )
    if target is None:
        raise ValueError("; ".join(issues))

    integration = build_keysuri_weather_binding_integration_report(lock_path)
    contexts = integration.get("visual_contexts") or {}
    if program_id not in contexts:
        raise ValueError(f"lock fixture missing visual context for {program_id!r}")

    ctx = deepcopy(contexts[program_id])
    ctx["weather_date"] = wardrobe_date_kst
    positive = build_r5d_positive_prompt(
        program_id,
        ctx,
        wardrobe_clause=target.wardrobe_clause,
    )
    return {
        "source": "keysuri_r5d_manual_creative_variation",
        "program_id": program_id,
        "positive_prompt": positive,
        "negative_prompt": build_r5d_negative_prompt(),
        "wardrobe_date_kst": wardrobe_date_kst,
        "wardrobe_profile_id": target.wardrobe_profile_id,
        "daily_wardrobe_seed": target.daily_wardrobe_seed,
        "wardrobe_palette_version": target.wardrobe_palette_version,
        "wardrobe_prompt_injected": True,
        "r5d_creative_variation": True,
        "variation_mode": "controlled_creative",
    }


def validate_r5d_positive_prompt(positive_prompt: str) -> List[str]:
    issues: List[str] = []
    lower = (positive_prompt or "").lower()
    required = (
        "deep navy",
        "cream silk",
        "silver brooch",
        "same kee-suri identity, not same image",
        "clear wardrobe variation from the previous charcoal suit look",
        "natural variation in pose and angle",
        "tablet may be held, lowered, or resting near her hands",
        "calm intelligent expression with subtle life",
        "premium office briefing composition, not fashion editorial",
        "private ai tech secretary",
    )
    for phrase in required:
        if phrase not in lower:
            issues.append(f"missing required R5D phrase: {phrase!r}")
    for phrase in R5D_FORBIDDEN_CONTINUITY_PHRASES:
        if phrase in lower:
            issues.append(f"forbidden R5D continuity phrase present: {phrase!r}")
    return issues


def check_r5d_default_prompt_unchanged(lock_path: str, program_id: str, wardrobe_date_kst: str) -> bool:
    integration = build_keysuri_weather_binding_integration_report(lock_path)
    contexts = integration.get("visual_contexts") or {}
    ctx = deepcopy(contexts[program_id])
    ctx["weather_date"] = wardrobe_date_kst
    default_contract = build_keysuri_weather_visual_prompt_contract(
        program_id,
        ctx,
        use_daily_wardrobe_prompt_snippet=False,
    )
    daily = default_contract.get("daily_wardrobe") or {}
    return daily.get("wardrobe_prompt_injected") is not True
