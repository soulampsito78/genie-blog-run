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

041559 baseline locked:
  - 105936 = slot 0 primary Bottom visual anchor
  - Asset01 = slot 1 secondary continuity reference
  - Same Key-Suri face family
  - Noble sensuality, exclusive owner-facing private mood
  - Warm wooden executive door setting
  - Premium handbag signal
  - Weather-aware wardrobe logic
  - QA-only isolation

Wardrobe & pose expansion (post-041559):
  - Each weather key has 3 premium 105936-family closet variants
  - 9 controlled pose variants; all private, owner-facing, not public
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Reference constants — v6 anchor hierarchy (041559 baseline locked)
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
# Gene E — Prop + Gesture Gene (base constraint, always present)
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
# Pose Variant Pool — controlled private gestures, not public
# One variant is selected per generation to add pose richness within the
# 041559 baseline identity band.
# ---------------------------------------------------------------------------

POSE_VARIANT_POOL: List[str] = [
    "One hand lightly holding the handbag handle, the other resting with quiet composure.",
    "One hand resting near the door handle — fingertips barely touching, a private closing gesture.",
    "Fingertips lightly near the handbag strap, wrist relaxed, posture still and composed.",
    "Hand lightly touching the coat lapel — a refined self-composed gesture, entirely private.",
    "A slim watch-adjusting gesture — unhurried, intimate, a closing ritual for the owner only.",
    "A slight turn from the doorway: one shoulder angled gently toward the owner, gaze steady.",
    "One shoulder angled softly toward the owner — not a full turn, a quiet acknowledgment.",
    "Gaze directly and calmly to the owner — composed, private, unattainable.",
    "A small private closing gesture near the chest — intimate, contained, not raised.",
]

# Forbidden pose terms — none of these must appear in any POSE_VARIANT_POOL entry.
POSE_FORBIDDEN_TERMS: List[str] = [
    "wave", "raised hand", "greeting", "receptionist", "hostess",
    "pointing", "public", "catalog", "stiff", "lifelessly",
]

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
# Note: pose_variant is appended within the prop/gesture section, not a new gene.
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

NEGATIVE_PROMPT_V5 = NEGATIVE_PROMPT_V6

# ---------------------------------------------------------------------------
# Weather-Mapped Closet Catalog — 105936-family premium closet
# Each weather key has 3 variants.
# Palette: ivory, cream, champagne, camel, charcoal, muted taupe.
# All variants: premium handbag always present, fitted/elegant silhouette.
# ---------------------------------------------------------------------------

