"""Kee-Suri weather-bound visual prompt contract integration (offline — no image API)."""
from __future__ import annotations

import re
from typing import Any, Dict, List

from genie_runtime_weather_binding import RUNTIME_BINDING_STATUS
from keysuri_daily_wardrobe_resolver import resolve_keysuri_daily_wardrobe
from keysuri_top_image_variation import (
    OUTFIT_VARIANTS,
    PROGRAM_VISUAL_CONTEXT,
    resolve_keysuri_top_image_variation,
)
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
    "not a public news anchor",
    "not a weathercaster",
    "not a ceo portrait",
    "not a generic office worker",
    "no collage",
    "no split screen",
    "no readable text overlay",
    "no fake readable ui text",
    "no pointing finger",
    "no tapping tablet",
    "no stylus",
    "no dramatic gesture",
    "no distorted hands",
    "no extra fingers",
    "no newsroom",
    "no broadcast desk",
    "no tv studio",
    "no umbrella",
    "no raincoat",
    "no today_geenee wardrobe logic",
    "not a different woman with similar clothes only",
    "no tomorrow_geenee",
    "no age label",
    "no ceo or chairwoman or senior executive framing",
    "no boardroom authority portrait",
    "no fashion model styling",
)

KOREA_EXTRA_NEGATIVE_PHRASES = (
    "bright cloudy daytime",
    "white-night office",
    "daylight-looking dusk",
    "black night",
    "cinematic noir",
    "hotel lounge",
    "bar lounge",
    "fashion editorial",
    "seductive night scene",
    "outdoor weather scene",
)

FORBIDDEN_KOREA_DAYLIGHT_POSITIVE_PHRASES = (
    "city lights just beginning",
    "blue-gray seoul dusk",
    "early evening 18:30",
    "seoul dusk outside",
)

REQUIRED_PRODUCTION_POSITIVE_PHRASES = (
    "same person as the reference",
    "same kee-suri identity",
    "small natural variation",
    "do not require large pose or composition change",
    "no pointing",
    "weather affects window light and atmosphere only",
)

REQUIRED_GLOBAL_POSITIVE_PHRASES = (
    "daytime or early afternoon",
    "tablet held simply",
    "relaxed hands",
    "fingers mostly hidden",
)

REQUIRED_KOREA_POSITIVE_PHRASES = (
    "winter 18:30",
    "after-sunset",
    "sun has already set",
    "deep blue-gray seoul evening city",
    "city lights already visible but not flashy",
    "warm premium interior office light",
    "calm after-work private briefing",
    "face clearly lit",
    "must not darken",
    "organized after-work private briefing",
    "tablet is optional",
    "hands calmly clasped",
    "already been organized",
    "ready to brief",
)

FORBIDDEN_POSITIVE_AGGRESSIVE_PHRASES = (
    "new pose and camera perspective",
    "new private briefing gesture",
    "subtle briefing gesture",
    "dramatic pose",
    "dramatic composition",
    "require dramatic",
    "pointing finger",
    "tapping tablet",
    "hand over the screen",
    "stylus",
    "one hand making a subtle briefing gesture",
    "tablet interaction angled toward the viewer",
)

PRODUCTION_REFERENCE_PARAGRAPH = (
    "Use reference image 01 for face, hair, glasses, and wardrobe continuity only. "
    "Keep the same Kee-Suri identity; small natural variation in head angle, gaze, "
    "and shoulder orientation is OK. Do not require large pose or composition change."
)

# Back-compat alias for tests importing the old constant name.
IDENTITY_ONLY_REFERENCE_CLAUSE = PRODUCTION_REFERENCE_PARAGRAPH

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

VARIATION_MODE = "minimal_micro"
POSE_POLICY = "calm_briefing_stable_tablet"
HAND_POLICY = "simple_edge_grip_no_gesture"
KOREA_POSE_POLICY = "calm_briefing_optional_tablet"
KOREA_HAND_POLICY = "calmly_clasped_or_simple_relaxed"
KOREA_TABLET_POLICY = "optional_or_absent"
KOREA_TIME_PROFILE = "winter_1830_after_sunset_blue_gray_warm_interior"
KOREA_MOOD = "organized_after_work_private_briefing"
SCENE_POLICY = "premium_private_office_moderate"
WEATHER_POLICY = "window_light_haze_only"

REFERENCE_USAGE_POLICY = {
    "reference_role": "identity_and_wardrobe_continuity_only",
    "variation_mode": VARIATION_MODE,
    "must_preserve": [
        "same Kee-Suri person as reference",
        "refined Korean facial impression",
        "sleek short bob hairstyle",
        "thin metal glasses",
        "calm attentive intelligent gaze",
        "private AI tech briefing secretary role",
        "one-person private briefing distance and mood",
        # Identity is preserved by face/hair/glasses/gaze/role — NOT by a single
        # locked outfit. The wardrobe may vary per run within refined private
        # tech secretary office styling; outfit must not define the identity.
        "premium private tech secretary wardrobe continuity within refined office palette",
        "premium private tech secretary presence",
    ],
    "must_not_copy": [
        "exact reference clone pose and composition",
    ],
    "variation_allowed": [
        "small head angle change",
        "small gaze shift",
        "small shoulder orientation change",
        "moderate private office layout",
        "window sky tone and mild city haze",
    ],
}

