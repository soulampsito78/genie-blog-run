"""Internal job endpoints (compatibility only — no active timeout customer send)."""
from __future__ import annotations

from typing import Any, Dict


def process_approval_timeouts(*, now: Any = None, limit: int = 500) -> Dict[str, Any]:
    """
    Compatibility no-op: timeout-based customer auto-send was removed from active policy.
    Historical artifacts with sent_after_timeout remain display-only.
    """
    _ = now
    _ = limit
    return {
        "ok": True,
        "retired": True,
        "sent": 0,
        "eligible": 0,
        "skipped": 0,
        "errors": 0,
        "run_ids_sent": [],
        "skip_reasons": {},
        "error_run_ids": [],
        "note": "timeout customer send retired",
    }
