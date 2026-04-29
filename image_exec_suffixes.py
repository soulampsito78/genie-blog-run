"""Server-side suffixes appended to Vertex image prompts for today_genie TPO execution paths."""
from __future__ import annotations

import hashlib
import json
from textwrap import dedent
from typing import Any, Dict


def _pick_from_seed(seed: str, key: str, options: tuple[str, ...]) -> str:
    h = int(hashlib.sha256(f"{seed}|{key}".encode("utf-8")).hexdigest(), 16)
    return options[h % len(options)]


# --- Deterministic variation pools (same seed coordinates top + bottom) ---

_TOP_WARDROBE_FAMILIES = (
    "navy tailored suit with ivory blouse",
    "cream wide-leg trouser suit",
    "soft blue shirt with charcoal slacks",
    "muted rose blouse with beige jacket",
    "black knit dress with cropped jacket",
    "white blouse with pencil skirt and structured blazer",
    "camel city jacket with tailored trousers",
    "sleeveless knit plus light jacket draped over shoulder",
)

_BOTTOM_WARDROBE_FAMILIES = (
    "trench or short coat with jeans",
    "knit top with long skirt",
    "cardigan over blouse with trousers",
    "shirt dress with light jacket",
    "casual blazer with denim (different color/fabric from any top suit; relaxed city posture)",
    "pleated skirt with simple knit",
    "city athleisure layer with tote bag",
    "blouse with rolled sleeves holding folder",
)

_TOP_POSE_ACTIONS = (
    "active briefing gesture: one hand slightly raised as if explaining a level, the other holding slim tablet or briefing cards",
    "standing near a market wall or desk; torso angled 20–35°; engaged briefing posture with visible hand asymmetry",
    "mid-gesture explaining move: fingers loosely open, energy in shoulders, not frozen smile template",
    "confident anchor stance allowed but with clear weight shift and asymmetric arms (no mirrored mannequin)",
    "three-quarter toward a briefing screen; glance can include lens connection without stiff head-on catalog symmetry",
)

_TOP_SCENES = (
    "premium newsroom or broadcast studio with soft professional light",
    "market wall / LED ribbon environment with shallow depth; finance briefing context",
    "morning briefing desk with papers and warm key light; still editorial, not cluttered",
    "polished studio hero set with negative space; premium finance morning show feel",
)

_TOP_CAMERA = (
    "medium 3/4 hero; subject fills ~55–70% frame height; controlled editorial proportion",
    "medium shot from slight diagonal; headroom for breathing composition; not dead-center symmetry",
    "controlled full-body hero with foreground desk edge or studio depth cue; still premium briefing read",
)

_BOTTOM_POSE_ACTIONS = (
    "walking with tote or folder; stride visible; gaze sideways along sidewalk",
    "checking phone near window; shoulders relaxed; body turned off-axis from lens",
    "seated at cafe table with laptop bag visible; hands occupied; environmental storytelling",
    "stepping out of building; one foot lower; adjusting coat or cardigan in motion",
    "holding coffee and documents; mid-stride lobby transition; asymmetrical balance",
    "leaning on railing with city background; torso twist; no frontal anchor pose",
    "crossing lobby while looking toward side light; medium-wide environmental read",
    "adjusting outer layer at crosswalk pause; clear daily-life motion blur acceptable in background only",
)

_BOTTOM_SCENES = (
    "Seoul weekday morning street with readable urban depth (no legible signage)",
    "office district building entrance or canopy zone",
    "elevator lobby with stone or glass depth; natural morning commuter light",
    "cafe window seat seen from outside; lifestyle transition not studio",
    "crosswalk approach with mild perspective; subject not centered template",
    "subway-adjacent street with restrained crowd bokeh",
    "riverside walk path before work; open air; different geometry from top set",
    "sidewalk beside tree line or planter ledge; medium-wide environmental frame",
)

_BOTTOM_CAMERA = (
    "medium-wide environmental frame; subject occupies visibly less of frame than a top hero would",
    "full-body lifestyle frame with foreground depth; camera angle differs from top (lower or higher than top pick)",
    "3/4 environmental with strong background scale; subject offset left or right third",
)


