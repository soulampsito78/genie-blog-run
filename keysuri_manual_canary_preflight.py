"""Kee-Suri manual opt-in wardrobe canary preflight (offline — no image API)."""
from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from keysuri_daily_wardrobe_resolver import (
    FORBIDDEN_PROGRAMS,
    KEYSURI_IMAGE_PROGRAMS,
    resolve_keysuri_daily_wardrobe,
)
from keysuri_weather_binding_integration import build_keysuri_weather_binding_integration_report
from keysuri_r5d_manual_canary import (
    R5D_APPROVED_MANUAL_OVERRIDE_PASS,
    R5D_CANARY_PROFILES,
    VISUAL_QA_STATUS as R5D_VISUAL_QA_STATUS,
    build_r5d_opt_in_prompt_source,
    check_r5d_default_prompt_unchanged,
    is_r5d_v2_profile_id,
    resolve_r5d_canary_target,
    validate_r5d_positive_prompt,
)
from keysuri_r5e_manual_canary import (
    R5E_APPROVED_STRUCTURE_VARIATION_PASS,
    R5E_CANARY_PROFILES,
    VISUAL_QA_STATUS as R5E_VISUAL_QA_STATUS,
    build_r5e_opt_in_prompt_source,
    check_r5e_default_prompt_unchanged,
    is_r5e_v3_profile_id,
    resolve_r5e_canary_target,
    validate_r5e_positive_prompt,
)
from keysuri_r5f_manual_canary import (
    R5F_APPROVED_STRUCTURE_VARIATION_PASS,
    R5F_CANARY_PROFILES,
    VISUAL_QA_STATUS as R5F_VISUAL_QA_STATUS,
    build_r5f_opt_in_prompt_source,
    check_r5f_default_prompt_unchanged,
    is_r5f_v4_profile_id,
    resolve_r5f_canary_target,
    validate_r5f_positive_prompt,
)
from keysuri_weather_visual_prompt_integration import (
    build_keysuri_weather_visual_prompt_contract,
    build_keysuri_weather_visual_prompt_report_from_canary_lock,
)

PASS_OFFLINE_ONLY = "PASS_OFFLINE_ONLY"
BLOCK_LIVE_CALL = "BLOCK_LIVE_CALL"
PREFLIGHT_PASS_FOR_ONE_MANUAL_CALL = "PREFLIGHT_PASS_FOR_ONE_MANUAL_CALL"
FAIL = "FAIL"

_REPO_ROOT = Path(__file__).resolve().parent
_DEFAULT_LOCK_PATH = (
    _REPO_ROOT / "ops" / "feeds" / "genie_weather_live_canary_lock_2026-06-04.sample.json"
)

_KST_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_BASELINE_REFERENCE_PATHS = {
    "keysuri_global_tech": (
        "output/keysuri_preview/image_canary/keysuri_global_canary_20260604_221233.jpg"
    ),
    "keysuri_korea_tech": (
        "output/keysuri_preview/image_canary/keysuri_korea_canary_20260604_225207.jpg"
    ),
}

_IDENTITY_PREFIX = (
    "Photorealistic premium Korean private tech secretary Kee-Suri (테크 비서 키수리). "
    "Same person as the reference: refined Korean facial impression, sleek short bob, "
    "thin metal glasses, calm intelligent gaze. "
)
_IDENTITY_SUFFIX = (
    " Quiet, competent private executive secretary — not public "
    "broadcast, not public anchor presentation, not weather-presenter styling"
)

_OPT_IN_ONLY_PHRASE = "fitted premium business silhouette"
_DEFAULT_WARDROBE_MARKERS = (
    "charcoal fitted suit",
    "ivory or soft cream blouse",
)
_SNIPPET_TAIL_FORBIDDEN = "not a lounge or glamour shoot"
_SNIPPET_IDENTITY_TAIL_FORBIDDEN = "private korean ai tech secretary kee-suri identity:"

_PRODUCTION_FLAG_KEYS = (
    "ready_for_production_auto_call",
    "ready_for_image_api_call",
    "ready_for_scheduler",
)
_SIDE_EFFECT_KEYS = (
    "called_image_api",
    "called_gemini",
    "called_weather_api",
)


@dataclass(frozen=True)
class ManualCanaryApproval:
    operator_ref: str
    wardrobe_date_kst: str
    program_id: str
    expected_wardrobe_profile_id: str
    expected_daily_wardrobe_seed: str


@dataclass(frozen=True)
class PreflightIssue:
    code: str
    message: str
    path: str


@dataclass(frozen=True)
class ManualCanaryPreflightResult:
    status: str
    target_date: str
    program_id: str
    wardrobe_profile_id: str | None
    daily_wardrobe_seed: str | None
    wardrobe_clause: str | None
    default_prompt_unchanged: bool
    opt_in_prompt_changed: bool
    production_flags_false: bool
    manual_approval_valid: bool
    review_required: bool
    new_visual_qa_required: bool
    baseline_reference_path: str | None
    baseline_file_exists: bool | None
    issues: tuple[PreflightIssue, ...]
    warnings: tuple[PreflightIssue, ...]


def _issue(code: str, message: str, path: str) -> PreflightIssue:
    return PreflightIssue(code=code, message=message, path=path)


