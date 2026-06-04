"""Kee-Suri daily wardrobe seed resolver (offline — no image API, no production wiring)."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Mapping, Tuple
from zoneinfo import ZoneInfo

RESOLVER_VERSION = "r5a_mvp_1"
DEFAULT_WARDROBE_GROUP = "keysuri_daily"
DEFAULT_PALETTE_VERSION = "v1"
DEFAULT_TIMEZONE = "Asia/Seoul"

KEYSURI_IMAGE_PROGRAMS = frozenset(
    {
        "keysuri_global_tech",
        "keysuri_korea_tech",
    }
)

FORBIDDEN_PROGRAMS = frozenset(
    {
        "today_geenee",
        "tomorrow_geenee",
        "tomorrow_genie",
        "Tomorrow_Geenee",
    }
)

SIDE_EFFECTS_DISABLED: Mapping[str, bool] = {
    "scheduler_changes": False,
    "cloud_run_changes": False,
    "gcp_changes": False,
    "image_api_calls": False,
    "gemini_or_llm_calls": False,
    "production_wiring": False,
}

_KST_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class WardrobeProfile:
    wardrobe_profile_id: str
    suit_description: str
    blouse_description: str
    prompt_snippet: str
    notes: str = ""


@dataclass(frozen=True)
class WardrobeResolveDebug:
    wardrobe_group: str
    wardrobe_date_kst: str
    wardrobe_palette_version: str
    wardrobe_profile_id: str
    daily_wardrobe_seed: str
    manual_override_applied: bool
    resolver_version: str
    program_id: str
    timezone: str


@dataclass(frozen=True)
class WardrobeResolveResult:
    wardrobe_profile_id: str
    daily_wardrobe_seed: str
    wardrobe_profile: WardrobeProfile
    debug: WardrobeResolveDebug


_PROFILE_01_CHARCOAL_IVORY = WardrobeProfile(
    wardrobe_profile_id="profile_01_charcoal_ivory",
    suit_description="Charcoal fitted suit",
    blouse_description="Ivory blouse",
    prompt_snippet=(
        "Charcoal fitted suit with ivory blouse, pencil skirt, fitted premium business "
        "silhouette. Same private Korean AI tech secretary Kee-Suri identity: sleek short "
        "bob, thin metal glasses, calm intelligent gaze — not a public news anchor, not a "
        "weathercaster, not a CEO portrait, not a lounge or glamour shoot."
    ),
    notes="Default-adjacent; matches accepted Global QA direction",
)

_PROFILE_02_NAVY_CREAM = WardrobeProfile(
    wardrobe_profile_id="profile_02_navy_cream",
    suit_description="Deep navy fitted suit",
    blouse_description="Soft cream blouse",
    prompt_snippet=(
        "Deep navy fitted suit with soft cream blouse, pencil skirt, fitted premium business "
        "silhouette. Same private Korean AI tech secretary Kee-Suri identity: sleek short "
        "bob, thin metal glasses, calm intelligent gaze — not a public news anchor, not a "
        "weathercaster, not a CEO portrait, not a lounge or glamour shoot."
    ),
    notes="Distinct but still premium business",
)

_PROFILE_03_GRAPHITE_CHAMPAGNE = WardrobeProfile(
    wardrobe_profile_id="profile_03_graphite_champagne",
    suit_description="Muted graphite suit",
    blouse_description="Champagne blouse",
    prompt_snippet=(
        "Muted graphite fitted suit with champagne blouse, pencil skirt, fitted premium "
        "business silhouette. Same private Korean AI tech secretary Kee-Suri identity: "
        "sleek short bob, thin metal glasses, calm intelligent gaze — not a public news "
        "anchor, not a weathercaster, not a CEO portrait, not a lounge or glamour shoot."
    ),
    notes="Slightly warmer neutral",
)

_PROFILE_04_SLATE_SOFT_IVORY = WardrobeProfile(
    wardrobe_profile_id="profile_04_slate_soft_ivory",
    suit_description="Dark slate suit",
    blouse_description="Soft ivory blouse",
    prompt_snippet=(
        "Dark slate fitted suit with soft ivory blouse, pencil skirt, fitted premium business "
        "silhouette. Same private Korean AI tech secretary Kee-Suri identity: sleek short bob, "
        "thin metal glasses, calm intelligent gaze — not a public news anchor, not a "
        "weathercaster, not a CEO portrait, not a lounge or glamour shoot."
    ),
    notes="Cool-neutral variant",
)

WARDROBE_PALETTES: Dict[str, Tuple[WardrobeProfile, ...]] = {
    "v1": (
        _PROFILE_01_CHARCOAL_IVORY,
        _PROFILE_02_NAVY_CREAM,
        _PROFILE_03_GRAPHITE_CHAMPAGNE,
        _PROFILE_04_SLATE_SOFT_IVORY,
    ),
}

_PROFILE_INDEX_BY_ID: Dict[str, Dict[str, WardrobeProfile]] = {
    version: {profile.wardrobe_profile_id: profile for profile in profiles}
    for version, profiles in WARDROBE_PALETTES.items()
}


def _raise(code: str, message: str) -> None:
    raise ValueError(f"{code}: {message}")


def _validate_kst_date(wardrobe_date_kst: str) -> str:
    date_str = (wardrobe_date_kst or "").strip()
    if not _KST_DATE_RE.match(date_str):
        _raise("invalid_wardrobe_date_kst", f"expected YYYY-MM-DD, got {wardrobe_date_kst!r}")
    year, month, day = (int(part) for part in date_str.split("-"))
    try:
        datetime(year, month, day)
    except ValueError as exc:
        _raise("invalid_wardrobe_date_kst", f"invalid calendar date {date_str!r}: {exc}")
    return date_str


def _validate_timezone(timezone: str) -> str:
    tz = (timezone or "").strip()
    if tz != DEFAULT_TIMEZONE:
        _raise("invalid_timezone", f"MVP requires {DEFAULT_TIMEZONE!r}, got {timezone!r}")
    return tz


def _validate_wardrobe_group(wardrobe_group: str) -> str:
    group = (wardrobe_group or "").strip()
    if group != DEFAULT_WARDROBE_GROUP:
        _raise(
            "invalid_wardrobe_group",
            f"MVP requires {DEFAULT_WARDROBE_GROUP!r}, got {wardrobe_group!r}",
        )
    return group


def _validate_program_id(program_id: str) -> str:
    pid = (program_id or "").strip()
    if pid in FORBIDDEN_PROGRAMS or pid.lower() in {p.lower() for p in FORBIDDEN_PROGRAMS}:
        _raise("invalid_program_id", f"forbidden program_id {program_id!r}")
    if pid not in KEYSURI_IMAGE_PROGRAMS:
        _raise(
            "invalid_program_id",
            f"program_id must be one of {sorted(KEYSURI_IMAGE_PROGRAMS)!r}, got {program_id!r}",
        )
    return pid


def _load_palette(wardrobe_palette_version: str) -> Tuple[WardrobeProfile, ...]:
    version = (wardrobe_palette_version or "").strip()
    if version not in WARDROBE_PALETTES:
        _raise("unknown_palette_version", f"unknown wardrobe_palette_version {version!r}")
    palette = WARDROBE_PALETTES[version]
    if not palette:
        _raise("empty_wardrobe_palette", f"palette {version!r} is empty")
    return palette


def _hash_payload(wardrobe_group: str, wardrobe_date_kst: str, wardrobe_palette_version: str) -> str:
    return f"{wardrobe_group}|{wardrobe_date_kst}|{wardrobe_palette_version}"


def _select_profile_index(payload: str, palette_size: int) -> int:
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return int(digest, 16) % palette_size


def _build_daily_wardrobe_seed(
    wardrobe_group: str,
    wardrobe_date_kst: str,
    wardrobe_palette_version: str,
    wardrobe_profile_id: str,
) -> str:
    return f"{wardrobe_group}|{wardrobe_date_kst}|{wardrobe_palette_version}|{wardrobe_profile_id}"


def derive_wardrobe_date_kst_from_datetime(
    dt: datetime,
    timezone: str = DEFAULT_TIMEZONE,
) -> str:
    """Derive KST calendar date string from a timezone-aware datetime."""
    _validate_timezone(timezone)
    if dt.tzinfo is None:
        _raise("naive_datetime_not_allowed", "datetime must be timezone-aware")
    kst = dt.astimezone(ZoneInfo(DEFAULT_TIMEZONE))
    return kst.strftime("%Y-%m-%d")


def resolve_keysuri_daily_wardrobe(
    wardrobe_date_kst: str,
    program_id: str,
    *,
    wardrobe_group: str = DEFAULT_WARDROBE_GROUP,
    wardrobe_palette_version: str = DEFAULT_PALETTE_VERSION,
    manual_override_profile_id: str | None = None,
    timezone: str = DEFAULT_TIMEZONE,
) -> WardrobeResolveResult:
    """Resolve Kee-Suri daily wardrobe profile and seed for a KST calendar date."""
    date_str = _validate_kst_date(wardrobe_date_kst)
    tz = _validate_timezone(timezone)
    group = _validate_wardrobe_group(wardrobe_group)
    pid = _validate_program_id(program_id)
    palette = _load_palette(wardrobe_palette_version)

    manual_override_applied = False
    if manual_override_profile_id is not None:
        override_id = manual_override_profile_id.strip()
        profile_by_id = _PROFILE_INDEX_BY_ID[wardrobe_palette_version]
        if override_id not in profile_by_id:
            _raise(
                "invalid_override_profile_id",
                f"override profile {manual_override_profile_id!r} not in palette {wardrobe_palette_version!r}",
            )
        profile = profile_by_id[override_id]
        manual_override_applied = True
    else:
        payload = _hash_payload(group, date_str, wardrobe_palette_version)
        index = _select_profile_index(payload, len(palette))
        profile = palette[index]

    seed = _build_daily_wardrobe_seed(
        group,
        date_str,
        wardrobe_palette_version,
        profile.wardrobe_profile_id,
    )
    debug = WardrobeResolveDebug(
        wardrobe_group=group,
        wardrobe_date_kst=date_str,
        wardrobe_palette_version=wardrobe_palette_version,
        wardrobe_profile_id=profile.wardrobe_profile_id,
        daily_wardrobe_seed=seed,
        manual_override_applied=manual_override_applied,
        resolver_version=RESOLVER_VERSION,
        program_id=pid,
        timezone=tz,
    )
    return WardrobeResolveResult(
        wardrobe_profile_id=profile.wardrobe_profile_id,
        daily_wardrobe_seed=seed,
        wardrobe_profile=profile,
        debug=debug,
    )
