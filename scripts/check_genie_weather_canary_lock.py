#!/usr/bin/env python3
"""Validate sanitized weather canary lock and emit runtime readiness summary (offline)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from genie_weather_runtime_policy import (  # noqa: E402
    build_genie_weather_runtime_readiness_summary,
    load_genie_weather_canary_lock_fixture,
    validate_genie_weather_canary_lock,
)

_LOCK_FIXTURE = _REPO / "ops" / "feeds" / "genie_weather_live_canary_lock_2026-06-04.sample.json"
_OUT_DIR = _REPO / "output" / "keysuri_preview" / "weather_canary"
_OUT_REPORT = _OUT_DIR / "weather_runtime_readiness_summary.json"


def main() -> int:
    lock = load_genie_weather_canary_lock_fixture(str(_LOCK_FIXTURE))
    issues = validate_genie_weather_canary_lock(lock)
    summary = build_genie_weather_runtime_readiness_summary(lock)

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "ok": len(issues) == 0,
        "lock_validation_issue_count": len(issues),
        "lock_validation_issues": issues,
        "readiness_summary": summary,
    }
    _OUT_REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    cli = {
        "weather_runtime_status": summary.get("weather_runtime_status"),
        "canonical_provider": summary.get("canonical_provider"),
        "weather_canary_passed": summary.get("weather_canary_passed"),
        "consumer_contexts_confirmed": summary.get("consumer_contexts_confirmed"),
        "ready_for_runtime_binding_plan": summary.get("ready_for_runtime_binding_plan"),
        "ready_for_scheduler": summary.get("ready_for_scheduler"),
        "ready_for_production_auto_call": summary.get("ready_for_production_auto_call"),
        "issue_count": len(issues),
        "output_file": str(_OUT_REPORT.relative_to(_REPO)),
    }
    print(json.dumps(cli, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