def today_genie_image_variation_bundle(variation_seed: str) -> Dict[str, str]:
    """
    Deterministic per-run axis choices for logging and for suffix text.
    Top and bottom use disjoint wardrobe pools; bottom pose/scene/camera pools
    enforce non-studio, non-mannequin daily motion.
    """
    s = (variation_seed or "").strip() or "default"
    top_w = _pick_from_seed(s, "top_w", _TOP_WARDROBE_FAMILIES)
    # Bottom wardrobe pick depends on top so the pair never shares an accidental twin template.
    bot_w = _pick_from_seed(f"{s}|{top_w}", "bot_w", _BOTTOM_WARDROBE_FAMILIES)
    return {
        "variation_seed": s,
        "top_wardrobe_family": top_w,
        "bottom_wardrobe_family": bot_w,
        "top_pose_action": _pick_from_seed(s, "top_p", _TOP_POSE_ACTIONS),
        "bottom_pose_action": _pick_from_seed(s, "bot_p", _BOTTOM_POSE_ACTIONS),
        "top_scene": _pick_from_seed(s, "top_s", _TOP_SCENES),
        "bottom_scene": _pick_from_seed(s, "bot_s", _BOTTOM_SCENES),
        "top_camera_framing": _pick_from_seed(s, "top_c", _TOP_CAMERA),
        "bottom_camera_framing": _pick_from_seed(s, "bot_c", _BOTTOM_CAMERA),
    }


def today_genie_suffix_studio_hero(variation_seed: str = "") -> str:
    """Vertex appendix for today_genie top hero after mood prefix + model image_prompt_studio."""
    b = today_genie_image_variation_bundle(variation_seed)
    run_pick = (
        "\n        THIS_RUN_SELECTED_CONTRACT (must obey; log-aligned):\n"
        f"        - top_wardrobe_family: {b['top_wardrobe_family']}\n"
        f"        - top_pose_action: {b['top_pose_action']}\n"
        f"        - top_scene: {b['top_scene']}\n"
        f"        - top_camera_framing: {b['top_camera_framing']}\n"
    )
    return dedent(
        f"""
        [VERTEX_RENDER_LOCK — today_genie top hero, morning market-opening briefing]

        Identity lock (ONLY these stay stable — not a mannequin repeat)
        Same premium Korean woman in her late 20s: same recognizable face **family**, same hair **identity**
        (long dark-brown soft waves), same age impression, same trustworthy premium Genie brand feel.
        Identity consistency must never mean mannequin repetition, catalogue swap, or one frozen template.

        Explicitly NOT fixed across runs (must vary this render vs prior inbox heroes)
        Not the same outfit formula, not the same blazer color story, not the same inner blouse,
        not the same hand position, not the same camera distance, not the same background geometry,
        not the same lighting recipe, not the same body angle, not the same expression template.
        The woman must read as the **same person living a different moment**, not the same doll redressed in one pose.

        {run_pick.strip()}

        Shot type
        today_genie top hero image for a morning market-opening briefing. The image may be either:
        - a polished studio-anchor hero shot, or
        - a city-morning hero shot with urban commuting energy.
        Render using THIS_RUN_SELECTED top_scene and top_camera_framing; wardrobe must match top_wardrobe_family visibly.

        Visual direction
        High click appeal; premium commercial realism; editorial quality; morning greeting energy;
        visually magnetic but still trustworthy; warm, lively, human presence; not stiff, not overposed.

        Proportion lock (hard)
        For full-body or strong 3/4 body framing, enforce 8.5 to 9-head-tall editorial fashion proportion.
        Mandatory body read: long leg line, high-waist visual balance, long lower-body silhouette,
        slim but healthy athletic build, elegant vertical posture, clean shoulder line, defined waist through tailoring or silhouette,
        graceful neck line, confident premium stance.
        This is a hard no-compact rule: do not render short, squat, torso-heavy, or mannequin-like proportion.

        Feminine appeal lock (premium / trustworthy, non-sexualized)
        Feminine but premium, refined, realistic, and trustworthy.
        Attractive without over-sexualization; appeal must come from confidence, styling, silhouette,
        gesture, expression, and editorial composition.
        Soft but alert eyes, composed warmth, subtle vitality, and clearly human micro-expression.
        No stiff mannequin face or frozen catalogue smile.

        Wardrobe variation contract (top — pick exactly the family above; make it unmistakably different from prior gray+pale defaults)
        Credible rotation pool (this run is locked to ONE line from THIS_RUN_SELECTED top_wardrobe_family; do not substitute a generic gray blazer):
        {_TOP_WARDROBE_FAMILIES[0]}; {_TOP_WARDROBE_FAMILIES[1]}; {_TOP_WARDROBE_FAMILIES[2]}; {_TOP_WARDROBE_FAMILIES[3]};
        {_TOP_WARDROBE_FAMILIES[4]}; {_TOP_WARDROBE_FAMILIES[5]}; {_TOP_WARDROBE_FAMILIES[6]}; {_TOP_WARDROBE_FAMILIES[7]}.

        Pose / body-action contract (top — execute top_pose_action literally)
        Mandatory briefing-body energy: use the selected top_pose_action; props allowed: tablet, slim folder, briefing cards.
        Eye contact is allowed but must not collapse into a stiff catalogue stare — keep micro-asymmetry in brows and mouth.

        Camera / framing contract (top)
        Polished studio or market-briefing feel using top_camera_framing; medium / 3/4 / controlled full-body hero only.
        Bottom image must later use a **different** crop language, head angle, and background scale — plan top so bottom can diverge clearly.

        Hard negatives (top)
        No repeated gray blazer + pale innerwear default as the dominant read.
        No catalogue mannequin outfit swap (same silhouette, new hex code).
        No identical silhouette to a typical prior top_genie inbox frame.
        No short-legged read. No squat body. No compact torso-heavy figure. No boxy silhouette.
        No stiff catalogue mannequin pose. No flat symmetrical standing pose. No childlike proportions.
        No cropped news-thumb body that shrinks figure presence.
        No cheap glamour, no lingerie, no excessive cleavage, no nightclub styling, no over-sexualized pose.

        Identity and controlled diversity
        Same person continuity must remain stable; no random person drift; no unrelated scene roulette.
        Diversity is mandatory in wardrobe, pose, lighting, and set geometry while preserving face/hair/brand feel.

        Visual quality
        Ultra realistic, editorial lifestyle photography, premium commercial image, cinematic natural light or polished studio light,
        high detail, elegant composition, realistic fabric and skin texture, no text, no logo, no watermark, no split screen,
        no collage, no UI overlay.
        """
    ).strip()