WEATHER_CLOSET_CATALOG: Dict[str, Dict[str, Any]] = {
    "clear_cool": {
        "label": "Clear / Cool (≤18°C)",
        "conditions": "clear or partly cloudy, ≤18°C",
        "variants": [
            (
                "A luxury ivory silk-knit top with clean refined structure, "
                "paired with a satin pencil skirt in warm ivory. "
                "Beige premium structured handbag. Pearl stud earrings. "
                "Private-owner luxury register — never casual, never public-facing."
            ),
            (
                "A champagne fine-knit blouse with subtle sheen and refined silhouette, "
                "paired with a cream fitted skirt in silk-blend. "
                "Structured premium handbag. Slim watch. "
                "Understated luxury — the exact private-owner register of the reference image."
            ),
            (
                "A cream boat-neck knit top, fitted and elegant with clean lines, "
                "paired with a silk-blend fitted skirt in soft champagne. "
                "Small luxury handbag. Simple gold stud earrings. "
                "Cool and composed — 105936-family premium closet."
            ),
        ],
    },
    "cold": {
        "label": "Cold (≤10°C)",
        "conditions": "any, ≤10°C",
        "variants": [
            (
                "A premium camel cashmere overcoat — clean structured silhouette, "
                "worn over an ivory fine-knit top. "
                "Refined skirt in warm taupe or ivory. Premium structured handbag. Slim watch. "
                "Seasonal warmth at luxury register — overcoat quality, not knitwear bulk."
            ),
            (
                "An ivory wool coat with elegant clean lines, "
                "worn over a champagne fine-knit layer. "
                "Taupe fitted luxury skirt. Premium structured handbag. "
                "Refined cold-weather register — same private-owner mood."
            ),
            (
                "A charcoal fine-wool coat over a cream fine-knit inner layer — "
                "clean, structured, impeccably proportioned. "
                "Muted luxury fitted skirt in ivory or taupe. Premium structured handbag. "
                "Cool intelligent register — 105936-family closet in cold weather."
            ),
        ],
    },
    "rainy": {
        "label": "Rainy",
        "conditions": "rainy, any temperature",
        "variants": [
            (
                "An ivory luxury trench coat, belted with clean structure, "
                "over a silk-knit inner in cream. "
                "Refined fitted skirt in champagne. Premium structured handbag. "
                "Rain does not lower the register — same owner-facing private luxury mood."
            ),
            (
                "A camel luxury trench coat with refined lapels and tailored belt, "
                "over a champagne silk blouse. "
                "Taupe fitted skirt. Premium structured handbag. "
                "Polished and private — the rain is outside, not in her register."
            ),
            (
                "A charcoal luxury coat — structured, not sporty, not casual — "
                "over an ivory fine-knit layer. "
                "Refined fitted skirt in muted champagne. Premium handbag. "
                "Quiet authority without exposure — 105936-family rainy register."
            ),
        ],
    },
    "warm": {
        "label": "Warm (19–26°C)",
        "conditions": "any, 19–26°C",
        "variants": [
            (
                "A light ivory silk-knit blouse with refined silhouette and subtle sheen, "
                "paired with an elegant fitted skirt in champagne. "
                "Premium luxury handbag. Slim watch. "
                "Breathable but never casual — owner-facing private exclusivity at warm temperature."
            ),
            (
                "A champagne short-sleeve silk-blend top — elegant silhouette, "
                "never revealing, fitted at the waist — "
                "paired with a refined ivory fitted skirt. "
                "Premium structured handbag. "
                "Warm-weather luxury register — same private closing mood."
            ),
            (
                "A cream lightweight knit top with clean refined structure, "
                "paired with a satin-blend fitted skirt in soft champagne. "
                "Small luxury handbag. Simple stud earrings. "
                "Cool and composed even in warm air — 105936-family warm register."
            ),
        ],
    },
    "hot": {
        "label": "Hot (≥27°C)",
        "conditions": "any, ≥27°C",
        "variants": [
            (
                "A breathable premium ivory silk-blend top with clean structure "
                "and an elegant silhouette, "
                "paired with a refined fitted skirt in champagne or cream. "
                "Premium handbag. No casual summer styling — luxury register unchanged."
            ),
            (
                "A cream sleeveless high-neck luxury top — "
                "no exposure, no casual summer cut — "
                "with a refined champagne fitted skirt. "
                "Small premium handbag. Slim watch. "
                "Hot weather does not change the private-owner exclusivity."
            ),
            (
                "A champagne lightweight blouse in fine silk-blend with refined drape, "
                "paired with a fitted satin skirt in soft ivory. "
                "Premium structured handbag. "
                "The same 105936-family luxury register — just in finer, lighter fabric."
            ),
        ],
    },
    "snowy": {
        "label": "Snowy / Freezing (≤0°C)",
        "conditions": "snow or freezing, ≤0°C",
        "variants": [
            (
                "A premium ivory cashmere coat — impeccably structured, no bulk — "
                "with an elegant refined scarf in ivory silk or cashmere. "
                "Premium structured handbag. "
                "Seasonal but never domestic — always at luxury register."
            ),
            (
                "A camel wool-cashmere coat with clean tailored lines, "
                "over a cream fine-knit inner layer. "
                "Refined fitted skirt in ivory. Premium structured handbag. "
                "Cold-weather luxury — not aunt-styling, not bulk-layer office wear."
            ),
            (
                "A charcoal premium structured coat — fine wool-cashmere blend, "
                "impeccably proportioned, never heavy or shapeless — "
                "with an ivory refined scarf. Premium handbag. "
                "Same 105936-family private-owner register, even in freezing weather."
            ),
        ],
    },
}

_DEFAULT_CLOSET_KEY = "clear_cool"


