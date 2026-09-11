"""Existing pre-review repair remains; frozen/Work-held runs stay manual."""
import hashlib
import subprocess
import sys
from unittest.mock import patch

import pytest

import admin_safety_store as store
from auto_remediation import plan_auto_remediation
from tests.test_auto_remediation_20260909 import today_meta


def test_unfrozen_existing_generation_repair_remains_available():
    assert plan_auto_remediation(today_meta()).eligible


def test_persistent_received_binding_blocks_automatic_repair_after_restart():
    meta = today_meta()
    key = "delegated_received_bindings/" + hashlib.sha256(meta["run_id"].encode()).hexdigest() + ".json"
    assert store._create_json_once(key, {"run_id": meta["run_id"]})
    for _ in range(2):
        result = subprocess.run([sys.executable, "-c",
            "from auto_remediation import plan_auto_remediation; "
            "from tests.test_auto_remediation_20260909 import today_meta; "
            "p=plan_auto_remediation(today_meta()); print(p.eligible,p.stop_reason)"],
            check=True, capture_output=True, text=True)
        assert result.stdout.strip() == "False delegated_candidate_frozen_manual_recovery_required"


@pytest.mark.parametrize("status", ["PASS", "HOLD_ANOMALY", "HOLD_INCOMPLETE", "REVIEW_UNAVAILABLE", "STATE_CONFLICT"])
def test_any_completed_work_review_requires_manual_recovery(status):
    result = plan_auto_remediation(today_meta(delegated_review_status=status))
    assert not result.eligible
    assert result.stop_reason == "delegated_review_requires_manual_recovery"


def test_unknown_persistent_boundary_does_not_trigger_generation():
    with patch.object(store, "_uses_gcs_backend", side_effect=OSError("unavailable")):
        result = plan_auto_remediation(today_meta())
    assert not result.eligible
    assert result.stop_reason == "delegated_review_boundary_unavailable"
