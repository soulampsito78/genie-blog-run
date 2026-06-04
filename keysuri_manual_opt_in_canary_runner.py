"""Kee-Suri manual opt-in wardrobe canary runner (R5B-II — preflight gate, dry-run/mock only)."""
from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, List

from keysuri_image_api_canary_client import (
    DEFAULT_LOCK_PATH,
    DEFAULT_OUTPUT_DIR,
    parse_bool_manual_approval,
    run_keysuri_image_api_canary,
)
from keysuri_manual_canary_preflight import (
    PREFLIGHT_PASS_FOR_ONE_MANUAL_CALL,
    ManualCanaryApproval,
    ManualCanaryPreflightResult,
    run_keysuri_manual_canary_preflight,
)
from keysuri_weather_binding_integration import build_keysuri_weather_binding_integration_report
from keysuri_weather_visual_prompt_integration import build_keysuri_weather_visual_prompt_contract

LIVE_CALL_NOT_ENABLED_IN_R5B_II = "LIVE_CALL_NOT_ENABLED_IN_R5B_II"
BLOCKED_NO_WARDROBE_APPROVAL = "blocked_no_wardrobe_approval"
BLOCKED_INCOMPLETE_WARDROBE_APPROVAL = "blocked_incomplete_wardrobe_approval"
BLOCKED_ENV_CLI_MISMATCH = "blocked_env_cli_mismatch"
BLOCKED_PREFLIGHT_FAILED = "blocked_preflight_failed"
BLOCKED_MULTI_PROGRAM_APPROVAL = "blocked_multi_program_approval"
PREFLIGHT_ONLY_PASS = "preflight_only_pass"
DRY_RUN_READY = "dry_run_ready"
MOCK_CALLED_ONCE = "mock_called_once"

ENV_MANUAL_APPROVAL = "GENIE_KEYSURI_IMAGE_MANUAL_APPROVAL"
ENV_APPROVED_DATE = "GENIE_KEYSURI_APPROVED_WARDROBE_DATE_KST"
ENV_APPROVED_PROGRAM = "GENIE_KEYSURI_APPROVED_PROGRAM_ID"
ENV_APPROVED_PROFILE = "GENIE_KEYSURI_APPROVED_PROFILE_ID"
ENV_APPROVED_SEED = "GENIE_KEYSURI_APPROVED_SEED"
ENV_APPROVED_OPERATOR = "GENIE_KEYSURI_APPROVED_OPERATOR_REF"

_REPO_ROOT = Path(__file__).resolve().parent
_DEFAULT_LOCK = _REPO_ROOT / DEFAULT_LOCK_PATH


@dataclass(frozen=True)
class ManualOptInCanaryRunResult:
    runner_status: str
    approval_present: bool
    wardrobe_date_kst: str | None
    program_id: str | None
    expected_wardrobe_profile_id: str | None
    expected_daily_wardrobe_seed: str | None
    preflight_status: str | None
    wardrobe_clause: str | None
    dry_run_would_proceed: bool
    preflight_result: ManualCanaryPreflightResult | None
    canary_report: dict | None
    issues: tuple[str, ...]
    audit_text: str


def _issue_message(code: str, message: str) -> str:
    return f"[{code}] {message}"


def _program_has_multi_select(value: str) -> bool:
    raw = (value or "").strip()
    return bool(raw) and ("," in raw or ";" in raw or " " in raw)


