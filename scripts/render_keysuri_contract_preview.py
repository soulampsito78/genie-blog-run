#!/usr/bin/env python3
"""Offline Kee-Suri contract preview DESIGN fixture renderer (no LLM, no email, no image API).

This script writes explicitly marked design-only HTML for renderer/CSS regression.
It must NOT be used for owner visual review — use run_keysuri_live_source_smoke.py
with --use-gemini --contract-preview instead.
"""
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

from keysuri_contract_preview_quality import validate_contract_preview_visible_body  # noqa: E402
from keysuri_contract_preview_renderer import (  # noqa: E402
    DEFAULT_REVIEW_STATE,
    IMAGE_MODE_PREVIEW,
    PROGRAM_GLOBAL,
    PROGRAM_KOREA,
    REVIEW_STATE_PREVIEW_PENDING,
    REVIEW_STATE_REVIEW_PASSED,
    REVIEW_STATE_SENT_ARCHIVED,
    SAFE_CLOSING_MESSAGE,
    prepare_contract_preview_fixture,
    render_keysuri_contract_preview_html,
)
from keysuri_html_preview_validation import validate_keysuri_html_preview  # noqa: E402

DEFAULT_OUTPUT_DIR = _REPO_ROOT / "output" / "keysuri_preview" / "html_test"
DESIGN_FILENAME_PATTERN_RE = re.compile(
    r"^keysuri_(korea|global)_\d{4}_design_fixture_\d{8}_\d{6}(?:_\d+)?\.html$",
    re.IGNORECASE,
)

DESIGN_FIXTURE_BANNER = "DESIGN FIXTURE — NOT OWNER REVIEW"


def _design_top_item(rank: int, *, scope: str) -> dict[str, Any]:
    """Staged placeholder item — design fixture only, never owner review."""
    return {
        "rank": rank,
        "korean_title": f"스테이징 한국어 헤드라인 {rank} — AI·플랫폼 신호 ({scope})",
        "headline": f"스테이징 한국어 헤드라인 {rank} — AI·플랫폼 신호 ({scope})",
        "what_happened": (
            f"스테이징 항목 {rank}에서 확인된 사실입니다. "
            f"공개 RSS 요약을 바탕으로 핵심 변화를 정리했습니다. "
            f"세부 수치는 향후 공식 발표를 통해 보완될 가능성이 있습니다."
        ),
        "why_now": (
            f"스테이징 항목 {rank}는 지금 시장·플랫폼 맥락에서 주목받는 신호입니다. "
            f"경쟁사와 공급망 의사결정에 직접 영향을 줄 수 있습니다."
        ),
        "owner_angle": (
            f"주인님께서는 항목 {rank}를 제품 로드맵·파트너 선정 기준에 반영할지 점검하시면 됩니다. "
            f"단기 과장과 장기 구조 변화를 구분해 보시는 것이 좋습니다."
        ),
        "keysuri_judgment_label": "관찰",
        "keysuri_judgment": f"스테이징 판단 {rank} — 추가 확인 후 활용 여부를 결정하세요.",
        "next_watch": f"항목 {rank} 관련 후속 공식 발표·가격·일정 공개 여부를 확인하세요.",
        "source_name": f"Sample Source {rank}",
        "source_url": f"https://example.com/source/{scope}-item-{rank}",
        "checked_at": "2026-06-05T12:00:00+09:00",
        "verification_status": "sample_only / not_verified",
    }


def _design_deep_dive_layers(*, scope: str) -> list[dict[str, str]]:
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


