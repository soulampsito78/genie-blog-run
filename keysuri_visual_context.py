"""Kee-Suri Seoul weather-aware visual context and image prompt contract (offline)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from keysuri_news_contract import (
    KEYSURI_PROGRAM_IDS,
    expected_news_scope_for_program,
    expected_top5_heading_for_program,
)

IDENTITY_LABEL = "테크 비서 키수리"
LOCATION_BASELINE = "Seoul"
TIMEZONE_SEOUL = "Asia/Seoul"
REQUIRED_OPERATIONAL_STATUS = "review_required"

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
ALLOWED_SOURCE_MODES = frozenset({"offline_fixture", "runtime_weather_api"})
ALLOWED_FINE_DUST_LEVELS = frozenset({"good", "moderate", "bad", "very_bad"})

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

PERSONA_FIXED_BLOCK = (
    "Attractive Korean woman in her mid-to-late 30s, sleek short bob hair, "
    "transparent or thin metal glasses, sharp attentive eyes, calm confident expression, "
    "elegant private tech secretary presence, slim tailored premium office outfit "
    "(structured jacket and pencil skirt or refined business dress), "
    "black charcoal deep navy ivory muted silver palette, graceful realistic proportions, "
    "beautiful intelligent cool refreshing quietly attractive highly competent, "
    "private executive tech secretary personally briefing a CEO or founder. "
    "Kee-Suri identity: 테크 비서 키수리 — 프라이빗 테크 비서."
)

NEGATIVE_PROMPT_RULES: List[str] = [
    "no collage",
    "no split screen",
    "no mosaic",
    "no text overlay",
    "no watermark",
    "no distorted hands",
    "no extra limbs",
    "no unrealistic body proportions",
    "no young idol look",
    "no overly sexualized look",
    "no public TV anchor",
    "no newsroom set",
    "no microphone",
    "no broadcast lower-third",
    "no broadcast weather desk pose",
    "no sci-fi armor",
    "no cartoon anime",
    "no multiple people",
    "no logos",
    "no readable chart numbers",
    "no fake UI text",
    "no nightlife bar lounge advertisement",
    "no cyberpunk city",
    "no generic stock photo secretary",
]

PROGRAM_VISUAL_CONFIG: Dict[str, Dict[str, str]] = {
    "keysuri_global_tech": {
        "program_label": "Kee-Suri Global Tech",
        "schedule_time_kst": "12:30",
        "visual_time_band": "daytime",
        "program_tone": (
            "global big tech, overseas market signals, international business context, "
            "CEO/founder private briefing, Seoul daytime executive office"
        ),
        "must_not_feel": (
            "TV newsroom, public news broadcast desk, generic stock photo secretary, nightlife scene"
        ),
    },
    "keysuri_korea_tech": {
        "program_label": "Kee-Suri Korea Tech",
        "schedule_time_kst": "18:30",
        "visual_time_band": "early_evening",
        "program_tone": (
            "domestic Korean tech industry briefing, Seoul office and city background, "
            "after-work executive summary, calm premium Korean tech briefing"
        ),
        "must_not_feel": (
            "nightlife advertisement, bar lounge mood, dark cyberpunk city, public newsroom, "
            "generic broadcast desk scene"
        ),
    },
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


def _scan_forbidden_strings(blob: str, path_prefix: str) -> List[Dict[str, str]]:
    issues: List[Dict[str, str]] = []
    for term in FORBIDDEN_IDENTITY_KO:
        if term in blob:
            issues.append(
                _issue(
                    "forbidden_identity_string",
                    f"Must not contain {term!r}",
                    path_prefix,
                )
            )
    for term in FORBIDDEN_IDENTITY_EN:
        if term.lower() in blob.lower():
            issues.append(
                _issue(
                    "forbidden_identity_string",
                    f"Must not contain {term!r}",
                    path_prefix,
                )
            )
    for term in FORBIDDEN_RETIRED:
        if term in blob:
            issues.append(
                _issue(
                    "forbidden_retired_reference",
                    f"Must not contain {term!r}",
                    path_prefix,
                )
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


def load_keysuri_weather_context_fixture(path: str) -> dict:
    """Load a weather context JSON fixture from disk."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Weather fixture must be a JSON object: {path}")
    return data