def _validate_kst_date(wardrobe_date_kst: str) -> tuple[str | None, PreflightIssue | None]:
    date_str = (wardrobe_date_kst or "").strip()
    if not date_str:
        return None, _issue("invalid_wardrobe_date_kst", "wardrobe_date_kst is required", "wardrobe_date_kst")
    if not _KST_DATE_RE.match(date_str):
        return None, _issue(
            "invalid_wardrobe_date_kst",
            f"expected YYYY-MM-DD, got {wardrobe_date_kst!r}",
            "wardrobe_date_kst",
        )
    year, month, day = (int(part) for part in date_str.split("-"))
    try:
        datetime(year, month, day)
    except ValueError as exc:
        return None, _issue(
            "invalid_wardrobe_date_kst",
            f"invalid calendar date {date_str!r}: {exc}",
            "wardrobe_date_kst",
        )
    return date_str, None


def _validate_program_id(program_id: str) -> tuple[str | None, PreflightIssue | None]:
    pid = (program_id or "").strip()
    if not pid:
        return None, _issue("invalid_program_id", "program_id is required", "program_id")
    lower = pid.lower()
    forbidden_lower = {p.lower() for p in FORBIDDEN_PROGRAMS}
    if lower in forbidden_lower or lower in ("tomorrow_geenee", "tomorrow_genie", "tomorrow"):
        return None, _issue("forbidden_program_id", f"forbidden program_id {program_id!r}", "program_id")
    if pid not in KEYSURI_IMAGE_PROGRAMS:
        return None, _issue(
            "invalid_program_id",
            f"program_id must be one of {sorted(KEYSURI_IMAGE_PROGRAMS)!r}, got {program_id!r}",
            "program_id",
        )
    return pid, None


def _extract_wardrobe_clause_from_positive_prompt(positive_prompt: str) -> str | None:
    pos = positive_prompt or ""
    if _IDENTITY_PREFIX not in pos:
        return None
    after_prefix = pos.split(_IDENTITY_PREFIX, 1)[1]
    if _IDENTITY_SUFFIX not in after_prefix:
        return None
    clause = after_prefix.split(_IDENTITY_SUFFIX, 1)[0].strip()
    if not clause:
        return None
    if not clause.endswith("."):
        clause = f"{clause}."
    return clause


def _visual_context_for_date(lock_path: Path, program_id: str, wardrobe_date_kst: str) -> dict:
    integration = build_keysuri_weather_binding_integration_report(str(lock_path))
    contexts = integration.get("visual_contexts") or {}
    if program_id not in contexts:
        raise ValueError(f"lock fixture missing visual context for {program_id!r}")
    ctx = deepcopy(contexts[program_id])
    ctx["weather_date"] = wardrobe_date_kst
    return ctx


def _build_contracts(
    lock_path: Path,
    program_id: str,
    wardrobe_date_kst: str,
) -> tuple[dict, dict]:
    ctx = _visual_context_for_date(lock_path, program_id, wardrobe_date_kst)
    default_contract = build_keysuri_weather_visual_prompt_contract(
        program_id,
        ctx,
        use_daily_wardrobe_prompt_snippet=False,
    )
    opt_in_contract = build_keysuri_weather_visual_prompt_contract(
        program_id,
        ctx,
        use_daily_wardrobe_prompt_snippet=True,
    )
    return default_contract, opt_in_contract


def _check_prompt_safety(
    default_contract: dict,
    opt_in_contract: dict,
    wardrobe_profile_id: str,
) -> tuple[bool, bool, List[PreflightIssue], List[PreflightIssue], str | None]:
    issues: List[PreflightIssue] = []
    warnings: List[PreflightIssue] = []

    default_prompt = str(default_contract.get("positive_prompt") or "")
    opt_in_prompt = str(opt_in_contract.get("positive_prompt") or "")
    default_lower = default_prompt.lower()
    opt_in_lower = opt_in_prompt.lower()

    default_ok = True
    for marker in _DEFAULT_WARDROBE_MARKERS:
        if marker not in default_lower:
            default_ok = False
            issues.append(
                _issue(
                    "default_prompt_missing_static_wardrobe",
                    f"default prompt must contain {marker!r}",
                    "positive_prompt",
                )
            )
    if _OPT_IN_ONLY_PHRASE in default_lower:
        default_ok = False
        issues.append(
            _issue(
                "default_prompt_opt_in_contamination",
                "default prompt must not contain opt-in-only wardrobe wording",
                "positive_prompt",
            )
        )
    if default_contract.get("daily_wardrobe", {}).get("wardrobe_prompt_injected") is True:
        default_ok = False
        issues.append(
            _issue(
                "default_prompt_injected",
                "default contract must not inject wardrobe prompt snippet",
                "daily_wardrobe.wardrobe_prompt_injected",
            )
        )

    opt_in_changed = default_prompt != opt_in_prompt
    if not opt_in_changed:
        issues.append(
            _issue(
                "opt_in_prompt_unchanged",
                "opt-in prompt must differ from default prompt",
                "positive_prompt",
            )
        )

    wardrobe_clause = _extract_wardrobe_clause_from_positive_prompt(opt_in_prompt)
    if not wardrobe_clause:
        issues.append(
            _issue(
                "opt_in_wardrobe_clause_missing",
                "could not extract wardrobe clause from opt-in positive_prompt",
                "positive_prompt",
            )
        )
    elif wardrobe_clause.lower().rstrip(".") not in opt_in_lower:
        issues.append(
            _issue(
                "opt_in_wardrobe_clause_not_present",
                "opt-in prompt must include extracted wardrobe clause",
                "positive_prompt",
            )
        )

    if _SNIPPET_TAIL_FORBIDDEN in opt_in_lower:
        issues.append(
            _issue(
                "opt_in_full_snippet_tail_injected",
                "opt-in prompt must not include full snippet tail",
                "positive_prompt",
            )
        )
    if _SNIPPET_IDENTITY_TAIL_FORBIDDEN in opt_in_lower:
        issues.append(
            _issue(
                "opt_in_snippet_identity_block_injected",
                "opt-in prompt must not duplicate full snippet identity block",
                "positive_prompt",
            )
        )

    if opt_in_contract.get("daily_wardrobe", {}).get("wardrobe_prompt_injected") is not True:
        issues.append(
            _issue(
                "opt_in_not_injected",
                "opt-in contract must set wardrobe_prompt_injected true",
                "daily_wardrobe.wardrobe_prompt_injected",
            )
        )

    review_required = (
        wardrobe_profile_id == "profile_01_charcoal_ivory"
        and str(opt_in_contract.get("daily_wardrobe", {}).get("wardrobe_date_kst") or "")
        == "2026-06-04"
    )
    new_visual_qa_required = wardrobe_profile_id != "profile_01_charcoal_ivory" or not review_required

    if review_required:
        warnings.append(
            _issue(
                "review_required",
                "2026-06-04 profile_01 opt-in changes wardrobe wording vs static stem",
                "wardrobe_profile_id",
            )
        )
    if new_visual_qa_required:
        warnings.append(
            _issue(
                "new_visual_qa_required",
                "non-profile_01 or non-2026-06-04 target requires new visual QA cycle",
                "wardrobe_profile_id",
            )
        )

    return default_ok, opt_in_changed, issues, warnings, wardrobe_clause


