"""File-based run artifacts for owner admin review and reissue tracking."""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

_RUN_ID_RE = re.compile(
    r"^[0-9]{8}_[0-9]{6}_(today_genie|tomorrow_genie)_[a-f0-9]{8}$"
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def admin_runs_dir() -> Path:
    d = repo_root() / "output" / "admin_runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def validate_run_id(run_id: str) -> bool:
    return bool(_RUN_ID_RE.match(str(run_id or "").strip()))


def generate_run_id(mode: str) -> str:
    kst = datetime.now(ZoneInfo("Asia/Seoul"))
    stamp = kst.strftime("%Y%m%d_%H%M%S")
    short = secrets.token_hex(4)
    safe_mode = mode if mode in ("today_genie", "tomorrow_genie") else "unknown"
    return f"{stamp}_{safe_mode}_{short}"


def artifact_json_path(run_id: str) -> Path:
    if not validate_run_id(run_id):
        raise ValueError("invalid run_id")
    return admin_runs_dir() / f"{run_id}.json"


def artifact_email_path(run_id: str) -> Path:
    if not validate_run_id(run_id):
        raise ValueError("invalid run_id")
    return admin_runs_dir() / f"{run_id}.email.html"


def derive_artifact_status(meta: Dict[str, Any]) -> str:
    if meta.get("parent_run_id"):
        if meta.get("email_sent"):
            return "reissued"
        if meta.get("artifact_status") == "failed":
            return "failed"
        return "reissued"
    if meta.get("response_status") not in (200, "200", None) and meta.get("response_status") is not None:
        if int(meta.get("response_status") or 0) != 200:
            return "failed"
    if meta.get("reason_summary") in ("request_failed", "invalid_response_body", "validation_block", "api_error"):
        if meta.get("response_status") != 200:
            return "failed"
    if meta.get("email_sent"):
        return "emailed"
    wf = str(meta.get("workflow_status") or "")
    vr = str(meta.get("validation_result") or "")
    if wf == "review_required" or vr == "draft_only":
        return "review_required"
    if vr == "pass" or wf == "validated":
        return "validated"
    if meta.get("response_status") == 200:
        return "generated"
    return "failed"


def save_run_artifact(
    meta: Dict[str, Any],
    email_html: str = "",
) -> str:
    run_id = str(meta.get("run_id") or "").strip()
    if not run_id:
        run_id = generate_run_id(str(meta.get("mode") or "unknown"))
        meta["run_id"] = run_id
    if not validate_run_id(run_id):
        raise ValueError("invalid run_id in metadata")

    meta = dict(meta)
    if "created_at" not in meta:
        meta["created_at"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    meta["artifact_status"] = derive_artifact_status(meta)

    artifact_json_path(run_id).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if email_html and email_html.strip():
        artifact_email_path(run_id).write_text(email_html, encoding="utf-8")

    parent_id = str(meta.get("parent_run_id") or "").strip()
    if parent_id and validate_run_id(parent_id):
        _increment_parent_reissue_count(parent_id)

    return run_id


def _increment_parent_reissue_count(parent_run_id: str) -> None:
    path = artifact_json_path(parent_run_id)
    if not path.is_file():
        return
    try:
        parent = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(parent, dict):
        return
    parent["reissue_count"] = int(parent.get("reissue_count") or 0) + 1
    parent["artifact_status"] = "reissue_requested"
    path.write_text(json.dumps(parent, ensure_ascii=False, indent=2), encoding="utf-8")


def load_run_artifact(run_id: str) -> Optional[Dict[str, Any]]:
    if not validate_run_id(run_id):
        return None
    path = artifact_json_path(run_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def load_run_email_html(run_id: str) -> Optional[str]:
    if not validate_run_id(run_id):
        return None
    path = artifact_email_path(run_id)
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def list_run_artifacts(limit: int = 50) -> List[Dict[str, Any]]:
    root = admin_runs_dir()
    files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: List[Dict[str, Any]] = []
    for path in files[: max(1, limit)]:
        run_id = path.stem
        if not validate_run_id(run_id):
            continue
        meta = load_run_artifact(run_id)
        if meta:
            out.append(meta)
    return out
