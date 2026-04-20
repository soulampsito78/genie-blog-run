#!/usr/bin/env python3
"""
One-shot bottom JPEG for today_genie TPO path: same prompt stack as TPO scripts
(mood prefix + image_prompt_outdoor), reference GENIE_REF_today_genie_master_v1.jpg.
Writes a timestamped JPEG under output/ only (MMDD_HHMM).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_REPO = Path(__file__).resolve().parents[1]


def _local_stamp() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%m%d_%H%M")
_FEEDS = [
    ("TODAY_GENIE_OVERNIGHT_US_MARKET_JSON", "overnight_us_market.json"),
    ("TODAY_GENIE_MACRO_INDICATORS_JSON", "macro_indicators.json"),
    ("TODAY_GENIE_TOP_MACRO_ISSUES_JSON", "top_macro_issues.json"),
    ("TODAY_GENIE_TOP_MARKET_NEWS_JSON", "top_market_news.json"),
    ("TODAY_GENIE_KOREA_MARKET_SCHEDULE_JSON", "korea_market_schedule.json"),
    ("TODAY_GENIE_RISK_FACTORS_JSON", "risk_factors.json"),
]


def _load_feeds_env() -> None:
    feeds_dir = _REPO / "ops" / "feeds"
    for env_key, fname in _FEEDS:
        p = feeds_dir / fname
        if not p.is_file():
            raise FileNotFoundError(str(p))
        os.environ[env_key] = json.dumps(
            json.loads(p.read_text(encoding="utf-8")),
            ensure_ascii=False,
            separators=(",", ":"),
        )


def _mood_prefix(data: dict) -> str:
    mood = (data.get("image_briefing_mood_state") or "").strip()
    basis = (data.get("image_mood_basis") or "").strip()
    if not mood and not basis:
        return ""
    parts: list[str] = []
    if mood:
        parts.append(f"BRIEFING_MOOD_STATE={mood}")
    if basis:
        parts.append(f"MOOD_BASIS={basis}")
    return "[" + " | ".join(parts) + "]\n\n"


def main() -> int:
    os.chdir(_REPO)
    sys.path.insert(0, str(_REPO))

    ref = _REPO / "static" / "email" / "GENIE_REF_today_genie_master_v1.jpg"
    out_dir = _REPO / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _local_stamp()
    out = out_dir / f"GENIE_EMAIL_today_genie_bottom_tpo_run_{stamp}.jpg"

    if not ref.is_file():
        print(json.dumps({"error": "reference_missing", "path": str(ref)}))
        return 2

    _load_feeds_env()

    from image_exec_suffixes import today_genie_suffix_outdoor_daily
    from image_generator import generate_image_file
    from main import build_full_prompt, build_runtime_input, call_gemini, parse_model_json
    from validators import validate_today_genie

    mode = "today_genie"
    ri = build_runtime_input(mode)
    if ri.get("input_feed_status") != "full":
        print(
            json.dumps(
                {"error": "feeds_not_full", "input_feed_status": ri.get("input_feed_status")},
                ensure_ascii=False,
            )
        )
        return 3

    prompt = build_full_prompt(mode, ri)
    raw = call_gemini(prompt, mode)
    data = parse_model_json(raw, mode)
    val = validate_today_genie(data, ri)
    if val.result == "block":
        print(
            json.dumps(
                {
                    "error": "validation_block",
                    "issues": [{"code": i.code, "message": i.message} for i in val.issues[:12]],
                },
                ensure_ascii=False,
            )
        )
        return 4

    p_out = (data.get("image_prompt_outdoor") or "").strip()
    if not p_out:
        print(json.dumps({"error": "missing_image_prompt_outdoor"}))
        return 5

    prefix = _mood_prefix(data)
    image_model = os.getenv("VERTEX_IMAGE_MODEL", "gemini-2.5-flash-image")
    project_id = (os.getenv("PROJECT_ID") or "").strip() or None
    location = os.getenv("VERTEX_LOCATION", "global")

    generate_image_file(
        prompt=prefix
        + p_out
        + "\n\n"
        + today_genie_suffix_outdoor_daily(
            ri,
            variation_seed=os.environ.get("TPO_BOTTOM_VARIATION_SEED") or stamp,
        ),
        output_path=out,
        model_name=image_model,
        reference_image_path=ref,
        project_id=project_id,
        location=location,
    )
    st = out.stat()
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(out),
                "size": st.st_size,
                "mtime": st.st_mtime,
                "reference": str(ref),
                "validation_result": val.result,
                "image_model": image_model,
                "local_stamp": stamp,
                "artifact_relative": str(out.resolve().relative_to(_REPO.resolve())),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
