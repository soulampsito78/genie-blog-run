#!/usr/bin/env python3
"""
Today_Geenee-only local dry-run helper for image prompt variation assembly.

Stdout-only: builds and prints prompt variation data. Does not call Vertex, Gemini,
Imagen, or any image API. Does not write image files. Does not read, open, or copy
files under static/email/** or output/**. Does not trigger the scheduler or send email.

The reference image path passed to the prompt log is metadata only (not opened or copied).
/tmp/*.jpg paths in the log are illustrative metadata only and are not written.

Run: python3 scripts/dry_run_today_genie_image_prompts.py
"""
from __future__ import annotations

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from image_exec_suffixes import (  # noqa: E402
    today_genie_image_prompt_log,
    today_genie_image_variation_bundle,
)


def main() -> None:
    print("DRY RUN — prompts only; no image API, no file writes, no email.")
    seed = "dry-proof-20260429"
    ri = {
        "target_date": "2026-04-10",
        "controlled_test_mode": True,
        "image_weather_context": {
            "source": "fallback",
            "weather_band": "mild_unknown",
            "wardrobe_hint": "blouse or light knit",
        },
    }
    mood = "[BRIEFING_MOOD_STATE=mixed_cautious | MOOD_BASIS=dry proof]\n\n"
    p_studio = (
        "A premium Korean female anchor for morning briefing; reference continuity; "
        "macro anchor: CPI; market: Nasdaq tone."
    )
    p_out = (
        "Same identity woman on a Seoul weekday morning; macro anchor: inflation narrative; "
        "weather-appropriate layers."
    )
    ref = os.path.join(_REPO, "static/email/GENIE_REF_today_genie_master_v1.jpg")
    log = today_genie_image_prompt_log(
        variation_seed=seed,
        runtime_input=ri,
        mood_prefix=mood,
        image_prompt_studio=p_studio,
        image_prompt_outdoor=p_out,
        reference_image_path=ref,
        top_output_path="/tmp/top_dry.jpg",
        bottom_output_path="/tmp/bottom_dry.jpg",
    )
    b = today_genie_image_variation_bundle(seed)
    print("=== variation bundle")
    for k in sorted(b.keys()):
        print(f"{k}: {b[k]}")
    print("\n=== wardrobe difference (top vs bottom)")
    print("TOP:", b["top_wardrobe_family"])
    print("BOTTOM:", b["bottom_wardrobe_family"])
    print("\n=== pose difference")
    print("TOP:", b["top_pose_action"][:120], "…")
    print("BOTTOM:", b["bottom_pose_action"][:120], "…")
    print("\n=== scene difference")
    print("TOP:", b["top_scene"][:120], "…")
    print("BOTTOM:", b["bottom_scene"][:120], "…")
    print("\n=== camera difference")
    print("TOP:", b["top_camera_framing"])
    print("BOTTOM:", b["bottom_camera_framing"])
    print("\n=== sample final top prompt (first 900 chars)\n")
    print(log["top_final_composed_prompt"][:900] + "\n…")
    print("\n=== sample final bottom prompt (first 900 chars)\n")
    print(log["bottom_final_composed_prompt"][:900] + "\n…")
    print("\n=== prompt hashes", log["top_prompt_hash"][:16], log["bottom_prompt_hash"][:16])


if __name__ == "__main__":
    main()
