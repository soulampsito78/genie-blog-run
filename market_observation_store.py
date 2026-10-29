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
from typing import Any, Dict, Optional, Tuple

from market_observation import PUBLISHABLE_STATUSES, _iso_date

logger = logging.getLogger(__name__)

STORE_SCHEMA_VERSION = "settled_market_observation_v1"
_STORE_PREFIX = "runtime_feed_cache"

# A settled close older than this is no longer a usable stand-in for "the last
# completed session" — better to block than to publish a week-old tape.
MAX_REPAIR_AGE_DAYS = 5


def _object_key(program: str, instrument: str) -> str:
    safe = "".join(ch for ch in instrument.upper() if ch.isalnum() or ch in "._-")
    return f"{_STORE_PREFIX}/{program}/settled_index/{safe}.json"


def _read_record_with_generation(
    program: str, instrument: str
) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
    """Read stored record along with its integer storage generation.

    Returns:
      (record, generation):
        - (None, 0): Confirmed NotFound (object does not exist, CAS generation 0).
        - (record_dict, gen_int): Valid record read pinned to generation gen_int (gen_int > 0).
        - (None, None): Read error, network/auth failure, or invalid/malformed generation/JSON (fail closed).
    """
    try:
        from admin_store import _get_gcs_bucket, admin_artifact_bucket_name

        if not admin_artifact_bucket_name():
            return None, None
        blob = _get_gcs_bucket().blob(_object_key(program, instrument))
        if not blob.exists():
            return None, 0
        blob.reload()
        raw_gen = blob.generation
        if raw_gen is None:
            return None, None
        try:
            gen = int(raw_gen)
        except (ValueError, TypeError):
            return None, None
        if gen <= 0:
            return None, None
        # Pin download to the exact generation read (same as admin_store)
        raw = blob.download_as_text(encoding="utf-8", if_generation_match=gen)
        if not raw:
            return None, None
        record = json.loads(raw)
        if not isinstance(record, dict):
            return None, None
        return record, gen
    except Exception as exc:  # noqa: BLE001 - fail closed on any read error
        logger.warning(
            "settled observation read failed instrument=%s error_type=%s",
            instrument,
            type(exc).__name__,
        )
        return None, None


def read_settled_observation(program: str, instrument: str) -> Optional[Dict[str, Any]]:
    """Last stored settled observation, or None when unavailable."""
    record, _ = _read_record_with_generation(program, instrument)
    if not record:
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
    """Persist a settled observation monotonically by market_date with GCS generation-CAS.

    Monotonicity & CAS rules:
    - Never overwrite an existing settled observation with an older market_date.
    - If generation is unknown, malformed, or existing read failed: fail closed without ANY upload.
    - If existing record is present but observation/date cannot be validated: return skipped_unverified_existing_observation without ANY upload.
    - Only confirmed NotFound gets generation 0 (create if not exists); existing generations must be positive integers.
    - Pin downloaded existing bytes to generation read so date and CAS refer to the exact same object.
    - Same-date correction is preserved only with valid CAS.
    - Concurrent modifications return 'conflict'.
    - Preserves prior failure bytes and performs no deletes.
    """
    try:
        if observation.get("observation_status") not in PUBLISHABLE_STATUSES:
            return "skipped_not_settled"

        new_market_date = _iso_date(observation.get("market_date"))
        if new_market_date is None:
            return "skipped_invalid_market_date"

        from admin_store import _get_gcs_bucket, admin_artifact_bucket_name

        if not admin_artifact_bucket_name():
            return "skipped_no_gcs_backend"

        existing_record, generation = _read_record_with_generation(program, instrument)
        if generation is None:
            # Read error, malformed generation, or unverified backend state -> fail closed, NEVER upload unconditionally
            return "skipped_unverified_existing_generation"

        if existing_record is not None:
            existing_obs = existing_record.get("observation")
            if not isinstance(existing_obs, dict):
                return "skipped_unverified_existing_observation"
            existing_market_date = _iso_date(existing_obs.get("market_date"))
            if existing_market_date is None:
                return "skipped_unverified_existing_observation"
            if new_market_date < existing_market_date:
                logger.warning(
                    "refusing non-monotonic settled observation write instrument=%s "
                    "existing_market_date=%s incoming_market_date=%s",
                    instrument,
                    existing_market_date.isoformat(),
                    new_market_date.isoformat(),
                )
                return "skipped_older_market_date"

        record = {
            "schema_version": STORE_SCHEMA_VERSION,
            "program": program,
            "instrument": instrument,
            "captured_at": captured_at,
            "observation": observation,
        }
        payload = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True)

        blob = _get_gcs_bucket().blob(_object_key(program, instrument))
        kwargs: Dict[str, Any] = {
            "content_type": "application/json",
            "if_generation_match": generation,
        }
        blob.upload_from_string(payload, **kwargs)
        return "written"
    except Exception as exc:  # noqa: BLE001 - a store failure must not fail the run.
        if getattr(exc, "code", None) in (409, 412) or exc.__class__.__name__ in {
            "Conflict",
            "PreconditionFailed",
        }:
            logger.warning(
                "settled observation write conflict instrument=%s error_type=%s",
                instrument,
                type(exc).__name__,
            )
            return "conflict"
        logger.warning(
            "settled observation write failed instrument=%s error_type=%s",
            instrument,
            type(exc).__name__,
        )
        return f"failed:{type(exc).__name__}"
