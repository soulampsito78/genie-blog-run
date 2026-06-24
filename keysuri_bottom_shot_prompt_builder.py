"""Key-Suri bottom-shot prompt builder — Contract v6 implementation.

Contract: docs/keysuri/KEYSURI_R6B_BOTTOM_SHOT_EMOTIONAL_LOCKIN_PLAN.md

Status:
  generation_allowed:      false
  runtime_enabled:         true (through keysuri_bottom_shot_generation)
  owner_approval_required: true

This module builds prompt text from Contract v6 but does NOT:
  - call any image API
  - set KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED

Wire-in point: the Korea beta ``if variation_enabled:`` branch in
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
  - Weather and limited-input keys rotate semantically distinct premium looks
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
    "Her sleek side-parted short bob lies close to the jaw — same sleek chin-length bob silhouette as the top image, "
    "same side-parted compact bob, jawline-length hair contour, smooth with natural inward-folding ends at the jaw, "
    "restrained and consistent hair volume, same haircut across all Kee-Suri runs. "
    "Thin metal rectangular glasses rest naturally on her face. "
    "Noble sensuality and controlled feminine magnetism expressed through posture, silhouette, and gaze — "
    "never through exposure. Premium presence without effort."
)

ANCHOR_ANTI_COPY_INSTRUCTION = (
    "Preserve identity only from the reference images: face, short bob, thin glasses, "
    "body proportions, and refined private-owner presence. Do not copy the reference outfit, "
    "reference colors, handbag, or door composition. Replace the wardrobe and setting with "
    "the selected wardrobe, prop, and scene descriptors below. The selected wardrobe must "
    "visibly differ from the anchor outfit while preserving the same person."
)

IDENTITY_INVARIANTS = {
    "anchor": "105936 reference image — primary visual identity source",
    "hair": "sleek side-parted short bob, same sleek chin-length bob silhouette as top image, same side-parted compact bob, hair close to jaw, smooth with natural inward-folding ends at the jaw, restrained and consistent hair volume, no bangs, no updos, no ponytails",
    "glasses": "thin metal rectangular frames — always present",
    "expression": "noble sensuality, controlled feminine magnetism, cool intelligence softened only for the owner",
    "ethnicity": "Korean woman",
}

# ---------------------------------------------------------------------------
# Gene B — Fixed Role + Relationship Gene
# ---------------------------------------------------------------------------

FIXED_ROLE_SCENE_GENE = (
    "She is Key-Suri, a premium private AI secretary. "
    "This is a secondary briefing-support visual — she is at a private work surface or side briefing table, "
    "reviewing printed briefing cards, memo notes, or a compact tech signal board for the owner — 대표님. "
    "She may appear at the side or partially engaged with the work surface; this is not a face-first portrait. "
    "The composition supports the briefing, not her appearance. "
    "Cool intelligence in a quiet working moment. Private, composed, assistant-facing — reserved only for 대표님."
)

ROLE_SCENE_INVARIANTS = {
    "role": "premium private AI secretary — secondary briefing-support visual at a private work surface",
    "emotional_register": "quiet working moment — cool intelligence, composed, assistant-facing, reserved for 대표님",
    "scene": "private work surface or side briefing table with briefing cards, memo notes, or tech signal board",
    "viewer_relationship": "reader is the owner (대표님) receiving the briefing support material",
    "forbidden_environment": [
        "busy public lobby, crowded corridor, public event space",
        "hallway, fashion corridor, coat-room, transition space, farewell scene",
        "full-body portrait mode, face-first beauty shot, main character entrance",
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
    "Use only the selected prop descriptor below; a visible prop is optional. "
    "If no prop is selected, keep both hands naturally composed. "
    "Her gesture remains small and restrained, as if closing the day for the owner only. "
    "The gesture is private and contained: not raised, not waving. "
    "Small scale. Interior scale. No tablet. No laptop. No notebook."
)

PROP_GESTURE_INVARIANTS = {
    "required_prop": "selected premium prop or no visible prop",
    "required_gesture": "small restrained private gesture — closing the day for the owner only, not raised, not waving",
    "forbidden": ["tablet", "laptop", "briefing device"],
}

# ---------------------------------------------------------------------------
# Pose Variant Pool — controlled private gestures, not public
# One variant is selected per generation to add pose richness within the
# 041559 baseline identity band.
# ---------------------------------------------------------------------------

POSE_VARIANT_POOL: List[str] = [
    "One hand resting naturally at her side, the other held with quiet composure.",
    "Fingertips barely touching a nearby architectural detail, a private closing gesture.",
    "Wrist relaxed near the waist, posture still and composed.",
    "Hand lightly touching the neckline or outer layer, a refined self-composed gesture.",
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
    "Upper-body to waist-up framing, desk-adjacent angle — "
    "showing Kee-Suri at or near the work surface with visible briefing material. "
    "This is a secondary briefing-support visual: the work surface and briefing material "
    "share the frame with the subject; face is not the sole focal point. "
    "Camera angle: eye level or slightly above, never dramatically below chin level. "
    "Lens: 85mm portrait equivalent, shallow depth of field, "
    "subject and briefing material sharp, background softly defocused."
)

CAMERA_INVARIANTS = {
        "framing": "upper-body to waist-up, desk-adjacent — work surface and briefing material share frame with subject",
    "angle": "eye level or slightly above — never dramatically below chin",
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
    "selected private premium interior in background, restrained executive-floor lighting. "
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
    "stiff corporate blazer, uniform navy blazer, mock-neck sweater, business suit, "
    "casual clothing, streetwear, athletic wear, hoodie, t-shirt, crop top, "
    "revealing low-cut neckline, open-front dress, décolleté, "
    "plain market clothes, cheap mall fashion, basic office-worker casual, "
    "full body shot, visible feet, wide shot, establishing shot, "
    "tight headshot, bust-only crop, mid-chest-to-crown crop, "
    "outfit-first composition, full-body lookbook, "
    "outdoor street scene, open doorway into a busy room, "
    "tablet, briefing tablet, tech screen, monitor wall, monitor, "
    "desk, keyboard, multiple monitors, large screen background, reading device, "
    "busy public lobby, crowded atrium, public open corridor, open hotel-like room, "
    "briefing posture, briefing host, senior analyst at desk, "
    "warm motherly smile, guardian-like smile, matronly expression, "
    "broad open smile, lively smile, wide smile, big smile, "
    "hands-clasped polite-matron pose, "
    "raised hand wave, open palm wave, waving pose, large hand gesture, "
    "event greeter pose, hotel receptionist pose, customer service pose, "
    "event greeter, hotel receptionist, office receptionist, friendly counselor, "
    "cheap office-cardigan styling, lifestyle blogger, friendly middle-aged office worker, "
    "overly warm lighting, golden hour, harsh shadows, overexposed face, "
    "excessive makeup, heavy contouring, dramatic eye makeup, "
    "motion blur, film grain, painterly style, illustration, anime, cartoon, "
    "C-curl cute bob, inward-curled bob, curled ends bob, volume at tips, "
    "young office worker, glamour model, "
    "friendly smile, welcoming expression, approachable warmth, "
    "ordinary office lady, lifestyle model, cheap sexiness, "
    "hostess, bar mood, lounge mood, lounge hostess, "
    "public-facing smile, open approachable expression, "
    "no full-body hallway portrait, no fashion hallway shot, "
    "no luxury transition shot, no coat-room portrait, no posing in corridor, "
    "no handbag-focused portrait, no main character beauty shot, "
    "no repeating top image as another portrait"
)

NEGATIVE_PROMPT_V5 = NEGATIVE_PROMPT_V6

# ---------------------------------------------------------------------------
# Weather-mapped wardrobe catalog. Variants remain ``str`` instances for
# compatibility while carrying structured metadata for artifact traceability.
# ---------------------------------------------------------------------------


class WardrobeVariant(str):
    def __new__(
        cls,
        text: str,
        *,
        family: str,
        palette: str,
        silhouette: str,
        prop: str,
        scene: str,
    ) -> "WardrobeVariant":
        value = str.__new__(cls, text)
        value.family = family
        value.palette = palette
        value.silhouette = silhouette
        value.prop = prop
        value.scene = scene
        return value


def _look(
    text: str,
    *,
    family: str,
    palette: str,
    silhouette: str,
    prop: str,
    scene: str,
) -> WardrobeVariant:
    return WardrobeVariant(
        text,
        family=family,
        palette=palette,
        silhouette=silhouette,
        prop=prop,
        scene=scene,
    )

WEATHER_CLOSET_CATALOG: Dict[str, Dict[str, Any]] = {
    "clear_cool": {
        "label": "Clear / Cool (≤18°C)",
        "conditions": "clear or partly cloudy, ≤18°C",
        "variants": [
            _look(
                "An ink-navy silk blouse with pearl-gray tailored wide-leg trousers, polished and fluid.",
                family="silk_blouse_wide_leg_trousers", palette="ink navy / pearl gray",
                silhouette="fluid tailored wide-leg", prop="slim clutch",
                scene="side briefing table with open documents",
            ),
            _look(
                "A deep-forest fine-knit midi dress with a clean column line and restrained waist definition.",
                family="knit_midi_dress", palette="deep forest",
                silhouette="refined column midi", prop="no visible prop",
                scene="compact briefing desk with printed cards",
            ),
            _look(
                "A dusty-rose silk blouse with a slate-blue A-line midi skirt, elegant without stiffness.",
                family="silk_blouse_a_line_midi", palette="dusty rose / slate blue",
                silhouette="soft A-line midi", prop="smartphone",
                scene="window-side briefing station",
            ),
            _look(
                "A pearl-gray refined cardigan set with espresso relaxed tailored trousers.",
                family="refined_cardigan_relaxed_trousers", palette="pearl gray / espresso brown",
                silhouette="soft layered tailoring", prop="structured handbag",
                scene="compact side table with briefing materials",
            ),
        ],
    },
    "cold": {
        "label": "Cold (≤10°C)",
        "conditions": "any, ≤10°C",
        "variants": [
            _look(
                "A camel cashmere coat over a muted-wine knit midi dress, warm but sharply refined.",
                family="cashmere_coat_knit_dress", palette="camel / muted wine",
                silhouette="long coat over column midi", prop="refined scarf",
                scene="private tech signal board beside a work surface",
            ),
            _look(
                "An ink-navy fine-wool coat with pearl-gray tailored wide-leg trousers and a silk inner layer.",
                family="wool_coat_wide_leg_trousers", palette="ink navy / pearl gray",
                silhouette="long tailored layers", prop="no visible prop",
                scene="private work surface with documents",
            ),
            _look(
                "A deep-forest refined cardigan jacket with a charcoal long pleated skirt.",
                family="cardigan_long_pleated_skirt", palette="deep forest / soft charcoal",
                silhouette="soft jacket over long pleats", prop="structured handbag",
                scene="quiet private work corner with briefing notes",
            ),
            _look(
                "An espresso wrap dress beneath a slate-blue tailored coat, composed and modern.",
                family="wrap_dress_tailored_coat", palette="espresso brown / slate blue",
                silhouette="defined wrap midi with long coat", prop="slim clutch",
                scene="compact briefing desk with printed cards",
            ),
        ],
    },
    "rainy": {
        "label": "Rainy",
        "conditions": "rainy, any temperature",
        "variants": [
            _look(
                "A slate-blue luxury trench over ink-navy tailored wide-leg trousers and a silk blouse.",
                family="trench_wide_leg_trousers", palette="slate blue / ink navy",
                silhouette="belted trench with fluid trousers", prop="slim umbrella",
                scene="private covered briefing station",
            ),
            _look(
                "A deep-forest wrap midi dress under a soft-charcoal rain coat.",
                family="wrap_dress_rain_coat", palette="deep forest / soft charcoal",
                silhouette="wrap midi with clean outer layer", prop="slim clutch",
                scene="side briefing table with open documents",
            ),
            _look(
                "A muted-wine silk blouse with a pearl-gray long pleated skirt and a light trench.",
                family="silk_blouse_long_pleated_skirt", palette="muted wine / pearl gray",
                silhouette="long moving pleats", prop="umbrella",
                scene="compact briefing desk with printed cards",
            ),
            _look(
                "A muted-teal cardigan set with espresso relaxed trousers and a water-resistant outer layer.",
                family="cardigan_relaxed_trousers", palette="muted teal / espresso brown",
                silhouette="relaxed tailored layers", prop="no visible prop",
                scene="compact side table with briefing materials",
            ),
        ],
    },
    "warm": {
        "label": "Warm (19–26°C)",
        "conditions": "any, 19–26°C",
        "variants": [
            _look(
                "A muted-teal silk blouse with pearl-gray tailored wide-leg trousers.",
                family="silk_blouse_wide_leg_trousers", palette="muted teal / pearl gray",
                silhouette="fluid wide-leg tailoring", prop="no visible prop",
                scene="window-side briefing station",
            ),
            _look(
                "A dusty-rose wrap midi dress with restrained drape and a refined waist line.",
                family="wrap_midi_dress", palette="dusty rose",
                silhouette="soft wrap midi", prop="slim clutch",
                scene="quiet private work corner with briefing notes",
            ),
            _look(
                "An ink-navy silk blouse with a pearl-gray A-line midi skirt.",
                family="silk_blouse_a_line_midi", palette="ink navy / pearl gray",
                silhouette="structured A-line midi", prop="smartphone",
                scene="side briefing table with open documents",
            ),
            _look(
                "A deep-forest lightweight knit dress with a long clean line and subtle movement.",
                family="lightweight_knit_dress", palette="deep forest",
                silhouette="long refined knit midi", prop="structured handbag",
                scene="compact briefing desk with printed cards",
            ),
        ],
    },
    "hot": {
        "label": "Hot (≥27°C)",
        "conditions": "any, ≥27°C",
        "variants": [
            _look(
                "A slate-blue sleeveless high-neck silk top with ink-navy wide-leg trousers, fully professional.",
                family="sleeveless_silk_wide_leg_trousers", palette="slate blue / ink navy",
                silhouette="airy wide-leg tailoring", prop="no visible prop",
                scene="window-side briefing station",
            ),
            _look(
                "A muted-teal short-sleeve wrap dress with refined drape and no party styling.",
                family="short_sleeve_wrap_dress", palette="muted teal",
                silhouette="light wrap midi", prop="slim clutch",
                scene="compact briefing desk with printed cards",
            ),
            _look(
                "A dusty-rose silk blouse with a pearl-gray long pleated skirt.",
                family="silk_blouse_long_pleated_skirt", palette="dusty rose / pearl gray",
                silhouette="light long pleats", prop="smartphone",
                scene="side briefing table with open documents",
            ),
            _look(
                "An ink-navy evening lounge midi dress with a clean neckline and restrained sheen, never party wear.",
                family="evening_lounge_midi_dress", palette="ink navy",
                silhouette="elongated lounge midi", prop="no visible prop",
                scene="quiet private work corner with briefing notes",
            ),
        ],
    },
    "snowy": {
        "label": "Snowy / Freezing (≤0°C)",
        "conditions": "snow or freezing, ≤0°C",
        "variants": [
            _look(
                "A soft-charcoal cashmere coat over a muted-wine knit midi dress.",
                family="cashmere_coat_knit_dress", palette="soft charcoal / muted wine",
                silhouette="long coat over column midi", prop="refined scarf",
                scene="private tech signal board beside a work surface",
            ),
            _look(
                "An espresso wool-cashmere coat with pearl-gray wide-leg trousers and a fine-knit layer.",
                family="cashmere_coat_wide_leg_trousers", palette="espresso brown / pearl gray",
                silhouette="long coat with fluid trousers", prop="folded scarf",
                scene="private work surface with documents",
            ),
            _look(
                "An ink-navy structured coat over a deep-forest A-line midi skirt and fine-knit top.",
                family="structured_coat_a_line_midi", palette="ink navy / deep forest",
                silhouette="long coat over A-line midi", prop="slim clutch",
                scene="compact briefing desk with printed cards",
            ),
            _look(
                "A pearl-gray tailored coat over a slate-blue knit dress, clean and warm without bulk.",
                family="tailored_coat_knit_dress", palette="pearl gray / slate blue",
                silhouette="tailored coat over knit midi", prop="no visible prop",
                scene="compact side table with briefing materials",
            ),
        ],
    },
    "unknown": {
        "label": "Limited / Unknown Weather",
        "conditions": "temperature unavailable and no decisive weather condition",
        "variants": [
            _look(
                "An ink-navy silk blouse with pearl-gray tailored wide-leg trousers.",
                family="silk_blouse_wide_leg_trousers", palette="ink navy / pearl gray",
                silhouette="fluid wide-leg tailoring", prop="no visible prop",
                scene="compact briefing desk with printed cards",
            ),
            _look(
                "A deep-forest wrap midi dress with restrained drape.",
                family="wrap_midi_dress", palette="deep forest",
                silhouette="soft wrap midi", prop="slim clutch",
                scene="quiet private work corner with briefing notes",
            ),
            _look(
                "A muted-wine knit dress with a clean column line.",
                family="knit_midi_dress", palette="muted wine",
                silhouette="refined column midi", prop="smartphone",
                scene="side briefing table with open documents",
            ),
            _look(
                "A pearl-gray refined cardigan set with espresso relaxed trousers.",
                family="cardigan_relaxed_trousers", palette="pearl gray / espresso brown",
                silhouette="soft layered tailoring", prop="structured handbag",
                scene="compact side table with briefing materials",
            ),
            _look(
                "A dusty-rose silk blouse with a slate-blue A-line midi skirt.",
                family="silk_blouse_a_line_midi", palette="dusty rose / slate blue",
                silhouette="soft A-line midi", prop="no visible prop",
                scene="window-side briefing station",
            ),
            _look(
                "A muted-teal silk blouse with a soft-charcoal long pleated skirt.",
                family="silk_blouse_long_pleated_skirt", palette="muted teal / soft charcoal",
                silhouette="long moving pleats", prop="smartphone",
                scene="private work surface with documents",
            ),
            _look(
                "An espresso evening lounge midi dress with restrained sheen, never party wear.",
                family="evening_lounge_midi_dress", palette="espresso brown",
                silhouette="elongated lounge midi", prop="slim clutch",
                scene="quiet private work corner with briefing notes",
            ),
            _look(
                "A slate-blue soft blazer with ink-navy relaxed tailored trousers, fluid rather than corporate.",
                family="soft_blazer_relaxed_trousers", palette="slate blue / ink navy",
                silhouette="soft blazer with relaxed trousers", prop="no visible prop",
                scene="compact briefing desk with printed cards",
            ),
        ],
    },
}

_DEFAULT_CLOSET_KEY = "unknown"


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
        return "clear_cool"

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
        "wardrobe_family": outfit_text.family,
        "color_palette": outfit_text.palette,
        "silhouette": outfit_text.silhouette,
        "prop": outfit_text.prop,
        "scene": outfit_text.scene,
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

    scene_text = f"Selected scene: {wardrobe_result['scene']}."
    prop_gesture_section = (
        f"{FIXED_PROP_GESTURE_GENE}\nSelected prop: {wardrobe_result['prop']}.\n{pose_text}"
    )

    prompt_parts = [
        SCENE_LOCK,
        FIXED_IDENTITY_GENE,
        ANCHOR_ANTI_COPY_INSTRUCTION,
        FIXED_ROLE_SCENE_GENE,
        scene_text,
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
            "wardrobe_family": wardrobe_result["wardrobe_family"],
            "color_palette": wardrobe_result["color_palette"],
            "silhouette": wardrobe_result["silhouette"],
            "prop": wardrobe_result["prop"],
            "scene": wardrobe_result["scene"],
        },
        "pose_variant_text": pose_text,
        "anchor_anti_copy_instruction": ANCHOR_ANTI_COPY_INSTRUCTION,
        "anchor_anti_copy_instruction_applied": True,
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
            "runtime_enabled": True,
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
    """Build prompt metadata without making an image call."""
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
        "bottom_shot_wardrobe_variant": result["weather_outfit_shell"]["outfit_variant_index"],
        "bottom_shot_wardrobe_family": result["weather_outfit_shell"]["wardrobe_family"],
        "bottom_shot_wardrobe_descriptor": result["weather_outfit_shell"]["outfit_descriptor"],
        "bottom_shot_color_palette": result["weather_outfit_shell"]["color_palette"],
        "bottom_shot_silhouette": result["weather_outfit_shell"]["silhouette"],
        "bottom_shot_prop": result["weather_outfit_shell"]["prop"],
        "bottom_shot_scene": result["weather_outfit_shell"]["scene"],
        "bottom_shot_pose_variant": result["pose_variant_text"],
        "bottom_shot_anti_copy_instruction_applied": True,
        "bottom_shot_prompt_preview": (
            f"Selected wardrobe: {result['weather_outfit_shell']['outfit_descriptor']}\n"
            f"Selected scene: {result['weather_outfit_shell']['scene']}\n"
            f"Selected prop: {result['weather_outfit_shell']['prop']}\n"
            f"{result['prompt_text']}"
        )[:1200],
        "bottom_shot_prompt_metadata": {
            "wardrobe": dict(result["weather_outfit_shell"]),
            "pose_variant": result["pose_variant_text"],
            "anti_copy_instruction_applied": True,
        },
    }