def _weather_to_closet_key(
    weather_condition: str,
    temperature_c: Optional[float],
    season: Optional[str],
) -> str:
    """Map weather inputs to a WEATHER_CLOSET_CATALOG key."""
    cond = (weather_condition or "").strip().lower()
    season_lower = (season or "").strip().lower()

    if temperature_c is not None:
        if temperature_c <= 0:
            return "snowy"
        if temperature_c <= 10:
            return "cold"
        if temperature_c >= 27:
            return "hot"
        if temperature_c >= 19:
            return "warm"

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
    wardrobe_variant: Optional[int] = None,
) -> Dict[str, Any]:
    """Resolve weather inputs to a 105936-family wardrobe entry.

    wardrobe_variant: index into the variant list. If None, random selection.
    taste_cluster: legacy override — accepted only if it matches a valid closet key.
    """
    if taste_cluster and taste_cluster.lower() in WEATHER_CLOSET_CATALOG:
        closet_key = taste_cluster.lower()
    else:
        closet_key = _weather_to_closet_key(weather_condition, temperature_c, season)

    entry = WEATHER_CLOSET_CATALOG[closet_key]
    variants = entry["variants"]

    if wardrobe_variant is not None:
        idx = wardrobe_variant % len(variants)
    else:
        idx = random.randrange(len(variants))

    outfit_text = variants[idx]

    if temperature_c is None:
        weather_outfit_source = "limited_condition_string"
    else:
        weather_outfit_source = "condition_plus_temperature"

    return {
        "outfit_descriptor": outfit_text,
        "outfit_variant_index": idx,
        "weather_case": entry["label"],
        "outfit_map_key": closet_key,
        "weather_closet_key": closet_key,
        "weather_closet_label": entry["label"],
        "taste_cluster": closet_key,
        "taste_cluster_label": entry["label"],
        "weather_outfit_source": weather_outfit_source,
    }


def _select_pose_variant(pose_variant: Optional[int] = None) -> str:
    """Select a pose variant from POSE_VARIANT_POOL.

    pose_variant: index into the pool. If None, random selection.
    """
    if pose_variant is not None:
        return POSE_VARIANT_POOL[pose_variant % len(POSE_VARIANT_POOL)]
    return random.choice(POSE_VARIANT_POOL)


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
    wardrobe_variant: Optional[int] = None,
    pose_variant: Optional[int] = None,
) -> Dict[str, Any]:
    """Build Contract v6 bottom-shot prompt from weather/context inputs.

    Does NOT call any image API. Returns a dict with:
      - prompt_text, negative_prompt, weather_outfit_shell,
      - fixed_identity_gene, fixed_role_scene_gene, fixed_camera_gene,
      - fixed_expression_gene, fixed_prop_gesture_gene,
      - assembly_order, reference_assets, builder_status, weather_input_metadata

    wardrobe_variant: int index to select a specific wardrobe variant (for testing/determinism).
    pose_variant: int index to select a specific pose variant (for testing/determinism).
    """
    if family_id not in SUPPORTED_FAMILIES:
        raise ValueError(
            f"Unsupported family_id: {family_id!r}. Must be one of {SUPPORTED_FAMILIES}"
        )

    wardrobe_result = _resolve_wardrobe(
        weather_condition, temperature_c, season, taste_cluster, wardrobe_variant
    )
    outfit_text = wardrobe_result["outfit_descriptor"]
    pose_text = _select_pose_variant(pose_variant)

    # Prop/gesture section: base constraint + selected pose variant
    prop_gesture_section = f"{FIXED_PROP_GESTURE_GENE}\n{pose_text}"

    prompt_parts = [
        SCENE_LOCK,
        FIXED_IDENTITY_GENE,
        FIXED_ROLE_SCENE_GENE,
        FIXED_EXPRESSION_GENE,
        outfit_text,
        prop_gesture_section,
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
            "outfit_variant_index": wardrobe_result["outfit_variant_index"],
            "weather_case": wardrobe_result["weather_case"],
            "outfit_map_key": wardrobe_result["outfit_map_key"],
            "weather_condition": weather_condition,
            "temperature_c": temperature_c,
            "season": season,
            "gene": "C_variable_wardrobe",
            "taste_cluster": wardrobe_result["taste_cluster"],
            "taste_cluster_label": wardrobe_result["taste_cluster_label"],
        },
        "pose_variant_text": pose_text,
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
