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
# Gene A — Fixed Identity Gene (v6: fresh/attractive, strip authority)
# ---------------------------------------------------------------------------

FIXED_IDENTITY_GENE = (
    "A Korean woman in her mid-to-late thirties with a naturally refined face, "
    "slightly angular jaw, almond-shaped eyes with a calm and perceptive gaze, "
    "a sleek side-parted short bob — hair lying close to the jaw line, "
    "naturally smooth and straight, no curl at the ends, no volume at the tips, "
    "and thin metal-framed rectangular glasses resting naturally on her face. "
    "Her look carries noble sensuality and controlled feminine magnetism, "
    "expressed through posture, silhouette, gaze, and luxury styling — never through exposure. "
    "Premium presence without effort, the kind of person you remember without knowing why."
)

IDENTITY_INVARIANTS = {
    "age": "mid-to-late 30s",
    "hair": "sleek side-parted short bob, hair close to jaw, smooth and straight, no curl at ends, no C-curl, no bangs, no updos, no ponytails",
    "glasses": "thin metal rectangular frames — always present",
    "expression": "noble sensuality, controlled feminine magnetism, cool intelligence softened only for the owner",
    "ethnicity": "Korean woman",
}

# ---------------------------------------------------------------------------
# Gene B — Fixed Role + Relationship Gene (v6: secretary, owner farewell)
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
# Gene C — Expression Gene (v6: fresh composed smile)
# ---------------------------------------------------------------------------

