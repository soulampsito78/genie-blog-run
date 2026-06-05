#!/usr/bin/env python3
"""Local Kee-Suri MirAI:ON image watermark CLI (offline post-process only).

Does not generate images, call image API, send email, or touch scheduler.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from keysuri_image_asset_manifest import (  # noqa: E402
    REVIEW_STATUS_PENDING,
    VALID_REVIEW_STATUSES,
    build_keysuri_image_asset_manifest,
    write_keysuri_image_asset_manifest,
)
from keysuri_image_overlay import (  # noqa: E402
    DEFAULT_POSITION,
    DEFAULT_WATERMARK_TEXT,
    FORBIDDEN_LEGACY_TEXTS,
    apply_keysuri_mirai_on_watermark,
)

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
VALID_POSITIONS = ("bottom_right", "bottom_left")
VALID_ROLES = ("top_shot", "bottom_shot")
VALID_PROGRAMS = ("keysuri_global_tech", "keysuri_korea_tech")

DEFAULT_PROGRAM = "keysuri_global_tech"
DEFAULT_SLOT = "manual_canary"
DEFAULT_REVIEW_STATUS = REVIEW_STATUS_PENDING

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_INPUT_ERROR = 2


def _resolve_path(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _validate_label(label: str) -> str | None:
    text = (label or "").strip() or DEFAULT_WATERMARK_TEXT
    for forbidden in FORBIDDEN_LEGACY_TEXTS:
        if forbidden in text:
            return f"forbidden label contains {forbidden!r}"
    return None


def _validate_input_path(input_path: Path) -> str | None:
    if not input_path.is_file():
        return f"input file not found: {input_path}"
    if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return f"unsupported input extension: {input_path.suffix!r} (JPEG or PNG only)"
    return None


def _build_payload(
    *,
    status: str,
    input_path: str,
    output_path: str | None,
    position: str,
    label: str,
    role: str | None,
    overlay_applied: bool,
    manifest_written: bool = False,
    manifest_path: str | None = None,
    program_id: str | None = None,
    slot: str | None = None,
    image_role: str | None = None,
    review_status: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "input_path": input_path,
        "output_path": output_path,
        "position": position,
        "label": label,
        "watermark_text": DEFAULT_WATERMARK_TEXT,
        "overlay_applied": overlay_applied,
        "manifest_written": manifest_written,
    }
    if role is not None:
        payload["role"] = role
    if manifest_path is not None:
        payload["manifest_path"] = manifest_path
    if program_id is not None:
        payload["program_id"] = program_id
    if slot is not None:
        payload["slot"] = slot
    if image_role is not None:
        payload["image_role"] = image_role
    if review_status is not None:
        payload["review_status"] = review_status
    if error:
        payload["error"] = error
    return payload


def _emit(payload: dict[str, Any], *, pretty: bool) -> None:
    if pretty:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False))


def run_apply_keysuri_image_watermark(
    *,
    input_path: str,
    output_path: str | None = None,
    position: str = DEFAULT_POSITION,
    label: str = DEFAULT_WATERMARK_TEXT,
    role: str | None = None,
    pretty: bool = False,
    write_manifest: bool = False,
    program: str = DEFAULT_PROGRAM,
    slot: str = DEFAULT_SLOT,
    review_status: str = DEFAULT_REVIEW_STATUS,
    review_notes: str = "",
    prompt_profile: str = "",
    source_generation_id: str | None = None,
    manifest_output: str | None = None,
) -> int:
    """Apply overlay and print JSON result to stdout. Returns process exit code."""
    resolved_input = _resolve_path(input_path)
    input_err = _validate_input_path(resolved_input)
    if input_err:
        payload = _build_payload(
            status="FAIL",
            input_path=str(resolved_input),
            output_path=None,
            position=position,
            label=label,
            role=role,
            overlay_applied=False,
            error=input_err,
        )
        _emit(payload, pretty=pretty)
        return EXIT_INPUT_ERROR

    if position not in VALID_POSITIONS:
        payload = _build_payload(
            status="FAIL",
            input_path=str(resolved_input),
            output_path=None,
            position=position,
            label=label,
            role=role,
            overlay_applied=False,
            error=f"unsupported position: {position!r}",
        )
        _emit(payload, pretty=pretty)
        return EXIT_INPUT_ERROR

    if program not in VALID_PROGRAMS:
        payload = _build_payload(
            status="FAIL",
            input_path=str(resolved_input),
            output_path=None,
            position=position,
            label=label,
            role=role,
            overlay_applied=False,
            error=f"unsupported program: {program!r}",
        )
        _emit(payload, pretty=pretty)
        return EXIT_INPUT_ERROR

    if review_status not in VALID_REVIEW_STATUSES:
        payload = _build_payload(
            status="FAIL",
            input_path=str(resolved_input),
            output_path=None,
            position=position,
            label=label,
            role=role,
            overlay_applied=False,
            error=f"unsupported review_status: {review_status!r}",
        )
        _emit(payload, pretty=pretty)
        return EXIT_INPUT_ERROR

    if role is not None and role not in VALID_ROLES:
        payload = _build_payload(
            status="FAIL",
            input_path=str(resolved_input),
            output_path=None,
            position=position,
            label=label,
            role=role,
            overlay_applied=False,
            error=f"unsupported role: {role!r}",
        )
        _emit(payload, pretty=pretty)
        return EXIT_INPUT_ERROR

    if write_manifest and role is None:
        payload = _build_payload(
            status="FAIL",
            input_path=str(resolved_input),
            output_path=None,
            position=position,
            label=label,
            role=None,
            overlay_applied=False,
            program_id=program,
            slot=slot,
            review_status=review_status,
            error="--role is required when --write-manifest is set",
        )
        _emit(payload, pretty=pretty)
        return EXIT_INPUT_ERROR

    label_err = _validate_label(label)
    if label_err:
        payload = _build_payload(
            status="FAIL",
            input_path=str(resolved_input),
            output_path=None,
            position=position,
            label=label,
            role=role,
            overlay_applied=False,
            error=label_err,
        )
        _emit(payload, pretty=pretty)
        return EXIT_FAIL

    normalized_label = (label or "").strip() or DEFAULT_WATERMARK_TEXT
    resolved_output: Path | None = _resolve_path(output_path) if output_path else None

    if resolved_output is not None and resolved_output.suffix.lower() not in SUPPORTED_EXTENSIONS:
        payload = _build_payload(
            status="FAIL",
            input_path=str(resolved_input),
            output_path=str(resolved_output),
            position=position,
            label=normalized_label,
            role=role,
            overlay_applied=False,
            error=f"unsupported output extension: {resolved_output.suffix!r} (JPEG or PNG only)",
        )
        _emit(payload, pretty=pretty)
        return EXIT_INPUT_ERROR

    try:
        result_path = apply_keysuri_mirai_on_watermark(
            resolved_input,
            resolved_output,
            position=position,
            label=normalized_label,
        )
    except Exception as exc:  # noqa: BLE001 — surface CLI failure as JSON
        payload = _build_payload(
            status="FAIL",
            input_path=str(resolved_input),
            output_path=str(resolved_output) if resolved_output else None,
            position=position,
            label=normalized_label,
            role=role,
            overlay_applied=False,
            error=str(exc),
        )
        _emit(payload, pretty=pretty)
        return EXIT_FAIL

    if not write_manifest:
        payload = _build_payload(
            status="PASS",
            input_path=str(resolved_input),
            output_path=str(result_path),
            position=position,
            label=normalized_label,
            role=role,
            overlay_applied=True,
            manifest_written=False,
        )
        _emit(payload, pretty=pretty)
        return EXIT_OK

    try:
        manifest = build_keysuri_image_asset_manifest(
            source_image_path=resolved_input,
            watermarked_image_path=result_path,
            program_id=program,
            slot=slot,
            image_role=role,
            watermark_position=position,
            review_status=review_status,
            review_notes=review_notes,
            prompt_profile=prompt_profile,
            source_generation_id=source_generation_id,
        )
        manifest_target = _resolve_path(manifest_output) if manifest_output else None
        manifest_path = write_keysuri_image_asset_manifest(manifest, manifest_target)
    except Exception as exc:  # noqa: BLE001 — surface manifest failure as JSON
        payload = _build_payload(
            status="FAIL",
            input_path=str(resolved_input),
            output_path=str(result_path),
            position=position,
            label=normalized_label,
            role=role,
            overlay_applied=True,
            manifest_written=False,
            program_id=program,
            slot=slot,
            image_role=role,
            review_status=review_status,
            error=f"manifest write failed: {exc}",
        )
        _emit(payload, pretty=pretty)
        return EXIT_FAIL

    payload = _build_payload(
        status="PASS",
        input_path=str(resolved_input),
        output_path=str(result_path),
        position=position,
        label=normalized_label,
        role=role,
        overlay_applied=True,
        manifest_written=True,
        manifest_path=str(manifest_path),
        program_id=program,
        slot=slot,
        image_role=role,
        review_status=review_status,
    )
    _emit(payload, pretty=pretty)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply visible MirAI:ON watermark to local Kee-Suri JPEG/PNG assets (offline only).",
    )
    parser.add_argument("--input", required=True, help="Existing JPEG or PNG input path.")
    parser.add_argument("--output", default=None, help="Optional output path.")
    parser.add_argument(
        "--position",
        default=DEFAULT_POSITION,
        choices=VALID_POSITIONS,
        help=f"Watermark placement (default: {DEFAULT_POSITION}).",
    )
    parser.add_argument(
        "--label",
        default=DEFAULT_WATERMARK_TEXT,
        help=f"Visible watermark text (default: {DEFAULT_WATERMARK_TEXT}).",
    )
    parser.add_argument(
        "--role",
        default=None,
        choices=VALID_ROLES,
        help="Optional image role metadata (top_shot or bottom_shot).",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    parser.add_argument(
        "--write-manifest",
        action="store_true",
        help="Write sidecar manifest JSON after successful overlay.",
    )
    parser.add_argument(
        "--program",
        default=DEFAULT_PROGRAM,
        choices=VALID_PROGRAMS,
        help=f"Kee-Suri program id for manifest (default: {DEFAULT_PROGRAM}).",
    )
    parser.add_argument(
        "--slot",
        default=DEFAULT_SLOT,
        help=f"Schedule slot label for manifest (default: {DEFAULT_SLOT}).",
    )
    parser.add_argument(
        "--review-status",
        default=DEFAULT_REVIEW_STATUS,
        choices=VALID_REVIEW_STATUSES,
        help=f"Manifest review status (default: {DEFAULT_REVIEW_STATUS}).",
    )
    parser.add_argument("--review-notes", default="", help="Optional manifest review notes.")
    parser.add_argument("--prompt-profile", default="", help="Optional wardrobe/profile id for manifest.")
    parser.add_argument(
        "--source-generation-id",
        default=None,
        help="Optional source generation id for manifest.",
    )
    parser.add_argument(
        "--manifest-output",
        default=None,
        help="Optional explicit manifest JSON output path.",
    )
    args = parser.parse_args(argv)

    return run_apply_keysuri_image_watermark(
        input_path=args.input,
        output_path=args.output,
        position=args.position,
        label=args.label,
        role=args.role,
        pretty=args.pretty,
        write_manifest=args.write_manifest,
        program=args.program,
        slot=args.slot,
        review_status=args.review_status,
        review_notes=args.review_notes,
        prompt_profile=args.prompt_profile,
        source_generation_id=args.source_generation_id,
        manifest_output=args.manifest_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
