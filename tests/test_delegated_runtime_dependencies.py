"""Deployment-image contract for the co-located delegated delivery adapter."""
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("dockerfile", ["Dockerfile", "Dockerfile.worker"])
def test_runtime_images_install_customer_authority_dependencies(dockerfile):
    text = (ROOT / dockerfile).read_text(encoding="utf-8")

    assert "COPY requirements.txt requirements-customer.txt ./" in text
    assert "pip install -r requirements.txt -r requirements-customer.txt" in text


def test_customer_runtime_declares_postgres_driver_and_orm():
    text = (ROOT / "requirements-customer.txt").read_text(encoding="utf-8")

    assert "SQLAlchemy" in text
    assert "psycopg[binary]" in text
