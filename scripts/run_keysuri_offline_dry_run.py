#!/usr/bin/env python3
"""Offline Kee-Suri full-pipeline dry-run (no Gemini, no email, no web)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from genie_weather_runtime_adapter import (  # noqa: E402
    load_genie_runtime_weather_payload_fixture,
    normalize_genie_runtime_weather_payload,
)
from keysuri_offline_dry_run import (  # noqa: E402
    dry_run_report_for_json,
    load_json_file,
    load_text_file,
    run_keysuri_offline_dry_run,
)

_FEEDS = _REPO / "ops" / "feeds"
_OUT_DIR = _REPO / "output" / "keysuri_preview"

_STANDARD_JOBS = (
    {
        "slug": "keysuri_global",
        "program_id": "keysuri_global_tech",
        "source_pack": "keysuri_global_sources.sample.json",
        "raw_response": "keysuri_global_raw_response.valid.sample.txt",
        "weather_payload": None,
        "report_name": "keysuri_global_offline_dry_run_report.json",
        "preview_name": "keysuri_global_offline_dry_run_preview.html",
    },
    {
        "slug": "keysuri_korea",
        "program_id": "keysuri_korea_tech",
        "source_pack": "keysuri_korea_sources.sample.json",
        "raw_response": "keysuri_korea_raw_response.valid.sample.txt",
        "weather_payload": None,
        "report_name": "keysuri_korea_offline_dry_run_report.json",
        "preview_name": "keysuri_korea_offline_dry_run_preview.html",
    },
)

_WEATHER_JOBS = (
    {
        "slug": "keysuri_global_weather_visual",
        "program_id": "keysuri_global_tech",
        "source_pack": "keysuri_global_sources.sample.json",
        "raw_response": "keysuri_global_raw_response.valid.sample.txt",
        "weather_payload": "genie_weather_runtime_seoul_cloudy.sample.json",
        "report_name": "keysuri_global_weather_visual_dry_run_report.json",
        "preview_name": "keysuri_global_weather_visual_dry_run_preview.html",
    },
    {
        "slug": "keysuri_korea_weather_visual",
        "program_id": "keysuri_korea_tech",
        "source_pack": "keysuri_korea_sources.sample.json",
        "raw_response": "keysuri_korea_raw_response.valid.sample.txt",
        "weather_payload": "genie_weather_runtime_seoul_rain.sample.json",
        "report_name": "keysuri_korea_weather_visual_dry_run_report.json",
        "preview_name": "keysuri_korea_weather_visual_dry_run_preview.html",
    },
)


def _run_job(job: dict) -> dict:
    pack = load_json_file(str(_FEEDS / job["source_pack"]))
    raw = load_text_file(str(_FEEDS / job["raw_response"]))
    weather_context = None
    if job.get("weather_payload"):
        payload = load_genie_runtime_weather_payload_fixture(
            str(_FEEDS / job["weather_payload"])
        )
        weather_context = normalize_genie_runtime_weather_payload(payload)
    return run_keysuri_offline_dry_run(
        job["program_id"],
        pack,
        raw,
        weather_context=weather_context,
    )


def _summary_from_result(job: dict, result: dict, report_path: Path, preview_path: Path) -> dict:
    side = result.get("runtime_side_effects") or {}
    vsum = result.get("visual_prompt_summary") or {}
    return {
        "program_id": result.get("program_id"),
        "news_scope": result.get("news_scope"),
        "dry_run_status": result.get("dry_run_status"),
        "weather_context_status": result.get("weather_context_status"),
        "visual_prompt_status": result.get("visual_prompt_status"),
        "weather_condition": vsum.get("weather_condition"),
        "schedule_time_kst": vsum.get("schedule_time_kst"),
        "visual_time_band": vsum.get("visual_time_band"),
        "parse_status": result.get("parse_status"),
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


def main() -> int:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []

    for job in list(_STANDARD_JOBS) + list(_WEATHER_JOBS):
        result = _run_job(job)
        report_path = _OUT_DIR / job["report_name"]
        preview_path = _OUT_DIR / job["preview_name"]

        report_path.write_text(
            json.dumps(dry_run_report_for_json(result), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        html = result.get("rendered_html")
        visual_preview = result.get("image_prompt_text_preview") or ""
        if isinstance(html, str) and html.strip():
            body = html
        else:
            body = "<!DOCTYPE html><html><body><p>No briefing preview rendered.</p></body></html>"
        if visual_preview.strip():
            escaped = (
                visual_preview.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            body += (
                "\n<hr/>\n<section><h2>Weather visual prompt preview (offline)</h2>"
                f"<pre>{escaped}</pre></section>"
            )
        preview_path.write_text(body + "\n", encoding="utf-8")

        summaries.append(_summary_from_result(job, result, report_path, preview_path))

    print(json.dumps({"ok": True, "dry_runs": summaries}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
