"""Kee-Suri top image deterministic diversity variation (offline — no image API).

Produces an identity-safe, deterministic set of visual variants (outfit, pose,
prop, background, camera, lighting, program visual context, subject cue) for the
KeeSuri Global/Korea owner-review top image.

Design rules (do NOT relax):
  * The variation NEVER changes face / short bob / thin glasses / private-briefing
    role. It only varies styling around a fixed identity.
  * No age label, no CEO / chairwoman / senior executive / anchor / model framing.
  * Catalog entries describe abstract cues only — never readable real text,
    company names, or policy names inside the image.
  * Same (program_id, run_date_kst, subject_top_headline, palette_version) ->
    identical variation. Different date / program / headline -> variation may differ.
  * No side effects: pure functions, no image API, no network, no secrets.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, Tuple

VARIATION_VERSION = "tiv1"
DEFAULT_PALETTE_VERSION = "v1"

KEYSURI_TOP_IMAGE_PROGRAMS = frozenset(
    {
        "keysuri_global_tech",
        "keysuri_korea_tech",
    }
)

SIDE_EFFECTS_DISABLED: Dict[str, bool] = {
    "image_api_calls": False,
    "gemini_or_llm_calls": False,
    "network_calls": False,
    "scheduler_changes": False,
    "secret_access": False,
}

# --- Identity-safe variant catalogs --------------------------------------------
# Each entry preserves face/hair/glasses/role and stays within "refined private
# tech secretary office styling". No age, no power-boss, no revealing styling.

OUTFIT_VARIANTS: Tuple[Tuple[str, str], ...] = (
    ("outfit_charcoal_ivory", "a charcoal fitted suit with an ivory blouse"),
    ("outfit_navy_cream", "a deep navy fitted suit with a soft cream blouse"),
    ("outfit_graphite_champagne", "a muted graphite suit with a champagne blouse"),
    ("outfit_slate_soft_ivory", "a dark slate suit with a soft ivory blouse"),
    ("outfit_taupe_knit", "a warm taupe tailored blazer over a fine ribbed knit top"),
    ("outfit_charcoal_knit", "a soft charcoal knit blazer with a high-neck ivory top"),
)

POSE_VARIANTS: Tuple[Tuple[str, str], ...] = (
    ("pose_three_quarter_standing", "standing in a calm three-quarter private briefing stance"),
    ("pose_relaxed_upright", "standing near the desk with a relaxed upright posture"),
    ("pose_seated_desk", "seated calmly at the briefing desk, turned slightly toward the viewer"),
    ("pose_side_on", "standing slightly side-on, attentively composed"),
)

PROP_VARIANTS: Tuple[Tuple[str, str], ...] = (
    ("prop_slim_tablet", "holding a slim tablet simply at waist height, fingers mostly hidden"),
    ("prop_briefing_folder", "holding a slim briefing folder against her side"),
    ("prop_signal_cards", "with a small stack of printed signal cards resting in one hand"),
    ("prop_laptop_desk", "a laptop open on the desk beside her, hands resting calmly"),
    ("prop_small_notebook", "a small notebook held lightly in one hand"),
    ("prop_phone_memo", "a phone and a memo pad on the desk, hands calmly arranged"),
    ("prop_none_hands_desk", "no handheld prop, hands calmly arranged near the desk"),
)

BACKGROUND_VARIANTS: Tuple[Tuple[str, str], ...] = (
    ("bg_windows_minimal_desk", "a premium private office with large windows and a clean minimal desk"),
    ("bg_low_shelf_objects", "a premium private office with a low shelf of abstract tech objects behind her"),
    ("bg_single_wall_monitor", "a premium private office with a single wall monitor showing abstract non-readable charts"),
    ("bg_neutral_panels_plant", "a premium private office with soft neutral wall panels and a plant near the window"),
    ("bg_corner_meeting_table", "a premium private office corner with a small meeting table"),
)

CAMERA_VARIANTS: Tuple[Tuple[str, str], ...] = (
    ("cam_waist_up_eye_level", "medium waist-up framing at eye level"),
    ("cam_three_quarter_above", "relaxed three-quarter framing slightly above eye level"),
    ("cam_upper_body_portrait", "calm upper-body portrait distance"),
    ("cam_standing_upper_body", "natural standing upper-body framing"),
)

LIGHTING_VARIANTS: Tuple[Tuple[str, str], ...] = (
    ("light_soft_even", "soft even premium interior light"),
    ("light_window_key", "gentle window-side key light with soft fill"),
    ("light_warm_ambience", "warm premium interior ambience"),
    ("light_diffused_indoor", "calm diffused indoor light"),
)

SUBJECT_CUES: Tuple[str, ...] = (
    "with a calm emphasis on the day's leading signal",
    "composed around a single standout briefing point",
    "framed to highlight one key tech signal of the day",
    "centered on the day's most notable development",
)

PROGRAM_VISUAL_CONTEXT: Dict[str, str] = {
    "keysuri_global_tech": (
        "Subtle global big-tech briefing cues: faint abstract world-map and "
        "data-center / server silhouettes, abstract semiconductor and cloud "
        "diagrams on a distant non-readable screen, cool blue-gray international "
        "tech briefing mood. No readable real company names or text in the image."
    ),
    "keysuri_korea_tech": (
        "Subtle Korean tech-ecosystem briefing cues: a domestic startup-and-policy "
        "briefing board with abstract non-readable Korean tech motifs, Seoul "
        "business-district ambience, a slightly warmer briefing mood. No readable "
        "real company or policy names or text in the image."
    ),
}

_KST_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class TopImageVariation:
    program_id: str
    run_date_kst: str
    palette_version: str
    variation_version: str
    diversity_seed_hash: str
    outfit_variant: str
    outfit_clause: str
    pose_variant: str
    pose_clause: str
    prop_variant: str
    prop_clause: str
    background_variant: str
    background_clause: str
    camera_variant: str
    camera_clause: str
    lighting_variant: str
    lighting_clause: str
    program_visual_context: str
    subject_cue: str
    prompt_variant_summary: str

    def as_metadata(self) -> Dict[str, Any]:
        """Artifact-safe metadata (no raw headline, no secrets)."""
        return {
            "top_image_program_visual_context": self.program_id,
            "top_image_wardrobe_variant": self.outfit_variant,
            "top_image_pose_variant": self.pose_variant,
            "top_image_prop_variant": self.prop_variant,
            "top_image_background_variant": self.background_variant,
            "top_image_camera_variant": self.camera_variant,
            "top_image_lighting_variant": self.lighting_variant,
            "top_image_subject_cue": self.subject_cue,
            "top_image_diversity_seed_hash": self.diversity_seed_hash,
            "top_image_prompt_variant_summary": self.prompt_variant_summary,
            "top_image_variation_version": self.variation_version,
        }


def _normalize_program_id(program_id: str) -> str:
    pid = (program_id or "").strip()
    if pid not in KEYSURI_TOP_IMAGE_PROGRAMS:
        raise ValueError(
            f"program_id must be one of {sorted(KEYSURI_TOP_IMAGE_PROGRAMS)!r}, got {program_id!r}"
        )
    return pid


def _validate_kst_date(run_date_kst: str) -> str:
    date_str = (run_date_kst or "").strip()
    if not _KST_DATE_RE.match(date_str):
        raise ValueError(f"run_date_kst must be YYYY-MM-DD, got {run_date_kst!r}")
    return date_str


def _normalize_headline(subject_top_headline: str) -> str:
    text = " ".join(str(subject_top_headline or "").split())
    return text.casefold()


def build_top_image_diversity_seed(
    program_id: str,
    run_date_kst: str,
    subject_top_headline: str,
    palette_version: str = DEFAULT_PALETTE_VERSION,
) -> str:
    """Build the deterministic seed string (program + date + headline + palette)."""
    pid = _normalize_program_id(program_id)
    date_str = _validate_kst_date(run_date_kst)
    headline = _normalize_headline(subject_top_headline)
    palette = (palette_version or DEFAULT_PALETTE_VERSION).strip() or DEFAULT_PALETTE_VERSION
    return f"{pid}|{date_str}|{headline}|{palette}|{VARIATION_VERSION}"


def diversity_seed_hash(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _pick(catalog: Tuple[Tuple[str, str], ...], seed: str, axis: str) -> Tuple[str, str]:
    digest = hashlib.sha256(f"{seed}::{axis}".encode("utf-8")).hexdigest()
    return catalog[int(digest, 16) % len(catalog)]


def _pick_str(catalog: Tuple[str, ...], seed: str, axis: str) -> str:
    digest = hashlib.sha256(f"{seed}::{axis}".encode("utf-8")).hexdigest()
    return catalog[int(digest, 16) % len(catalog)]


def resolve_keysuri_top_image_variation(
    program_id: str,
    run_date_kst: str,
    subject_top_headline: str = "",
    palette_version: str = DEFAULT_PALETTE_VERSION,
) -> TopImageVariation:
    """Resolve the deterministic, identity-safe top image variation."""
    pid = _normalize_program_id(program_id)
    date_str = _validate_kst_date(run_date_kst)
    palette = (palette_version or DEFAULT_PALETTE_VERSION).strip() or DEFAULT_PALETTE_VERSION
    seed = build_top_image_diversity_seed(pid, date_str, subject_top_headline, palette)
    seed_hash = diversity_seed_hash(seed)

    outfit_id, outfit_clause = _pick(OUTFIT_VARIANTS, seed, "outfit")
    pose_id, pose_clause = _pick(POSE_VARIANTS, seed, "pose")
    prop_id, prop_clause = _pick(PROP_VARIANTS, seed, "prop")
    bg_id, bg_clause = _pick(BACKGROUND_VARIANTS, seed, "background")
    cam_id, cam_clause = _pick(CAMERA_VARIANTS, seed, "camera")
    light_id, light_clause = _pick(LIGHTING_VARIANTS, seed, "lighting")
    subject_cue = _pick_str(SUBJECT_CUES, seed, "subject_cue")

    summary = (
        f"outfit={outfit_id}; pose={pose_id}; prop={prop_id}; "
        f"background={bg_id}; camera={cam_id}; lighting={light_id}"
    )

    return TopImageVariation(
        program_id=pid,
        run_date_kst=date_str,
        palette_version=palette,
        variation_version=VARIATION_VERSION,
        diversity_seed_hash=seed_hash,
        outfit_variant=outfit_id,
        outfit_clause=outfit_clause,
        pose_variant=pose_id,
        pose_clause=pose_clause,
        prop_variant=prop_id,
        prop_clause=prop_clause,
        background_variant=bg_id,
        background_clause=bg_clause,
        camera_variant=cam_id,
        camera_clause=cam_clause,
        lighting_variant=light_id,
        lighting_clause=light_clause,
        program_visual_context=PROGRAM_VISUAL_CONTEXT[pid],
        subject_cue=subject_cue,
        prompt_variant_summary=summary,
    )
