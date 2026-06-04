#!/usr/bin/env python3
"""Offline Kee-Suri weather-aware visual image prompt sample builder."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from keysuri_renderer import load_keysuri_prompt_input_fixture  # noqa: E402
from keysuri_visual_context import (  # noqa: E402
    IDENTITY_LABEL,
    build_keysuri_image_prompt,
    load_keysuri_weather_context_fixture,
)

_FEEDS = _REPO / "ops" / "feeds"
_OUT_DIR = _REPO / "output" / "keysuri_preview" / "visual_prompts"

_WEATHER_FIXTURES = {
    "sunny": "keysuri_weather_seoul_sunny.sample.json",
    "cloudy": "keysuri_weather_seoul_cloudy.sample.json",
    "rainy": "keysuri_weather_seoul_rainy.sample.json",
    "fine_dust": "keysuri_weather_seoul_fine_dust.sample.json",
    "cold": "keysuri_weather_seoul_cold.sample.json",
}

_PROGRAMS = (
    ("keysuri_global_tech", "global", "keysuri_global_prompt_input.sample.json"),
    ("keysuri_korea_tech", "korea", "keysuri_korea_prompt_input.sample.json"),
)


def main() -> int:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []

    for program_id, slug, prompt_fixture in _PROGRAMS:
        prompt_input = load_keysuri_prompt_input_fixture(str(_FEEDS / prompt_fixture))
        for condition, weather_file in _WEATHER_FIXTURES.items():
            weather = load_keysuri_weather_context_fixture(str(_FEEDS / weather_file))
            image_prompt = build_keysuri_image_prompt(program_id, weather, prompt_input)

            base = f"keysuri_{slug}_{condition}_image_prompt"
            json_path = _OUT_DIR / f"{base}.json"
            txt_path = _OUT_DIR / f"{base}.txt"

            json_path.write_text(
                json.dumps(image_prompt, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            txt_path.write_text(image_prompt["image_prompt_text"] + "\n", encoding="utf-8")

            summaries.append(
                {
                    "program_id": program_id,
                    "weather_condition": condition,
                    "schedule_time_kst": image_prompt.get("schedule_time_kst"),
                    "visual_time_band": image_prompt.get("visual_time_band"),
                    "output_json_file": str(json_path.relative_to(_REPO)),
                    "output_text_file": str(txt_path.relative_to(_REPO)),
                    "identity_label": IDENTITY_LABEL,
                    "source_mode": image_prompt.get("source_mode"),
                }
            )

    print(json.dumps({"ok": True, "samples": summaries}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
