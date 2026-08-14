"""Helpers for approval tests that exercise the immutable snapshot boundary."""
from __future__ import annotations

import os
import tempfile
from unittest import mock

from admin_approval import create_approval_snapshot
from admin_store import approve_run, load_run_artifact, load_run_email_html


def approve_run_with_snapshot(run_id: str, **kwargs):
    operator_id = "test_operator"
    meta = load_run_artifact(run_id) or {}
    saved_html = load_run_email_html(run_id) or ""
    with tempfile.TemporaryDirectory() as safety_dir:
        with mock.patch.dict(
            os.environ,
            {
                "GENIE_ADMIN_SAFETY_LOCAL_DIR": safety_dir,
                "GENIE_ADMIN_ALLOW_LOCAL_SAFETY_STORE": "1",
            },
        ):
            snapshot, _ = create_approval_snapshot(
                run_id=run_id,
                meta=meta,
                saved_html=saved_html,
                operator_id=operator_id,
            )
            return approve_run(
                run_id,
                approval_snapshot_id=str(snapshot["approval_snapshot_id"]),
                operator_id=operator_id,
                **kwargs,
            )