def build_design_fixture(
    *,
    program_id: str,
    slot: str,
    review_state: str = DEFAULT_REVIEW_STATE,
) -> dict[str, Any]:
    """Build explicit design-only fixture — NOT for owner visual review."""
    if program_id == PROGRAM_KOREA:
        scope = "korea"
        return {
            "program_id": PROGRAM_KOREA,
            "slot": slot,
            "review_state": review_state,
            "fixture_mode": "design_only",
            "title_candidates": [
                "[키수리 브리핑] Staged domestic infra signal sample",
                "[키수리] Staged regulation pressure sample",
            ],
            "selected_title": "[키수리 브리핑] Staged domestic infra signal sample",
            "opening_lead": "Staged opening lead — domestic tech signal first, not greeting-first.",
            "top_5_heading": "국내 테크 TOP 5",
            "top_5_items": [_design_top_item(i, scope=scope) for i in range(1, 6)],
            "deep_dive_heading": "키수리의 딥-다이브",
            "deep_dive_layers": _design_deep_dive_layers(scope=scope),
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
                "mode": "design_fixture",
                "status": "design_only",
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
            "fixture_mode": "design_only",
            "title_candidates": [
                "[키수리 브리핑] Staged global infra signal sample",
                "[키수리] Staged platform control sample",
            ],
            "selected_title": "[키수리 브리핑] Staged global infra signal sample",
            "opening_lead": (
                "주인님, 오늘 글로벌 테크 신호는 개별 헤드라인보다 AI·플랫폼·업무 루틴 쪽 구조적 움직임으로 읽힙니다. "
                "배포 레이어와 공급망 압력이 동시에 커지고 있습니다. "
                "키수리는 주인님께 의사결정에 바로 쓸 수 있는 관점으로 정리했습니다."
            ),
            "top_5_heading": "글로벌 테크 TOP 5",
            "top_5_items": [_design_top_item(i, scope=scope) for i in range(1, 6)],
            "deep_dive_heading": "키수리의 딥-다이브",
            "deep_dive_body": (
                "주인님, 오늘 선정된 다섯 신호는 AI 기능 발표보다 배포·검색·개발 루틴 장악 속도에 초점이 맞춰져 있습니다. "
                "확인된 사실은 공식 블로그·보도자료·RSS 요약 범위 안에 머무릅니다. "
                "키수리 해석상 플랫폼 통제권은 모델 성능 경쟁에서 워크플로 락인 경쟁으로 이동 중입니다. "
                "한국 운영자·창업자에게는 API 가격·지역 가용성·데이터 주권이 곧바로 비용 구조에 반영될 수 있습니다. "
                "아직 불확실한 점은 각사의 상용 일정과 엔터프라이즈 계약 조건입니다."
            ),
            "deep_dive_layers": _design_deep_dive_layers(scope=scope),
            "one_line_checkpoint": "주인님, 오늘 신호는 'AI 기능'보다 'AI가 업무·검색·개발 루틴을 장악하는 속도'를 봐야 합니다.",
            "closing_message": SAFE_CLOSING_MESSAGE,
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
                "mode": "design_fixture",
                "status": "design_only",
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
    base = f"keysuri_{program_token}_{slot_token}_design_fixture_{stamp}.html"
    if suffix <= 0:
        return base
    return f"keysuri_{program_token}_{slot_token}_design_fixture_{stamp}_{suffix}.html"


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


def render_and_write_design_fixture(
    *,
    program_id: str,
    slot: str,
    review_state: str,
    output_dir: Path,
) -> Path:
    fixture = build_design_fixture(
        program_id=program_id,
        slot=slot,
        review_state=review_state,
    )
    prepare_contract_preview_fixture(fixture, repo_root=_REPO_ROOT, image_mode=IMAGE_MODE_PREVIEW)
    html = render_keysuri_contract_preview_html(
        fixture,
        repo_root=_REPO_ROOT,
        image_mode=IMAGE_MODE_PREVIEW,
        auto_prepare=False,
    )
    output_path = _resolve_output_path(output_dir, program_id, slot)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Render Kee-Suri contract-preview DESIGN fixture HTML only "
            "(offline, not owner visual review)."
        ),
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
        help="Directory for timestamped design fixture HTML files",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print validation JSON output",
    )
    parser.add_argument(
        "--fixture",
        choices=("design",),
        default="design",
        help="Fixture source (design fixture only)",
    )
    args = parser.parse_args(argv)

    if args.fixture != "design":
        print(json.dumps({"error": "unsupported_fixture", "fixture": args.fixture}), file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = (_REPO_ROOT / output_dir).resolve()

    try:
        output_path = render_and_write_design_fixture(
            program_id=args.program,
            slot=args.slot,
            review_state=args.review_state,
            output_dir=output_dir,
        )
    except (ValueError, FileExistsError, OSError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 2

    html = output_path.read_text(encoding="utf-8")
    visible_quality = validate_contract_preview_visible_body(html)
    result = validate_keysuri_html_preview(str(output_path), program_id=args.program)
    payload = result.to_dict()
    payload["output_path"] = str(output_path)
    payload["validation_status"] = result.validation_status
    payload["program"] = args.program
    payload["slot"] = args.slot
    payload["review_state"] = args.review_state
    payload["design_fixture"] = True
    payload["owner_visual_review"] = False
    payload["owner_visual_review_status"] = "NOT_READY — design fixture only"
    payload["visible_body_quality_pass"] = visible_quality.ok
    payload["visible_body_quality_issues"] = [f"{i.code}: {i.message}" for i in visible_quality.issues]
    payload["design_fixture_banner_present"] = DESIGN_FIXTURE_BANNER in html

    if args.pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