def validate_keysuri_weather_context(weather_context: dict) -> List[dict]:
    """Validate Seoul weather context object. Returns issue dicts (empty if ok)."""
    issues: List[dict] = []
    if not isinstance(weather_context, dict):
        issues.append(_issue("weather_context_invalid", "weather_context must be a dict", "weather_context"))
        return issues

    location = str(weather_context.get("location") or "").strip()
    if location != LOCATION_BASELINE:
        issues.append(
            _issue(
                "location_invalid",
                f"location must be {LOCATION_BASELINE!r}, got {location!r}",
                "location",
            )
        )

    tz = str(weather_context.get("timezone") or "").strip()
    if tz != TIMEZONE_SEOUL:
        issues.append(
            _issue(
                "timezone_invalid",
                f"timezone must be {TIMEZONE_SEOUL!r}, got {tz!r}",
                "timezone",
            )
        )

    if not str(weather_context.get("weather_date") or "").strip():
        issues.append(_issue("weather_date_missing", "weather_date is required", "weather_date"))

    if not str(weather_context.get("observed_or_forecast_time_kst") or "").strip():
        issues.append(
            _issue(
                "observed_time_missing",
                "observed_or_forecast_time_kst is required",
                "observed_or_forecast_time_kst",
            )
        )

    condition = str(weather_context.get("weather_condition") or "").strip()
    if condition not in ALLOWED_WEATHER_CONDITIONS:
        issues.append(
            _issue(
                "weather_condition_invalid",
                f"weather_condition must be one of {sorted(ALLOWED_WEATHER_CONDITIONS)}",
                "weather_condition",
            )
        )

    source_mode = str(weather_context.get("source_mode") or "").strip()
    if source_mode not in ALLOWED_SOURCE_MODES:
        issues.append(
            _issue(
                "source_mode_invalid",
                f"source_mode must be one of {sorted(ALLOWED_SOURCE_MODES)}",
                "source_mode",
            )
        )

    if not str(weather_context.get("source_label") or "").strip():
        issues.append(_issue("source_label_missing", "source_label is required", "source_label"))

    dust = weather_context.get("fine_dust_level")
    if dust is not None and str(dust).strip() and str(dust).strip() not in ALLOWED_FINE_DUST_LEVELS:
        issues.append(
            _issue(
                "fine_dust_level_invalid",
                f"fine_dust_level invalid: {dust!r}",
                "fine_dust_level",
            )
        )

    texts: List[str] = []
    _collect_strings(weather_context, texts)
    issues.extend(_scan_forbidden_strings("\n".join(texts), "weather_context"))

    return issues


def _weather_family(condition: str) -> str:
    if condition in ("sunny", "clear"):
        return "clear"
    if condition in ("cloudy", "overcast"):
        return "cloudy"
    if condition == "rainy":
        return "rainy"
    if condition in ("snow", "cold"):
        return "cold"
    if condition in ("fine_dust", "haze"):
        return "haze"
    return condition


