#!/usr/bin/env python3
"""Apply ops/feeds/*.json to Cloud Run TODAY_GENIE_*_JSON env vars (comma-safe via gcloud ^|^)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FEEDS = ROOT / "feeds"
KEY_FILES = [
    ("TODAY_GENIE_OVERNIGHT_US_MARKET_JSON", "overnight_us_market.json"),
    ("TODAY_GENIE_MACRO_INDICATORS_JSON", "macro_indicators.json"),
    ("TODAY_GENIE_TOP_MARKET_NEWS_JSON", "top_market_news.json"),
    ("TODAY_GENIE_RISK_FACTORS_JSON", "risk_factors.json"),
]


def main() -> int:
    parts: list[str] = []
    for env_key, fname in KEY_FILES:
        p = FEEDS / fname
        if not p.is_file():
            print(f"missing {p}", file=sys.stderr)
            return 2
        val = json.dumps(json.loads(p.read_text(encoding="utf-8")), separators=(",", ":"), ensure_ascii=False)
        parts.append(f"{env_key}={val}")
    delim = "|"
    arg = f"^{delim}^{delim.join(parts)}"
    cmd = [
        "gcloud",
        "run",
        "services",
        "update",
        "genie-blog-run",
        "--region=asia-northeast3",
        "--project=gen-lang-client-0667098249",
        f"--update-env-vars={arg}",
    ]
    print("running:", " ".join(cmd[:7]), f"--update-env-vars=^{delim}^<payload>")
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