def parse_manual_canary_approval_from_env(
    environ: dict[str, str] | None = None,
) -> tuple[ManualCanaryApproval | None, List[str]]:
    """Parse wardrobe manual approval from env. Returns approval and issue messages."""
    env = environ if environ is not None else os.environ
    issues: List[str] = []

    if not parse_bool_manual_approval(env.get(ENV_MANUAL_APPROVAL)):
        issues.append(_issue_message(BLOCKED_NO_WARDROBE_APPROVAL, "master manual approval env is missing or false"))
        return None, issues

    date_str = (env.get(ENV_APPROVED_DATE) or "").strip()
    program_id = (env.get(ENV_APPROVED_PROGRAM) or "").strip()
    profile_id = (env.get(ENV_APPROVED_PROFILE) or "").strip()
    seed = (env.get(ENV_APPROVED_SEED) or "").strip()
    operator_ref = (env.get(ENV_APPROVED_OPERATOR) or "").strip() or "unspecified-operator"

    if not date_str:
        issues.append(_issue_message(BLOCKED_INCOMPLETE_WARDROBE_APPROVAL, f"{ENV_APPROVED_DATE} is required"))
    if not program_id:
        issues.append(_issue_message(BLOCKED_INCOMPLETE_WARDROBE_APPROVAL, f"{ENV_APPROVED_PROGRAM} is required"))
    elif _program_has_multi_select(program_id):
        issues.append(
            _issue_message(
                BLOCKED_MULTI_PROGRAM_APPROVAL,
                "exactly one program per approval; multi-program values are forbidden",
            )
        )
    if not profile_id:
        issues.append(_issue_message(BLOCKED_INCOMPLETE_WARDROBE_APPROVAL, f"{ENV_APPROVED_PROFILE} is required"))
    if not seed:
        issues.append(_issue_message(BLOCKED_INCOMPLETE_WARDROBE_APPROVAL, f"{ENV_APPROVED_SEED} is required"))

    if issues:
        return None, issues

    return ManualCanaryApproval(
        operator_ref=operator_ref,
        wardrobe_date_kst=date_str,
        program_id=program_id,
        expected_wardrobe_profile_id=profile_id,
        expected_daily_wardrobe_seed=seed,
    ), []


def _resolve_cli_env_values(
    approval: ManualCanaryApproval | None,
    wardrobe_date_kst: str | None,
    program_id: str | None,
) -> tuple[str | None, str | None, List[str]]:
    issues: List[str] = []
    if approval is None:
        return wardrobe_date_kst, program_id, issues

    resolved_date = approval.wardrobe_date_kst
    resolved_program = approval.program_id

    if wardrobe_date_kst is not None and wardrobe_date_kst.strip() != approval.wardrobe_date_kst:
        issues.append(
            _issue_message(
                BLOCKED_ENV_CLI_MISMATCH,
                "CLI wardrobe date must match approval env when both are supplied",
            )
        )
    elif wardrobe_date_kst is not None:
        resolved_date = wardrobe_date_kst.strip()

    if program_id is not None and program_id.strip() != approval.program_id:
        issues.append(
            _issue_message(
                BLOCKED_ENV_CLI_MISMATCH,
                "CLI program id must match approval env when both are supplied",
            )
        )
    elif program_id is not None:
        resolved_program = program_id.strip()

    if program_id is not None and _program_has_multi_select(program_id):
        issues.append(
            _issue_message(
                BLOCKED_MULTI_PROGRAM_APPROVAL,
                "exactly one program per run; multi-program CLI values are forbidden",
            )
        )

    return resolved_date, resolved_program, issues


def build_opt_in_prompt_source(
    *,
    lock_path: str | Path,
    program_id: str,
    wardrobe_date_kst: str,
) -> dict:
    """Build opt-in wardrobe prompt source for one approved program/date."""
    integration = build_keysuri_weather_binding_integration_report(str(lock_path))
    contexts = integration.get("visual_contexts") or {}
    if program_id not in contexts:
        raise ValueError(f"lock fixture missing visual context for {program_id!r}")

    ctx = deepcopy(contexts[program_id])
    ctx["weather_date"] = wardrobe_date_kst
    contract = build_keysuri_weather_visual_prompt_contract(
        program_id,
        ctx,
        use_daily_wardrobe_prompt_snippet=True,
    )
    daily = contract.get("daily_wardrobe") or {}
    return {
        "source": "keysuri_manual_opt_in_wardrobe",
        "program_id": program_id,
        "positive_prompt": str(contract.get("positive_prompt") or ""),
        "negative_prompt": str(contract.get("negative_prompt") or ""),
        "wardrobe_date_kst": wardrobe_date_kst,
        "wardrobe_profile_id": daily.get("wardrobe_profile_id"),
        "daily_wardrobe_seed": daily.get("daily_wardrobe_seed"),
        "wardrobe_prompt_injected": True,
    }


