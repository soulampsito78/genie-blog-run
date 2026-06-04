#!/usr/bin/env python3
"""Build Kee-Suri weather binding integration dry-run report (offline, no live API)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from keysuri_weather_binding_integration import (  # noqa: E402
    build_keysuri_weather_binding_integration_report,
)

_LOCK_FIXTURE = _REPO / "ops" / "feeds" / "genie_weather_live_canary_lock_2026-06-04.sample.json"
_OUT_DIR = _REPO / "output" / "keysuri_preview" / "weather_canary"
_OUT_REPORT = _OUT_DIR / "keysuri_weather_binding_integration_report.json"


def main() -> int:
    report = build_keysuri_weather_binding_integration_report(str(_LOCK_FIXTURE))
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    _OUT_REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    cli = {
        "integration_status": report.get("integration_status"),
        "integration_type": report.get("integration_type"),
        "runtime_binding_status": report.get("runtime_binding_status"),
        "weather_context_source": report.get("weather_context_source"),
        "visual_contexts_built": sorted((report.get("visual_contexts") or {}).keys()),
        "ready_for_scheduler": report.get("ready_for_scheduler"),
        "ready_for_production_auto_call": report.get("ready_for_production_auto_call"),
        "side_effects": report.get("side_effects"),
        "issue_count": len(report.get("issues") or []),
        "output_file": str(_OUT_REPORT.relative_to(_REPO)),
    }
    print(json.dumps(cli, ensure_ascii=False, indent=2))
    return 0 if report.get("integration_status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
