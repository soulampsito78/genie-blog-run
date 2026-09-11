#!/usr/bin/env python3
"""Exercise delegation CAS semantics against an isolated real-GCS prefix.

This verification never reads or writes the production delegation pointer.  It
leaves a small immutable evidence namespace in the configured artifact bucket
so the result can be audited after the release decision.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-id", required=True)
    args = parser.parse_args()
    evidence_id = str(args.evidence_id).strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{7,63}", evidence_id):
        raise RuntimeError("invalid_evidence_id")
    if not os.getenv("GENIE_ADMIN_ARTIFACT_BUCKET", "").strip():
        raise RuntimeError("GENIE_ADMIN_ARTIFACT_BUCKET_required")

    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    import admin_beta_delegation as delegation
    import admin_safety_store as store
    import admin_store
    import email_sender
    from delegated_delivery_safety import DeliverySafetyError

    if not store._uses_gcs_backend():
        raise RuntimeError("real_gcs_backend_required")
    isolated_prefix = f"admin_safety_validation/admin_beta_cas/{evidence_id}"
    store.SAFETY_PREFIX = isolated_prefix

    recipients = [f"gcs-cas-{index:02d}@example.test" for index in range(12)]
    admin_store.load_beta_recipient_config = lambda: {
        "recipients": recipients,
        "disabled_recipients": [],
        "version": 1,
        "load_ok": True,
    }
    email_sender.parse_customer_to_addrs = lambda: []
    now = datetime.now(timezone.utc)
    grant = delegation.activate_admin_beta_delegation(
        products=delegation.ALLOWED_MODES,
        operator_id="isolated-gcs-cas-verifier",
        now=now,
    )
    loaded = delegation.load_active_admin_beta_delegation()
    if loaded.get("grant_id") != grant.get("grant_id"):
        raise RuntimeError("immutable_grant_readback_failed")

    pointer, generation = delegation._read_current_with_generation()
    revoked = {
        "schema": delegation.DELEGATION_SCHEMA,
        "status": "REVOKED",
        "grant_id": grant["grant_id"],
        "operator_id": "isolated-gcs-cas-verifier",
        "reason": "actual-gcs-generation-conflict-test",
        "revoked_at": now.isoformat(),
    }
    delegation._compare_and_swap_current(generation, revoked)
    conflict_observed = False
    try:
        delegation._compare_and_swap_current(generation, pointer)
    except DeliverySafetyError as exc:
        conflict_observed = str(exc) == "ADMIN_BETA_DELEGATION_STATE_CONFLICT"
    if not conflict_observed:
        raise RuntimeError("actual_gcs_generation_conflict_not_observed")

    revoked_pointer, revoked_generation = delegation._read_current_with_generation()
    if revoked_pointer != revoked or revoked_generation == generation:
        raise RuntimeError("revocation_readback_failed")

    # Simulate the transport reporting an error after GCS committed the write.
    # The caller must fail closed, while a fresh read reconciles the committed
    # pointer and prevents any stale generation from overwriting it.
    real_bucket = store._get_gcs_bucket()
    uncertain_payload = {
        "schema": delegation.DELEGATION_SCHEMA,
        "status": "TEST_UNCERTAIN_COMMITTED",
        "grant_id": grant["grant_id"],
        "at": now.isoformat(),
    }

    class UncertainBlob:
        def __init__(self, blob):
            self._blob = blob

        def upload_from_string(self, *call_args, **call_kwargs):
            self._blob.upload_from_string(*call_args, **call_kwargs)
            raise RuntimeError("simulated_response_lost_after_commit")

    class UncertainBucket:
        def blob(self, name):
            return UncertainBlob(real_bucket.blob(name))

    original_bucket_factory = store._get_gcs_bucket
    store._get_gcs_bucket = lambda: UncertainBucket()
    unavailable_observed = False
    try:
        delegation._compare_and_swap_current(revoked_generation, uncertain_payload)
    except DeliverySafetyError as exc:
        unavailable_observed = str(exc) == "ADMIN_BETA_DELEGATION_STATE_UNAVAILABLE"
    finally:
        store._get_gcs_bucket = original_bucket_factory
    if not unavailable_observed:
        raise RuntimeError("uncertain_write_did_not_fail_closed")

    reconciled, reconciled_generation = delegation._read_current_with_generation()
    if reconciled != uncertain_payload or reconciled_generation == revoked_generation:
        raise RuntimeError("uncertain_write_readback_failed")
    stale_after_uncertain = False
    try:
        delegation._compare_and_swap_current(revoked_generation, revoked)
    except DeliverySafetyError as exc:
        stale_after_uncertain = str(exc) == "ADMIN_BETA_DELEGATION_STATE_CONFLICT"
    if not stale_after_uncertain:
        raise RuntimeError("stale_write_after_uncertain_commit_not_blocked")

    result = {
        "ok": True,
        "backend": "gcs",
        "isolated_prefix": isolated_prefix,
        "immutable_grant_readback": True,
        "recipient_count": loaded["recipient_count"],
        "generation_conflict_observed": True,
        "revocation_readback": True,
        "uncertain_write_failed_closed": True,
        "uncertain_write_reconciled_by_readback": True,
        "stale_write_after_uncertain_commit_blocked": True,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