def build_audit_text(result: ManualOptInCanaryRunResult) -> str:
    lines = [
        "KEYSURI R5B-II Manual Opt-In Canary Runner Audit",
        "",
        f"approval present: {'true' if result.approval_present else 'false'}",
        f"target date: {result.wardrobe_date_kst or '(none)'}",
        f"program id: {result.program_id or '(none)'}",
        f"expected wardrobe profile id: {result.expected_wardrobe_profile_id or '(none)'}",
        f"expected daily wardrobe seed: {result.expected_daily_wardrobe_seed or '(none)'}",
        f"preflight status: {result.preflight_status or '(none)'}",
        f"wardrobe clause: {result.wardrobe_clause or '(none)'}",
        f"dry-run/mock canary would proceed: {'true' if result.dry_run_would_proceed else 'false'}",
        f"runner status: {result.runner_status}",
        "",
        "issues:",
    ]
    if result.issues:
        lines.extend(f"  - {item}" for item in result.issues)
    else:
        lines.append("  (none)")
    lines.extend(
        [
            "",
            "No image API was called in R5B-II implementation mode.",
            "This runner does not authorize Scheduler, production wiring, automatic retry, or batch generation.",
        ]
    )
    return "\n".join(lines)


def _finalize_result(result: ManualOptInCanaryRunResult) -> ManualOptInCanaryRunResult:
    return replace(result, audit_text=build_audit_text(result))


def _blocked_result(
    runner_status: str,
    issues: List[str],
    *,
    approval_present: bool = False,
    approval: ManualCanaryApproval | None = None,
    preflight_result: ManualCanaryPreflightResult | None = None,
) -> ManualOptInCanaryRunResult:
    result = ManualOptInCanaryRunResult(
        runner_status=runner_status,
        approval_present=approval_present,
        wardrobe_date_kst=approval.wardrobe_date_kst if approval else None,
        program_id=approval.program_id if approval else None,
        expected_wardrobe_profile_id=approval.expected_wardrobe_profile_id if approval else None,
        expected_daily_wardrobe_seed=approval.expected_daily_wardrobe_seed if approval else None,
        preflight_status=preflight_result.status if preflight_result else None,
        wardrobe_clause=preflight_result.wardrobe_clause if preflight_result else None,
        dry_run_would_proceed=False,
        preflight_result=preflight_result,
        canary_report=None,
        issues=tuple(issues),
        audit_text="",
    )
    return _finalize_result(result)


