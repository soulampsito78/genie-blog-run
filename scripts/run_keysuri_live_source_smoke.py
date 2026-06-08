#!/usr/bin/env python3
"""Kee-Suri live public RSS source-pack smoke (minimal — not production automation)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from keysuri_live_source_smoke import (  # noqa: E402
    PROGRAM_GLOBAL,
    _DEFAULT_EMAIL_SUBJECT,
    run_keysuri_live_source_smoke,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Kee-Suri live public RSS source-pack smoke (owner-review HTML, no customer delivery)."
    )
    parser.add_argument("--program", default=PROGRAM_GLOBAL, choices=("keysuri_global_tech", "keysuri_korea_tech"))
    parser.add_argument("--max-items", type=int, default=5)
    parser.add_argument("--html-out", default=None, help="Optional output HTML path")
    parser.add_argument("--source-pack-out", default=None, help="Optional output source pack JSON path")
    parser.add_argument("--send", action="store_true", help="Attempt owner-review email via SMTP harness")
    parser.add_argument("--no-email", action="store_true", help="Explicit no-email (default)")
    parser.add_argument("--confirm", default=None, help='Must be "SEND" when --send is set')
    parser.add_argument(
        "--to",
        action="append",
        default=[],
        help="Allowlisted owner-review recipient(s); comma-separated values allowed",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        default=True,
        help="Allow network fetch (default true for this smoke)",
    )
    parser.add_argument("--no-network", action="store_true", help="Fail fast without network fetch")
    parser.add_argument(
        "--contract-preview",
        action="store_true",
        help="Render contract-preview HTML under html_test/ (requires --use-gemini)",
    )
    parser.add_argument(
        "--use-gemini",
        action="store_true",
        help="Build generation prompt, call Gemini/Vertex, parse, and render generated briefing",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Vertex project id (default: PROJECT_ID or GOOGLE_CLOUD_PROJECT)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Vertex model name (default: VERTEX_MODEL or gemini-2.5-flash)",
    )
    parser.add_argument(
        "--image-path",
        default=None,
        help=(
            "Explicit test override only — embed candidate/non-registry image for manual review. "
            "Routine contract-preview uses approved registry asset when omitted."
        ),
    )
    parser.add_argument(
        "--subject",
        default=None,
        help="Email subject when --send is used",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON report")
    args = parser.parse_args(argv)

    if args.no_email:
        send = False
    else:
        send = bool(args.send)

    recipients: list[str] = []
    for raw in args.to:
        recipients.extend(part.strip() for part in raw.split(",") if part.strip())

    result = run_keysuri_live_source_smoke(
        program_id=args.program,
        max_items=max(5, args.max_items),
        allow_network=not args.no_network,
        use_gemini=args.use_gemini,
        contract_preview=args.contract_preview,
        project_id=args.project_id,
        model=args.model,
        send=send,
        send_confirm=args.confirm,
        recipients=recipients,
        html_out=Path(args.html_out) if args.html_out else None,
        source_pack_out=Path(args.source_pack_out) if args.source_pack_out else None,
        repo_root=_REPO,
        email_subject=args.subject,
        top_shot_image_path=Path(args.image_path) if args.image_path else None,
    )

    payload = result.to_dict()
    if args.pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
