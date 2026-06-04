#!/usr/bin/env python3
"""Offline Kee-Suri owner-review HTML preview generator (no Gemini, no email, no web)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from keysuri_generated_briefing import load_keysuri_generated_briefing_fixture  # noqa: E402
from keysuri_renderer import (  # noqa: E402
    GENERATION_PENDING_LABEL,
    IDENTITY_TITLE,
    load_keysuri_prompt_input_fixture,
    render_keysuri_owner_review_html,
)

_FEEDS = _REPO / "ops" / "feeds"
_OUT_DIR = _REPO / "output" / "keysuri_preview"

_JOBS = (
    {
        "prompt_file": "keysuri_global_prompt_input.sample.json",
        "generated_file": None,
        "output_file": "keysuri_global_owner_review_preview.html",
    },
    {
        "prompt_file": "keysuri_korea_prompt_input.sample.json",
        "generated_file": None,
        "output_file": "keysuri_korea_owner_review_preview.html",
    },
    {
        "prompt_file": "keysuri_global_prompt_input.sample.json",
        "generated_file": "keysuri_global_generated_briefing.sample.json",
        "output_file": "keysuri_global_generated_owner_review_preview.html",
    },
    {
        "prompt_file": "keysuri_korea_prompt_input.sample.json",
        "generated_file": "keysuri_korea_generated_briefing.sample.json",
        "output_file": "keysuri_korea_generated_owner_review_preview.html",
    },
)


def _top5_count(prompt_input: dict) -> int:
    top = prompt_input.get("top_5_news")
    if isinstance(top, dict) and isinstance(top.get("items"), list):
        return len(top["items"])
    sel = prompt_input.get("top_5_selection_result")
    if isinstance(sel, dict):
        nested = sel.get("top_5_news")
        if isinstance(nested, dict) and isinstance(nested.get("items"), list):
            return len(nested["items"])
    return 0


def main() -> int:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []

    for job in _JOBS:
        in_path = _FEEDS / job["prompt_file"]
        out_path = _OUT_DIR / job["output_file"]
        prompt_input = load_keysuri_prompt_input_fixture(str(in_path))

        generated_briefing = None
        generated_path = None
        if job["generated_file"]:
            generated_path = _FEEDS / job["generated_file"]
            generated_briefing = load_keysuri_generated_briefing_fixture(str(generated_path))

        html_out = render_keysuri_owner_review_html(prompt_input, generated_briefing)
        out_path.write_text(html_out, encoding="utf-8")

        summary = {
            "input_prompt_file": str(in_path.relative_to(_REPO)),
            "generated_briefing_file": (
                str(generated_path.relative_to(_REPO)) if generated_path else None
            ),
            "output_file": str(out_path.relative_to(_REPO)),
            "program_id": prompt_input.get("program_id"),
            "news_scope": prompt_input.get("news_scope"),
            "section_heading": prompt_input.get("section_heading"),
            "top_5_count": _top5_count(prompt_input),
            "prompt_status": prompt_input.get("prompt_status"),
            "generated_status": (
                generated_briefing.get("generated_status")
                if generated_briefing
                else GENERATION_PENDING_LABEL
            ),
            "operational_status": prompt_input.get("operational_status"),
            "identity_label": IDENTITY_TITLE,
        }
        summaries.append(summary)

    print(json.dumps({"ok": True, "previews": summaries}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
