"""Key-Suri bottom-shot prompt builder — Contract v5 implementation.

Contract: docs/keysuri/KEYSURI_R6B_BOTTOM_SHOT_PROMPT_CONTRACT_V5.md

Status:
  generation_allowed:      false
  runtime_enabled:         false
  owner_approval_required: true

This module builds prompt text from Contract v5 but does NOT:
  - call any image API
  - attach to active runtime generation
  - set KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED

Wire-in point: the disabled ``if variation_enabled:`` branch in
``keysuri_service_full_run.resolve_korea_bottom_email_image_path()``.

References:
  Asset01 (primary identity reference):
    assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png
  105936 (direction reference only — NOT image input, NOT fixed final asset):
    output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Reference constants
# ---------------------------------------------------------------------------

ASSET01_PATH = "assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png"
ASSET01_ROLE = "primary_identity_reference"

DIRECTION_REF_105936_PATH = (
    "output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg"
)
DIRECTION_REF_105936_ROLE = "direction_reference_only"
DIRECTION_REF_105936_NOTE = (
    "NOT image input. NOT fixed final asset. "
    "Do not replicate silk-knit/satin outfit from 105936."
)

# ---------------------------------------------------------------------------
# Gene A — Fixed Identity Gene (never vary)
# ---------------------------------------------------------------------------

FIXED_IDENTITY_GENE = (
    "A Korean woman in her mid-to-late thirties, with a naturally composed face, "
    "slightly angular jaw, almond-shaped eyes with a calm and perceptive gaze, "
    "a clean chin-length bob haircut with subtle volume at the crown, "
    "and thin metal-framed rectangular glasses resting naturally on her face. "
    "Her expression carries quiet authority — emotionally present but never "
    "performative, warm but contained, the look of someone who has already "
    "processed the room."
)

IDENTITY_INVARIANTS = {
    "age": "mid-to-late 30s",
    "hair": "chin-length bob, natural volume, no bangs, no updos, no ponytails",
    "glasses": "thin metal rectangular frames — always present",
    "expression": "composed, non-performative, warm gravity",
    "ethnicity": "Korean woman",
}

# ---------------------------------------------------------------------------
# Gene B — Fixed Role/Scene Gene (never vary)
# ---------------------------------------------------------------------------

FIXED_ROLE_SCENE_GENE = (
    "She is pausing at the threshold of the chairman's office — "
    "the briefing is finished, the day's work is done. "
    "A large closed premium wooden door with brass hardware fills the background, "
    "set into warm wood-paneled walls. She is facing the viewer — "
    "the reader is the owner, the one she is leaving. "
    "Her posture carries the quiet warmth of a closing ritual: "
    "everything is handled, and she is saying goodbye. "
    "Off-duty, composed, unhurried. "
    "No tablet. No laptop. No tech screen. No monitor. "
    "No outdoor scenes. No open door leading to another room. No full-body framing."
)

ROLE_SCENE_INVARIANTS = {
    "role": "off-duty private AI secretary — briefing finished, leaving-work farewell",
    "emotional_register": "closing ritual — calm farewell, everything handled",
    "scene": "chairman/CEO office threshold — closed wooden door, wood-paneled wall",
    "viewer_relationship": "reader is the owner (대표님) she is leaving toward",
    "forbidden_environment": [
        "outdoor scenes",
        "open door leading to another room",
        "lobby, atrium, open corridor",
        "tablet, tech screen, monitor wall, desk",
        "briefing posture, briefing host framing",
    ],
}

# ---------------------------------------------------------------------------
# Gene D — Camera/Framing Gene (never vary)
# ---------------------------------------------------------------------------

FIXED_CAMERA_GENE = (
    "Framing: knee-up portrait — from approximately the knee to just above the crown, "
    "showing 3 to 4 units of body. Face-first composition: the face is the primary subject, "
    "the outfit reads naturally below. "
    "Camera angle: eye level or 2–3 degrees above, never below chin level. "
    "Lens: 85mm portrait equivalent, minimal depth of field, subject sharp, "
    "background softly defocused. "
    "No full-body shot. No visible feet. No wide establishing shot. "
    "No tight mid-chest-to-crown crop."
)

CAMERA_INVARIANTS = {
    "framing": "knee-up / 3-4 body — face-first, outfit visible below",
    "angle": "eye level or 2-3 degrees above — never below chin",
    "lens": "85mm portrait equivalent",
    "depth_of_field": "subject sharp, background softly defocused",
    "forbidden": [
        "full body shot",
        "visible feet",
        "wide shot",
        "establishing shot",
        "tight mid-chest-to-crown portrait crop",
    ],
}

# ---------------------------------------------------------------------------
# Assembly order (critical — do not reorder)
# ---------------------------------------------------------------------------
# [Scene lock] → [Identity Gene] → [Role/Scene Gene] → [Camera Gene]
#   → [Weather/Outfit Shell] → [Negative]
# Outfit always last to prevent outfit-first composition.

ASSEMBLY_ORDER = (
    "scene_lock",
    "identity_gene",
    "role_scene_gene",
    "camera_gene",
    "weather_outfit_shell",
    "negative_prompt",
)

SCENE_LOCK = (
    "Knee-up portrait, eye-level, 85mm lens, shallow depth of field, "
    "closed premium wooden office door in background, warm executive-floor interior lighting."
)

# ---------------------------------------------------------------------------
# Negative Prompt v5 — Failure Blocklist
# ---------------------------------------------------------------------------

NEGATIVE_PROMPT_V5 = (
    "deformed hands, extra fingers, fused fingers, blurry face, asymmetric eyes, "
    "double chin, thick-framed glasses, no glasses, sunglasses, colored glasses, "
    "round glasses, oval glasses, "
    "heavy jewelry, statement necklace, flashy accessories, "
    "casual clothing, streetwear, athletic wear, hoodie, t-shirt, crop top, "
    "low-cut neckline, V-neck wrap dress, open-front dress, satin wrap dress, "
    "silk blouse with plunging neckline, "
    "full body shot, visible feet, wide shot, establishing shot, "
    "outdoor scene, open door, open doorway, window with outdoor view, "
    "tablet, briefing tablet, tech screen, monitor wall, monitor, "
    "desk, keyboard, multiple monitors, large screen background, reading device, "
    "lobby, atrium, open corridor, open hotel-like room, "
    "briefing posture, briefing host, senior analyst at desk, "
    "overly warm lighting, golden hour, harsh shadows, overexposed face, "
    "performative expression, smile with teeth, surprised expression, "
    "excessive makeup, heavy contouring, dramatic eye makeup, "
    "motion blur, film grain, painterly style, illustration, anime, cartoon, "
    "C-curl cute bob, young office worker, glamour model, décolleté, "
    "outfit-first composition, active wave, full-body lookbook"
)

# ---------------------------------------------------------------------------
# Gene C — Weather/Outfit Shell mapping
# Maps collapsed weather_condition string → outfit descriptor
# ---------------------------------------------------------------------------

_WEATHER_OUTFIT_MAP: Dict[str, Dict[str, str]] = {
    # clear/sunny warm (≥18°C when temperature_c available)
    "clear_warm": {
        "outfit": (
            "A lightweight structured blazer in cream or warm ivory over a fitted silk "
            "shell top in champagne or soft nude. The blazer is open, draped with "
            "effortless precision. Minimal accessories: small gold stud earrings only."
        ),
        "weather_case": "Clear / Sunny (warm, 18°C+)",
    },
    # clear/sunny cool (<18°C)
    "clear_cool": {
        "outfit": (
            "A tailored wool blazer in charcoal or slate over a fine-knit mock-neck "
            "sweater in ivory or warm grey. Clean, layered, no visible texture contrast issues."
        ),
        "weather_case": "Clear / Sunny (cool, below 18°C)",
    },
    # sunny — temperature unknown, default to cool variant
    "sunny": {
        "outfit": (
            "A tailored structured blazer in charcoal or slate over a fine-knit "
            "mock-neck sweater in ivory or warm grey. Clean, layered professional styling."
        ),
        "weather_case": "Clear / Sunny (temperature unspecified)",
    },
    "clear": {
        "outfit": (
            "A tailored structured blazer in charcoal or slate over a fine-knit "
            "mock-neck sweater in ivory or warm grey. Clean, layered professional styling."
        ),
        "weather_case": "Clear (temperature unspecified)",
    },
    "cloudy": {
        "outfit": (
            "A structured jacket in muted camel or stone over a cotton-blend shell top "
            "in off-white. Understated, professional, seasonally neutral."
        ),
        "weather_case": "Partly Cloudy",
    },
    "overcast": {
        "outfit": (
            "A collarless structured coat in deep charcoal or navy, worn over a ribbed "
            "fine-knit turtleneck in cream. The coat is buttoned at the top third only. No brooch."
        ),
        "weather_case": "Overcast / Grey",
    },
    "rainy": {
        "outfit": (
            "A fitted waterproof shell jacket in deep navy or slate, zipped to mid-chest, "
            "over a lightweight knit layer. Clean lines. No hood visible."
        ),
        "weather_case": "Light Rain / Drizzle",
    },
    "snow": {
        "outfit": (
            "A premium merino turtleneck in oatmeal or charcoal under a structured "
            "wool-cashmere overcoat in camel or deep grey. Coat collar softly framing face."
        ),
        "weather_case": "Snow / Cold (below 2°C)",
    },
    "cold": {
        "outfit": (
            "A premium merino turtleneck in oatmeal or charcoal under a structured "
            "wool-cashmere overcoat in camel or deep grey. Coat collar softly framing face."
        ),
        "weather_case": "Cold",
    },
    "fine_dust": {
        "outfit": (
            "A structured jacket in muted camel or stone over a cotton-blend shell top "
            "in off-white. Clean, contained, indoor-professional styling."
        ),
        "weather_case": "Fine Dust / Haze",
    },
    "haze": {
        "outfit": (
            "A structured jacket in muted camel or stone over a cotton-blend shell top "
            "in off-white. Clean, contained, indoor-professional styling."
        ),
        "weather_case": "Fine Dust / Haze",
    },
    # Season-explicit overrides
    "autumn_evening": {
        "outfit": (
            "A tailored charcoal blazer over a fine-knit ivory mock-neck sweater. "
            "The blazer sits cleanly on her shoulders. Small gold stud earrings, nothing else. "
            "The autumn evening light falls evenly on her face from slightly above frame left."
        ),
        "weather_case": "Autumn Evening (Family A v5 reference cluster G)",
    },
    "winter_evening": {
        "outfit": (
            "A premium merino turtleneck in oatmeal under a structured camel overcoat. "
            "Coat collar framing the face softly. Warm interior light against deep evening blue outside."
        ),
        "weather_case": "Winter Evening",
    },
    "humid_hot": {
        "outfit": (
            "A sleeveless structured top in silk-matte finish in warm white or pale "
            "champagne, under a very lightweight linen blazer in ecru. "
            "Clean and breathable without being casual."
        ),
        "weather_case": "Humid / Hot (above 28°C)",
    },
}

_TEMP_THRESHOLD_WARM_C = 18.0
_TEMP_THRESHOLD_HOT_C = 28.0


def _resolve_weather_outfit_key(
    weather_condition: str,
    temperature_c: Optional[float],
    season: Optional[str],
) -> str:
    """Resolve the weather/outfit map key from available inputs."""
    cond = (weather_condition or "").strip().lower()
    season_lower = (season or "").strip().lower()

    # Season-explicit overrides take priority
    if "autumn" in season_lower and "evening" in season_lower:
        return "autumn_evening"
    if "winter" in season_lower and "evening" in season_lower:
        return "winter_evening"
    if "humid" in season_lower or (
        temperature_c is not None and temperature_c >= _TEMP_THRESHOLD_HOT_C
    ):
        return "humid_hot"

    # Temperature split for clear/sunny
    if cond in ("clear", "sunny"):
        if temperature_c is None:
            return cond  # falls back to generic clear/sunny entry
        if temperature_c >= _TEMP_THRESHOLD_WARM_C:
            return "clear_warm"
        return "clear_cool"

    if cond in _WEATHER_OUTFIT_MAP:
        return cond

    # Fallback
    return "cloudy"


def _resolve_outfit(
    weather_condition: str,
    temperature_c: Optional[float],
    season: Optional[str],
) -> Dict[str, Any]:
    key = _resolve_weather_outfit_key(weather_condition, temperature_c, season)
    entry = _WEATHER_OUTFIT_MAP.get(key) or _WEATHER_OUTFIT_MAP["cloudy"]
    return {
        "outfit_descriptor": entry["outfit"],
        "weather_case": entry["weather_case"],
        "outfit_map_key": key,
    }


# ---------------------------------------------------------------------------
# Family ID constants
# ---------------------------------------------------------------------------

FAMILY_A = "family_a"
SUPPORTED_FAMILIES = frozenset({FAMILY_A})

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_bottom_shot_prompt(
    *,
    weather_condition: str,
    temperature_c: Optional[float] = None,
    season: Optional[str] = None,
    program_id: str = "keysuri_korea_tech",
    family_id: str = FAMILY_A,
) -> Dict[str, Any]:
    """Build Contract v5 bottom-shot prompt from weather/context inputs.

    Does NOT call any image API. Returns a dict with:
      - prompt_text:              assembled positive prompt (str)
      - negative_prompt:         failure blocklist (str)
      - weather_outfit_shell:    outfit descriptor + metadata (dict)
      - fixed_identity_gene:     identity text + invariants (dict)
      - fixed_role_scene_gene:   role/scene text + invariants (dict)
      - fixed_camera_gene:       camera/framing text + invariants (dict)
      - assembly_order:          gene assembly sequence (tuple)
      - reference_assets:        asset01 + 105936 roles (dict)
      - builder_status:          gate/generation status flags (dict)
      - weather_input_metadata:  what was actually supplied (dict)

    Args:
        weather_condition: Collapsed condition string from weather adapter.
            Allowed: clear, sunny, cloudy, overcast, rainy, snow, cold,
            fine_dust, haze.
        temperature_c: Celsius float if available from runtime adapter.
            None if not surfaced (recorded as temperature_c_unavailable).
        season: Optional semantic season hint (e.g. "autumn_evening").
            When provided, may override weather-to-outfit mapping.
        program_id: keysuri_korea_tech (default) or keysuri_global_tech.
        family_id: Prompt family. Only family_a supported.
    """
    if family_id not in SUPPORTED_FAMILIES:
        raise ValueError(f"Unsupported family_id: {family_id!r}. Must be one of {SUPPORTED_FAMILIES}")

    outfit_result = _resolve_outfit(weather_condition, temperature_c, season)
    outfit_text = outfit_result["outfit_descriptor"]

    # Assembly: [Scene lock] → [Identity] → [Role/Scene] → [Camera] → [Outfit] → end
    prompt_parts = [
        SCENE_LOCK,
        FIXED_IDENTITY_GENE,
        FIXED_ROLE_SCENE_GENE,
        FIXED_CAMERA_GENE,
        outfit_text,
    ]
    prompt_text = "\n\n".join(p.strip() for p in prompt_parts if p.strip())

    weather_input_metadata: Dict[str, Any] = {
        "weather_condition_input": weather_condition,
        "temperature_c_unavailable": temperature_c is None,
        "fine_dust_unavailable": weather_condition not in ("fine_dust", "haze"),
        "season_input": season,
    }
    if temperature_c is not None:
        weather_input_metadata["temperature_c"] = temperature_c
    if weather_condition in ("fine_dust", "haze"):
        weather_input_metadata["fine_dust_unavailable"] = False
    if temperature_c is None:
        weather_input_metadata["weather_outfit_source"] = "limited_condition_string"
    else:
        weather_input_metadata["weather_outfit_source"] = "condition_plus_temperature"

    return {
        "prompt_text": prompt_text,
        "negative_prompt": NEGATIVE_PROMPT_V5,
        "weather_outfit_shell": {
            "outfit_descriptor": outfit_text,
            "weather_case": outfit_result["weather_case"],
            "outfit_map_key": outfit_result["outfit_map_key"],
            "weather_condition": weather_condition,
            "temperature_c": temperature_c,
            "season": season,
            "gene": "C_variable_weather_outfit_shell",
        },
        "fixed_identity_gene": {
            "text": FIXED_IDENTITY_GENE,
            "gene": "A_fixed_identity",
            "invariants": IDENTITY_INVARIANTS,
        },
        "fixed_role_scene_gene": {
            "text": FIXED_ROLE_SCENE_GENE,
            "gene": "B_fixed_role_scene",
            "invariants": ROLE_SCENE_INVARIANTS,
        },
        "fixed_camera_gene": {
            "text": FIXED_CAMERA_GENE,
            "gene": "D_fixed_camera_framing",
            "invariants": CAMERA_INVARIANTS,
        },
        "assembly_order": ASSEMBLY_ORDER,
        "reference_assets": {
            "primary_identity_reference": {
                "path": ASSET01_PATH,
                "role": ASSET01_ROLE,
            },
            "direction_reference": {
                "path": DIRECTION_REF_105936_PATH,
                "role": DIRECTION_REF_105936_ROLE,
                "note": DIRECTION_REF_105936_NOTE,
            },
        },
        "builder_status": {
            "generation_allowed": False,
            "runtime_enabled": False,
            "owner_approval_required": True,
            "image_api_called": False,
            "contract_version": "v5",
            "family_id": family_id,
            "program_id": program_id,
        },
        "weather_input_metadata": weather_input_metadata,
    }


def build_bottom_shot_prompt_metadata_only(
    *,
    weather_condition: str,
    temperature_c: Optional[float] = None,
    season: Optional[str] = None,
    program_id: str = "keysuri_korea_tech",
) -> Dict[str, Any]:
    """Build prompt metadata for the disabled variation branch — no image call.

    Used in ``keysuri_service_full_run.resolve_korea_bottom_email_image_path()``
    when ``korea_bottom_variation_enabled()`` is True but generation is not yet
    implemented. Records what the prompt *would be* without calling anything.
    """
    result = build_bottom_shot_prompt(
        weather_condition=weather_condition,
        temperature_c=temperature_c,
        season=season,
        program_id=program_id,
    )
    return {
        "bottom_shot_prompt_contract_version": "v5",
        "bottom_shot_prompt_builder_status": "built_no_generation",
        "bottom_shot_generation_allowed": False,
        "bottom_shot_image_api_called": False,
        "bottom_shot_weather_case": result["weather_outfit_shell"]["weather_case"],
        "bottom_shot_outfit_map_key": result["weather_outfit_shell"]["outfit_map_key"],
        "bottom_shot_weather_outfit_source": result["weather_input_metadata"]["weather_outfit_source"],
        "bottom_shot_prompt_preview": result["prompt_text"][:200],
    }
