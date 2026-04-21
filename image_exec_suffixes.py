"""Server-side suffixes appended to Vertex image prompts for today_genie TPO execution paths."""
from __future__ import annotations

import hashlib
import json
from textwrap import dedent
from typing import Any, Dict


def today_genie_suffix_studio_hero() -> str:
    """Vertex appendix for today_genie top hero after mood prefix + model image_prompt_studio."""
    return dedent(
        """
        [VERTEX_RENDER_LOCK — today_genie top hero, morning market-opening briefing]

        Subject / identity
        A premium Korean female presenter in her late 20s, same person identity as the reference image,
        same face identity, same hair identity, long dark-brown softly waved hair, clear skin,
        refined broadcast-ready makeup, elegant and camera-friendly.

        Shot type
        today_genie top hero image for a morning market-opening briefing. The image may be either:
        - a polished studio-anchor hero shot, or
        - a city-morning hero shot with urban commuting energy.
        Choose based on the briefing mood already stated above; wardrobe and styling follow that mood (not hard-fixed in advance).

        Visual direction
        High click appeal; premium commercial realism; editorial quality; morning greeting energy;
        visually magnetic but still trustworthy; warm, lively, human presence; not stiff, not overposed.

        Framing and body (premium anchor silhouette — top hero)
        Either a strong 3/4 shot or a full-body hero shot. When full-body or strong 3/4 is used, keep a **balanced ~7.5–8 head** proportion with **healthy feminine curves** and **soft glamour** (broadcast-credible, not runway-emaciated).
        Positive: softly glamorous presence; confident anchor posture; natural waist definition; smooth shoulder line; realistic healthy body volume; elegant weight shift; one leg subtly leading when stance allows.
        Avoid: overly thin or stretched runway legs; exaggerated wasp-waist; collapsed foreshortening; compact squat balance; flat symmetrical mannequin stance; any look that reads as generic-AI thinness.

        Expression (vary naturally across runs; alive and human, not one repeated smile template)
        Natural morning greeting warmth; soft eye engagement; subtle cheek lift; relaxed human smile;
        bright but unforced vitality; friendly confidence without a posed presenter grin.

        Wardrobe and tone (premium presenter — rotate families; do not repeat one template)
        Wardrobe follows the briefing mood but must vary the tailoring family across runs—do not default every time to the same gray blazer with pale blue innerwear.
        Credible rotation pool (pick one coherent direction per image; mix is ok only if still editorial-clean):
        light gray tailored suit; warm beige tailored suit; cream or ivory tailored set; soft blue professional suit or separates;
        dusty rose or muted mauve blouse with coordinated jacket; elegant pencil skirt set with refined jacket or knit;
        refined slim dress with structured blazer; polished city-morning business fashion with premium fabric read.
        Same person identity stays stable; vary wardrobe family, lapel line, color story, and inner layer while preserving broadcast-ready credibility.

        Identity and controlled diversity
        Same person continuity must remain stable; no random person drift; no unrelated scene roulette.
        Diversity only in controlled ways: scene, tailoring color family, styling, camera distance, light mood, body angle, gesture nuance.

        Visual quality
        Ultra realistic, editorial lifestyle photography, premium commercial image, cinematic natural light or polished studio light,
        high detail, elegant composition, realistic fabric and skin texture, no text, no logo, no watermark, no split screen,
        no collage, no UI overlay.
        """
    ).strip()


def _pick_from_seed(seed: str, key: str, options: tuple[str, ...]) -> str:
    h = int(hashlib.sha256(f"{seed}|{key}".encode("utf-8")).hexdigest(), 16)
    return options[h % len(options)]


def _bottom_image_variation_directive(seed: str) -> str:
    """Deterministic per-run axis mix: same identity, different pose / frame / outfit family / camera."""
    if not (seed or "").strip():
        return ""
    camera = _pick_from_seed(
        seed,
        "cam",
        (
            "eye-level, medium-wide environmental (subject not dead-center; use background depth).",
            "slightly low angle, 3/4 as if mid-stride on a crosswalk; show forward motion.",
            "slightly high / clean fashion look; more headroom; subject glances off-camera.",
            "closer medium shot, waist-up to mid-thigh; hands/ prop in frame; less wide background.",
        ),
    )
    pose = _pick_from_seed(
        seed,
        "pose",
        (
            "weight on one leg, shoulder line turned 20–30°; natural contrapposto, not square to camera.",
            "brief pause: one hand adjusting coat lapel, scarf, or bag strap; the other relaxed.",
            "light walk with a compact umbrella or folded layer in hand (only if weather-appropriate; no brand logo).",
            "seated or leaning at a simple outdoor bench / ledge; still daily-believable, not a studio pose.",
        ),
    )
    wardrobe = _pick_from_seed(
        seed,
        "outfit",
        (
            "soft camel or sand long coat over a warm neutral knit; clean daily premium read.",
            "ivory or cream tailored short coat with a slightly different inner color than the last default ‘gray+blue’ mix.",
            "light structured blazer + wide tailored trouser; different lapel and color story from a classic newsroom template.",
            "belted midi dress with a light weather-appropriate layer; vary texture (matte knit vs. soft wool).",
        ),
    )
    face = _pick_from_seed(
        seed,
        "face",
        (
            "subtle closed-mouth ease; eyes toward light, not a big smile template.",
            "soft half-smile; more relaxed brows; less ‘headline’ energy than a news open still.",
            "attentive neutral-pleasant; as if listening to the city, not performing to camera.",
        ),
    )
    return dedent(
        f"""
        CONTROLLED_DIVERSITY_LOCK (this render; keep one continuous person; obey weather block above)
        - Camera & distance: {camera}
        - Posture & hands: {pose}
        - Wardrobe family (rotate; must still match weather; no logos): {wardrobe}
        - Expression: {face}
        Intentionally differ from a repeated default: do not output the same head angle, same straight-on stance, and same gray-blazer template every time.
        """
    ).strip()


