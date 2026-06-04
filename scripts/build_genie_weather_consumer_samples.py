#!/usr/bin/env python3
"""Offline GENIE weather consumer context samples (no Today_Geenee runtime, no live API)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from genie_weather_runtime_adapter import (  # noqa: E402
    build_genie_weather_consumer_context,
    load_genie_runtime_weather_payload_fixture,
    normalize_genie_runtime_weather_payload,
)

_FEEDS = _REPO / "ops" / "feeds"
_OUT_DIR = _REPO / "output" / "keysuri_preview" / "weather_consumers"

_PAYLOAD_FIXTURES = (
    ("clear", "genie_weather_runtime_seoul_clear.sample.json"),
    ("cloudy", "genie_weather_runtime_seoul_cloudy.sample.json"),
    ("rain", "genie_weather_runtime_seoul_rain.sample.json"),
    ("fine_dust", "genie_weather_runtime_seoul_fine_dust.sample.json"),
    ("cold", "genie_weather_runtime_seoul_cold.sample.json"),
    ("snow", "genie_weather_runtime_seoul_snow.sample.json"),
)

_CONSUMERS = ("today_geenee", "keysuri_global_tech", "keysuri_korea_tech")


def main() -> int:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []

    for weather_slug, payload_file in _PAYLOAD_FIXTURES:
        payload = load_genie_runtime_weather_payload_fixture(str(_FEEDS / payload_file))
        weather_context = normalize_genie_runtime_weather_payload(payload)
        for consumer_id in _CONSUMERS:
            ctx = build_genie_weather_consumer_context(consumer_id, weather_context)
            out_name = f"{consumer_id}_{weather_slug}_weather_consumer.json"
            out_path = _OUT_DIR / out_name
            out_path.write_text(
                json.dumps(ctx, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            summaries.append(
                {
                    "consumer_id": consumer_id,
                    "weather_slug": weather_slug,
                    "weather_condition": weather_context.get("weather_condition"),
                    "schedule_time_kst": ctx.get("schedule_time_kst"),
                    "output_file": str(out_path.relative_to(_REPO)),
                    "source_mode": weather_context.get("source_mode"),
                }
            )

    print(json.dumps({"ok": True, "samples": summaries}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
