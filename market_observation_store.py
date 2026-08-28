"""Durable memory of the last settled observation per instrument.

A briefing that runs late — a recovery run, an owner reissue — asks a live
quote endpoint a question only a completed session can answer, and gets back
whatever the market is doing at that moment. Blocking is the safe response,
but it is not the useful one: the correct settled observation was already in
hand when the scheduled run executed.

This store keeps that observation so a later run repairs from it instead of
either publishing a live tape or failing outright. It holds only observations
that already passed the settlement contract, so reusing one can never
introduce a fact that was not established at capture time.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from market_observation import PUBLISHABLE_STATUSES

logger = logging.getLogger(__name__)

STORE_SCHEMA_VERSION = "settled_market_observation_v1"
_STORE_PREFIX = "runtime_feed_cache"

# A settled close older than this is no longer a usable stand-in for "the last
# completed session" — better to block than to publish a week-old tape.
MAX_REPAIR_AGE_DAYS = 5


def _object_key(program: str, instrument: str) -> str:
    safe = "".join(ch for ch in instrument.upper() if ch.isalnum() or ch in "._-")
    return f"{_STORE_PREFIX}/{program}/settled_index/{safe}.json"


def read_settled_observation(program: str, instrument: str) -> Optional[Dict[str, Any]]:
    """Last stored settled observation, or None when unavailable."""
    try:
        from admin_store import _gcs_download_text, admin_artifact_bucket_name

        if not admin_artifact_bucket_name():
            return None
        raw = _gcs_download_text(_object_key(program, instrument))
    except Exception as exc:  # noqa: BLE001 - the store is an optimisation, never a dependency.
        logger.warning(
            "settled observation read failed instrument=%s error_type=%s",
            instrument,
            type(exc).__name__,
        )
        return None
    if not raw:
        return None
    try:
        record = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    observation = record.get("observation")
    if not isinstance(observation, dict):
        return None
    if observation.get("observation_status") not in PUBLISHABLE_STATUSES:
        return None
    return observation


def write_settled_observation(
    program: str,
    instrument: str,
    observation: Dict[str, Any],
    *,
    captured_at: str,
) -> str:
    """Persist a settled observation. Never raises into the calling run."""
    if observation.get("observation_status") not in PUBLISHABLE_STATUSES:
        return "skipped_not_settled"
    try:
        from admin_store import _gcs_upload_text, admin_artifact_bucket_name

        if not admin_artifact_bucket_name():
            return "skipped_no_gcs_backend"
        record = {
            "schema_version": STORE_SCHEMA_VERSION,
            "program": program,
            "instrument": instrument,
            "captured_at": captured_at,
            "observation": observation,
        }
        _gcs_upload_text(
            _object_key(program, instrument),
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
            content_type="application/json",
        )
        return "written"
    except Exception as exc:  # noqa: BLE001 - a store failure must not fail the run.
        logger.warning(
            "settled observation write failed instrument=%s error_type=%s",
            instrument,
            type(exc).__name__,
        )
        return f"failed:{type(exc).__name__}"