def run_keysuri_manual_opt_in_canary(
    *,
    wardrobe_date_kst: str | None = None,
    program_id: str | None = None,
    reference_asset: str | None = None,
    check_preflight_only: bool = False,
    dry_run: bool = False,
    lock_path: str | Path | None = None,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    environ: dict[str, str] | None = None,
    _generate_image_fn: Callable[..., Path] | None = None,
    _allow_mock_generate_for_tests: bool = False,
) -> ManualOptInCanaryRunResult:
    """Run manual opt-in canary path gated by R5B-I preflight (dry-run/mock only by default)."""
    resolved_lock = Path(lock_path) if lock_path is not None else _DEFAULT_LOCK
    approval, parse_issues = parse_manual_canary_approval_from_env(environ=environ)
    if parse_issues:
        status = BLOCKED_NO_WARDROBE_APPROVAL
        if any(BLOCKED_INCOMPLETE_WARDROBE_APPROVAL in item for item in parse_issues):
            status = BLOCKED_INCOMPLETE_WARDROBE_APPROVAL
        elif any(BLOCKED_MULTI_PROGRAM_APPROVAL in item for item in parse_issues):
            status = BLOCKED_MULTI_PROGRAM_APPROVAL
        return _blocked_result(status, parse_issues)

    assert approval is not None
    resolved_date, resolved_program, mismatch_issues = _resolve_cli_env_values(
        approval,
        wardrobe_date_kst,
        program_id,
    )
    if mismatch_issues:
        return _blocked_result(BLOCKED_ENV_CLI_MISMATCH, mismatch_issues, approval_present=True, approval=approval)

    preflight = run_keysuri_manual_canary_preflight(
        wardrobe_date_kst=resolved_date,
        program_id=resolved_program,
        approval=approval,
        lock_path=resolved_lock,
    )
    if preflight.status != PREFLIGHT_PASS_FOR_ONE_MANUAL_CALL:
        issues = [_issue_message(BLOCKED_PREFLIGHT_FAILED, f"preflight status is {preflight.status}")]
        issues.extend(f"[{issue.code}] {issue.message}" for issue in preflight.issues)
        return _blocked_result(
            BLOCKED_PREFLIGHT_FAILED,
            issues,
            approval_present=True,
            approval=approval,
            preflight_result=preflight,
        )

    if check_preflight_only:
        result = ManualOptInCanaryRunResult(
            runner_status=PREFLIGHT_ONLY_PASS,
            approval_present=True,
            wardrobe_date_kst=resolved_date,
            program_id=resolved_program,
            expected_wardrobe_profile_id=approval.expected_wardrobe_profile_id,
            expected_daily_wardrobe_seed=approval.expected_daily_wardrobe_seed,
            preflight_status=preflight.status,
            wardrobe_clause=preflight.wardrobe_clause,
            dry_run_would_proceed=False,
            preflight_result=preflight,
            canary_report=None,
            issues=(),
            audit_text="",
        )
        return _finalize_result(result)

    if not dry_run and not _allow_mock_generate_for_tests:
        return _blocked_result(
            LIVE_CALL_NOT_ENABLED_IN_R5B_II,
            [
                _issue_message(
                    LIVE_CALL_NOT_ENABLED_IN_R5B_II,
                    "live image call is not enabled in R5B-II; use --dry-run or --check-preflight-only",
                )
            ],
            approval_present=True,
            approval=approval,
            preflight_result=preflight,
        )

    prompt_source = build_opt_in_prompt_source(
        lock_path=resolved_lock,
        program_id=resolved_program,
        wardrobe_date_kst=resolved_date,
    )

    use_mock_generate = (
        _allow_mock_generate_for_tests
        and _generate_image_fn is not None
        and not dry_run
    )
    canary_dry_run = dry_run and not use_mock_generate

    canary_report = run_keysuri_image_api_canary(
        program_id=resolved_program,
        manual_approval=True,
        dry_run=canary_dry_run,
        reference_asset=reference_asset,
        output_dir=output_dir,
        lock_path=str(resolved_lock),
        prompt_source_override=prompt_source,
        _generate_image_fn=_generate_image_fn if use_mock_generate else None,
    )

    if canary_dry_run:
        runner_status = DRY_RUN_READY if canary_report.get("canary_status") == "dry_run_ready" else BLOCKED_PREFLIGHT_FAILED
    else:
        runner_status = str(canary_report.get("canary_status") or MOCK_CALLED_ONCE)

    dry_run_would_proceed = canary_dry_run and canary_report.get("canary_status") == "dry_run_ready"

    result = ManualOptInCanaryRunResult(
        runner_status=runner_status,
        approval_present=True,
        wardrobe_date_kst=resolved_date,
        program_id=resolved_program,
        expected_wardrobe_profile_id=approval.expected_wardrobe_profile_id,
        expected_daily_wardrobe_seed=approval.expected_daily_wardrobe_seed,
        preflight_status=preflight.status,
        wardrobe_clause=preflight.wardrobe_clause,
        dry_run_would_proceed=dry_run_would_proceed,
        preflight_result=preflight,
        canary_report=canary_report,
        issues=(),
        audit_text="",
    )
    return _finalize_result(result)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Kee-Suri manual opt-in wardrobe canary runner (R5B-II dry-run/preflight only).",
    )
    parser.add_argument("--check-preflight-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--wardrobe-date-kst", default=None)
    parser.add_argument("--program-id", default=None)
    parser.add_argument("--reference-asset", default=None)
    args = parser.parse_args(argv)

    result = run_keysuri_manual_opt_in_canary(
        wardrobe_date_kst=args.wardrobe_date_kst,
        program_id=args.program_id,
        reference_asset=args.reference_asset,
        check_preflight_only=args.check_preflight_only,
        dry_run=args.dry_run,
    )
    print(result.audit_text)
    if result.runner_status in (PREFLIGHT_ONLY_PASS, DRY_RUN_READY, MOCK_CALLED_ONCE, "called_once", "dry_run_ready"):
        return 0
    if result.canary_report and result.canary_report.get("canary_status") == "dry_run_ready":
        return 0
    return 1
