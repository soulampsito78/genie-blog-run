"""Kee-Suri R5E manual canary-only failure-history (v3 — REVIEW_NOT_ACCEPTED, not production resolver)."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Dict, List

from keysuri_r5d_manual_canary import check_r5d_default_prompt_unchanged
from keysuri_weather_binding_integration import build_keysuri_weather_binding_integration_report
from keysuri_weather_visual_prompt_integration import _GLOBAL_SCENE_WEATHER_STEM

VISUAL_QA_STATUS = "REVIEW_NOT_ACCEPTED"

R5E_APPROVED_STRUCTURE_VARIATION_PASS = "R5E_APPROVED_STRUCTURE_VARIATION_PASS"
ENV_R5E_STRUCTURE_VARIATION = "GENIE_KEYSURI_R5E_STRUCTURE_VARIATION"
R5E_PALETTE_VERSION = "v3"
R5E_PROFILE_V3_01 = "profile_v3_01_navy_tie_neck_secretary"

R5E_WARDROBE_CLAUSE_V3_01 = (
    "Deep navy fitted blazer with an ivory tie-neck silk blouse with a clearly visible tied "
    "neck detail, charcoal pencil skirt, slim silver watch, holding a thin executive document "
    "folder instead of a tablet, premium Korean executive secretary briefing look."
)

R5E_CANARY_PROFILES: Dict[str, dict] = {
    R5E_PROFILE_V3_01: {
        "wardrobe_profile_id": R5E_PROFILE_V3_01,
        "wardrobe_clause": R5E_WARDROBE_CLAUSE_V3_01,
        "wardrobe_palette_version": R5E_PALETTE_VERSION,
        "visual_qa_status": "REVIEW_NOT_ACCEPTED",
        "visual_qa_reason": (
            "Tie-neck detail appeared, but dark blazer / tablet-like prop pattern remained "
            "too close; not accepted."
        ),
    },
}

R5E_REFERENCE_IDENTITY_ONLY = (
    "Use reference image for face, hair, and glasses identity continuity only — "
    "do not copy the reference outfit, pose, or composition."
)
R5E_IDENTITY_VARIATION_BLOCK = "Same Kee-Suri identity, not same image."
R5E_ANTI_REPEAT_STRUCTURE_BLOCK = (
    "Do not repeat the previous dark blazer and pale blouse outfit structure."
)
R5E_BLOUSE_STRUCTURE_BLOCK = (
    "Visible tie-neck blouse detail must be clear at neck and chest."
)
R5E_PROP_POSE_BLOCK = (
    "Hold a thin executive document folder instead of a tablet as the primary hand prop. "
    "Natural variation in pose and camera angle is allowed within a premium private briefing. "
    "Hands must remain natural and simple."
)
R5E_EXPRESSION_BLOCK = (
    "Calm intelligent expression with subtle life, not blank or stiff."
)
R5E_MOOD_BLOCK = (
    "Composed Korean executive secretary briefing. Premium private office briefing composition, "
    "not fashion editorial. Private AI tech secretary — not public news anchor, not CEO portrait, "
    "not weathercaster, not lounge or glamour shoot."
)

R5E_NEGATIVE_PHRASES = (
    "not a public news anchor",
    "not a weathercaster",
    "not a ceo portrait",
    "not fashion editorial",
    "not a glamour shoot",
    "not a lounge shoot",
    "no tablet held up as primary prop",
    "no collage",
    "no split screen",
    "no readable text overlay",
    "no pointing finger",
    "no distorted hands",
    "no extra fingers",
    "no identity drift",
    "not a different woman with similar clothes only",
)

R5E_FORBIDDEN_CONTINUITY_PHRASES = (
    "charcoal fitted suit continuity",
    "ivory or soft cream blouse continuity",
    "charcoal fitted suit, ivory or soft cream blouse",
    "wardrobe continuity only",
    "do not require large pose or composition change",
    "minimal_micro",
    "tablet held simply at waist",
)


@dataclass(frozen=True)
class R5ECanaryTarget:
    wardrobe_date_kst: str
    program_id: str
    wardrobe_profile_id: str
    daily_wardrobe_seed: str
    wardrobe_clause: str
    wardrobe_palette_version: str
    visual_qa_status: str
    visual_qa_reason: str


def is_r5e_v3_profile_id(profile_id: str) -> bool:
    pid = (profile_id or "").strip()
    return pid.startswith("profile_v3_")


def build_r5e_daily_wardrobe_seed(wardrobe_date_kst: str, wardrobe_profile_id: str) -> str:
    return f"keysuri_daily|{wardrobe_date_kst}|{R5E_PALETTE_VERSION}|{wardrobe_profile_id}"


def resolve_r5e_canary_target(
    *,
    wardrobe_date_kst: str,
    program_id: str,
    wardrobe_profile_id: str,
    expected_daily_wardrobe_seed: str,
) -> tuple[R5ECanaryTarget | None, List[str]]:
    issues: List[str] = []
    profile_id = (wardrobe_profile_id or "").strip()
    if profile_id not in R5E_CANARY_PROFILES:
        issues.append(f"[blocked_unknown_r5e_profile] profile {profile_id!r} is not in R5E canary catalog")
        return None, issues

    expected_seed = build_r5e_daily_wardrobe_seed(wardrobe_date_kst, profile_id)
    if (expected_daily_wardrobe_seed or "").strip() != expected_seed:
        issues.append(
            "[blocked_r5e_seed_mismatch] expected_daily_wardrobe_seed must match R5E canary seed format"
        )
        return None, issues

    profile = R5E_CANARY_PROFILES[profile_id]
    return R5ECanaryTarget(
        wardrobe_date_kst=wardrobe_date_kst,
        program_id=program_id,
        wardrobe_profile_id=profile_id,
        daily_wardrobe_seed=expected_seed,
        wardrobe_clause=str(profile["wardrobe_clause"]),
        wardrobe_palette_version=str(profile["wardrobe_palette_version"]),
        visual_qa_status=str(profile["visual_qa_status"]),
        visual_qa_reason=str(profile["visual_qa_reason"]),
    ), []


def build_r5e_positive_prompt(
    program_id: str,
    visual_context: dict,
    *,
    wardrobe_clause: str,
) -> str:
    if program_id != "keysuri_global_tech":
        raise ValueError("R5E manual canary MVP supports keysuri_global_tech only")

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
        R5E_REFERENCE_IDENTITY_ONLY,
        R5E_IDENTITY_VARIATION_BLOCK,
        R5E_ANTI_REPEAT_STRUCTURE_BLOCK,
        R5E_BLOUSE_STRUCTURE_BLOCK,
        wardrobe_clause.strip(),
        R5E_EXPRESSION_BLOCK,
        R5E_PROP_POSE_BLOCK,
        R5E_MOOD_BLOCK,
        "Premium office layout may vary — desk, window, and monitor arrangement may differ from prior images.",
        _GLOBAL_SCENE_WEATHER_STEM,
        summary,
        bg,
        light,
        mood,
        props,
    ]
    return ". ".join(p for p in parts if p)


def build_r5e_negative_prompt() -> str:
    return ", ".join(R5E_NEGATIVE_PHRASES)


def build_r5e_opt_in_prompt_source(
    *,
    lock_path: str,
    program_id: str,
    wardrobe_date_kst: str,
    wardrobe_profile_id: str,
    daily_wardrobe_seed: str,
) -> dict:
    target, issues = resolve_r5e_canary_target(
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
    positive = build_r5e_positive_prompt(
        program_id,
        ctx,
        wardrobe_clause=target.wardrobe_clause,
    )
    return {
        "source": "keysuri_r5e_manual_structure_variation",
        "program_id": program_id,
        "positive_prompt": positive,
        "negative_prompt": build_r5e_negative_prompt(),
        "wardrobe_date_kst": wardrobe_date_kst,
        "wardrobe_profile_id": target.wardrobe_profile_id,
        "daily_wardrobe_seed": target.daily_wardrobe_seed,
        "wardrobe_palette_version": target.wardrobe_palette_version,
        "wardrobe_prompt_injected": True,
        "r5e_structure_variation": True,
        "variation_mode": "controlled_outfit_structure",
    }


def validate_r5e_positive_prompt(positive_prompt: str) -> List[str]:
    issues: List[str] = []
    lower = (positive_prompt or "").lower()
    required = (
        "same kee-suri identity, not same image",
        "do not repeat the previous dark blazer and pale blouse outfit structure",
        "tie-neck",
        "tied neck detail",
        "deep navy",
        "executive document folder",
        "instead of a tablet",
        "charcoal pencil skirt",
        "slim silver watch",
        "calm intelligent expression with subtle life",
        "premium private office briefing",
        "private ai tech secretary",
    )
    for phrase in required:
        if phrase not in lower:
            issues.append(f"missing required R5E phrase: {phrase!r}")
    for phrase in R5E_FORBIDDEN_CONTINUITY_PHRASES:
        if phrase in lower:
            issues.append(f"forbidden R5E continuity phrase present: {phrase!r}")
    return issues


check_r5e_default_prompt_unchanged = check_r5d_default_prompt_unchanged
