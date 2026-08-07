"""Public admin/review URL helpers for owner-review email links."""
from __future__ import annotations

import os
from typing import Optional

from admin_store import validate_run_id


def resolve_admin_public_base_url() -> str:
    """Return configured public base URL for admin UI (no trailing slash)."""
    for key in ("GENIE_ADMIN_PUBLIC_BASE_URL", "GENIE_PUBLIC_BASE_URL"):
        raw = os.getenv(key, "").strip().rstrip("/")
        if raw:
            return raw
    return ""


def build_owner_review_admin_url(run_id: str) -> Optional[str]:
    """Build owner-review admin detail URL for a run_id (no secrets in URL)."""
    rid = str(run_id or "").strip()
    if not rid or not validate_run_id(rid):
        return None
    base = resolve_admin_public_base_url()
    if not base:
        return None
    return f"{base}/admin/runs/{rid}"


def build_incident_admin_url(incident_id: str) -> Optional[str]:
    """Build Admin incident detail deep-link (view-only GET; no secrets)."""
    from natural_run_incident_store import validate_incident_id

    iid = str(incident_id or "").strip()
    if not iid or not validate_incident_id(iid):
        return None
    base = resolve_admin_public_base_url()
    if not base:
        return None
    # Reject obviously non-public bases (localhost / internal hosts).
    lowered = base.lower()
    if "localhost" in lowered or "127.0.0.1" in lowered or lowered.startswith("http://10."):
        return None
    return f"{base}/admin/incidents/{iid}"
