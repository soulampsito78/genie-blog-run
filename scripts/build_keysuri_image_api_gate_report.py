#!/usr/bin/env python3
"""Build Kee-Suri image API controlled dry-run gate report (offline, no image API)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from keysuri_image_api_gate import (  # noqa: E402
    build_keysuri_image_api_gate_report_from_canary_lock,
)

_LOCK_FIXTURE = _REPO / "ops" / "feeds" / "genie_weather_live_canary_lock_2026-06-04.sample.json"
_OUT_DIR = _REPO / "output" / "keysuri_preview" / "weather_canary"
_OUT_REPORT = _OUT_DIR / "keysuri_image_api_gate_report.json"


def main() -> int:
    report = build_keysuri_image_api_gate_report_from_canary_lock(
        str(_LOCK_FIXTURE),
        manual_approval=False,
    )
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    _OUT_REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    cli = {
        "report_status": report.get("report_status"),
        "report_type": report.get("report_type"),
        "runtime_binding_status": report.get("runtime_binding_status"),
        "manual_approval_required": report.get("manual_approval_required"),
        "manual_approval_present": report.get("manual_approval_present"),
        "ready_for_image_api_call": report.get("ready_for_image_api_call"),
        "image_api_call_allowed": report.get("image_api_call_allowed"),
        "image_api_call_status": report.get("image_api_call_status"),
        "gate_entries_built": sorted((report.get("gate_entries") or {}).keys()),
        "side_effects": report.get("side_effects"),
        "issue_count": len(report.get("issues") or []),
        "output_file": str(_OUT_REPORT.relative_to(_REPO)),
    }
    print(json.dumps(cli, ensure_ascii=False, indent=2))
    return 0 if report.get("report_status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
