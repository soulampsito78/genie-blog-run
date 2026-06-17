"""Key-Suri bottom-shot prompt builder — Contract v6 implementation.

Contract: docs/keysuri/KEYSURI_R6B_BOTTOM_SHOT_EMOTIONAL_LOCKIN_PLAN.md

Status:
  generation_allowed:      false
  runtime_enabled:         false
  owner_approval_required: true

This module builds prompt text from Contract v6 but does NOT:
  - call any image API
  - attach to active runtime generation
  - set KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED

Wire-in point: the disabled ``if variation_enabled:`` branch in
``keysuri_service_full_run.resolve_korea_bottom_email_image_path()``.

References:
  105936 (primary Bottom visual anchor — image input, slot 0):
    output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg
  Asset01 (secondary same-person continuity reference — image input, slot 1 if available):
    assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Reference constants — v6 anchor hierarchy
# ---------------------------------------------------------------------------

# Primary Bottom visual anchor — passed as first image input in Bottom QA generation.
# All Bottom wardrobe variations must stay inside this image's quality/identity band.
BOTTOM_ANCHOR_PATH = (
    "output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg"
)
BOTTOM_ANCHOR_ROLE = "primary_bottom_visual_anchor"

# Secondary same-person / on-duty continuity reference.
# Passed as second image input to reinforce Key-Suri identity across on-duty/off-duty registers.
ASSET01_PATH = "assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png"
ASSET01_ROLE = "secondary_same_person_continuity_reference"

# Deprecated aliases — kept for any external code that imported the old names.
# Do not use in new code.
DIRECTION_REF_105936_PATH = BOTTOM_ANCHOR_PATH
DIRECTION_REF_105936_ROLE = BOTTOM_ANCHOR_ROLE
DIRECTION_REF_105936_NOTE = (
    "Now primary_bottom_visual_anchor — passed as first image input for Bottom generation. "
    "Previously 'direction reference only'; that designation is retired."
)

# ---------------------------------------------------------------------------
# Gene A — Fixed Identity Gene
# Appearance and identity are anchored by the 105936 reference image.
# Text gene reinforces hair/glasses invariants and register only.
# Age language removed — visual anchor carries age impression.
# ---------------------------------------------------------------------------

FIXED_IDENTITY_GENE = (
    "She is Key-Suri. Maintain her exact identity from the reference image. "
    "Her sleek side-parted short bob lies close to the jaw — smooth and straight, no curl at the ends. "
    "Thin metal rectangular glasses rest naturally on her face. "
    "Noble sensuality and controlled feminine magnetism expressed through posture, silhouette, and gaze — "
    "never through exposure. Premium presence without effort."
)

IDENTITY_INVARIANTS = {
    "anchor": "105936 reference image — primary visual identity source",
    "hair": "sleek side-parted short bob, hair close to jaw, smooth and straight, no curl at ends, no C-curl, no bangs, no updos, no ponytails",
    "glasses": "thin metal rectangular frames — always present",
    "expression": "noble sensuality, controlled feminine magnetism, cool intelligence softened only for the owner",
    "ethnicity": "Korean woman",
}

# ---------------------------------------------------------------------------
# Gene B — Fixed Role + Relationship Gene
# ---------------------------------------------------------------------------

FIXED_ROLE_SCENE_GENE = (
    "She is Key-Suri, a premium private AI secretary. "
    "The briefing is finished and she is pausing at the threshold of the CEO's office "
    "to say a personal farewell to the owner — 대표님. "
    "A large closed premium wooden door with brass hardware fills the background, "
    "set into warm wood-paneled walls. She faces the viewer directly — "
    "the reader is the owner she is leaving toward. "
    "This is an exclusive owner-facing private closing moment, reserved only for 대표님. "
    "Unattainable, not approachable. Cool intelligence softened only for the owner. "
    "Private secretary intimacy with strict dignity."
)

ROLE_SCENE_INVARIANTS = {
    "role": "premium private AI secretary — briefing finished, personal farewell to owner",
    "emotional_register": "exclusive owner-facing private closing moment — unattainable, noble sensuality, reserved for 대표님 only",
    "scene": "CEO office threshold — closed wooden door, wood-paneled wall",
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
# Gene C — Expression Gene
# ---------------------------------------------------------------------------

FIXED_EXPRESSION_GENE = (
    "Her expression is a restrained composed slight smile — cool reserved intelligence, barely softened for the owner. "
    "Lips barely curved at the corners. "
    "The quiet private pleasure of a day well finished — shared only with the owner. "
    "Modern. Not broad. Not lively. Not performative. "
    "Steady, direct eye contact with the viewer — private, not public."
)

EXPRESSION_INVARIANTS = {
    "target": "fresh composed smile / 싱그러운 미소",
    "forbidden": [
        "warm motherly smile",
        "guardian-like smile",
        "conservative family-meeting expression",
        "hands-clasped polite-matron pose",
    ],
}

# ---------------------------------------------------------------------------
# Gene E — Prop + Gesture Gene
# ---------------------------------------------------------------------------

FIXED_PROP_GESTURE_GENE = (
    "She holds a small premium handbag at her side with one hand. "
    "Her free hand rests naturally close to her body — "
    "a small restrained private gesture, as if closing the day for the owner only. "
    "The gesture is private and contained: not raised, not waving. "
    "Small scale. Interior scale. No tablet. No laptop. No notebook."
)

PROP_GESTURE_INVARIANTS = {
    "required_prop": "small premium handbag",
    "required_gesture": "small restrained private gesture — closing the day for the owner only, not raised, not waving",
    "forbidden": ["tablet", "laptop", "briefing device"],
}

# ---------------------------------------------------------------------------
# Gene F — Camera/Framing Gene
# ---------------------------------------------------------------------------

FIXED_CAMERA_GENE = (
    "Knee-up portrait showing approximately three-quarters of her body — "
    "from the knee to just above the crown. "
    "Face-first composition: the face is the primary subject, "
    "the outfit and handbag read naturally below. "
    "Camera angle: eye level or 2–3 degrees above, never below chin level. "
    "Lens: 85mm portrait equivalent, shallow depth of field, "
    "subject sharp, background softly defocused."
)

CAMERA_INVARIANTS = {
    "framing": "knee-up / 3/4 body — face-first, outfit and handbag visible below",
    "angle": "eye level or 2-3 degrees above — never below chin",
    "lens": "85mm portrait equivalent",
    "depth_of_field": "subject sharp, background softly defocused",
    "forbidden": [
        "full body shot",
        "visible feet",
        "wide shot",
        "establishing shot",
        "tight headshot crop",
        "mid-chest-to-crown portrait crop",
    ],
}

# ---------------------------------------------------------------------------
# Assembly order (v6: 8 genes)
# ---------------------------------------------------------------------------

ASSEMBLY_ORDER = (
    "scene_lock",
    "identity_gene",
    "role_scene_gene",
    "expression_gene",
    "wardrobe_gene",
    "prop_gesture_gene",
    "camera_gene",
    "negative_prompt",
)

SCENE_LOCK = (
    "Knee-up portrait, eye-level, 85mm lens, shallow depth of field, "
    "closed premium wooden office door in background, warm executive-floor interior lighting. "
    "High-end commercial portrait quality. Luxury editorial realism."
)

# ---------------------------------------------------------------------------
# Negative Prompt v6 — lean targeted blocklist
# Anchor image + constrained closet text carry quality; negatives block hard failures only.
# ---------------------------------------------------------------------------

NEGATIVE_PROMPT_V6 = (
    "deformed hands, extra fingers, fused fingers, blurry face, asymmetric eyes, "
    "double chin, thick-framed glasses, no glasses, sunglasses, colored glasses, "
    "round glasses, oval glasses, "
    "heavy jewelry, statement necklace, flashy accessories, "
    "CEO portrait, executive portrait, consultant headshot, company profile photo, "
    "professor portrait, manager portrait, corporate uniform, "
    "blazer, mock-neck sweater, business suit, formal office attire, "
    "casual clothing, streetwear, athletic wear, hoodie, t-shirt, crop top, "
    "low-cut neckline, V-neck wrap dress, open-front dress, décolleté, "
    "plain market clothes, cheap mall fashion, basic office-worker casual, "
    "full body shot, visible feet, wide shot, establishing shot, "
    "tight headshot, bust-only crop, mid-chest-to-crown crop, "
    "outfit-first composition, full-body lookbook, "
    "outdoor scene, open door, open doorway, window with outdoor view, "
    "tablet, briefing tablet, tech screen, monitor wall, monitor, "
    "desk, keyboard, multiple monitors, large screen background, reading device, "
    "lobby, atrium, open corridor, open hotel-like room, "
    "briefing posture, briefing host, senior analyst at desk, "
    "warm motherly smile, guardian-like smile, matronly expression, "
    "broad open smile, lively smile, wide smile, big smile, "
    "hands-clasped polite-matron pose, "
    "raised hand wave, open palm wave, waving pose, large hand gesture, "
    "event greeter pose, hotel receptionist pose, customer service pose, "
    "event greeter, hotel receptionist, office receptionist, friendly counselor, "
    "cardigan office lady, lifestyle blogger, friendly middle-aged office worker, "
    "overly warm lighting, golden hour, harsh shadows, overexposed face, "
    "excessive makeup, heavy contouring, dramatic eye makeup, "
    "motion blur, film grain, painterly style, illustration, anime, cartoon, "
    "C-curl cute bob, inward-curled bob, curled ends bob, volume at tips, "
    "young office worker, glamour model, "
    "friendly smile, welcoming expression, approachable warmth, "
    "ordinary office lady, lifestyle model, cheap sexiness, "
    "hostess, bar mood, lounge mood, lounge hostess, "
    "public-facing smile, open approachable expression"
)

# Keep v5 name as alias for backward compat
NEGATIVE_PROMPT_V5 = NEGATIVE_PROMPT_V6

# ---------------------------------------------------------------------------
# Weather-Mapped Closet (v6 anchor patch)
# Replaces A–H taste-cluster catalog.
# All variants derived from 105936 luxury private-secretary register.
# Palette: ivory, cream, champagne, camel, charcoal, muted taupe.
# Silhouette: fitted/elegant, premium handbag always present.
# ---------------------------------------------------------------------------

_WEATHER_CLOSET: Dict[str, Dict[str, str]] = {
    "clear_cool": {
        "label": "Clear / Cool (≤18°C)",
        "conditions": "clear or partly cloudy, ≤18°C",
        "outfit": (
            "A luxury ivory or cream silk-knit top with clean refined structure, "
            "paired with an elegant fitted skirt in warm champagne or soft ivory. "
            "Premium structured handbag. Delicate pearl or simple gold earrings. Slim watch. "
            "Private-owner luxury register — never casual, never public-facing."
        ),
    },
    "cold": {
        "label": "Cold (≤10°C)",
        "conditions": "any, ≤10°C",
        "outfit": (
            "A premium camel or ivory cashmere overcoat — clean structured silhouette, "
            "worn over a fine-knit top in ivory or cream. "
            "Fitted luxury skirt in warm charcoal or ivory. Premium structured handbag. Slim watch. "
            "Seasonal warmth at luxury register — overcoat quality, not knitwear bulk."
        ),
    },
    "rainy": {
        "label": "Rainy",
        "conditions": "rainy, any temperature",
        "outfit": (
            "A refined ivory or camel luxury trench coat or structured luxury coat, "
            "belted with clean lines. Fine-knit top underneath in ivory. "
            "Fitted skirt in muted champagne or warm taupe. Premium structured handbag. "
            "Rain does not lower the register — same owner-facing private luxury mood."
        ),
    },
    "warm": {
        "label": "Warm (19–26°C)",
        "conditions": "any, 19–26°C",
        "outfit": (
            "A light ivory silk-knit blouse with refined silhouette and subtle sheen, "
            "paired with an elegant fitted skirt in champagne or cream satin-blend. "
            "Premium luxury handbag. Slim watch. "
            "Breathable but never casual — same owner-facing private exclusivity at warm temperature."
        ),
    },
    "hot": {
        "label": "Hot (≥27°C)",
        "conditions": "any, ≥27°C",
        "outfit": (
            "A breathable premium ivory silk-blend top with clean structure and elegant silhouette, "
            "paired with a refined fitted skirt in champagne or cream. Premium handbag. "
            "No casual summer styling — hot weather does not change the luxury register."
        ),
    },
    "snowy": {
        "label": "Snowy / Freezing (≤0°C)",
        "conditions": "snow or freezing, ≤0°C",
        "outfit": (
            "A premium cashmere overcoat in camel or ivory — impeccably structured, no bulk. "
            "Fine-knit top underneath in ivory or cream. Luxury fitted skirt. "
            "Premium structured handbag. "
            "Seasonal but never domestic — always at luxury register."
        ),
    },
}

_DEFAULT_CLOSET_KEY = "clear_cool"


def _weather_to_closet_key(
    weather_condition: str,
    temperature_c: Optional[float],
    season: Optional[str],
) -> str:
    """Map weather inputs to a _WEATHER_CLOSET key."""
    cond = (weather_condition or "").strip().lower()
    season_lower = (season or "").strip().lower()

    # Temperature takes priority when available
    if temperature_c is not None:
        if temperature_c <= 0:
            return "snowy"
        if temperature_c <= 10:
            return "cold"
        if temperature_c >= 27:
            return "hot"
        if temperature_c >= 19:
            return "warm"
        # 11–18°C falls through to condition check below

    # Condition-based fallback
    if cond == "snow" or "winter" in season_lower:
        return "snowy"
    if cond == "cold":
        return "cold"
    if cond == "rainy":
        return "rainy"
    if "humid" in season_lower or cond in ("humid_hot",):
        return "hot"

    return _DEFAULT_CLOSET_KEY


def _resolve_wardrobe(
    weather_condition: str,
    temperature_c: Optional[float],
    season: Optional[str],
    taste_cluster: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve weather inputs to a 105936-family wardrobe entry.

    taste_cluster: legacy override — if it matches a valid closet key it is
    honoured; old A–H cluster names are silently ignored and weather takes over.
    """
    # taste_cluster override: accept only if it's a valid closet key
    if taste_cluster and taste_cluster.lower() in _WEATHER_CLOSET:
        closet_key = taste_cluster.lower()
    else:
        closet_key = _weather_to_closet_key(weather_condition, temperature_c, season)

    entry = _WEATHER_CLOSET[closet_key]

    # weather_outfit_source metadata (unchanged contract)
    if temperature_c is None:
        weather_outfit_source = "limited_condition_string"
    else:
        weather_outfit_source = "condition_plus_temperature"

    return {
        "outfit_descriptor": entry["outfit"],
        "weather_case": entry["label"],
        "outfit_map_key": closet_key,
        "weather_closet_key": closet_key,
        "weather_closet_label": entry["label"],
        # Keep taste_cluster key for backward compat in report consumers
        "taste_cluster": closet_key,
        "taste_cluster_label": entry["label"],
        "weather_outfit_source": weather_outfit_source,
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
    taste_cluster: Optional[str] = None,
    emotional_temperature: str = "medium",
    gesture_variant: Optional[str] = None,
) -> Dict[str, Any]:
    """Build Contract v6 bottom-shot prompt from weather/context inputs.

    Does NOT call any image API. Returns a dict with:
      - prompt_text, negative_prompt, weather_outfit_shell,
      - fixed_identity_gene, fixed_role_scene_gene, fixed_camera_gene,
      - fixed_expression_gene, fixed_prop_gesture_gene,
      - assembly_order, reference_assets, builder_status, weather_input_metadata
    """
    if family_id not in SUPPORTED_FAMILIES:
        raise ValueError(
            f"Unsupported family_id: {family_id!r}. Must be one of {SUPPORTED_FAMILIES}"
        )

    wardrobe_result = _resolve_wardrobe(weather_condition, temperature_c, season, taste_cluster)
    outfit_text = wardrobe_result["outfit_descriptor"]

    prompt_parts = [
        SCENE_LOCK,
        FIXED_IDENTITY_GENE,
        FIXED_ROLE_SCENE_GENE,
        FIXED_EXPRESSION_GENE,
        outfit_text,
        FIXED_PROP_GESTURE_GENE,
        FIXED_CAMERA_GENE,
    ]
    prompt_text = "\n\n".join(p.strip() for p in prompt_parts if p.strip())

    weather_input_metadata: Dict[str, Any] = {
        "weather_condition_input": weather_condition,
        "temperature_c_unavailable": temperature_c is None,
        "fine_dust_unavailable": weather_condition not in ("fine_dust", "haze"),
        "season_input": season,
        "weather_outfit_source": wardrobe_result["weather_outfit_source"],
    }
    if temperature_c is not None:
        weather_input_metadata["temperature_c"] = temperature_c
    if weather_condition in ("fine_dust", "haze"):
        weather_input_metadata["fine_dust_unavailable"] = False

    return {
        "prompt_text": prompt_text,
        "negative_prompt": NEGATIVE_PROMPT_V6,
        "weather_outfit_shell": {
            "outfit_descriptor": outfit_text,
            "weather_case": wardrobe_result["weather_case"],
            "outfit_map_key": wardrobe_result["outfit_map_key"],
            "weather_condition": weather_condition,
            "temperature_c": temperature_c,
            "season": season,
            "gene": "C_variable_wardrobe",
            "taste_cluster": wardrobe_result["taste_cluster"],
            "taste_cluster_label": wardrobe_result["taste_cluster_label"],
        },
        "fixed_identity_gene": {
            "text": FIXED_IDENTITY_GENE,
            "gene": "A_fixed_identity",
            "invariants": IDENTITY_INVARIANTS,
        },
        "fixed_role_scene_gene": {
            "text": FIXED_ROLE_SCENE_GENE,
            "gene": "B_fixed_role_relationship",
            "invariants": ROLE_SCENE_INVARIANTS,
        },
        "fixed_expression_gene": {
            "text": FIXED_EXPRESSION_GENE,
            "gene": "C_fixed_expression",
            "invariants": EXPRESSION_INVARIANTS,
        },
        "fixed_prop_gesture_gene": {
            "text": FIXED_PROP_GESTURE_GENE,
            "gene": "E_fixed_prop_gesture",
            "invariants": PROP_GESTURE_INVARIANTS,
        },
        "fixed_camera_gene": {
            "text": FIXED_CAMERA_GENE,
            "gene": "F_fixed_camera_framing",
            "invariants": CAMERA_INVARIANTS,
        },
        "assembly_order": ASSEMBLY_ORDER,
        "reference_assets": {
            "primary_bottom_anchor": {
                "path": BOTTOM_ANCHOR_PATH,
                "role": BOTTOM_ANCHOR_ROLE,
                "note": "Primary visual anchor — passed as first image input (slot 0) in Bottom generation.",
            },
            "secondary_continuity_reference": {
                "path": ASSET01_PATH,
                "role": ASSET01_ROLE,
                "note": "Secondary same-person continuity reference — passed as second image input (slot 1) if available.",
            },
        },
        "builder_status": {
            "generation_allowed": False,
            "runtime_enabled": False,
            "owner_approval_required": True,
            "image_api_called": False,
            "contract_version": "v6",
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
        "bottom_shot_prompt_contract_version": "v6",
        "bottom_shot_prompt_builder_status": "built_no_generation",
        "bottom_shot_generation_allowed": False,
        "bottom_shot_image_api_called": False,
        "bottom_shot_weather_case": result["weather_outfit_shell"]["weather_case"],
        "bottom_shot_outfit_map_key": result["weather_outfit_shell"]["outfit_map_key"],
        "bottom_shot_weather_outfit_source": result["weather_input_metadata"]["weather_outfit_source"],
        "bottom_shot_prompt_preview": result["prompt_text"][:200],
    }
