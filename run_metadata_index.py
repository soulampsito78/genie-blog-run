"""Small per-run summaries used by the watchdog instead of large artifacts."""
from __future__ import annotations

import heapq
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from artifact_atomic import atomic_write_text
from delivery_status import is_customer_delivery_terminal_success, is_owner_review_accepted
from execution_state import SCHEDULED_SLOTS, build_logical_execution_key, scheduled_at_for_key

GCS_LIST_PAGE_SIZE = 250
GCS_LIST_SCAN_LIMIT = 10_000

INDEX_FIELDS = (
    "run_id",
    "logical_execution_key",
    "program_id",
    "mode",
    "scheduled_at_kst",
    "current_stage",
    "owner_email_delivery_status",
    "customer_delivery_status",
    "retry_count",
    "terminal_status",
    "validation_result",
    "selected_count",
    "required_count",
    "shortfall_count",
    "required_images_complete",
    "artifact_manifest_state",
    "business_success_event_emitted",
    "watchdog_deadline_event_emitted",
)


def summary_from_artifact(meta: Dict[str, Any]) -> Dict[str, Any]:
    out = {key: meta.get(key) for key in INDEX_FIELDS if key in meta}
    out["schema_version"] = "run_metadata_index_v1"
    out["run_id"] = str(meta.get("run_id") or "")
    out["program_id"] = str(meta.get("program_id") or meta.get("mode") or "")
    logical_key = str(meta.get("logical_execution_key") or "")
    trigger = str(meta.get("trigger_source") or "")
    if not logical_key and trigger.lower().startswith("scheduled") and out["program_id"] in SCHEDULED_SLOTS:
        created = str(meta.get("created_at") or "")
        scheduled_date = created[:10] if len(created) >= 10 else ""
        run_id = out["run_id"]
        if not scheduled_date and len(run_id) >= 8 and run_id[:8].isdigit():
            scheduled_date = f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}"
        if scheduled_date:
            logical_key = build_logical_execution_key(
                program_id=out["program_id"],
                scheduled_date_kst=scheduled_date,
                scheduled_slot_kst=SCHEDULED_SLOTS[out["program_id"]],
                trigger_source="scheduled",
            )
    if logical_key:
        out["logical_execution_key"] = logical_key
        out["scheduled_at_kst"] = str(meta.get("scheduled_at_kst") or scheduled_at_for_key(logical_key))
    owner_delivery = meta.get("owner_email_delivery_status")
    if owner_delivery in (None, "") and meta.get("email_sent") is True:
        owner_delivery = "smtp_accepted"
    out["owner_review_accepted"] = is_owner_review_accepted(owner_delivery)
    out["customer_delivery_accepted"] = is_customer_delivery_terminal_success(
        meta.get("customer_delivery_status")
    )
    out["updated_at"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    return out


def _local_root() -> Path:
    raw = os.getenv("GENIE_METADATA_INDEX_ROOT", "").strip()
    if raw:
        root = Path(raw)
    else:
        from admin_store import admin_runs_dir

        root = admin_runs_dir() / "metadata_index"
    root.mkdir(parents=True, exist_ok=True)
    return root


def update_run_metadata_index(meta: Dict[str, Any]) -> None:
    summary = summary_from_artifact(meta)
    run_id = summary["run_id"]
    if not run_id:
        return
    raw = os.getenv("GENIE_METADATA_INDEX_ROOT", "").strip()
    from admin_store import admin_artifact_bucket_name

    if admin_artifact_bucket_name() and not raw:
        from admin_store import _gcs_atomic_update_json, admin_artifact_gcs_prefix

        key = f"{admin_artifact_gcs_prefix()}/metadata_index/{run_id}.json"

        def _replace(current: Dict[str, Any]) -> None:
            current.clear()
            current.update(summary)

        _gcs_atomic_update_json(key, mutator=_replace)
        return
    atomic_write_text(
        _local_root() / f"{run_id}.json",
        json.dumps(summary, ensure_ascii=False, indent=2),
    )


def list_recent_metadata(*, limit: int = 100) -> List[Dict[str, Any]]:
    raw = os.getenv("GENIE_METADATA_INDEX_ROOT", "").strip()
    from admin_store import admin_artifact_bucket_name

    rows: List[Dict[str, Any]] = []
    if admin_artifact_bucket_name() and not raw:
        from admin_store import _get_gcs_bucket, admin_artifact_gcs_prefix

        prefix = f"{admin_artifact_gcs_prefix()}/metadata_index/"
        requested = max(1, int(limit))
        iterator = _get_gcs_bucket().list_blobs(prefix=prefix, page_size=GCS_LIST_PAGE_SIZE)
        pages = getattr(iterator, "pages", None)
        if pages is None:
            pages = (iterator,)

        newest: list[tuple[float, int, Any]] = []
        scanned = 0
        for page in pages:
            for blob in page:
                scanned += 1
                if scanned > GCS_LIST_SCAN_LIMIT:
                    raise RuntimeError("metadata_index_scan_limit_exceeded")
                updated = getattr(blob, "updated", None)
                if isinstance(updated, datetime):
                    if updated.tzinfo is None:
                        updated = updated.replace(tzinfo=ZoneInfo("UTC"))
                    timestamp = updated.timestamp()
                else:
                    timestamp = float("-inf")
                candidate = (timestamp, scanned, blob)
                if len(newest) < requested:
                    heapq.heappush(newest, candidate)
                elif candidate[:2] > newest[0][:2]:
                    heapq.heapreplace(newest, candidate)

        blobs = [entry[2] for entry in sorted(newest, key=lambda entry: entry[:2], reverse=True)]
        for blob in blobs:
            data = json.loads(blob.download_as_text(encoding="utf-8"))
            if isinstance(data, dict):
                rows.append(data)
        return rows
    files = sorted(_local_root().glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in files[: max(1, limit)]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            rows.append(data)
    return rows


def claim_watchdog_event(logical_execution_key: str) -> bool:
    """Atomically claim one deadline event for an expected logical slot."""
    import hashlib

    token = hashlib.sha256(logical_execution_key.encode("utf-8")).hexdigest()
    payload = json.dumps(
        {
            "schema_version": "watchdog_event_claim_v1",
            "logical_execution_key": logical_execution_key,
            "claimed_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
        },
        ensure_ascii=False,
    )
    raw = os.getenv("GENIE_METADATA_INDEX_ROOT", "").strip()
    from admin_store import admin_artifact_bucket_name

    if admin_artifact_bucket_name() and not raw:
        from admin_store import _gcs_upload_text, admin_artifact_gcs_prefix

        try:
            _gcs_upload_text(
                f"{admin_artifact_gcs_prefix()}/watchdog_claims/{token}.json",
                payload,
                content_type="application/json",
                if_generation_match=0,
            )
            return True
        except Exception as exc:
            if type(exc).__name__ in {"PreconditionFailed", "Conflict"}:
                return False
            raise
    root = _local_root() / "watchdog_claims"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{token}.json"
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(payload)
    return True
