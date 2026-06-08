#!/usr/bin/env python3
"""Read-only CLI for Kee-Suri HTML preview validation."""
from __future__ import annotations

import argparse
import json
import sys
from glob import glob
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from keysuri_html_preview_validation import validate_keysuri_html_preview  # noqa: E402


def _expand_paths(raw_paths: list[str]) -> list[Path]:
    expanded: list[Path] = []
    for raw in raw_paths:
        matches = glob(raw)
        if matches:
            expanded.extend(Path(match) for match in sorted(matches))
        else:
            expanded.append(Path(raw))
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in expanded:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            deduped.append(path)
    return deduped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Kee-Suri HTML preview files (read-only).")
    parser.add_argument("paths", nargs="+", help="HTML file path(s) or glob pattern(s)")
    parser.add_argument(
        "--program-id",
        choices=("keysuri_global_tech", "keysuri_korea_tech"),
        default=None,
        help="Optional program id override",
    )
    parser.add_argument(
        "--profile",
        choices=("auto", "contract_preview", "owner_review"),
        default="auto",
        help="Validation profile (default: auto-detect from path/content)",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    profile = None if args.profile == "auto" else args.profile

    paths = _expand_paths(args.paths)
    if not paths:
        print(json.dumps({"error": "no_input_paths", "results": []}), file=sys.stderr)
        return 2

    results = []
    all_pass = True
    for path in paths:
        result = validate_keysuri_html_preview(
            str(path),
            program_id=args.program_id,
            profile=profile,
        )
        payload = result.to_dict()
        results.append(payload)
        if not result.is_pass():
            all_pass = False

    output = {"results": results, "validation_status": "PASS" if all_pass else "FAIL"}
    if args.pretty:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(output, ensure_ascii=False))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