def today_genie_suffix_outdoor_daily(ri: Dict[str, Any], variation_seed: str = "") -> str:
    """Vertex appendix for today_genie bottom / outdoor daily slot after mood prefix + model prompt."""
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
    b = today_genie_image_variation_bundle(seed)
    run_pick = (
        "\n        THIS_RUN_SELECTED_CONTRACT (must obey; log-aligned):\n"
        f"        - bottom_wardrobe_family: {b['bottom_wardrobe_family']}\n"
        f"        - bottom_pose_action: {b['bottom_pose_action']}\n"
        f"        - bottom_scene: {b['bottom_scene']}\n"
        f"        - bottom_camera_framing: {b['bottom_camera_framing']}\n"
        f"        - paired_top_wardrobe_family (for contrast only): {b['top_wardrobe_family']}\n"
    )
    return dedent(
        f"""
        [VERTEX_RENDER_LOCK — today_genie bottom, daily-life morning]

        Identity lock (ONLY these stay stable — not a second studio mannequin)
        Same premium Korean woman in her late 20s: same recognizable face **family**, same hair **identity**
        (long dark-brown soft waves), same age impression, same premium trustworthy brand feel.
        She must feel like **the same person in a different life moment**, not the same doll pasted outdoors.

        Explicitly NOT fixed
        Not the same outfit as top, not the same blazer silhouette or color story as top, not the same inner layer,
        not the same pose family as top, not the same camera distance as top, not the same head angle,
        not the same centered composition, not studio lighting recipe.

        {run_pick.strip()}

        Shot type
        today_genie bottom image for a daily-life morning scene connected to the day’s weather and lived-in urban routine.
        {date_line}
        If runtime lacks explicit forecast numbers, do not invent numeric weather—use qualitative seasonal / morning impression only.
        {weather_lock}

        Scene contract (bottom — must be clearly NOT the top studio)
        Render bottom_scene from THIS_RUN_SELECTED; must read as outdoor or transitional civic space — never a second anchor studio portrait.
        Bottom is a **closing lifestyle transition** image, not another briefing anchor.

        Wardrobe variation contract (bottom)
        Must use bottom_wardrobe_family exactly; must NOT reuse top_wardrobe_family or read as “studio blazer outdoors.”
        If a blazer appears, it must be **casual city styling** with different color, fabric drape, and posture from any top tailoring.
        Allowed pool for reference (this run locked to one): {", ".join(_BOTTOM_WARDROBE_FAMILIES)}.

        Pose / body-action contract (bottom — execute bottom_pose_action literally)
        Bottom must **not** be a frontal anchor pose; must **not** be a static mannequin stance.
        Show daily-life motion or environmental action with clear asymmetry and context.

        Camera / framing contract (bottom)
        Apply bottom_camera_framing; subject should occupy **less** of the frame than top when possible; visible environment must matter.
        Top and bottom must **not** share the same crop recipe, same head angle, same background scale, or same dead-center composition.

        Hard negatives (bottom)
        No repeated gray blazer + pale innerwear default.
        No same outfit family as top; no catalogue mannequin outfit swap; no identical silhouette to top.

        Visual direction
        Practical but attractive daily-life scene; weather-reactive lifestyle image;
        feminine appeal without random glamour drift; natural daily movement and real-world presence;
        visually appealing enough to support strong engagement; not stiff, not catalogue-like, not mannequin-like.

        Expression (vary naturally across runs; lived-in, not catalogue-staged)
        Relaxed daily-life expression; gentle lived-in warmth; soft calm attractiveness;
        light natural smile or quietly pleasant ease; feminine but unperformed presence;
        subtle motion, breath, gaze shift, or weight shift so the moment feels human.

        Proportion lock (hard — bottom daily image)
        For full-body or strong 3/4 body framing, enforce 8.5 to 9-head-tall editorial fashion proportion.
        Mandatory body read: long leg line, high-waist visual balance, long lower-body silhouette,
        slim but healthy athletic build, elegant vertical posture, clean shoulder line, defined waist through tailoring or silhouette,
        graceful neck line, and movement-led stance.
        Keep a long silhouette even in casual clothing; avoid compact/squat/mannequin body balance.

        Feminine appeal lock (premium daily-life)
        Daily-life but visibly elegant and feminine in a premium, realistic, trustworthy way.
        Attractive without sexualization; appeal comes from confident movement, styling, silhouette,
        gesture, expression, and editorial environment composition.
        Soft but alert eyes, composed warmth, subtle vitality, and non-stiff human expression.
        Not another blazer mannequin.

        Hard negatives (bottom)
        No short-legged read. No squat body. No compact torso-heavy figure. No boxy silhouette.
        No stiff catalogue mannequin pose. No flat symmetrical standing pose. No childlike proportions.
        No cheap glamour, no lingerie, no excessive cleavage, no nightclub styling, no over-sexualized pose.

        Identity and controlled diversity
        Same person continuity must remain stable; no random person drift; no unrelated scene roulette.
        Diversity stays controlled through weather, styling, location tone, posture, and micro-expression.

        Visual quality
        Ultra realistic, editorial lifestyle photography, premium commercial image, natural city light, high detail,
        attractive urban setting, realistic texture, no text, no logo, no watermark, no split screen, no collage, no UI overlay.
        """
    ).strip()