def _check_global_korea_parity(
    lock_path: Path,
    wardrobe_date_kst: str,
) -> List[PreflightIssue]:
    issues: List[PreflightIssue] = []
    global_default, global_opt_in = _build_contracts(
        lock_path, "keysuri_global_tech", wardrobe_date_kst
    )
    korea_default, korea_opt_in = _build_contracts(
        lock_path, "keysuri_korea_tech", wardrobe_date_kst
    )

    g_meta = global_opt_in.get("daily_wardrobe") or {}
    k_meta = korea_opt_in.get("daily_wardrobe") or {}

    if g_meta.get("wardrobe_profile_id") != k_meta.get("wardrobe_profile_id"):
        issues.append(
            _issue(
                "parity_profile_mismatch",
                "Global/Korea wardrobe_profile_id must match for same date",
                "daily_wardrobe.wardrobe_profile_id",
            )
        )
    if g_meta.get("daily_wardrobe_seed") != k_meta.get("daily_wardrobe_seed"):
        issues.append(
            _issue(
                "parity_seed_mismatch",
                "Global/Korea daily_wardrobe_seed must match for same date",
                "daily_wardrobe.daily_wardrobe_seed",
            )
        )

    g_clause = _extract_wardrobe_clause_from_positive_prompt(
        str(global_opt_in.get("positive_prompt") or "")
    )
    k_clause = _extract_wardrobe_clause_from_positive_prompt(
        str(korea_opt_in.get("positive_prompt") or "")
    )
    if g_clause != k_clause:
        issues.append(
            _issue(
                "parity_wardrobe_clause_mismatch",
                "Global/Korea wardrobe clause must match for same date",
                "positive_prompt",
            )
        )

    g_pos = str(global_opt_in.get("positive_prompt") or "").lower()
    k_pos = str(korea_opt_in.get("positive_prompt") or "").lower()
    if "daytime or early afternoon" not in g_pos:
        issues.append(
            _issue(
                "parity_global_scene_missing",
                "Global prompt must retain daytime scene stem",
                "positive_prompt",
            )
        )
    if "winter 18:30" not in k_pos:
        issues.append(
            _issue(
                "parity_korea_scene_missing",
                "Korea prompt must retain winter 18:30 scene stem",
                "positive_prompt",
            )
        )
    if g_pos == k_pos:
        issues.append(
            _issue(
                "parity_program_prompts_identical",
                "Global/Korea prompts must differ in scene/pose/time",
                "positive_prompt",
            )
        )
    if "tablet held simply" not in g_pos:
        issues.append(
            _issue(
                "parity_global_pose_missing",
                "Global prompt must retain tablet pose stem",
                "positive_prompt",
            )
        )
    if "tablet is optional" not in k_pos:
        issues.append(
            _issue(
                "parity_korea_pose_missing",
                "Korea prompt must retain optional tablet pose stem",
                "positive_prompt",
            )
        )

    if global_default.get("positive_prompt") == korea_default.get("positive_prompt"):
        issues.append(
            _issue(
                "parity_default_prompts_identical",
                "Global/Korea default prompts must differ in scene/pose/time",
                "positive_prompt",
            )
        )

    return issues


def _check_production_flags(lock_path: Path) -> tuple[bool, List[PreflightIssue]]:
    issues: List[PreflightIssue] = []
    report = build_keysuri_weather_visual_prompt_report_from_canary_lock(str(lock_path))

    for key in _PRODUCTION_FLAG_KEYS:
        if report.get(key) is not False:
            issues.append(
                _issue(
                    f"{key}_invalid",
                    f"{key} must be false",
                    key,
                )
            )

    side_effects = report.get("side_effects") or {}
    for key in _SIDE_EFFECT_KEYS:
        if key in side_effects and side_effects.get(key) is not False:
            issues.append(
                _issue(
                    f"side_effects_{key}_invalid",
                    f"side_effects.{key} must be false",
                    f"side_effects.{key}",
                )
            )

    return not issues, issues


