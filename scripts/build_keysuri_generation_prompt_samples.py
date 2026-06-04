#!/usr/bin/env python3
"""Offline Kee-Suri generation prompt sample builder (no Gemini, no email, no web)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from keysuri_generation_prompt import (  # noqa: E402
    IDENTITY_TITLE,
    build_keysuri_generation_prompt,
    build_keysuri_generation_prompt_contract,
)
from keysuri_renderer import load_keysuri_prompt_input_fixture  # noqa: E402

_FEEDS = _REPO / "ops" / "feeds"
_OUT_DIR = _REPO / "output" / "keysuri_preview"

_JOBS = (
    ("keysuri_global_prompt_input.sample.json", "keysuri_global"),
    ("keysuri_korea_prompt_input.sample.json", "keysuri_korea"),
)


def main() -> int:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []

    for prompt_name, slug in _JOBS:
        in_path = _FEEDS / prompt_name
        prompt_input = load_keysuri_prompt_input_fixture(str(in_path))
        contract = build_keysuri_generation_prompt_contract(prompt_input)
        prompt_text = build_keysuri_generation_prompt(prompt_input)

        prompt_out = _OUT_DIR / f"{slug}_generation_prompt.txt"
        contract_out = _OUT_DIR / f"{slug}_generation_prompt_contract.json"
        prompt_out.write_text(prompt_text, encoding="utf-8")
        contract_out.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        summaries.append(
            {
                "input_file": str(in_path.relative_to(_REPO)),
                "output_prompt_file": str(prompt_out.relative_to(_REPO)),
                "output_contract_file": str(contract_out.relative_to(_REPO)),
                "program_id": prompt_input.get("program_id"),
                "news_scope": prompt_input.get("news_scope"),
                "section_heading": prompt_input.get("section_heading"),
                "allowed_source_id_count": len(contract.get("allowed_source_ids") or []),
                "identity_label": IDENTITY_TITLE,
            }
        )

    print(json.dumps({"ok": True, "samples": summaries}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
