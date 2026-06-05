#!/usr/bin/env python3
"""Offline Kee-Suri contract preview HTML generator (no LLM, no email, no image API)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from keysuri_contract_preview_renderer import (  # noqa: E402
    DEFAULT_REVIEW_STATE,
    PROGRAM_GLOBAL,
    PROGRAM_KOREA,
    REVIEW_STATE_PREVIEW_PENDING,
    REVIEW_STATE_REVIEW_PASSED,
    REVIEW_STATE_SENT_ARCHIVED,
    render_keysuri_contract_preview_html,
)
from keysuri_html_preview_validation import validate_keysuri_html_preview  # noqa: E402

DEFAULT_OUTPUT_DIR = _REPO_ROOT / "output" / "keysuri_preview" / "html_test"
FILENAME_PATTERN_RE = re.compile(
    r"^keysuri_(korea|global)_\d{4}_contract_preview_\d{8}_\d{6}(?:_\d+)?\.html$",
    re.IGNORECASE,
)


def _sample_top_item(rank: int, *, scope: str) -> dict[str, Any]:
    return {
        "rank": rank,
        "headline": f"Staged sample headline {rank} ({scope})",
        "what_happened": f"Staged sample signal capture for item {rank}.",
        "why_it_matters": f"Staged structural relevance note {rank}.",
        "business_implication": f"Staged business implication {rank}.",
        "risk_note": f"Staged optional risk note {rank}.",
        "source_name": f"Sample Source {rank}",
        "source_url": f"https://example.com/source/{scope}-item-{rank}",
        "checked_at": "2026-06-05T12:00:00+09:00",
        "verification_status": "sample_only / not_verified",
    }


def _sample_deep_dive_layers(*, scope: str) -> list[dict[str, str]]:
    if scope == "korea":
        return [
            {
                "layer_number": "1",
                "layer_title": "물리·인프라 병목",
                "layer_body": "Staged Korea layer one — infrastructure bottleneck sample.",
            },
            {
                "layer_number": "2",
                "layer_title": "규제·주권·조달 압력",
                "layer_body": "Staged Korea layer two — regulation and procurement pressure sample.",
            },
            {
                "layer_number": "3",
                "layer_title": "워크플로·락인",
                "layer_body": "Staged Korea layer three — workflow lock-in sample.",
            },
        ]
    return [
        {
            "layer_number": "1",
            "layer_title": "Infrastructure signal",
            "layer_body": "Staged global layer one — infrastructure movement sample.",
        },
        {
            "layer_number": "2",
            "layer_title": "Platform control shift",
            "layer_body": "Staged global layer two — platform control sample.",
        },
        {
            "layer_number": "3",
            "layer_title": "Workflow leverage",
            "layer_body": "Staged global layer three — workflow leverage sample.",
        },
    ]


def build_sample_fixture(
    *,
    program_id: str,
    slot: str,
    review_state: str = DEFAULT_REVIEW_STATE,
) -> dict[str, Any]:
    """Build staged sample fixture — not live news."""
    if program_id == PROGRAM_KOREA:
        scope = "korea"
        return {
            "program_id": PROGRAM_KOREA,
            "slot": slot,
            "review_state": review_state,
            "title_candidates": [
                "[키수리 브리핑] Staged domestic infra signal sample",
                "[키수리] Staged regulation pressure sample",
            ],
            "selected_title": "[키수리 브리핑] Staged domestic infra signal sample",
            "opening_lead": "Staged opening lead — domestic tech signal first, not greeting-first.",
            "top_5_heading": "국내 테크 TOP 5",
            "top_5_items": [_sample_top_item(i, scope=scope) for i in range(1, 6)],
            "deep_dive_heading": "키수리의 딥-다이브",
            "deep_dive_layers": _sample_deep_dive_layers(scope=scope),
            "one_line_checkpoint": "Staged one-line decision cue for domestic preview.",
            "warm_close_text": "오늘도 수고하셨습니다. 내일 다시 뵙겠습니다.",
            "closing_message": "Staged closing message for domestic contract preview.",
            "source_list": [
                {
                    "source_id": "korea-t0-sample",
                    "source_name": "Sample Domestic Official",
                    "source_url": "https://example.com/source/korea-official",
                    "verification_status": "sample_only / not_verified",
                }
            ],
            "operation_metadata": {
                "program_id": PROGRAM_KOREA,
                "mode": "contract_preview",
                "status": "review_required",
                "slot": slot,
                "production": False,
                "scheduler_ready": False,
                "email_ready": False,
            },
        }

    if program_id == PROGRAM_GLOBAL:
        scope = "global"
        return {
            "program_id": PROGRAM_GLOBAL,
            "slot": slot,
            "review_state": review_state,
            "title_candidates": [
                "[키수리 브리핑] Staged global infra signal sample",
                "[키수리] Staged platform control sample",
            ],
            "selected_title": "[키수리 브리핑] Staged global infra signal sample",
            "opening_lead": "Staged opening lead — global tech signal first, not greeting-first.",
            "top_5_heading": "글로벌 테크 TOP 5",
            "top_5_items": [_sample_top_item(i, scope=scope) for i in range(1, 6)],
            "deep_dive_heading": "키수리의 딥-다이브",
            "deep_dive_layers": _sample_deep_dive_layers(scope=scope),
            "one_line_checkpoint": "Staged one-line decision cue for global preview.",
            "closing_message": "Staged closing message for global contract preview.",
            "source_list": [
                {
                    "source_id": "global-t0-sample",
                    "source_name": "Sample Global Official",
                    "source_url": "https://example.com/source/global-official",
                    "verification_status": "sample_only / not_verified",
                }
            ],
            "operation_metadata": {
                "program_id": PROGRAM_GLOBAL,
                "mode": "contract_preview",
                "status": "review_required",
                "slot": slot,
                "production": False,
                "scheduler_ready": False,
                "email_ready": False,
            },
        }

    raise ValueError(f"Unsupported program_id: {program_id!r}")


def _program_token(program_id: str) -> str:
    if program_id == PROGRAM_KOREA:
        return "korea"
    if program_id == PROGRAM_GLOBAL:
        return "global"
    raise ValueError(f"Unsupported program_id: {program_id!r}")


def _slot_token(slot: str) -> str:
    token = slot.strip().replace(":", "")
    if not token.isdigit():
        raise ValueError(f"Invalid slot: {slot!r}")
    return token


def _build_filename(program_id: str, slot: str, stamp: str, suffix: int = 0) -> str:
    program_token = _program_token(program_id)
    slot_token = _slot_token(slot)
    base = f"keysuri_{program_token}_{slot_token}_contract_preview_{stamp}.html"
    if suffix <= 0:
        return base
    return f"keysuri_{program_token}_{slot_token}_contract_preview_{stamp}_{suffix}.html"


def _resolve_output_path(output_dir: Path, program_id: str, slot: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = output_dir / _build_filename(program_id, slot, stamp)
    if not candidate.exists():
        return candidate

    for suffix in range(2, 100):
        alt = output_dir / _build_filename(program_id, slot, stamp, suffix=suffix)
        if not alt.exists():
            return alt

    raise FileExistsError(
        f"Could not allocate unique filename for stamp {stamp} in {output_dir}"
    )


def render_and_write_contract_preview(
    *,
    program_id: str,
    slot: str,
    review_state: str,
    output_dir: Path,
) -> Path:
    fixture = build_sample_fixture(
        program_id=program_id,
        slot=slot,
        review_state=review_state,
    )
    html = render_keysuri_contract_preview_html(fixture)
    output_path = _resolve_output_path(output_dir, program_id, slot)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render Kee-Suri contract-validation HTML preview (offline sample only).",
    )
    parser.add_argument(
        "--program",
        choices=(PROGRAM_KOREA, PROGRAM_GLOBAL),
        default=PROGRAM_KOREA,
        help="Kee-Suri program id",
    )
    parser.add_argument(
        "--slot",
        choices=("18:30", "12:30"),
        default="18:30",
        help="Program slot",
    )
    parser.add_argument(
        "--review-state",
        choices=(
            REVIEW_STATE_PREVIEW_PENDING,
            REVIEW_STATE_REVIEW_PASSED,
            REVIEW_STATE_SENT_ARCHIVED,
        ),
        default=REVIEW_STATE_PREVIEW_PENDING,
        help="Review confirmation box state",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for timestamped html_test preview files",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print validation JSON output",
    )
    parser.add_argument(
        "--fixture",
        choices=("sample",),
        default="sample",
        help="Fixture source (v0: sample only)",
    )
    args = parser.parse_args(argv)

    if args.fixture != "sample":
        print(json.dumps({"error": "unsupported_fixture", "fixture": args.fixture}), file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = (_REPO_ROOT / output_dir).resolve()

    try:
        output_path = render_and_write_contract_preview(
            program_id=args.program,
            slot=args.slot,
            review_state=args.review_state,
            output_dir=output_dir,
        )
    except (ValueError, FileExistsError, OSError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 2

    result = validate_keysuri_html_preview(str(output_path), program_id=args.program)
    payload = result.to_dict()
    payload["output_path"] = str(output_path)
    payload["validation_status"] = result.validation_status
    payload["program"] = args.program
    payload["slot"] = args.slot
    payload["review_state"] = args.review_state

    if args.pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))

    return 0 if result.is_pass() else 1


if __name__ == "__main__":
    raise SystemExit(main())