def today_genie_suffix_outdoor_daily(ri: Dict[str, Any], variation_seed: str = "") -> str:
    """Vertex appendix for today_genie bottom / outdoor daily slot after mood prefix + model prompt.

    variation_seed: per-run id (e.g. local TPO stamp) so framing / pose / outfit instructions rotate deterministically
    without breaking identity or weather-reactive rules.
    """
    td = (ri.get("target_date") or "").strip()
    date_line = f"Context date (Seoul KST calendar): {td}." if td else "Context: Seoul weekday morning."
    iw = ri.get("image_weather_context")
    weather_lock = ""
    if isinstance(iw, dict) and iw:
        weather_lock = (
            "\n\n        WEATHER_FOR_BOTTOM_IMAGE_ONLY (wardrobe and scene; obey avoid_items; do not contradict band):\n        "
            + json.dumps(iw, ensure_ascii=False, separators=(",", ":"))
        )
    seed = (variation_seed or "").strip() or td or "default"
    variation_block = _bottom_image_variation_directive(seed)
    variation_section = ""
    if variation_block:
        variation_section = "\n\n        " + variation_block.replace("\n", "\n        ")
    return dedent(
        f"""
        [VERTEX_RENDER_LOCK — today_genie bottom, daily-life morning]

        Subject / identity
        A premium Korean woman in her late 20s, same person identity as the reference image,
        same face identity, same hair identity, long dark-brown softly waved hair, clear skin,
        refined natural makeup, feminine and attractive but realistic.

        Shot type
        today_genie bottom image for a daily-life morning scene connected to the day’s weather and lived-in urban routine.
        {date_line}
        If runtime lacks explicit forecast numbers, do not invent numeric weather—use qualitative seasonal / morning impression only.
        {weather_lock}
        {variation_section}

        Visual direction
        Practical but attractive daily-life scene; weather-reactive lifestyle image;
        feminine appeal without random glamour drift; natural daily movement and real-world presence;
        visually appealing enough to support strong engagement; not stiff, not catalogue-like, not mannequin-like.

        Scene and styling
        The scene should respond to the day’s weather and practical context.
        Outfit can vary naturally across dress, light athleisure, casual lifestyle styling, smart daily outerwear,
        or other believable everyday combinations. No single fixed outfit logic; avoid a repetitive same-scene template.
        Urban morning realism with controlled diversity.

        Expression (vary naturally across runs; lived-in, not catalogue-staged)
        Relaxed daily-life expression; gentle lived-in warmth; soft calm attractiveness;
        light natural smile or quietly pleasant ease; feminine but unperformed presence;
        subtle motion, breath, gaze shift, or weight shift so the moment feels human.
        Expression should feel naturally lived, not staged for a catalogue.

        Framing and body (premium daily silhouette — bottom / daily-life)
        May be full-body, 3/4, or lifestyle medium-wide framing depending on the scene; when full-body or strong 3/4, keep **balanced ~7.5–8 head** proportion with **healthy curves** and **soft glamour** (realistic daily premium, not catalogue-thin).
        Positive: softly glamorous, lived-in attractiveness; natural waist and hip volume; smooth posture; believable stride; relaxed vertical presence; one leg subtly leading.
        Avoid: overly thin legs; stretched runway proportions; catalogue stiffness that flattens the figure; generic-AI waif silhouette; loss of identity continuity versus the reference face.

        Identity and controlled diversity
        Same person continuity must remain stable; no random person drift; no unrelated scene roulette.
        Diversity stays controlled through weather, styling, location tone, posture, and micro-expression.

        Visual quality
        Ultra realistic, editorial lifestyle photography, premium commercial image, natural city light, high detail,
        attractive urban setting, realistic texture, no text, no logo, no watermark, no split screen, no collage, no UI overlay.
        """
    ).strip()
