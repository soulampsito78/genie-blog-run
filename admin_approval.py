"""Build and verify immutable owner approval targets."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo

from admin_safety_store import (
    APPROVAL_SNAPSHOT_TTL_SECONDS,
    generate_approval_snapshot_id,
    load_approval_snapshot,
    save_approval_snapshot,
)
from admin_store import resolve_customer_recipients
from delivery_trace import mask_email_addresses


class ApprovalTargetError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PreparedApprovalTarget:
    run_id: str
    mode: str
    subject: str
    customer_html: str
    inline_jpeg_parts: List[Tuple[str, str, str]]
    recipients: List[str]
    snapshot_fields: Dict[str, Any]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ApprovalTargetError("APPROVAL_IMAGE_UNAVAILABLE") from exc
    return digest.hexdigest()


def _canonical_json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(encoded)


def _prepare_content_and_images(
    mode: str, saved_html: str, meta: Dict[str, Any]
) -> tuple[str, str, List[Tuple[str, str, str]]]:
    if mode == "today_genie":
        from today_geenee_customer_delivery import prepare_today_geenee_customer_delivery

        prepared = prepare_today_geenee_customer_delivery(saved_html, meta)
    elif mode in {"keysuri_global_tech", "keysuri_korea_tech"}:
        from keysuri_customer_delivery import prepare_keysuri_customer_delivery

        prepared = prepare_keysuri_customer_delivery(saved_html, meta)
    else:
        raise ApprovalTargetError("unsupported_mode")
    if not prepared.get("ok"):
        raise ApprovalTargetError(str(prepared.get("error") or "APPROVAL_TARGET_UNAVAILABLE"))
    parts = list(prepared.get("inline_jpeg_parts") or [])
    if not parts:
        raise ApprovalTargetError("APPROVAL_IMAGE_UNAVAILABLE")
    return str(prepared["subject"]), str(prepared["html_body"]), parts


def build_current_approval_target(
    *, run_id: str, meta: Dict[str, Any], saved_html: str
) -> PreparedApprovalTarget:
    mode = str(meta.get("mode") or meta.get("program_id") or "")
    subject, customer_html, inline_parts = _prepare_content_and_images(mode, saved_html, meta)
    resolved = resolve_customer_recipients()
    if not resolved.get("admin_config_ok", True):
        raise ApprovalTargetError("RECIPIENT_CONFIG_UNAVAILABLE")
    recipients = [str(item).strip().lower() for item in resolved.get("final_recipients") or []]
    if not recipients:
        raise ApprovalTargetError("missing_customer_to")
    image_rows = [
        {
            "position": "top" if index == 0 else ("bottom" if index == 1 else f"image_{index + 1}"),
            "cid": str(cid),
            "filename": Path(filename).name,
            "sha256": _sha256_file(path),
        }
        for index, (path, cid, filename) in enumerate(inline_parts)
    ]
    config_version = str(resolved.get("recipient_configuration_version") or "unknown")
    config_hash = str(resolved.get("recipient_configuration_hash") or _canonical_json_hash(recipients))
    fields = {
        "run_id": run_id,
        "program": mode,
        "rendered_content_sha256": _sha256_text(customer_html),
        "subject": subject,
        "subject_sha256": _sha256_text(subject.strip()),
        "images": image_rows,
        "image_set_sha256": _canonical_json_hash(image_rows),
        "recipients": recipients,
        "recipients_masked": mask_email_addresses(recipients),
        "recipient_count": len(recipients),
        "recipient_configuration_version": config_version,
        "recipient_configuration_hash": config_hash,
        "safety_verdict": str(meta.get("safety_verdict") or ""),
        "editorial_verdict": str(meta.get("editorial_verdict") or ""),
        "review_issue_codes": list(meta.get("review_issue_codes") or [])[:48],
        "warning_confirmation_required": (
            mode in {"keysuri_global_tech", "keysuri_korea_tech"}
            and str(meta.get("editorial_verdict") or "") == "REVIEW"
        ),
    }
    fields["approval_target_sha256"] = _canonical_json_hash(fields)
    return PreparedApprovalTarget(
        run_id=run_id,
        mode=mode,
        subject=subject,
        customer_html=customer_html,
        inline_jpeg_parts=inline_parts,
        recipients=recipients,
        snapshot_fields=fields,
    )


def create_approval_snapshot(
    *, run_id: str, meta: Dict[str, Any], saved_html: str, operator_id: str
) -> tuple[Dict[str, Any], PreparedApprovalTarget]:
    target = build_current_approval_target(run_id=run_id, meta=meta, saved_html=saved_html)
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    snapshot = {
        "approval_snapshot_id": generate_approval_snapshot_id(),
        **target.snapshot_fields,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=APPROVAL_SNAPSHOT_TTL_SECONDS)).isoformat(),
        "operator_id": str(operator_id or "unknown"),
        "authority": "durable_store_not_browser_state",
    }
    if not save_approval_snapshot(snapshot):
        raise ApprovalTargetError("APPROVAL_SNAPSHOT_COLLISION")
    return snapshot, target


def verify_approval_snapshot(
    *,
    snapshot_id: str,
    run_id: str,
    meta: Dict[str, Any],
    saved_html: str,
    operator_id: str,
) -> tuple[Dict[str, Any], PreparedApprovalTarget]:
    snapshot = load_approval_snapshot(snapshot_id)
    if not snapshot or str(snapshot.get("run_id") or "") != run_id:
        raise ApprovalTargetError("INVALID_APPROVAL_SNAPSHOT")
    if str(snapshot.get("operator_id") or "") != str(operator_id or ""):
        raise ApprovalTargetError("INVALID_APPROVAL_SNAPSHOT")
    try:
        expires_at = datetime.fromisoformat(str(snapshot.get("expires_at") or ""))
    except ValueError as exc:
        raise ApprovalTargetError("STALE_APPROVAL_SNAPSHOT") from exc
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    if expires_at < datetime.now(ZoneInfo("Asia/Seoul")):
        raise ApprovalTargetError("STALE_APPROVAL_SNAPSHOT")
    current = build_current_approval_target(run_id=run_id, meta=meta, saved_html=saved_html)
    if str(snapshot.get("approval_target_sha256") or "") != str(
        current.snapshot_fields.get("approval_target_sha256") or ""
    ):
        raise ApprovalTargetError("APPROVAL_TARGET_CHANGED")
    return snapshot, current
