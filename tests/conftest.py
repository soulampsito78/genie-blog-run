"""Per-test durable roots for the C-2 execution reservation contract."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_execution_state_root(tmp_path, monkeypatch):
    monkeypatch.setenv("GENIE_EXECUTION_STATE_ROOT", str(tmp_path / "execution_state"))
    monkeypatch.setenv("GENIE_EXECUTION_LEASE_SECONDS", "120")