def _weather_visual_bundle(program_id: str, condition: str) -> Dict[str, str]:
    """Return weather_visual_summary, background, lighting, props, mood for program+weather."""
    family = _weather_family(condition)
    is_global = program_id == "keysuri_global_tech"

    bundles: Dict[str, Dict[str, Dict[str, str]]] = {
        "clear": {
            "keysuri_global_tech": {
                "weather_visual_summary": "Seoul clear daytime with sunlit executive office atmosphere",
                "background_direction": (
                    "sunlit executive office, bright daylight, clear window background, "
                    "polished global tech briefing atmosphere, international business desk mood, "
                    "clean Seoul skyline if visible"
                ),
                "lighting_direction": "sharp but natural window daylight, premium calm office light",
                "prop_direction": "minimal executive desk props, global business cues, no broadcast gear",
                "mood_direction": "competent quietly attractive private global tech secretary briefing",
            },
            "keysuri_korea_tech": {
                "weather_visual_summary": "Seoul late afternoon early evening glow for domestic tech briefing",
                "background_direction": (
                    "Seoul office window with late afternoon early evening glow, "
                    "calm closing-business-day mood, gentle transition to evening"
                ),
                "lighting_direction": "warm restrained office light, premium early evening interior",
                "prop_direction": "Korean tech executive desk, domestic briefing cues, no nightlife props",
                "mood_direction": "calm premium after-work Korean tech executive summary",
            },
        },
        "cloudy": {
            "keysuri_global_tech": {
                "weather_visual_summary": "Seoul cloudy daytime with soft diffused office light",
                "background_direction": (
                    "soft diffused daylight, gray Seoul sky through window, calm focused office, not dark"
                ),
                "lighting_direction": "even diffused daylight, premium calm work mood",
                "prop_direction": "understated executive desk, global briefing materials abstract",
                "mood_direction": "focused premium daytime private secretary briefing",
            },
            "keysuri_korea_tech": {
                "weather_visual_summary": "Seoul muted early-evening cloudy sky with indoor premium light",
                "background_direction": (
                    "muted early-evening Seoul sky, indoor premium composition, subdued not gloomy"
                ),
                "lighting_direction": "soft interior premium light, early evening calm",
                "prop_direction": "Seoul office setting, domestic tech briefing mood",
                "mood_direction": "practical calm Korean tech briefing atmosphere",
            },
        },
        "rainy": {
            "keysuri_global_tech": {
                "weather_visual_summary": "Seoul daytime rain with window droplets and wet reflections",
                "background_direction": (
                    "daytime rain, raindrops on office window, wet road reflections outside, "
                    "soft diffused daylight, premium calm work mood"
                ),
                "lighting_direction": "soft diffused daylight with reflective window highlights",
                "prop_direction": "executive office rain ambience, no depressing storm drama",
                "mood_direction": "calm competent rainy-day private briefing, not gloomy",
            },
            "keysuri_korea_tech": {
                "weather_visual_summary": "Seoul early evening rain with warm interior and wet street reflections",
                "background_direction": (
                    "early evening rain, raindrops on glass, wet Seoul street reflections, "
                    "warm interior lighting, calm after-work briefing mood"
                ),
                "lighting_direction": "warm interior against cool rainy window",
                "prop_direction": "Seoul evening office, domestic tech calm",
                "mood_direction": "premium calm after-work Korean tech briefing in rain",
            },
        },
        "cold": {
            "keysuri_global_tech": {
                "weather_visual_summary": "Seoul cold daylight with warm indoor contrast",
                "background_direction": (
                    "cold daylight, winter Seoul office window, refined warm indoor contrast, "
                    "optional subtle coat detail, not heavy outdoor scene"
                ),
                "lighting_direction": "cool window light with warm interior balance",
                "prop_direction": "winter executive office, global tech briefing calm",
                "mood_direction": "premium winter daytime private secretary briefing",
            },
            "keysuri_korea_tech": {
                "weather_visual_summary": "Seoul cold early evening with warm office interior",
                "background_direction": (
                    "cold early evening, warm office interior, Seoul winter city outside, "
                    "premium winter tech briefing mood"
                ),
                "lighting_direction": "warm interior vs cold evening window",
                "prop_direction": "Seoul winter office, domestic tech executive calm",
                "mood_direction": "premium winter after-work Korean tech briefing",
            },
        },
        "haze": {
            "keysuri_global_tech": {
                "weather_visual_summary": "Seoul hazy daytime with indoor-focused premium office calm",
                "background_direction": (
                    "hazy Seoul daytime sky, mostly indoor composition, air quality subtly visible "
                    "through softened window, premium office calm"
                ),
                "lighting_direction": "soft hazy daylight, indoor-focused premium light",
                "prop_direction": "executive desk, fine dust haze mood without gloom",
                "mood_direction": "calm competent hazy-day private global briefing",
            },
            "keysuri_korea_tech": {
                "weather_visual_summary": "Seoul hazy early evening with muted city lights",
                "background_direction": (
                    "hazy early evening Seoul, indoor-focused composition, muted city lights, "
                    "practical Korean tech briefing mood"
                ),
                "lighting_direction": "muted evening interior with soft haze outside",
                "prop_direction": "Seoul office haze ambience, domestic briefing",
                "mood_direction": "practical premium hazy evening Korean tech briefing",
            },
        },
    }

    pid = program_id if program_id in bundles.get(family, {}) else program_id
    return bundles[family][pid]


def build_keysuri_visual_context(program_id: str, weather_context: dict) -> dict:
    """Build program-specific visual context from validated Seoul weather."""
    pid = (program_id or "").strip()
    if pid not in KEYSURI_PROGRAM_IDS:
        raise ValueError(f"Unsupported program_id for visual context: {program_id!r}")

    w_issues = validate_keysuri_weather_context(weather_context)
    if w_issues:
        messages = "; ".join(f"{i['code']}: {i['message']}" for i in w_issues[:3])
        raise ValueError(f"Invalid weather_context: {messages}")

    cfg = PROGRAM_VISUAL_CONFIG[pid]
    condition = str(weather_context.get("weather_condition") or "").strip()
    bundle = _weather_visual_bundle(pid, condition)

    return {
        "program_id": pid,
        "program_label": cfg["program_label"],
        "schedule_time_kst": cfg["schedule_time_kst"],
        "visual_time_band": cfg["visual_time_band"],
        "section_heading": expected_top5_heading_for_program(pid),
        "news_scope": expected_news_scope_for_program(pid),
        "location_baseline": LOCATION_BASELINE,
        "timezone": TIMEZONE_SEOUL,
        "weather_condition": condition,
        "weather_date": weather_context.get("weather_date"),
        "observed_or_forecast_time_kst": weather_context.get("observed_or_forecast_time_kst"),
        "source_mode": weather_context.get("source_mode"),
        "source_label": weather_context.get("source_label"),
        "program_tone": cfg["program_tone"],
        "must_not_feel": cfg["must_not_feel"],
        "wardrobe_direction": (
            "slim tailored premium office outfit, black charcoal deep navy ivory muted silver, "
            "structured jacket and pencil skirt or refined business dress"
        ),
        **bundle,
    }