def today_genie_image_prompt_log(
    *,
    variation_seed: str,
    runtime_input: Dict[str, Any],
    mood_prefix: str,
    image_prompt_studio: str,
    image_prompt_outdoor: str,
    reference_image_path: str,
    top_output_path: str = "",
    bottom_output_path: str = "",
) -> Dict[str, Any]:
    """Structured fields for JSON manifests / TPO snapshots (no Vertex calls)."""
    bundle = today_genie_image_variation_bundle(variation_seed)
    sfx_top = today_genie_suffix_studio_hero(variation_seed)
    sfx_bot = today_genie_suffix_outdoor_daily(runtime_input, variation_seed)
    top_final = f"{mood_prefix}{image_prompt_studio}\n\n{sfx_top}".strip()
    bot_final = f"{mood_prefix}{image_prompt_outdoor}\n\n{sfx_bot}".strip()
    return {
        **bundle,
        "top_final_composed_prompt": top_final,
        "bottom_final_composed_prompt": bot_final,
        "reference_image_path": reference_image_path,
        "top_output_path": top_output_path,
        "bottom_output_path": bottom_output_path,
        "top_prompt_hash": hashlib.sha256(top_final.encode("utf-8")).hexdigest(),
        "bottom_prompt_hash": hashlib.sha256(bot_final.encode("utf-8")).hexdigest(),
    }