def _validate_manual_approval(
    approval: ManualCanaryApproval,
    wardrobe_date_kst: str,
    program_id: str,
    wardrobe_profile_id: str,
    daily_wardrobe_seed: str,
) -> tuple[bool, List[PreflightIssue]]:
    issues: List[PreflightIssue] = []
    if not (approval.operator_ref or "").strip():
        issues.append(
            _issue("approval_operator_ref_missing", "operator_ref is required", "approval.operator_ref")
        )
    if approval.wardrobe_date_kst != wardrobe_date_kst:
        issues.append(
            _issue(
                "approval_date_mismatch",
                "approval wardrobe_date_kst must match target",
                "approval.wardrobe_date_kst",
            )
        )
    if approval.program_id != program_id:
        issues.append(
            _issue(
                "approval_program_mismatch",
                "approval program_id must match target",
                "approval.program_id",
            )
        )
    if approval.expected_wardrobe_profile_id != wardrobe_profile_id:
        issues.append(
            _issue(
                "approval_profile_mismatch",
                "approval expected_wardrobe_profile_id must match resolver",
                "approval.expected_wardrobe_profile_id",
            )
        )
    if approval.expected_daily_wardrobe_seed != daily_wardrobe_seed:
        issues.append(
            _issue(
                "approval_seed_mismatch",
                "approval expected_daily_wardrobe_seed must match resolver",
                "approval.expected_daily_wardrobe_seed",
            )
        )
    return not issues, issues


