#!/usr/bin/env python3
"""Offline Kee-Suri full-pipeline dry-run (no Gemini, no email, no web)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from keysuri_offline_dry_run import (  # noqa: E402
    dry_run_report_for_json,
    run_keysuri_global_offline_dry_run,
    run_keysuri_korea_offline_dry_run,
)

_OUT_DIR = _REPO / "output" / "keysuri_preview"

_JOBS = (
    ("keysuri_global", run_keysuri_global_offline_dry_run),
    ("keysuri_korea", run_keysuri_korea_offline_dry_run),
)


def main() -> int:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []

    for slug, runner in _JOBS:
        result = runner()
        report_path = _OUT_DIR / f"{slug}_offline_dry_run_report.json"
        preview_path = _OUT_DIR / f"{slug}_offline_dry_run_preview.html"

        report_path.write_text(
            json.dumps(dry_run_report_for_json(result), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        html = result.get("rendered_html")
        if isinstance(html, str) and html.strip():
            preview_path.write_text(html, encoding="utf-8")
        else:
            preview_path.write_text(
                "<!DOCTYPE html><html><body><p>No preview rendered.</p></body></html>\n",
                encoding="utf-8",
            )

        side = result.get("runtime_side_effects") or {}
        summaries.append(
            {
                "program_id": result.get("program_id"),
                "news_scope": result.get("news_scope"),
                "dry_run_status": result.get("dry_run_status"),
                "source_gate_result": result.get("source_gate_result"),
                "prompt_status": result.get("prompt_status"),
                "parse_status": result.get("parse_status"),
                "top_5_count": result.get("top_5_count"),
                "generated_status": result.get("generated_status"),
                "preview_file": str(preview_path.relative_to(_REPO)),
                "report_file": str(report_path.relative_to(_REPO)),
                "identity_label": result.get("identity_label"),
                "called_gemini": side.get("called_gemini", False),
                "fetched_live_news": side.get("fetched_live_news", False),
                "sent_email": side.get("sent_email", False),
                "published_naver": side.get("published_naver", False),
                "changed_scheduler": side.get("changed_scheduler", False),
            }
        )

    print(json.dumps({"ok": True, "dry_runs": summaries}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
