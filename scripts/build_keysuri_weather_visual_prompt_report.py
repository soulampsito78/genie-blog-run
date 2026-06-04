#!/usr/bin/env python3
"""Build Kee-Suri weather visual prompt integration report (offline, no image API)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from keysuri_weather_visual_prompt_integration import (  # noqa: E402
    build_keysuri_weather_visual_prompt_report_from_canary_lock,
)

_LOCK_FIXTURE = _REPO / "ops" / "feeds" / "genie_weather_live_canary_lock_2026-06-04.sample.json"
_OUT_DIR = _REPO / "output" / "keysuri_preview" / "weather_canary"
_OUT_REPORT = _OUT_DIR / "keysuri_weather_visual_prompt_report.json"


def main() -> int:
    report = build_keysuri_weather_visual_prompt_report_from_canary_lock(str(_LOCK_FIXTURE))
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    _OUT_REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    cli = {
        "report_status": report.get("report_status"),
        "report_type": report.get("report_type"),
        "runtime_binding_status": report.get("runtime_binding_status"),
        "weather_context_source": report.get("weather_context_source"),
        "prompt_contracts_built": sorted((report.get("prompt_contracts") or {}).keys()),
        "ready_for_image_api_call": report.get("ready_for_image_api_call"),
        "ready_for_scheduler": report.get("ready_for_scheduler"),
        "ready_for_production_auto_call": report.get("ready_for_production_auto_call"),
        "side_effects": report.get("side_effects"),
        "issue_count": len(report.get("issues") or []),
        "output_file": str(_OUT_REPORT.relative_to(_REPO)),
    }
    print(json.dumps(cli, ensure_ascii=False, indent=2))
    return 0 if report.get("report_status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
