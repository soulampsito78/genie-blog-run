#!/usr/bin/env python3
"""Manual Seoul weather API controlled canary (at most one live request per run)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from genie_weather_provider_client import (  # noqa: E402
    run_seoul_weather_controlled_canary,
    sanitize_canary_report_for_output,
)

_OUT_DIR = _REPO / "output" / "keysuri_preview" / "weather_canary"
_REPORT_PATH = _OUT_DIR / "seoul_weather_api_canary_report.json"


def _cli_summary(report: dict) -> dict:
    norm = report.get("normalized_weather_context") or {}
    consumers = report.get("consumer_contexts") or {}
    built = [k for k, v in consumers.items() if v is not None]
    return {
        "canary_status": report.get("canary_status"),
        "provider": report.get("provider"),
        "request_count": report.get("request_count"),
        "location": report.get("location"),
        "weather_condition": norm.get("weather_condition"),
        "weather_date": norm.get("weather_date"),
        "observed_or_forecast_time_kst": norm.get("observed_or_forecast_time_kst"),
        "consumer_contexts_built": built,
        "secrets_exposed": bool(report.get("secrets_exposed", False)),
        "raw_provider_payload_saved": report.get("raw_provider_payload_saved"),
        "runtime_side_effects": report.get("runtime_side_effects"),
    }


def main() -> int:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = run_seoul_weather_controlled_canary()
    safe_report = sanitize_canary_report_for_output(report)
    _REPORT_PATH.write_text(
        json.dumps(safe_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = _cli_summary(safe_report)
    summary["report_file"] = str(_REPORT_PATH.relative_to(_REPO))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