WARDROBE_LOCK = {
    "wardrobe_role": "premium_private_tech_secretary_professional",
    "allowed": [
        "charcoal fitted suit",
        "ivory or soft cream blouse",
        "pencil skirt",
        "refined business silhouette",
        "thin glasses",
        "tablet as briefing prop only",
        "premium understated styling",
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
        "umbrella",
        "raincoat",
        "seasonal outdoor weather gear",
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
    "variation_role": POSE_POLICY,
    "pose_policy": POSE_POLICY,
    "hand_policy": HAND_POLICY,
    "scene_policy": SCENE_POLICY,
    "weather_policy": WEATHER_POLICY,
    "global_tech_allowed_variations": [
        "standing or slight three-quarter private briefing stance",
        "tablet at waist with simple edge grip",
        "small head angle or gaze shift",
        "moderate premium office desk and window layout",
    ],
    "korea_tech_allowed_variations": [
        "standing or slight three-quarter private briefing stance",
        "winter 18:30 after-sunset blue-gray Seoul evening through windows",
        "city lights already visible but not flashy",
        "warm premium interior office light",
        "hands calmly clasped at waist or simple relaxed posture",
        "tablet optional or absent",
        "small head angle or gaze shift",
    ],
    "must_not": [
        "pointing finger",
        "tapping tablet",
        "stylus",
        "hand over tablet screen",
        "dramatic gesture",
        "background-only identity loss",
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
        "sky tone and haze",
    ],
    "must_not_affect": [
        "persona identity",
        "wardrobe",
        "pose",
        "role identity",
        "accessories",
        "indoor scene type",
        "news anchor framing",
        "weathercaster framing",
    ],
}


def _issue(code: str, message: str, path: str) -> Dict[str, str]:
    return {"code": code, "message": message, "path": path}


def _positive_contains_unnegated_phrase(pos_lower: str, phrase: str) -> bool:
    """True if phrase appears outside common negation prefixes."""
    needle = phrase.lower()
    if needle not in pos_lower:
        return False
    for prefix in ("not ", "no ", "avoid ", "without ", "never "):
        if prefix + needle in pos_lower:
            return False
    return True


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


_PRODUCTION_IDENTITY_PREFIX = (
    "Photorealistic premium Korean private tech secretary Kee-Suri (테크 비서 키수리). "
    "Same person as the reference: refined Korean facial impression, sleek short bob, "
    "thin metal glasses, calm intelligent gaze. "
)
_DEFAULT_WARDROBE_CLAUSE = (
    "Charcoal fitted suit, ivory or soft cream blouse, pencil skirt, premium private "
    "tech briefing mood."
)
_PRODUCTION_IDENTITY_SUFFIX = (
    " Quiet, competent private executive secretary — not public "
    "broadcast, not public anchor presentation, not weather-presenter styling"
)


def _build_production_identity_stem(wardrobe_clause: str | None = None) -> str:
    clause = _DEFAULT_WARDROBE_CLAUSE if wardrobe_clause is None else wardrobe_clause.strip()
    if not clause:
        raise ValueError("empty_wardrobe_clause")
    return f"{_PRODUCTION_IDENTITY_PREFIX}{clause}{_PRODUCTION_IDENTITY_SUFFIX}"


_PRODUCTION_IDENTITY_STEM = _build_production_identity_stem()

_GLOBAL_POSE_HAND_STEM = (
    "Calm private briefing in a premium office: standing or slight three-quarter, "
    "tablet held simply at waist or low chest with relaxed hands on the edge, fingers "
    "mostly hidden or naturally curled. Keep hands simple with no pointing, tapping, "
    "or screen-covering gestures"
)

_KOREA_POSE_HAND_STEM = (
    "Calm private briefing in a premium office: standing or slight three-quarter. "
    "Tablet is optional or may be absent for the Korea evening profile. Kee-Suri may "
    "stand with hands calmly clasped at the waist or with a simple relaxed hand posture, "
    "as if the key domestic tech signals have already been organized and she is ready "
    "to brief — not handing work to the user. Keep hands simple with no pointing, tapping, "
    "or screen-covering gestures; avoid complex finger exposure"
)

_GLOBAL_SCENE_WEATHER_STEM = (
    "Premium private office with large windows, desk and monitor with abstract "
    "non-readable charts. Daytime or early afternoon, Seoul-like cloudy overcast "
    "light: soft diffused daylight, grey sky, mild city haze through the window. "
    "Weather affects window light and atmosphere only — not outfit, pose, or role. "
    "Global tech executive briefing mood, "
    "understated and professional"
)

_KOREA_SCENE_WEATHER_STEM = (
    "Premium private office with large windows, desk and monitor with abstract "
    "non-readable charts. Winter 18:30 after-sunset Korean tech briefing mood: the sun "
    "has already set outside the office windows, deep blue-gray Seoul evening city, "
    "city lights already visible but not flashy, warm premium interior office light, "
    "calm after-work private briefing atmosphere, subdued but not gloomy. "
    "Keep Kee-Suri's face clearly lit and premium; the evening mood must not darken, "
    "muddy, or soften the face. Weather affects window light and atmosphere only — not "
    "outfit, pose, or role. Time and sky affect window light, city haze, sky tone, and "
    "interior ambience only. Korean tech and startup platform briefing mood, understated "
    "and professional — organized after-work private briefing"
)


def _extract_wardrobe_prompt_clause(prompt_snippet: str) -> str:
    snippet = (prompt_snippet or "").strip()
    if not snippet:
        raise ValueError("empty_wardrobe_prompt_snippet")
    if ". Same private" in snippet:
        clause = snippet.split(". Same private", 1)[0].strip()
    else:
        clause = snippet.split(".", 1)[0].strip()
    if not clause:
        raise ValueError("empty_wardrobe_prompt_clause")
    if not clause.endswith("."):
        clause = f"{clause}."
    return clause


def _build_positive_prompt(
    program_id: str,
    visual_context: dict,
    *,
    wardrobe_clause: str | None = None,
) -> str:
    """Build production-stable positive prompt from weather-bound visual context."""
    bg = str(visual_context.get("background_direction") or "").strip()
    light = str(visual_context.get("lighting_direction") or "").strip()
    mood = str(visual_context.get("mood_direction") or "").strip()
    summary = str(visual_context.get("weather_visual_summary") or "").strip()
    props = str(visual_context.get("prop_direction") or "").strip()

    if program_id == "keysuri_global_tech":
        pose_hand = _GLOBAL_POSE_HAND_STEM
        scene_weather = _GLOBAL_SCENE_WEATHER_STEM
    else:
        pose_hand = _KOREA_POSE_HAND_STEM
        scene_weather = _KOREA_SCENE_WEATHER_STEM

    identity_stem = _build_production_identity_stem(wardrobe_clause)
    parts = [
        identity_stem,
        PRODUCTION_REFERENCE_PARAGRAPH,
        pose_hand,
        scene_weather,
        summary,
        bg,
        light,
        mood,
        props,
    ]
    return ". ".join(p for p in parts if p)


def _build_negative_prompt(program_id: str) -> str:
    phrases = list(REQUIRED_NEGATIVE_PHRASES)
    if program_id == "keysuri_korea_tech":
        phrases.extend(KOREA_EXTRA_NEGATIVE_PHRASES)
    return ", ".join(phrases)


# --- Production top image prompt (diversified, identity-locked, age-free) -------
# This is the prompt the live owner-review run actually sends. It is separate from
# the design-report contract above: it injects the deterministic daily wardrobe +
# pose/prop/background/camera/lighting variation and the program visual context,
# while keeping the fixed identity lock (face / short bob / thin glasses / role).
_PRODUCTION_TOP_IMAGE_IDENTITY = (
    "Photorealistic premium Korean private AI tech briefing secretary Kee-Suri "
    "(테크 비서 키수리). Same person as the reference image: refined Korean visual "
    "impression, sleek short bob, thin metal glasses, calm attentive intelligent "
    "gaze. One-person private briefing mood — standing beside or near the user, "
    "quietly competent, composed, and helpful, in a premium private tech briefing "
    "atmosphere. Not a public news anchor, not a weathercaster, not a CEO or "
    "chairwoman or senior executive, not a fashion model, not a generic office "
    "worker, no powerful-boss or boardroom authority portrait"
)

# Reference separation: the reference image must drive FACE/HAIR/GLASSES identity
# ONLY. It must NOT carry the reference outfit, blouse, skirt, tablet, office,
# monitor wall, pose, lighting, or scene into the result — those come from the
# selected daily variant. (Root cause of the prior failure: "wardrobe continuity".)
_PRODUCTION_TOP_IMAGE_REFERENCE = (
    "Use reference image 01 only for facial identity, short bob hairstyle, thin "
    "glasses, and calm attentive eye impression. Do not preserve the reference "
    "outfit, blouse, skirt, tablet, office background, monitor wall, pose, "
    "lighting, or scene composition. Same person does not mean same wardrobe or "
    "same office. Daily wardrobe, pose, prop, and background must follow the "
    "selected variant below"
)

# Light time/mood stem for production — NO hard office+monitor lock. Background is
# decided by the selected background variant + program visual context, not here.
_PRODUCTION_TIME_MOOD_STEM = {
    "keysuri_global_tech": (
        "Daytime, bright cool natural light, understated professional global tech "
        "briefing mood"
    ),
    "keysuri_korea_tech": (
        "Early evening, warm Seoul interior light with a soft city dusk through the "
        "window, understated domestic tech briefing mood"
    ),
}

# Hard office/monitor stem fragments that must NOT reappear in the final prompt.
_FINAL_FORBIDDEN_OFFICE_STEM_TOKENS = (
    "desk and monitor with abstract non-readable charts",
    "premium private office with large windows, desk and monitor",
)
# Reference-continuity phrases that must NOT reappear in the final prompt.
_FINAL_FORBIDDEN_CONTINUITY_TOKENS = (
    "wardrobe continuity",
    "outfit continuity",
    "same wardrobe",
    "same suit",
    "same blouse",
    "same office",
    "same background",
)


# Age tokens that must be wholly absent from the final image prompt (no negation
# is acceptable — KeeSuri must carry no age label at all).
_FINAL_FORBIDDEN_AGE_TOKENS = (
    "late 20s",
    "late twenties",
    "mature professional age",
    "30s",
    "thirties",
    "mid-to-late",
)
# Role tokens that may appear ONLY inside an explicit negation ("not a ...").
_FINAL_NEGATABLE_ROLE_TOKENS = (
    "public news anchor",
    "weathercaster",
    "ceo",
    "chairwoman",
    "senior executive",
    "fashion model",
    "generic office worker",
)
_FINAL_REQUIRED_POSITIVE_PHRASES = (
    "same person as the reference",
    "sleek short bob",
    "thin metal glasses",
    "private",
    "tech",
    "secretary",
    "one-person private briefing",
    "no readable real",
)
_FINAL_REQUIRED_NEGATIVE_PHRASES = (
    "no readable text overlay",
    "no age label",
    "not a public news anchor",
    "not a weathercaster",
    "no fashion model styling",
)
_FINAL_PROGRAM_CONTEXT_MARKER = {
    "keysuri_global_tech": "global big-tech",
    "keysuri_korea_tech": "korean tech-ecosystem",
}
_SENTENCE_SPLIT_RE = re.compile(r"[.!?]\s+")


def _occurrence_is_negated(sentence: str, token: str) -> bool:
    """True if every occurrence of token in the sentence follows a negation word."""
    start = 0
    while True:
        idx = sentence.find(token, start)
        if idx == -1:
            return True
        prefix = sentence[:idx]
        if not re.search(r"\b(not|no|avoid|without|never)\b", prefix):
            return False
        start = idx + len(token)


def validate_keysuri_final_top_image_prompt(
    program_id: str,
    positive_prompt: str,
    negative_prompt: str,
) -> List[Dict[str, str]]:
    """Validate the FINAL image-API prompt (the diversified one actually sent).

    This closes the gap where the safety gate validated only the static design
    snapshot: the prompt that reaches the image API must itself pass identity,
    age, role, readable-text, wardrobe-variant, and program-context checks.
    Returns issue dicts (empty list == pass).
    """
    issues: List[Dict[str, str]] = []
    pid = (program_id or "").strip()
    pos = str(positive_prompt or "")
    pos_lower = pos.lower()
    neg_lower = str(negative_prompt or "").lower()
    # The reference-separation paragraph legitimately mentions the very tokens it
    # forbids ("do not preserve the reference ... tablet ... same wardrobe or same
    # office"). Scan the forbidden-continuity / office-stem / Korea-tablet rules on
    # the text with that known paragraph removed, so negated mentions don't trip.
    scan_lower = pos_lower.replace(_PRODUCTION_TOP_IMAGE_REFERENCE.lower(), " ")

    if pid not in KEYSURI_PROGRAMS:
        issues.append(_issue("final_program_invalid", f"unknown program {program_id!r}", "program_id"))

    for phrase in _FINAL_REQUIRED_POSITIVE_PHRASES:
        if phrase not in pos_lower:
            issues.append(
                _issue(
                    "final_positive_phrase_missing",
                    f"final positive_prompt must include {phrase!r}",
                    "positive_prompt",
                )
            )
    for phrase in _FINAL_REQUIRED_NEGATIVE_PHRASES:
        if phrase not in neg_lower:
            issues.append(
                _issue(
                    "final_negative_phrase_missing",
                    f"final negative_prompt must include {phrase!r}",
                    "negative_prompt",
                )
            )

    for token in _FINAL_FORBIDDEN_AGE_TOKENS:
        if token in pos_lower:
            issues.append(
                _issue(
                    "final_age_label_present",
                    f"final positive_prompt must not contain age token {token!r}",
                    "positive_prompt",
                )
            )

    sentences = _SENTENCE_SPLIT_RE.split(pos_lower)
    for token in _FINAL_NEGATABLE_ROLE_TOKENS:
        for sentence in sentences:
            if token in sentence and not _occurrence_is_negated(sentence, token):
                issues.append(
                    _issue(
                        "final_forbidden_role_unnegated",
                        f"final positive_prompt has un-negated forbidden role {token!r}",
                        "positive_prompt",
                    )
                )
                break

    marker = _FINAL_PROGRAM_CONTEXT_MARKER.get(pid)
    if marker and marker not in pos_lower:
        issues.append(
            _issue(
                "final_program_context_missing",
                f"final positive_prompt must include {marker!r} program visual context",
                "positive_prompt",
            )
        )
    other_marker = _FINAL_PROGRAM_CONTEXT_MARKER.get(
        "keysuri_korea_tech" if pid == "keysuri_global_tech" else "keysuri_global_tech"
    )
    if other_marker and other_marker in pos_lower:
        issues.append(
            _issue(
                "final_program_context_crossed",
                f"final positive_prompt must not include the other program's context {other_marker!r}",
                "positive_prompt",
            )
        )

    allowed_outfit_clauses = [clause.lower() for _id, clause in OUTFIT_VARIANTS]
    if not any(clause in pos_lower for clause in allowed_outfit_clauses):
        issues.append(
            _issue(
                "final_wardrobe_variant_not_allowed",
                "final positive_prompt must use an allowed wardrobe variant clause",
                "positive_prompt",
            )
        )

    # --- Reference separation: identity-only, no scene/outfit preservation -------
    if "only for facial identity" not in pos_lower:
        issues.append(
            _issue(
                "reference_identity_only_missing",
                "final positive_prompt must restrict the reference to facial identity / hair / glasses only",
                "positive_prompt",
            )
        )
    if "do not preserve the reference outfit" not in pos_lower:
        issues.append(
            _issue(
                "reference_do_not_preserve_scene_missing",
                "final positive_prompt must instruct not to preserve reference outfit/background/pose/tablet/office",
                "positive_prompt",
            )
        )
    for token in _FINAL_FORBIDDEN_CONTINUITY_TOKENS:
        if token in scan_lower:
            issues.append(
                _issue(
                    "reference_wardrobe_continuity_present",
                    f"final positive_prompt must not preserve reference continuity ({token!r})",
                    "positive_prompt",
                )
            )

    # --- Old generic office/monitor scene stem must not be a hard requirement ----
    for token in _FINAL_FORBIDDEN_OFFICE_STEM_TOKENS:
        if token in scan_lower:
            issues.append(
                _issue(
                    "old_office_monitor_stem_present",
                    f"final positive_prompt must not hard-fix the old office/monitor stem ({token!r})",
                    "positive_prompt",
                )
            )

    # --- Program-specific prop rule ---------------------------------------------
    if pid == "keysuri_global_tech":
        if "tablet" not in scan_lower and "ipad" not in scan_lower:
            issues.append(
                _issue(
                    "global_tablet_prop_missing",
                    "Global daytime final prompt must include a tablet/iPad briefing prop",
                    "positive_prompt",
                )
            )
    elif pid == "keysuri_korea_tech":
        if "tablet" in scan_lower or "ipad" in scan_lower:
            issues.append(
                _issue(
                    "korea_tablet_prop_present",
                    "Korea evening final prompt must use a non-tablet domestic briefing prop",
                    "positive_prompt",
                )
            )
        korea_prop_markers = ("notebook", "briefing cards", "laptop", "phone and a memo", "briefing board")
        if not any(m in pos_lower for m in korea_prop_markers):
            issues.append(
                _issue(
                    "korea_domestic_prop_missing",
                    "Korea evening final prompt must include a domestic briefing prop (notebook/cards/laptop/phone-memo/board)",
                    "positive_prompt",
                )
            )

    return issues


def build_keysuri_production_top_image_prompt(
    program_id: str,
    *,
    run_date_kst: str,
    subject_top_headline: str = "",
    palette_version: str = "v1",
) -> Dict[str, Any]:
    """Build the diversified production top image prompt for a Kee-Suri program.

    Deterministic on (program_id, run_date_kst, subject_top_headline, palette_version).
    Returns positive_prompt, negative_prompt, artifact-safe variation metadata, and
    the final-prompt validation status/issues for the prompt actually returned.
    """
    pid = (program_id or "").strip()
    if _program_is_forbidden(pid):
        raise ValueError(f"Forbidden program for top image prompt: {program_id!r}")
    if pid not in KEYSURI_PROGRAMS:
        raise ValueError(f"Unknown program for top image prompt: {program_id!r}")

    variation = resolve_keysuri_top_image_variation(
        pid,
        run_date_kst,
        subject_top_headline,
        palette_version,
    )

    # Daily selected variant block — placed immediately after identity + reference
    # separation, and BEFORE any scene/mood wording, so the model follows the
    # variant instead of collapsing back to the reference look.
    wardrobe = (
        f"Today she wears {variation.outfit_clause}, refined and understated "
        "premium private tech secretary office styling — clearly different from a "
        "plain charcoal business suit, not over-luxury, not revealing; the outfit "
        "varies by day and must not define her identity"
    )
    pose_prop = (
        f"Calm one-person private briefing: {variation.pose_clause}, "
        f"{variation.prop_clause}. Keep hands simple and natural with no pointing, "
        "tapping, stylus, or screen-covering gestures"
    )
    framing = (
        f"Background today: {variation.background_clause}, {variation.camera_clause}, "
        f"{variation.lighting_clause}"
    )
    time_mood = _PRODUCTION_TIME_MOOD_STEM[pid]

    parts = [
        _PRODUCTION_TOP_IMAGE_IDENTITY,
        _PRODUCTION_TOP_IMAGE_REFERENCE,
        wardrobe,
        pose_prop,
        framing,
        variation.program_visual_context,
        time_mood,
        variation.subject_cue,
    ]
    positive_prompt = ". ".join(p.strip().rstrip(".") for p in parts if p) + "."
    negative_prompt = _build_negative_prompt(pid)

    validation_issues = validate_keysuri_final_top_image_prompt(
        pid, positive_prompt, negative_prompt
    )
    validation_status = "block" if validation_issues else "pass"

    metadata = variation.as_metadata()
    metadata["top_image_program_visual_context"] = pid
    metadata["top_image_identity_lock"] = (
        "face+short_bob+thin_glasses+calm_gaze+private_briefing_role"
    )
    metadata["top_image_final_prompt_validated"] = True
    metadata["top_image_final_prompt_validation_status"] = validation_status
    metadata["top_image_final_prompt_validation_issues"] = [
        i["code"] for i in validation_issues
    ]

    return {
        "program_id": pid,
        "positive_prompt": positive_prompt,
        "negative_prompt": negative_prompt,
        "variation": metadata,
        "final_prompt_validation_status": validation_status,
        "final_prompt_validation_issues": validation_issues,
    }


_DAILY_WARDROBE_METADATA_KEYS = (
    "wardrobe_group",
    "wardrobe_date_kst",
    "wardrobe_palette_version",
    "wardrobe_profile_id",
    "daily_wardrobe_seed",
    "manual_override_applied",
    "resolver_version",
    "program_id",
    "wardrobe_prompt_injected",
)


def _extract_wardrobe_date_kst(visual_context: dict) -> str:
    date_str = str(visual_context.get("weather_date") or "").strip()
    if not date_str:
        raise ValueError("visual_context.weather_date is required for daily wardrobe metadata")
    return date_str


def _resolve_daily_wardrobe_for_context(program_id: str, visual_context: dict):
    pid = (program_id or "").strip()
    wardrobe_date_kst = _extract_wardrobe_date_kst(visual_context)
    return resolve_keysuri_daily_wardrobe(wardrobe_date_kst, pid)


def _daily_wardrobe_metadata_from_result(result, *, wardrobe_prompt_injected: bool) -> dict:
    debug = result.debug
    return {
        "wardrobe_group": debug.wardrobe_group,
        "wardrobe_date_kst": debug.wardrobe_date_kst,
        "wardrobe_palette_version": debug.wardrobe_palette_version,
        "wardrobe_profile_id": debug.wardrobe_profile_id,
        "daily_wardrobe_seed": debug.daily_wardrobe_seed,
        "manual_override_applied": debug.manual_override_applied,
        "resolver_version": debug.resolver_version,
        "program_id": debug.program_id,
        "wardrobe_prompt_injected": wardrobe_prompt_injected,
    }


def build_daily_wardrobe_metadata(
    program_id: str,
    visual_context: dict,
    *,
    wardrobe_prompt_injected: bool = False,
) -> dict:
    """Resolve Kee-Suri daily wardrobe metadata for prompt contracts (no prompt injection)."""
    result = _resolve_daily_wardrobe_for_context(program_id, visual_context)
    return _daily_wardrobe_metadata_from_result(
        result,
        wardrobe_prompt_injected=wardrobe_prompt_injected,
    )


def build_keysuri_weather_visual_prompt_contract(
    program_id: str,
    visual_context: dict,
    *,
    include_daily_wardrobe_metadata: bool = True,
    use_daily_wardrobe_prompt_snippet: bool = False,
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

    wardrobe_clause = None
    wardrobe_result = None
    if include_daily_wardrobe_metadata or use_daily_wardrobe_prompt_snippet:
        wardrobe_result = _resolve_daily_wardrobe_for_context(pid, visual_context)
    if use_daily_wardrobe_prompt_snippet:
        wardrobe_clause = _extract_wardrobe_prompt_clause(
            wardrobe_result.wardrobe_profile.prompt_snippet
        )

    pose_policy = POSE_POLICY if pid == "keysuri_global_tech" else KOREA_POSE_POLICY
    hand_policy = HAND_POLICY if pid == "keysuri_global_tech" else KOREA_HAND_POLICY
    pose_variation = dict(POSE_VARIATION_POLICY)
    pose_variation["pose_policy"] = pose_policy
    pose_variation["hand_policy"] = hand_policy
    pose_variation["variation_role"] = pose_policy

    contract: Dict[str, Any] = {
        "program_id": pid,
        "prompt_contract_type": PROMPT_CONTRACT_TYPE,
        "source_mode": SOURCE_MODE,
        "runtime_binding_status": RUNTIME_BINDING_STATUS,
        "visual_time_context": visual_time,
        "weather_condition": condition,
        "location": LOCATION,
        "identity": dict(IDENTITY_BLOCK),
        "weather_visual_usage": dict(WEATHER_VISUAL_USAGE),
        "variation_mode": VARIATION_MODE,
        "pose_policy": pose_policy,
        "hand_policy": hand_policy,
        "scene_policy": SCENE_POLICY,
        "weather_policy": WEATHER_POLICY,
        "reference_usage_policy": dict(REFERENCE_USAGE_POLICY),
        "wardrobe_lock": dict(WARDROBE_LOCK),
        "pose_variation_policy": pose_variation,
        "positive_prompt": _build_positive_prompt(
            pid,
            visual_context,
            wardrobe_clause=wardrobe_clause,
        ),
        "negative_prompt": _build_negative_prompt(pid),
        "safety_constraints": dict(SAFETY_CONSTRAINTS),
        "side_effects": dict(SIDE_EFFECTS_DISABLED),
    }
    if pid == "keysuri_korea_tech":
        contract["korea_time_profile"] = KOREA_TIME_PROFILE
        contract["korea_tablet_policy"] = KOREA_TABLET_POLICY
        contract["korea_hand_posture_policy"] = KOREA_HAND_POLICY
        contract["korea_mood"] = KOREA_MOOD
    if include_daily_wardrobe_metadata:
        if wardrobe_result is None:
            wardrobe_result = _resolve_daily_wardrobe_for_context(pid, visual_context)
        contract["daily_wardrobe"] = _daily_wardrobe_metadata_from_result(
            wardrobe_result,
            wardrobe_prompt_injected=use_daily_wardrobe_prompt_snippet,
        )
    return contract


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
        if _positive_contains_unnegated_phrase(pos_lower, term):
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
        if ref_policy.get("variation_mode") != VARIATION_MODE:
            issues.append(
                _issue(
                    "variation_mode_invalid",
                    f"variation_mode must be {VARIATION_MODE!r}",
                    "reference_usage_policy.variation_mode",
                )
            )
        for key in ("must_preserve", "variation_allowed"):
            if not isinstance(ref_policy.get(key), list) or not ref_policy.get(key):
                issues.append(
                    _issue(
                        "reference_usage_policy_list_invalid",
                        f"reference_usage_policy.{key} must be a non-empty list",
                        f"reference_usage_policy.{key}",
                    )
                )
        if isinstance(ref_policy.get("variation_required"), list) and ref_policy.get("variation_required"):
            issues.append(
                _issue(
                    "variation_required_forbidden",
                    "variation_required must not be used in production profile",
                    "reference_usage_policy.variation_required",
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
            "umbrella",
            "raincoat",
        ):
            if term not in forbidden_wardrobe:
                issues.append(
                    _issue(
                        "wardrobe_forbidden_missing",
                        f"wardrobe_lock.forbidden must include {term!r}",
                        "wardrobe_lock.forbidden",
                    )
                )

    daily_wardrobe = contract.get("daily_wardrobe")
    if daily_wardrobe is not None:
        if not isinstance(daily_wardrobe, dict):
            issues.append(
                _issue(
                    "daily_wardrobe_invalid",
                    "daily_wardrobe must be a dict when present",
                    "daily_wardrobe",
                )
            )
        else:
            for key in _DAILY_WARDROBE_METADATA_KEYS:
                if key not in daily_wardrobe:
                    issues.append(
                        _issue(
                            "daily_wardrobe_missing_field",
                            f"daily_wardrobe must include {key!r}",
                            f"daily_wardrobe.{key}",
                        )
                    )
            if daily_wardrobe.get("program_id") and daily_wardrobe.get("program_id") != pid:
                issues.append(
                    _issue(
                        "daily_wardrobe_program_mismatch",
                        "daily_wardrobe.program_id must match contract program_id",
                        "daily_wardrobe.program_id",
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
    else:
        expected_pose = POSE_POLICY if pid == "keysuri_global_tech" else KOREA_POSE_POLICY
        if pose_policy.get("variation_role") != expected_pose:
            issues.append(
                _issue(
                    "pose_variation_role_invalid",
                    f"variation_role must be {expected_pose!r}",
                    "pose_variation_policy.variation_role",
                )
            )
        expected_hand = HAND_POLICY if pid == "keysuri_global_tech" else KOREA_HAND_POLICY
        if pose_policy.get("hand_policy") != expected_hand:
            issues.append(
                _issue(
                    "hand_policy_invalid",
                    f"hand_policy must be {expected_hand!r}",
                    "pose_variation_policy.hand_policy",
                )
            )
        if pose_policy.get("weather_policy") != WEATHER_POLICY:
            issues.append(
                _issue(
                    "weather_policy_invalid",
                    f"weather_policy must be {WEATHER_POLICY!r}",
                    "pose_variation_policy.weather_policy",
                )
            )
        if pid == "keysuri_global_tech":
            global_vars = " ".join(
                str(x).lower() for x in (pose_policy.get("global_tech_allowed_variations") or [])
            )
            if "three-quarter" not in global_vars and "tablet at waist" not in global_vars:
                issues.append(
                    _issue(
                        "global_variation_missing",
                        "global_tech_allowed_variations must include stable briefing stance",
                        "pose_variation_policy.global_tech_allowed_variations",
                    )
                )
        if pid == "keysuri_korea_tech":
            korea_vars = " ".join(
                str(x).lower() for x in (pose_policy.get("korea_tech_allowed_variations") or [])
            )
            has_after_sunset = "after-sunset" in korea_vars or "after sunset" in korea_vars
            has_hands = "clasped" in korea_vars or "relaxed posture" in korea_vars
            if not has_after_sunset or not has_hands:
                issues.append(
                    _issue(
                        "korea_variation_missing",
                        "korea_tech_allowed_variations must include after-sunset evening and clasped/relaxed hands",
                        "pose_variation_policy.korea_tech_allowed_variations",
                    )
                )
        must_not_pose = " ".join(str(x).lower() for x in (pose_policy.get("must_not") or []))
        for term in ("pointing finger", "tapping tablet", "stylus"):
            if term not in must_not_pose:
                issues.append(
                    _issue(
                        "pose_must_not_missing",
                        f"must_not must include {term!r}",
                        "pose_variation_policy.must_not",
                    )
                )

    if contract.get("variation_mode") != VARIATION_MODE:
        issues.append(
            _issue(
                "contract_variation_mode_invalid",
                f"variation_mode must be {VARIATION_MODE!r}",
                "variation_mode",
            )
        )
    expected_hand_policy = HAND_POLICY if pid == "keysuri_global_tech" else KOREA_HAND_POLICY
    if contract.get("hand_policy") != expected_hand_policy:
        issues.append(
            _issue(
                "contract_hand_policy_invalid",
                f"hand_policy must be {expected_hand_policy!r}",
                "hand_policy",
            )
        )

    for phrase in REQUIRED_PRODUCTION_POSITIVE_PHRASES:
        if phrase not in pos_lower:
            issues.append(
                _issue(
                    "production_positive_phrase_missing",
                    f"positive_prompt must include {phrase!r}",
                    "positive_prompt",
                )
            )

    if pid == "keysuri_global_tech":
        for phrase in REQUIRED_GLOBAL_POSITIVE_PHRASES:
            if phrase not in pos_lower:
                issues.append(
                    _issue(
                        "global_positive_phrase_missing",
                        f"global positive_prompt must include {phrase!r}",
                        "positive_prompt",
                    )
                )
        for forbidden_evening in (
            "winter 18:30",
            "after-sunset",
            "sun has already set",
            "deep blue-gray seoul evening",
            "city lights already visible",
            "early evening 18:30",
            "blue-gray seoul dusk",
        ):
            if forbidden_evening in pos_lower:
                issues.append(
                    _issue(
                        "global_evening_language_forbidden",
                        f"global positive_prompt must not include Korea evening stem {forbidden_evening!r}",
                        "positive_prompt",
                    )
                )
                break
        if "tablet is optional" in pos_lower:
            issues.append(
                _issue(
                    "global_tablet_optional_forbidden",
                    "global positive_prompt must not use Korea tablet-optional language",
                    "positive_prompt",
                )
            )
    elif pid == "keysuri_korea_tech":
        for phrase in REQUIRED_KOREA_POSITIVE_PHRASES:
            if phrase not in pos_lower:
                issues.append(
                    _issue(
                        "korea_positive_phrase_missing",
                        f"korea positive_prompt must include {phrase!r}",
                        "positive_prompt",
                    )
                )
        for field, expected in (
            ("korea_time_profile", KOREA_TIME_PROFILE),
            ("korea_tablet_policy", KOREA_TABLET_POLICY),
            ("korea_hand_posture_policy", KOREA_HAND_POLICY),
            ("korea_mood", KOREA_MOOD),
        ):
            if contract.get(field) != expected:
                issues.append(
                    _issue(
                        "korea_profile_field_invalid",
                        f"{field} must be {expected!r}",
                        field,
                    )
                )
        for extra_neg in KOREA_EXTRA_NEGATIVE_PHRASES:
            if extra_neg not in neg:
                issues.append(
                    _issue(
                        "korea_negative_phrase_missing",
                        f"korea negative_prompt must include {extra_neg!r}",
                        "negative_prompt",
                    )
                )
        for daylight_phrase in FORBIDDEN_KOREA_DAYLIGHT_POSITIVE_PHRASES:
            if daylight_phrase in pos_lower:
                issues.append(
                    _issue(
                        "korea_daylight_language_forbidden",
                        f"korea positive_prompt must not include ambiguous daylight stem {daylight_phrase!r}",
                        "positive_prompt",
                    )
                )

    for aggressive in FORBIDDEN_POSITIVE_AGGRESSIVE_PHRASES:
        if _positive_contains_unnegated_phrase(pos_lower, aggressive):
            issues.append(
                _issue(
                    "forbidden_aggressive_language_in_positive",
                    f"positive_prompt must not contain {aggressive!r}",
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
