"""Program registry foundation for separated GENIE lifecycle programs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


class UnknownProgramError(LookupError):
    """Raised when a program_id or alias cannot be resolved."""


@dataclass(frozen=True)
class ProgramSpec:
    program_id: str
    schedule_kst: str
    persona_id: str
    display_name_ko: str
    role: str
    content_domain: str
    runtime_builder: str
    prompt_profile: str
    validator: str
    source_gate_profile: str
    visual_profile: str
    output_contract: str
    channels: Tuple[str, ...]
    inline_html_body_enabled: bool
    paste_body_enabled: bool
    html_attachment_enabled: bool
    image_attachment_enabled: bool
    naver_assets_enabled: bool
    in_app_enabled: bool
    auto_send_after_timeout_enabled: bool
    customer_send_requires_approval: bool
    source_gate_enabled: bool = False
    legacy_mode: str | None = None


PROGRAMS: Dict[str, ProgramSpec] = {
    "today_geenee": ProgramSpec(
        program_id="today_geenee",
        legacy_mode="today_genie",
        schedule_kst="06:30",
        persona_id="genie_today",
        display_name_ko="오늘의 지니",
        role="warm_morning_anchor",
        content_domain="market_finance_morning",
        runtime_builder="today_geenee_runtime",
        prompt_profile="today_geenee_v1",
        validator="today_geenee_v1",
        source_gate_profile="genie_finance_feed_gate",
        visual_profile="genie_today_v1",
        output_contract="genie_html_email_body_v1",
        channels=("email",),
        inline_html_body_enabled=True,
        paste_body_enabled=False,
        html_attachment_enabled=False,
        image_attachment_enabled=False,
        naver_assets_enabled=False,
        in_app_enabled=False,
        auto_send_after_timeout_enabled=False,
        customer_send_requires_approval=True,
    ),
    "keysuri_global_tech": ProgramSpec(
        program_id="keysuri_global_tech",
        schedule_kst="12:30",
        persona_id="keysuri",
        display_name_ko="키수리",
        role="glamorous_premium_ai_tech_secretary",
        content_domain="global_ai_bigtech_semi_platforms_policy",
        runtime_builder="keysuri_global_runtime",
        prompt_profile="keysuri_global_tech_v1",
        validator="keysuri_global_v1",
        source_gate_profile="keysuri_source_gate_v1",
        visual_profile="keysuri_v1",
        output_contract="keysuri_private_briefing_v1",
        channels=("email", "in_app"),
        inline_html_body_enabled=False,
        paste_body_enabled=False,
        html_attachment_enabled=False,
        image_attachment_enabled=False,
        naver_assets_enabled=False,
        in_app_enabled=True,
        source_gate_enabled=True,
        auto_send_after_timeout_enabled=False,
        customer_send_requires_approval=True,
    ),
    "keysuri_korea_tech": ProgramSpec(
        program_id="keysuri_korea_tech",
        schedule_kst="18:30",
        persona_id="keysuri",
        display_name_ko="키수리",
        role="glamorous_premium_ai_tech_secretary",
        content_domain="korea_ai_startups_platforms_policy_support",
        runtime_builder="keysuri_korea_runtime",
        prompt_profile="keysuri_korea_tech_v1",
        validator="keysuri_korea_v1",
        source_gate_profile="keysuri_source_gate_v1",
        visual_profile="keysuri_v1",
        output_contract="keysuri_private_briefing_v1",
        channels=("email", "in_app"),
        inline_html_body_enabled=False,
        paste_body_enabled=False,
        html_attachment_enabled=False,
        image_attachment_enabled=False,
        naver_assets_enabled=False,
        in_app_enabled=True,
        source_gate_enabled=True,
        auto_send_after_timeout_enabled=False,
        customer_send_requires_approval=True,
    ),
}

LEGACY_MODE_ALIASES: Dict[str, str] = {
    spec.legacy_mode: spec.program_id
    for spec in PROGRAMS.values()
    if spec.legacy_mode
}


def get_program(program_id: str) -> ProgramSpec:
    """Return the program spec for a canonical program_id."""
    key = (program_id or "").strip()
    if not key:
        raise UnknownProgramError("program_id must not be empty")
    spec = PROGRAMS.get(key)
    if spec is None:
        known = ", ".join(sorted(PROGRAMS))
        raise UnknownProgramError(f"Unknown program_id: {program_id!r}. Known programs: {known}")
    return spec


def resolve_program_id(value: str) -> str:
    """Resolve a canonical program_id or legacy mode alias to program_id."""
    key = (value or "").strip()
    if not key:
        raise UnknownProgramError("program reference must not be empty")
    if key in PROGRAMS:
        return key
    if key in LEGACY_MODE_ALIASES:
        return LEGACY_MODE_ALIASES[key]
    known = ", ".join(sorted(list(PROGRAMS) + list(LEGACY_MODE_ALIASES)))
    raise UnknownProgramError(f"Unknown program reference: {value!r}. Known: {known}")


def list_programs() -> List[ProgramSpec]:
    """Return all registered programs sorted by schedule_kst then program_id."""
    return sorted(PROGRAMS.values(), key=lambda spec: (spec.schedule_kst, spec.program_id))
