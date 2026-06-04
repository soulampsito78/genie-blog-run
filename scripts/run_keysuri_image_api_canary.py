#!/usr/bin/env python3
"""Manual Kee-Suri image API controlled canary (default blocked — no API call without approval)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from keysuri_image_api_canary_client import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    DEFAULT_OUTPUT_REPORT,
    run_keysuri_image_api_canary,
    sanitize_keysuri_image_api_canary_report,
)
from keysuri_image_provider_contract import (  # noqa: E402
    get_keysuri_image_provider_env_summary_from_env,
    validate_keysuri_image_output_path,
)

_OUT_REPORT = _REPO / DEFAULT_OUTPUT_REPORT


def _cli_summary(report: dict) -> dict:
    side = report.get("side_effects") or {}
    return {
        "report_type": report.get("report_type"),
        "canary_status": report.get("canary_status"),
        "provider": report.get("provider"),
        "program_id": report.get("program_id"),
        "request_count": report.get("request_count"),
        "manual_approval_present": report.get("manual_approval_present"),
        "dry_run": report.get("dry_run"),
        "image_api_call_status": report.get("image_api_call_status"),
        "image_generation_status": report.get("image_generation_status"),
        "output_image_path": report.get("output_image_path"),
        "secrets_exposed": report.get("secrets_exposed"),
        "raw_provider_payload_saved": report.get("raw_provider_payload_saved"),
        "side_effects": side,
        "issue_count": len(report.get("issues") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Kee-Suri manual image API canary (default blocked).")
    parser.add_argument("--check-env", action="store_true", help="Print env summary only; no API call.")
    parser.add_argument("--dry-run", action="store_true", help="Validate readiness; no API call.")
    parser.add_argument(
        "--program",
        choices=("keysuri_global_tech", "keysuri_korea_tech"),
        help="Select exactly one Kee-Suri program for canary.",
    )
    parser.add_argument(
        "--manual-approval",
        action="store_true",
        help="Explicit manual approval (required for any future live call).",
    )
    parser.add_argument(
        "--reference-asset",
        default=None,
        help="Reference asset selector: 01, 02, or assets/keysuri/reference/... path.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for generated images (must be under output/keysuri_preview/image_canary/).",
    )
    args = parser.parse_args()

    if args.check_env:
        summary = get_keysuri_image_provider_env_summary_from_env()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    path_issues = validate_keysuri_image_output_path(args.output_dir)
    if path_issues:
        print(
            json.dumps(
                {
                    "error": "invalid_output_dir",
                    "issues": path_issues,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    report = run_keysuri_image_api_canary(
        program_id=args.program,
        manual_approval=args.manual_approval,
        dry_run=args.dry_run,
        reference_asset=args.reference_asset,
        output_dir=args.output_dir,
    )
    safe = sanitize_keysuri_image_api_canary_report(report)
    _OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    _OUT_REPORT.write_text(
        json.dumps(safe, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = _cli_summary(safe)
    summary["report_file"] = str(_OUT_REPORT.relative_to(_REPO))
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    blocked_ok = safe.get("canary_status", "").startswith("blocked") or safe.get("canary_status") == "dry_run_ready"
    if blocked_ok and safe.get("request_count") == 0:
        return 0
    if safe.get("canary_status") == "called_once" and safe.get("request_count") == 1:
        return 0
    if safe.get("canary_status") == "api_error":
        return 1
    return 0 if not safe.get("issues") else 1


if __name__ == "__main__":
    raise SystemExit(main())
