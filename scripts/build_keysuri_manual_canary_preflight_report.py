#!/usr/bin/env python3
"""Build Kee-Suri R5B-I manual canary preflight report (offline, no image API)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from keysuri_manual_canary_preflight import (  # noqa: E402
    FAIL,
    ManualCanaryPreflightResult,
    run_keysuri_manual_canary_preflight,
)

DEFAULT_WARDROBE_DATE_KST = "2026-06-04"
DEFAULT_PROGRAM_ID = "keysuri_global_tech"
_REPORT_TITLE = "KEYSURI R5B-I Manual Canary Preflight Report"


def _format_bool(value: bool | None) -> str:
    if value is None:
        return "not checked"
    return "true" if value else "false"


def _format_issues(result: ManualCanaryPreflightResult, field: str) -> str:
    items = result.issues if field == "issues" else result.warnings
    if not items:
        return "  (none)"
    return "\n".join(f"  - [{item.code}] {item.message} ({item.path})" for item in items)


def build_report_text(result: ManualCanaryPreflightResult) -> str:
    """Render a human-readable offline preflight report."""
    lines = [
        _REPORT_TITLE,
        "",
        f"target date: {result.target_date}",
        f"program id: {result.program_id}",
        f"status: {result.status}",
        f"wardrobe_profile_id: {result.wardrobe_profile_id or '(none)'}",
        f"daily_wardrobe_seed: {result.daily_wardrobe_seed or '(none)'}",
        f"wardrobe_clause: {result.wardrobe_clause or '(none)'}",
        f"default_prompt_unchanged: {_format_bool(result.default_prompt_unchanged)}",
        f"opt_in_prompt_changed: {_format_bool(result.opt_in_prompt_changed)}",
        f"production_flags_false: {_format_bool(result.production_flags_false)}",
        f"manual_approval_valid: {_format_bool(result.manual_approval_valid)}",
        f"review_required: {_format_bool(result.review_required)}",
        f"new_visual_qa_required: {_format_bool(result.new_visual_qa_required)}",
        f"baseline_reference_path: {result.baseline_reference_path or '(none)'}",
        f"baseline_file_exists: {_format_bool(result.baseline_file_exists)}",
        "",
        "issues:",
        _format_issues(result, "issues"),
        "",
        "warnings:",
        _format_issues(result, "warnings"),
        "",
        "No image API was called.",
        "This report does not authorize Scheduler, production wiring, automatic retry, or batch generation.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Kee-Suri R5B-I manual canary preflight report (offline, no approval by default).",
    )
    parser.add_argument(
        "--wardrobe-date-kst",
        default=DEFAULT_WARDROBE_DATE_KST,
        help=f"Target KST wardrobe date (default: {DEFAULT_WARDROBE_DATE_KST}).",
    )
    parser.add_argument(
        "--program-id",
        default=DEFAULT_PROGRAM_ID,
        help=f"Kee-Suri program id (default: {DEFAULT_PROGRAM_ID}).",
    )
    parser.add_argument(
        "--check-baseline-exists",
        action="store_true",
        help="Check whether the local baseline reference file exists (warning only if missing).",
    )
    args = parser.parse_args(argv)

    result = run_keysuri_manual_canary_preflight(
        wardrobe_date_kst=args.wardrobe_date_kst,
        program_id=args.program_id,
        approval=None,
        check_baseline_exists=args.check_baseline_exists,
    )
    print(build_report_text(result))
    return 1 if result.status == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
