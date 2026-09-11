"""Keep durable safety ledgers separate between independent test cases.

Persistence and concurrency tests deliberately share their own directory within
one case (including child processes). Production claims are never reset here.
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_admin_safety_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("GENIE_ADMIN_SAFETY_LOCAL_DIR", str(tmp_path / "admin_safety"))