FIXED_EXPRESSION_GENE = (
    "Her expression is a restrained composed slight smile — cool reserved intelligence, barely softened for the owner. "
    "lips barely curved at the corners. "
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
# Gene E — Prop + Gesture Gene (v6: handbag, hand farewell)
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
# Gene F — Camera/Framing Gene (v6: single consistent knee-up signal)
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
# [Scene lock] → [Identity] → [Role/Relationship] → [Expression]
#   → [Wardrobe] → [Prop/Gesture] → [Camera] → [Negative]

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
# Negative Prompt v6 — retargeted blocklist
# ---------------------------------------------------------------------------

NEGATIVE_PROMPT_V6 = (
    "deformed hands, extra fingers, fused fingers, blurry face, asymmetric eyes, "
    "double chin, thick-framed glasses, no glasses, sunglasses, colored glasses, "
    "round glasses, oval glasses, "
    "heavy jewelry, statement necklace, flashy accessories, "
    # persona drift blocks
    "CEO portrait, executive portrait, consultant headshot, company profile photo, "
    "professor portrait, manager portrait, corporate uniform, "
    "blazer, mock-neck sweater, business suit, formal office attire, "
    # wardrobe failures
    "casual clothing, streetwear, athletic wear, hoodie, t-shirt, crop top, "
    "low-cut neckline, V-neck wrap dress, open-front dress, décolleté, "
    "plain market clothes, cheap mall fashion, basic office-worker casual, "
    # framing failures
    "full body shot, visible feet, wide shot, establishing shot, "
    "tight headshot, bust-only crop, mid-chest-to-crown crop, "
    "outfit-first composition, full-body lookbook, "
    # environment failures
    "outdoor scene, open door, open doorway, window with outdoor view, "
    "tablet, briefing tablet, tech screen, monitor wall, monitor, "
    "desk, keyboard, multiple monitors, large screen background, reading device, "
    "lobby, atrium, open corridor, open hotel-like room, "
    "briefing posture, briefing host, senior analyst at desk, "
    # expression/style failures
    "warm motherly smile, guardian-like smile, matronly expression, "
    "broad open smile, lively smile, wide smile, big smile, "
    "hands-clasped polite-matron pose, "
    # gesture failures
    "raised hand wave, open palm wave, waving pose, large hand gesture, "
    "event greeter pose, hotel receptionist pose, customer service pose, "
    # persona drift
    "event greeter, hotel receptionist, office receptionist, friendly counselor, "
    "cardigan office lady, lifestyle blogger, friendly middle-aged office worker, "
    "overly warm lighting, golden hour, harsh shadows, overexposed face, "
    "excessive makeup, heavy contouring, dramatic eye makeup, "
    "motion blur, film grain, painterly style, illustration, anime, cartoon, "
    "C-curl cute bob, inward-curled bob, curled ends bob, volume at tips, "
    "young office worker, glamour model, "
    # approachability/public-facing drift blocks
    "friendly smile, welcoming expression, approachable warmth, "
    "ordinary office lady, lifestyle model, cheap sexiness, "
    "hostess, bar mood, lounge mood, lounge hostess, "
    "public-facing smile, open approachable expression"
)

# Keep v5 name as alias for backward compat in any external references
NEGATIVE_PROMPT_V5 = NEGATIVE_PROMPT_V6

# ---------------------------------------------------------------------------
# Taste Cluster Wardrobe Catalog (v6 — replaces weather→blazer map)
# ---------------------------------------------------------------------------

_TASTE_CLUSTER_CATALOG: Dict[str, Dict[str, str]] = {
    "A": {
        "label": "Soft Classic",
        "outfit": (
            "A refined ivory silk-knit draped layer over a silk blouse in soft champagne, "
            "paired with a slim structured skirt in warm beige. "
            "Small structured premium handbag. Pearl stud earrings. "
            "Quiet luxury — elevated, never casual."
        ),
    },
    "B": {
        "label": "Elegant Office Casual",
        "outfit": (
            "A luxury fitted silk-knit boat-neck top in warm ivory, "
            "paired with a satin-finish high-waisted structured skirt in champagne. "
            "Premium mini handbag. Slim watch and delicate pearl earrings."
        ),
    },
    "C": {
        "label": "Cool Executive Off-Duty",
        "outfit": (
            "A smoky blue silk blouse with subtle sheen under a refined ivory structured fine-knit layer, "
            "paired with a dark charcoal pencil skirt. "
            "Slim watch only. Clean, intelligent, premium. "
            "Luxury private-secretary off-duty — understated and high-end."
        ),
    },
    "D": {
        "label": "Feminine Minimal",
        "outfit": (
            "A refined neutral shirt dress with a thin leather belt at the waist. "
            "Small gold earrings and a slim watch. "
            "Clean silhouette, approachable elegance."
        ),
    },
    "E": {
        "label": "Luxury Quiet",
        "outfit": (
            "A premium cashmere knit top in oatmeal or cream, "
            "paired with a dark pencil skirt in fine wool. "
            "Small leather handbag. Restrained, high-end, mature elegance."
        ),
    },
    "F": {
        "label": "Summer Light",
        "outfit": (
            "A short-sleeve office-appropriate silk blouse in pale ivory "
            "under a lightweight linen-blend cardigan in soft ecru, "
            "paired with a beige structured skirt. "
            "Airy and fresh, sleeves always covered under cardigan."
        ),
    },
    "G": {
        "label": "Fall/Winter Warm",
        "outfit": (
            "A structured premium camel cashmere overcoat draped over a charcoal fine-knit top, "
            "paired with a dark structured skirt. "
            "Small premium leather handbag. Warm indoor evening light. "
            "Seasonal warmth at luxury register — overcoat quality, not knitwear casual."
        ),
    },
    "H": {
        "label": "Personal but Premium",
        "outfit": (
            "A refined knit dress in warm beige with a light trench coat draped over one arm. "
            "Premium structured handbag. "
            "Slightly more private off-duty moment, still office-exit appropriate."
        ),
    },
}

_DEFAULT_TASTE_CLUSTER = "B"

# ---------------------------------------------------------------------------
# Weather → fabric/layer modifier (v6: weather adjusts fabric, never blazer)
# ---------------------------------------------------------------------------

_TEMP_THRESHOLD_WARM_C = 18.0
_TEMP_THRESHOLD_HOT_C = 28.0


def _weather_fabric_modifier(
    weather_condition: str,
    temperature_c: Optional[float],
    season: Optional[str],
) -> str:
    cond = (weather_condition or "").strip().lower()
    season_lower = (season or "").strip().lower()

    if "winter" in season_lower or cond in ("snow", "cold"):
        return "Heavy knit layers, cashmere or wool textures for cold weather."
    if temperature_c is not None and temperature_c < 10.0:
        return "Warm layering with fine-knit textures for cold conditions."
    if "autumn" in season_lower:
        return "Autumn-weight fabrics with warm tonal palette."
    if temperature_c is not None and temperature_c >= _TEMP_THRESHOLD_HOT_C:
        return "Lightweight breathable fabrics for warm weather."
    if "humid" in season_lower:
        return "Lightweight breathable fabrics for humid conditions."
    if cond in ("rainy",):
        return "Weather-appropriate fabrics with clean lines."
    if cond in ("fine_dust", "haze"):
        return "Indoor-appropriate clean fabrics."
    return ""


def _resolve_weather_outfit_key(
    weather_condition: str,
    temperature_c: Optional[float],
    season: Optional[str],
) -> str:
    cond = (weather_condition or "").strip().lower()
    season_lower = (season or "").strip().lower()

    if "autumn" in season_lower and "evening" in season_lower:
        return "autumn_evening"
    if "winter" in season_lower and "evening" in season_lower:
        return "winter_evening"
    if "humid" in season_lower or (
        temperature_c is not None and temperature_c >= _TEMP_THRESHOLD_HOT_C
    ):
        return "humid_hot"

    if cond in ("clear", "sunny"):
        if temperature_c is None:
            return cond
        if temperature_c >= _TEMP_THRESHOLD_WARM_C:
            return "clear_warm"
        return "clear_cool"

    if cond in ("cloudy", "overcast", "rainy", "snow", "cold", "fine_dust", "haze"):
        return cond

    return "cloudy"


def _resolve_wardrobe(
    weather_condition: str,
    temperature_c: Optional[float],
    season: Optional[str],
    taste_cluster: Optional[str] = None,
) -> Dict[str, Any]:
    cluster_key = (taste_cluster or _DEFAULT_TASTE_CLUSTER).upper()
    if cluster_key not in _TASTE_CLUSTER_CATALOG:
        cluster_key = _DEFAULT_TASTE_CLUSTER

    entry = _TASTE_CLUSTER_CATALOG[cluster_key]
    outfit_text = entry["outfit"]

    fabric_mod = _weather_fabric_modifier(weather_condition, temperature_c, season)
    if fabric_mod:
        outfit_text = f"{outfit_text} {fabric_mod}"

    weather_key = _resolve_weather_outfit_key(weather_condition, temperature_c, season)

    weather_case_labels = {
        "clear_warm": "Clear / Sunny (warm, 18°C+)",
        "clear_cool": "Clear / Sunny (cool, below 18°C)",
        "clear": "Clear (temperature unspecified)",
        "sunny": "Clear / Sunny (temperature unspecified)",
        "cloudy": "Partly Cloudy",
        "overcast": "Overcast / Grey",
        "rainy": "Light Rain / Drizzle",
        "snow": "Snow / Cold (below 2°C)",
        "cold": "Cold",
        "fine_dust": "Fine Dust / Haze",
        "haze": "Fine Dust / Haze",
        "autumn_evening": "Autumn Evening",
        "winter_evening": "Winter Evening",
        "humid_hot": "Humid / Hot (above 28°C)",
    }

    return {
        "outfit_descriptor": outfit_text,
        "weather_case": weather_case_labels.get(weather_key, "Partly Cloudy"),
        "outfit_map_key": weather_key,
        "taste_cluster": cluster_key,
        "taste_cluster_label": entry["label"],
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
        raise ValueError(f"Unsupported family_id: {family_id!r}. Must be one of {SUPPORTED_FAMILIES}")

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