def build_keysuri_image_prompt(
    program_id: str,
    weather_context: dict,
    prompt_input: dict | None = None,
) -> dict:
    """Build structured Kee-Suri image prompt object."""
    pid = (program_id or "").strip()
    visual = build_keysuri_visual_context(pid, weather_context)

    if prompt_input is not None:
        if not isinstance(prompt_input, dict):
            raise ValueError("prompt_input must be a dict")
        pi_pid = str(prompt_input.get("program_id") or "").strip()
        if pi_pid != pid:
            raise ValueError(
                f"prompt_input.program_id {pi_pid!r} does not match program_id {pid!r}"
            )
        expected_scope = expected_news_scope_for_program(pid)
        if str(prompt_input.get("news_scope") or "").strip() != expected_scope:
            raise ValueError(
                f"prompt_input.news_scope must be {expected_scope!r} for {pid}"
            )

    image_prompt = {
        "program_id": visual["program_id"],
        "program_label": visual["program_label"],
        "news_scope": visual["news_scope"],
        "section_heading": visual["section_heading"],
        "schedule_time_kst": visual["schedule_time_kst"],
        "visual_time_band": visual["visual_time_band"],
        "location_baseline": visual["location_baseline"],
        "weather_condition": visual["weather_condition"],
        "weather_visual_summary": visual["weather_visual_summary"],
        "background_direction": visual["background_direction"],
        "lighting_direction": visual["lighting_direction"],
        "wardrobe_direction": visual["wardrobe_direction"],
        "prop_direction": visual["prop_direction"],
        "mood_direction": visual["mood_direction"],
        "identity_label": IDENTITY_LABEL,
        "persona_fixed_block": PERSONA_FIXED_BLOCK,
        "negative_prompt_rules": list(NEGATIVE_PROMPT_RULES),
        "source_mode": visual.get("source_mode"),
        "operational_status": REQUIRED_OPERATIONAL_STATUS,
    }
    image_prompt["image_prompt_text"] = build_keysuri_image_prompt_text(image_prompt)
    return image_prompt


def build_keysuri_image_prompt_text(visual_context: dict) -> str:
    """Build full photorealistic image prompt text from visual context or image prompt dict."""
    if not isinstance(visual_context, dict):
        raise ValueError("visual_context must be a dict")

    neg = visual_context.get("negative_prompt_rules")
    neg_lines = "\n".join(f"- {rule}" for rule in neg) if isinstance(neg, list) else ""

    sections = [
        "=== Kee-Suri Image Prompt (offline staged — not live weather or image API) ===",
        f"Identity: {IDENTITY_LABEL} — 프라이빗 테크 비서",
        "",
        "PROGRAM",
        f"- program_id: {visual_context.get('program_id')}",
        f"- program_label: {visual_context.get('program_label')}",
        f"- schedule_time_kst: {visual_context.get('schedule_time_kst')}",
        f"- visual_time_band: {visual_context.get('visual_time_band')}",
        f"- news_scope: {visual_context.get('news_scope')}",
        f"- section_heading: {visual_context.get('section_heading')}",
        "",
        "LOCATION / WEATHER (Seoul baseline)",
        f"- location: {visual_context.get('location_baseline', LOCATION_BASELINE)}",
        f"- weather_condition: {visual_context.get('weather_condition')}",
        f"- weather_visual_summary: {visual_context.get('weather_visual_summary')}",
        f"- source_mode: {visual_context.get('source_mode')}",
        "",
        "VISUAL DIRECTION",
        f"- background: {visual_context.get('background_direction')}",
        f"- lighting: {visual_context.get('lighting_direction')}",
        f"- wardrobe: {visual_context.get('wardrobe_direction')}",
        f"- props: {visual_context.get('prop_direction')}",
        f"- mood: {visual_context.get('mood_direction')}",
        "",
        "PERSONA (fixed)",
        str(visual_context.get("persona_fixed_block") or PERSONA_FIXED_BLOCK),
        "",
        "IMAGE TYPE",
        "- high-quality photorealistic image",
        "- single scene only",
        "",
        "NEGATIVE PROMPT RULES",
        neg_lines,
        "",
        "END",
    ]
    text = "\n".join(sections)
    positive_blob = "\n".join(
        [
            str(visual_context.get("background_direction") or ""),
            str(visual_context.get("lighting_direction") or ""),
            str(visual_context.get("mood_direction") or ""),
            str(visual_context.get("prop_direction") or ""),
            str(visual_context.get("persona_fixed_block") or PERSONA_FIXED_BLOCK),
            str(visual_context.get("program_label") or ""),
        ]
    )
    extra_issues = _scan_forbidden_strings(positive_blob, "image_prompt_text")
    if extra_issues:
        raise ValueError(
            "image_prompt_text contains forbidden content: "
            + "; ".join(i["message"] for i in extra_issues[:2])
        )
    return text
