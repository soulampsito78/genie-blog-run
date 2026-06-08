#!/usr/bin/env python3
"""Kee-Suri Global top-shot canary CLI (default dry-run — no image API without explicit approval)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from keysuri_topshot_test_generation import generate_keysuri_global_topshot_test  # noqa: E402

_CANARY_HELP = (
    "Canary-only Kee-Suri Global top-shot test generator. "
    "Default is --dry-run (blocked, no image API). "
    "Does not promote assets. Does not update the approved image registry. "
    "Live generation requires explicit --allow-image-api and --manual-approval."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=_CANARY_HELP,
        epilog=(
            "Safety: canary outputs stay under output/keysuri_preview/image_canary/. "
            "Manifests mark approved_asset=false and registry_promoted=false."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--allow-image-api",
        action="store_true",
        help="Explicit opt-in to call the image API (required for live generation).",
    )
    parser.add_argument(
        "--manual-approval",
        action="store_true",
        help="Explicit owner/manual approval (required with --allow-image-api for live generation).",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Vertex project id (default: GENIE_VERTEX_PROJECT_ID or GOOGLE_CLOUD_PROJECT)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Vertex image model (default: VERTEX_IMAGE_MODEL or gemini-2.5-flash-image)",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON result")
    args = parser.parse_args(argv)

    # argparse cannot express "default True dry_run unless allow-image-api"; derive mode here.
    dry_run = not args.allow_image_api

    result = generate_keysuri_global_topshot_test(
        repo_root=_REPO,
        project_id=args.project_id,
        model_name=args.model,
        dry_run=dry_run,
        allow_image_api=args.allow_image_api,
        manual_approval=args.manual_approval,
    )
    payload = result.to_dict()
    if args.pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))

    if result.blocked_reason and not result.ok:
        return 2
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