def _run_r5d_manual_canary_preflight(
    *,
    date_str: str,
    pid: str,
    approval: ManualCanaryApproval | None,
    resolved_path: Path,
    baseline_reference_path: str | None,
    baseline_file_exists: bool | None,
    check_baseline_exists: bool,
) -> ManualCanaryPreflightResult:
    """Offline preflight for R5D v2 failure-history canary (NOT_ACCEPTED — not v1 resolver)."""
    issues: List[PreflightIssue] = []
    warnings: List[PreflightIssue] = []

    if approval is None:
        return ManualCanaryPreflightResult(
            status=BLOCK_LIVE_CALL,
            target_date=date_str,
            program_id=pid,
            wardrobe_profile_id=None,
            daily_wardrobe_seed=None,
            wardrobe_clause=None,
            default_prompt_unchanged=False,
            opt_in_prompt_changed=False,
            production_flags_false=False,
            manual_approval_valid=False,
            review_required=False,
            new_visual_qa_required=True,
            baseline_reference_path=baseline_reference_path,
            baseline_file_exists=baseline_file_exists,
            issues=tuple(issues),
            warnings=tuple(warnings),
        )

    if not is_r5d_v2_profile_id(approval.expected_wardrobe_profile_id):
        issues.append(
            _issue(
                "r5d_profile_required",
                "R5D failure-history requires a profile_v2_* wardrobe profile id (NOT_ACCEPTED)",
                "approval.expected_wardrobe_profile_id",
            )
        )

    target, target_issues = resolve_r5d_canary_target(
        wardrobe_date_kst=date_str,
        program_id=pid,
        wardrobe_profile_id=approval.expected_wardrobe_profile_id,
        expected_daily_wardrobe_seed=approval.expected_daily_wardrobe_seed,
    )
    for msg in target_issues:
        code = msg.split("]", 1)[0].lstrip("[")
        issues.append(_issue(code, msg, "r5d_target"))

    wardrobe_profile_id = target.wardrobe_profile_id if target else None
    daily_wardrobe_seed = target.daily_wardrobe_seed if target else None
    wardrobe_clause = target.wardrobe_clause if target else None

    default_prompt_unchanged = False
    opt_in_prompt_changed = False
    if target is not None:
        default_prompt_unchanged = check_r5d_default_prompt_unchanged(str(resolved_path), pid, date_str)
        if not default_prompt_unchanged:
            issues.append(
                _issue(
                    "default_prompt_injected",
                    "default contract must remain unchanged while R5D opt-in runs",
                    "daily_wardrobe.wardrobe_prompt_injected",
                )
            )
        try:
            prompt_source = build_r5d_opt_in_prompt_source(
                lock_path=str(resolved_path),
                program_id=pid,
                wardrobe_date_kst=date_str,
                wardrobe_profile_id=target.wardrobe_profile_id,
                daily_wardrobe_seed=target.daily_wardrobe_seed,
            )
        except ValueError as exc:
            issues.append(_issue("r5d_prompt_build_failed", str(exc), "r5d_prompt"))
            prompt_source = None

        if prompt_source is not None:
            default_contract, _ = _build_contracts(resolved_path, pid, date_str)
            opt_in_prompt = str(prompt_source.get("positive_prompt") or "")
            default_prompt = str(default_contract.get("positive_prompt") or "")
            opt_in_prompt_changed = default_prompt != opt_in_prompt
            if not opt_in_prompt_changed:
                issues.append(
                    _issue(
                        "r5d_prompt_unchanged",
                        "R5D opt-in prompt must differ from default prompt",
                        "positive_prompt",
                    )
                )
            for msg in validate_r5d_positive_prompt(opt_in_prompt):
                issues.append(_issue("r5d_prompt_invalid", msg, "positive_prompt"))

    production_flags_false, flag_issues = _check_production_flags(resolved_path)
    issues.extend(flag_issues)

    if approval is not None and target is not None:
        _, approval_issues = _validate_manual_approval(
            approval,
            date_str,
            pid,
            target.wardrobe_profile_id,
            target.daily_wardrobe_seed,
        )
        issues.extend(approval_issues)

    warnings.append(
        _issue(
            "r5d_not_accepted",
            f"R5D is failure-history only (visual_qa_status={R5D_VISUAL_QA_STATUS}); not an accepted creative path",
            "visual_qa_status",
        )
    )
    if target is not None:
        profile_meta = R5D_CANARY_PROFILES.get(target.wardrobe_profile_id, {})
        qa_reason = profile_meta.get("visual_qa_reason")
        if qa_reason:
            warnings.append(
                _issue(
                    "r5d_visual_qa_reason",
                    str(qa_reason),
                    "visual_qa_reason",
                )
            )

    if issues:
        status = FAIL
        manual_approval_valid = False
    else:
        status = R5D_APPROVED_MANUAL_OVERRIDE_PASS
        manual_approval_valid = True
        warnings.append(
            _issue(
                "manual_one_call_only",
                "approval authorizes one manual image call only; no retry, batch, Scheduler, or production wiring",
                "approval",
            )
        )

    return ManualCanaryPreflightResult(
        status=status,
        target_date=date_str,
        program_id=pid,
        wardrobe_profile_id=wardrobe_profile_id,
        daily_wardrobe_seed=daily_wardrobe_seed,
        wardrobe_clause=wardrobe_clause,
        default_prompt_unchanged=default_prompt_unchanged,
        opt_in_prompt_changed=opt_in_prompt_changed,
        production_flags_false=production_flags_false,
        manual_approval_valid=manual_approval_valid,
        review_required=False,
        new_visual_qa_required=True,
        baseline_reference_path=baseline_reference_path,
        baseline_file_exists=baseline_file_exists,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


def _run_r5f_manual_canary_preflight(
    *,
    date_str: str,
    pid: str,
    approval: ManualCanaryApproval | None,
    resolved_path: Path,
    baseline_reference_path: str | None,
    baseline_file_exists: bool | None,
    check_baseline_exists: bool,
) -> ManualCanaryPreflightResult:
    """Offline preflight for R5F v4 accepted-direction canary (PASS_DIRECTION — not production resolver)."""
    issues: List[PreflightIssue] = []
    warnings: List[PreflightIssue] = []

    if approval is None:
        return ManualCanaryPreflightResult(
            status=BLOCK_LIVE_CALL,
            target_date=date_str,
            program_id=pid,
            wardrobe_profile_id=None,
            daily_wardrobe_seed=None,
            wardrobe_clause=None,
            default_prompt_unchanged=False,
            opt_in_prompt_changed=False,
            production_flags_false=False,
            manual_approval_valid=False,
            review_required=False,
            new_visual_qa_required=True,
            baseline_reference_path=baseline_reference_path,
            baseline_file_exists=baseline_file_exists,
            issues=tuple(issues),
            warnings=tuple(warnings),
        )

    if not is_r5f_v4_profile_id(approval.expected_wardrobe_profile_id):
        issues.append(
            _issue(
                "r5f_profile_required",
                "R5F structure variation requires a profile_v4_* wardrobe profile id",
                "approval.expected_wardrobe_profile_id",
            )
        )

    target, target_issues = resolve_r5f_canary_target(
        wardrobe_date_kst=date_str,
        program_id=pid,
        wardrobe_profile_id=approval.expected_wardrobe_profile_id,
        expected_daily_wardrobe_seed=approval.expected_daily_wardrobe_seed,
    )
    for msg in target_issues:
        code = msg.split("]", 1)[0].lstrip("[")
        issues.append(_issue(code, msg, "r5f_target"))

    wardrobe_profile_id = target.wardrobe_profile_id if target else None
    daily_wardrobe_seed = target.daily_wardrobe_seed if target else None
    wardrobe_clause = target.wardrobe_clause if target else None

    default_prompt_unchanged = False
    opt_in_prompt_changed = False
    if target is not None:
        default_prompt_unchanged = check_r5f_default_prompt_unchanged(str(resolved_path), pid, date_str)
        if not default_prompt_unchanged:
            issues.append(
                _issue(
                    "default_prompt_injected",
                    "default contract must remain unchanged while R5F opt-in runs",
                    "daily_wardrobe.wardrobe_prompt_injected",
                )
            )
        try:
            prompt_source = build_r5f_opt_in_prompt_source(
                lock_path=str(resolved_path),
                program_id=pid,
                wardrobe_date_kst=date_str,
                wardrobe_profile_id=target.wardrobe_profile_id,
                daily_wardrobe_seed=target.daily_wardrobe_seed,
            )
        except ValueError as exc:
            issues.append(_issue("r5f_prompt_build_failed", str(exc), "r5f_prompt"))
            prompt_source = None

        if prompt_source is not None:
            default_contract, _ = _build_contracts(resolved_path, pid, date_str)
            opt_in_prompt = str(prompt_source.get("positive_prompt") or "")
            default_prompt = str(default_contract.get("positive_prompt") or "")
            opt_in_prompt_changed = default_prompt != opt_in_prompt
            if not opt_in_prompt_changed:
                issues.append(
                    _issue(
                        "r5f_prompt_unchanged",
                        "R5F opt-in prompt must differ from default prompt",
                        "positive_prompt",
                    )
                )
            for msg in validate_r5f_positive_prompt(
                opt_in_prompt,
                profile_id=target.wardrobe_profile_id,
            ):
                issues.append(_issue("r5f_prompt_invalid", msg, "positive_prompt"))

    production_flags_false, flag_issues = _check_production_flags(resolved_path)
    issues.extend(flag_issues)

    if approval is not None and target is not None:
        _, approval_issues = _validate_manual_approval(
            approval,
            date_str,
            pid,
            target.wardrobe_profile_id,
            target.daily_wardrobe_seed,
        )
        issues.extend(approval_issues)

    warnings.append(
        _issue(
            "r5f_pass_direction",
            f"R5F is the accepted direction candidate (visual_qa_status={R5F_VISUAL_QA_STATUS}); canary-only, not production resolver",
            "visual_qa_status",
        )
    )
    if target is not None:
        profile_meta = R5F_CANARY_PROFILES.get(target.wardrobe_profile_id, {})
        qa_reason = profile_meta.get("visual_qa_reason")
        if qa_reason:
            warnings.append(
                _issue(
                    "r5f_visual_qa_reason",
                    str(qa_reason),
                    "visual_qa_reason",
                )
            )

    if issues:
        status = FAIL
        manual_approval_valid = False
    else:
        status = R5F_APPROVED_STRUCTURE_VARIATION_PASS
        manual_approval_valid = True
        warnings.append(
            _issue(
                "manual_one_call_only",
                "approval authorizes one manual image call only; no retry, batch, Scheduler, or production wiring",
                "approval",
            )
        )

    return ManualCanaryPreflightResult(
        status=status,
        target_date=date_str,
        program_id=pid,
        wardrobe_profile_id=wardrobe_profile_id,
        daily_wardrobe_seed=daily_wardrobe_seed,
        wardrobe_clause=wardrobe_clause,
        default_prompt_unchanged=default_prompt_unchanged,
        opt_in_prompt_changed=opt_in_prompt_changed,
        production_flags_false=production_flags_false,
        manual_approval_valid=manual_approval_valid,
        review_required=False,
        new_visual_qa_required=True,
        baseline_reference_path=baseline_reference_path,
        baseline_file_exists=baseline_file_exists,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


def _run_r5e_manual_canary_preflight(
    *,
    date_str: str,
    pid: str,
    approval: ManualCanaryApproval | None,
    resolved_path: Path,
    baseline_reference_path: str | None,
    baseline_file_exists: bool | None,
    check_baseline_exists: bool,
) -> ManualCanaryPreflightResult:
    """Offline preflight for R5E v3 failure-history canary (REVIEW_NOT_ACCEPTED — not production resolver)."""
    issues: List[PreflightIssue] = []
    warnings: List[PreflightIssue] = []

    if approval is None:
        return ManualCanaryPreflightResult(
            status=BLOCK_LIVE_CALL,
            target_date=date_str,
            program_id=pid,
            wardrobe_profile_id=None,
            daily_wardrobe_seed=None,
            wardrobe_clause=None,
            default_prompt_unchanged=False,
            opt_in_prompt_changed=False,
            production_flags_false=False,
            manual_approval_valid=False,
            review_required=False,
            new_visual_qa_required=True,
            baseline_reference_path=baseline_reference_path,
            baseline_file_exists=baseline_file_exists,
            issues=tuple(issues),
            warnings=tuple(warnings),
        )

    if not is_r5e_v3_profile_id(approval.expected_wardrobe_profile_id):
        issues.append(
            _issue(
                "r5e_profile_required",
                "R5E failure-history requires a profile_v3_* wardrobe profile id (REVIEW_NOT_ACCEPTED)",
                "approval.expected_wardrobe_profile_id",
            )
        )

    target, target_issues = resolve_r5e_canary_target(
        wardrobe_date_kst=date_str,
        program_id=pid,
        wardrobe_profile_id=approval.expected_wardrobe_profile_id,
        expected_daily_wardrobe_seed=approval.expected_daily_wardrobe_seed,
    )
    for msg in target_issues:
        code = msg.split("]", 1)[0].lstrip("[")
        issues.append(_issue(code, msg, "r5e_target"))

    wardrobe_profile_id = target.wardrobe_profile_id if target else None
    daily_wardrobe_seed = target.daily_wardrobe_seed if target else None
    wardrobe_clause = target.wardrobe_clause if target else None

    default_prompt_unchanged = False
    opt_in_prompt_changed = False
    if target is not None:
        default_prompt_unchanged = check_r5e_default_prompt_unchanged(str(resolved_path), pid, date_str)
        if not default_prompt_unchanged:
            issues.append(
                _issue(
                    "default_prompt_injected",
                    "default contract must remain unchanged while R5E opt-in runs",
                    "daily_wardrobe.wardrobe_prompt_injected",
                )
            )
        try:
            prompt_source = build_r5e_opt_in_prompt_source(
                lock_path=str(resolved_path),
                program_id=pid,
                wardrobe_date_kst=date_str,
                wardrobe_profile_id=target.wardrobe_profile_id,
                daily_wardrobe_seed=target.daily_wardrobe_seed,
            )
        except ValueError as exc:
            issues.append(_issue("r5e_prompt_build_failed", str(exc), "r5e_prompt"))
            prompt_source = None

        if prompt_source is not None:
            default_contract, _ = _build_contracts(resolved_path, pid, date_str)
            opt_in_prompt = str(prompt_source.get("positive_prompt") or "")
            default_prompt = str(default_contract.get("positive_prompt") or "")
            opt_in_prompt_changed = default_prompt != opt_in_prompt
            if not opt_in_prompt_changed:
                issues.append(
                    _issue(
                        "r5e_prompt_unchanged",
                        "R5E opt-in prompt must differ from default prompt",
                        "positive_prompt",
                    )
                )
            for msg in validate_r5e_positive_prompt(opt_in_prompt):
                issues.append(_issue("r5e_prompt_invalid", msg, "positive_prompt"))

    production_flags_false, flag_issues = _check_production_flags(resolved_path)
    issues.extend(flag_issues)

    if approval is not None and target is not None:
        _, approval_issues = _validate_manual_approval(
            approval,
            date_str,
            pid,
            target.wardrobe_profile_id,
            target.daily_wardrobe_seed,
        )
        issues.extend(approval_issues)

    warnings.append(
        _issue(
            "r5e_review_not_accepted",
            f"R5E is failure-history only (visual_qa_status={R5E_VISUAL_QA_STATUS}); not an accepted creative path",
            "visual_qa_status",
        )
    )
    if target is not None:
        profile_meta = R5E_CANARY_PROFILES.get(target.wardrobe_profile_id, {})
        qa_reason = profile_meta.get("visual_qa_reason")
        if qa_reason:
            warnings.append(
                _issue(
                    "r5e_visual_qa_reason",
                    str(qa_reason),
                    "visual_qa_reason",
                )
            )

    if issues:
        status = FAIL
        manual_approval_valid = False
    else:
        status = R5E_APPROVED_STRUCTURE_VARIATION_PASS
        manual_approval_valid = True
        warnings.append(
            _issue(
                "manual_one_call_only",
                "approval authorizes one manual image call only; no retry, batch, Scheduler, or production wiring",
                "approval",
            )
        )

    return ManualCanaryPreflightResult(
        status=status,
        target_date=date_str,
        program_id=pid,
        wardrobe_profile_id=wardrobe_profile_id,
        daily_wardrobe_seed=daily_wardrobe_seed,
        wardrobe_clause=wardrobe_clause,
        default_prompt_unchanged=default_prompt_unchanged,
        opt_in_prompt_changed=opt_in_prompt_changed,
        production_flags_false=production_flags_false,
        manual_approval_valid=manual_approval_valid,
        review_required=False,
        new_visual_qa_required=True,
        baseline_reference_path=baseline_reference_path,
        baseline_file_exists=baseline_file_exists,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


def run_keysuri_manual_canary_preflight(
    *,
    wardrobe_date_kst: str,
    program_id: str,
    approval: ManualCanaryApproval | None = None,
    lock_path: str | Path | None = None,
    check_global_korea_parity: bool = True,
    check_baseline_exists: bool = False,
    r5d_creative_variation: bool = False,
    r5e_structure_variation: bool = False,
    r5f_structure_variation: bool = False,
) -> ManualCanaryPreflightResult:
    """Run offline preflight for a single manual opt-in wardrobe canary candidate."""
    issues: List[PreflightIssue] = []
    warnings: List[PreflightIssue] = []

    date_str, date_issue = _validate_kst_date(wardrobe_date_kst)
    if date_issue:
        issues.append(date_issue)
    pid, program_issue = _validate_program_id(program_id)
    if program_issue:
        issues.append(program_issue)

    resolved_path = Path(lock_path) if lock_path is not None else _DEFAULT_LOCK_PATH
    if not resolved_path.is_file():
        issues.append(
            _issue(
                "lock_path_missing",
                f"canary lock fixture not found: {resolved_path}",
                "lock_path",
            )
        )

    wardrobe_profile_id: str | None = None
    daily_wardrobe_seed: str | None = None
    wardrobe_clause: str | None = None
    default_prompt_unchanged = False
    opt_in_prompt_changed = False
    production_flags_false = False
    manual_approval_valid = False
    review_required = False
    new_visual_qa_required = False

    baseline_reference_path = _BASELINE_REFERENCE_PATHS.get(pid or "") if pid else None
    baseline_file_exists: bool | None = None
    if baseline_reference_path and check_baseline_exists:
        exists = (_REPO_ROOT / baseline_reference_path).is_file()
        baseline_file_exists = exists
        if not exists:
            warnings.append(
                _issue(
                    "baseline_file_missing",
                    f"baseline reference file not found locally: {baseline_reference_path}",
                    "baseline_reference_path",
                )
            )

    if issues:
        return ManualCanaryPreflightResult(
            status=FAIL,
            target_date=date_str or (wardrobe_date_kst or ""),
            program_id=pid or (program_id or ""),
            wardrobe_profile_id=wardrobe_profile_id,
            daily_wardrobe_seed=daily_wardrobe_seed,
            wardrobe_clause=wardrobe_clause,
            default_prompt_unchanged=default_prompt_unchanged,
            opt_in_prompt_changed=opt_in_prompt_changed,
            production_flags_false=production_flags_false,
            manual_approval_valid=manual_approval_valid,
            review_required=review_required,
            new_visual_qa_required=new_visual_qa_required,
            baseline_reference_path=baseline_reference_path,
            baseline_file_exists=baseline_file_exists,
            issues=tuple(issues),
            warnings=tuple(warnings),
        )

    if r5f_structure_variation:
        return _run_r5f_manual_canary_preflight(
            date_str=date_str,
            pid=pid,
            approval=approval,
            resolved_path=resolved_path,
            baseline_reference_path=baseline_reference_path,
            baseline_file_exists=baseline_file_exists,
            check_baseline_exists=check_baseline_exists,
        )

    if r5e_structure_variation:
        return _run_r5e_manual_canary_preflight(
            date_str=date_str,
            pid=pid,
            approval=approval,
            resolved_path=resolved_path,
            baseline_reference_path=baseline_reference_path,
            baseline_file_exists=baseline_file_exists,
            check_baseline_exists=check_baseline_exists,
        )

    if r5d_creative_variation:
        return _run_r5d_manual_canary_preflight(
            date_str=date_str,
            pid=pid,
            approval=approval,
            resolved_path=resolved_path,
            baseline_reference_path=baseline_reference_path,
            baseline_file_exists=baseline_file_exists,
            check_baseline_exists=check_baseline_exists,
        )

    try:
        resolved = resolve_keysuri_daily_wardrobe(date_str, pid)
    except ValueError as exc:
        issues.append(_issue("resolver_failed", str(exc), "resolver"))
        return ManualCanaryPreflightResult(
            status=FAIL,
            target_date=date_str,
            program_id=pid,
            wardrobe_profile_id=wardrobe_profile_id,
            daily_wardrobe_seed=daily_wardrobe_seed,
            wardrobe_clause=wardrobe_clause,
            default_prompt_unchanged=default_prompt_unchanged,
            opt_in_prompt_changed=opt_in_prompt_changed,
            production_flags_false=production_flags_false,
            manual_approval_valid=manual_approval_valid,
            review_required=review_required,
            new_visual_qa_required=new_visual_qa_required,
            baseline_reference_path=baseline_reference_path,
            baseline_file_exists=baseline_file_exists,
            issues=tuple(issues),
            warnings=tuple(warnings),
        )

    wardrobe_profile_id = resolved.wardrobe_profile_id
    daily_wardrobe_seed = resolved.daily_wardrobe_seed

    try:
        default_contract, opt_in_contract = _build_contracts(resolved_path, pid, date_str)
    except ValueError as exc:
        issues.append(_issue("prompt_contract_build_failed", str(exc), "prompt_contract"))
        return ManualCanaryPreflightResult(
            status=FAIL,
            target_date=date_str,
            program_id=pid,
            wardrobe_profile_id=wardrobe_profile_id,
            daily_wardrobe_seed=daily_wardrobe_seed,
            wardrobe_clause=wardrobe_clause,
            default_prompt_unchanged=default_prompt_unchanged,
            opt_in_prompt_changed=opt_in_prompt_changed,
            production_flags_false=production_flags_false,
            manual_approval_valid=manual_approval_valid,
            review_required=review_required,
            new_visual_qa_required=new_visual_qa_required,
            baseline_reference_path=baseline_reference_path,
            baseline_file_exists=baseline_file_exists,
            issues=tuple(issues),
            warnings=tuple(warnings),
        )

    (
        default_prompt_unchanged,
        opt_in_prompt_changed,
        prompt_issues,
        prompt_warnings,
        wardrobe_clause,
    ) = _check_prompt_safety(default_contract, opt_in_contract, wardrobe_profile_id)
    issues.extend(prompt_issues)
    warnings.extend(prompt_warnings)
    review_required = any(w.code == "review_required" for w in prompt_warnings)
    new_visual_qa_required = any(w.code == "new_visual_qa_required" for w in prompt_warnings)

    if check_global_korea_parity:
        issues.extend(_check_global_korea_parity(resolved_path, date_str))

    production_flags_false, flag_issues = _check_production_flags(resolved_path)
    issues.extend(flag_issues)

    if approval is not None:
        _, approval_issues = _validate_manual_approval(
            approval,
            date_str,
            pid,
            wardrobe_profile_id,
            daily_wardrobe_seed,
        )
        issues.extend(approval_issues)

    if issues:
        status = FAIL
        manual_approval_valid = False
    elif approval is None:
        status = BLOCK_LIVE_CALL
        manual_approval_valid = False
    else:
        status = PREFLIGHT_PASS_FOR_ONE_MANUAL_CALL
        manual_approval_valid = True
        warnings.append(
            _issue(
                "manual_one_call_only",
                "approval authorizes one manual image call only; no retry, batch, Scheduler, or production wiring",
                "approval",
            )
        )

    return ManualCanaryPreflightResult(
        status=status,
        target_date=date_str,
        program_id=pid,
        wardrobe_profile_id=wardrobe_profile_id,
        daily_wardrobe_seed=daily_wardrobe_seed,
        wardrobe_clause=wardrobe_clause,
        default_prompt_unchanged=default_prompt_unchanged,
        opt_in_prompt_changed=opt_in_prompt_changed,
        production_flags_false=production_flags_false,
        manual_approval_valid=manual_approval_valid,
        review_required=review_required,
        new_visual_qa_required=new_visual_qa_required,
        baseline_reference_path=baseline_reference_path,
        baseline_file_exists=baseline_file_exists,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )
