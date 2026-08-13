"""Alembic integrity: single head, no ORM drift, canonical seed, safe config."""

import os

import pytest

sa = pytest.importorskip("sqlalchemy", reason="SQLAlchemy not installed")
pytest.importorskip("alembic", reason="Alembic not installed")

from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

from tests.customer_db_fixtures import (  # noqa: E402
    REPO_ROOT,
    customer_engine,
    requires_customer_db,
    session,
)

__all__ = ["customer_engine", "session"]


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    config.set_main_option(
        "script_location", os.path.join(REPO_ROOT, "customer/migrations")
    )
    return ScriptDirectory.from_config(config)


def test_migration_history_has_exactly_one_head():
    """Two heads mean two competing schema truths."""
    assert len(_script_directory().get_heads()) == 1


def test_repository_declares_a_single_alembic_environment():
    """A second migration environment would split schema authority."""
    found = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in {".git", "__pycache__", "node_modules", "output", "venv"}
        ]
        if "alembic.ini" in filenames:
            found.append(os.path.join(dirpath, "alembic.ini"))

    assert found == [os.path.join(REPO_ROOT, "alembic.ini")]


def test_alembic_ini_contains_no_database_url():
    """Connection details must come from the environment, not the repository."""
    with open(os.path.join(REPO_ROOT, "alembic.ini"), "r", encoding="utf-8") as handle:
        content = handle.read()

    assert "sqlalchemy.url" not in content
    assert "postgresql://" not in content.replace("postgresql+psycopg://...", "")


@requires_customer_db
def test_orm_metadata_matches_the_migrated_schema(customer_engine):
    """Zero drift between the ORM models and what the migration produced."""
    import customer.persistence.models  # noqa: F401
    from customer.persistence.base import customer_metadata

    with customer_engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True, "compare_server_default": True},
        )
        diff = compare_metadata(context, customer_metadata)

    assert diff == [], "ORM/migration drift: {0}".format(diff)


@requires_customer_db
def test_seeded_products_are_the_three_canonical_briefings(session):
    from customer.persistence.models import Product

    codes = set(session.scalars(sa.select(Product.code)))

    assert codes == {"today_genie", "keysuri_global", "keysuri_korea"}


@requires_customer_db
@pytest.mark.parametrize(
    "plan_code,expected_price",
    [
        ("today_genie", 6600),
        ("keysuri_global", 9900),
        ("keysuri_korea", 6600),
        ("package_two", 11000),
        ("full_set", 16500),
    ],
)
def test_seeded_catalog_prices_are_canonical(session, plan_code, expected_price):
    from customer.persistence.models import PlanCatalog

    price = session.scalar(
        sa.select(PlanCatalog.price_krw).where(
            PlanCatalog.plan_code == plan_code, PlanCatalog.price_version == 1
        )
    )

    assert price == expected_price


@requires_customer_db
def test_seeded_catalog_is_vat_inclusive_krw(session):
    from customer.persistence.models import PlanCatalog

    rows = session.scalars(sa.select(PlanCatalog)).all()

    assert rows
    assert all(row.currency == "KRW" and row.vat_included for row in rows)


@requires_customer_db
def test_seeded_full_set_membership_is_all_three_products(session):
    from customer.persistence.models import PlanFixedProduct

    codes = set(
        session.scalars(
            sa.select(PlanFixedProduct.product_code).where(
                PlanFixedProduct.plan_code == "full_set"
            )
        )
    )

    assert codes == {"today_genie", "keysuri_global", "keysuri_korea"}


@requires_customer_db
def test_package_two_has_no_seeded_fixed_membership(session):
    from customer.persistence.models import PlanFixedProduct

    count = session.scalar(
        sa.select(sa.func.count())
        .select_from(PlanFixedProduct)
        .where(PlanFixedProduct.plan_code == "package_two")
    )

    assert count == 0


def test_session_module_refuses_to_default_a_database_url(monkeypatch):
    from customer.persistence.session import (
        CustomerDatabaseNotConfigured,
        customer_database_url,
    )

    monkeypatch.delenv("CUSTOMER_DATABASE_URL", raising=False)

    with pytest.raises(CustomerDatabaseNotConfigured):
        customer_database_url()


def test_session_module_rejects_non_postgresql_urls(monkeypatch):
    """SQLite would silently drop partial indexes and constraint triggers."""
    from customer.persistence.session import (
        CustomerDatabaseNotConfigured,
        customer_database_url,
    )

    monkeypatch.setenv("CUSTOMER_DATABASE_URL", "sqlite:///./customer.db")

    with pytest.raises(CustomerDatabaseNotConfigured):
        customer_database_url()
