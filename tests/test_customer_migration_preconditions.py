"""Phase 2 migration safety.

Proves the two cases that matter for `session_token_hash NOT NULL`:

  CASE A - the expected fresh customer DB migrates cleanly.
  CASE B - an unexpected pre-existing browser_session row makes the migration
           REFUSE, and that row is still there afterwards.

These build their own throwaway database rather than using the shared migrated
fixture, because the whole point is to control what exists at each revision.
"""

import datetime as dt
import os
import uuid

import pytest

sa = pytest.importorskip("sqlalchemy", reason="SQLAlchemy not installed")
pytest.importorskip("alembic", reason="Alembic not installed")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from tests.customer_db_fixtures import (  # noqa: E402
    CUSTOMER_TEST_DATABASE_URL_ENV,
    REPO_ROOT,
    requires_customer_db,
)

pytestmark = requires_customer_db

PHASE_1_HEAD = "36e752113d5e"
PHASE_2_HEAD = "847937edd08e"

UTC = dt.timezone.utc


def _alembic_config(url):
    config = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    config.set_main_option(
        "script_location", os.path.join(REPO_ROOT, "customer/migrations")
    )
    os.environ["CUSTOMER_DATABASE_URL"] = url
    return config


@pytest.fixture()
def scratch_database():
    """A dedicated empty database, dropped afterwards.

    Created via a separate connection to `postgres` with AUTOCOMMIT, since
    CREATE/DROP DATABASE cannot run inside a transaction.
    """
    base_url = os.environ.get(CUSTOMER_TEST_DATABASE_URL_ENV, "").strip()
    if not base_url:  # pragma: no cover - guarded by requires_customer_db
        pytest.skip("no customer test database configured")

    name = "genie_migration_precondition_{0}".format(uuid.uuid4().hex[:10])
    admin_url = base_url.replace("/genie_customer_test?", "/postgres?")
    admin_engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(sa.text('CREATE DATABASE "{0}"'.format(name)))

    scratch_url = base_url.replace("/genie_customer_test?", "/{0}?".format(name))
    previous = os.environ.get("CUSTOMER_DATABASE_URL")
    try:
        yield scratch_url
    finally:
        if previous is None:
            os.environ.pop("CUSTOMER_DATABASE_URL", None)
        else:
            os.environ["CUSTOMER_DATABASE_URL"] = previous
        with admin_engine.connect() as connection:
            connection.execute(
                sa.text(
                    'DROP DATABASE IF EXISTS "{0}" WITH (FORCE)'.format(name)
                )
            )
        admin_engine.dispose()


def _insert_phase1_browser_session(url):
    """Insert a row that is valid under the Phase 1 schema only."""
    engine = sa.create_engine(url)
    now = dt.datetime.now(UTC)
    with engine.begin() as connection:
        person_id = uuid.uuid4()
        account_id = uuid.uuid4()
        session_id = uuid.uuid4()
        connection.execute(
            sa.text(
                "INSERT INTO person_identity "
                "(id, idv_stable_key, idv_provider, adult_verified, "
                " adult_verified_at, created_at, updated_at) "
                "VALUES (:id, :k, 'test_idv', TRUE, :now, :now, :now)"
            ),
            {"id": person_id, "k": "DI-legacy-{0}".format(uuid.uuid4().hex[:8]), "now": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO customer_account "
                "(id, person_id, account_email, status, created_at, updated_at) "
                "VALUES (:id, :pid, :email, 'active', :now, :now)"
            ),
            {
                "id": account_id,
                "pid": person_id,
                "email": "legacy@example.com",
                "now": now,
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO browser_session "
                "(id, account_id, remember_login, absolute_expires_at, "
                " inactivity_expires_at, last_seen_at, created_at) "
                "VALUES (:id, :aid, FALSE, :abs, :inact, :now, :now)"
            ),
            {
                "id": session_id,
                "aid": account_id,
                "abs": now + dt.timedelta(hours=12),
                "inact": now + dt.timedelta(hours=2),
                "now": now,
            },
        )
    engine.dispose()
    return session_id


def _browser_session_count(url):
    engine = sa.create_engine(url)
    with engine.connect() as connection:
        count = connection.execute(
            sa.text("SELECT count(*) FROM browser_session")
        ).scalar_one()
    engine.dispose()
    return count


def _current_revision(url):
    engine = sa.create_engine(url)
    with engine.connect() as connection:
        revision = connection.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    engine.dispose()
    return revision


# ---------------------------------------------------------------------------
# CASE A - expected fresh customer database
# ---------------------------------------------------------------------------


def test_case_a_fresh_database_migrates_through_both_revisions(scratch_database):
    config = _alembic_config(scratch_database)

    command.upgrade(config, PHASE_1_HEAD)
    assert _browser_session_count(scratch_database) == 0

    command.upgrade(config, "head")

    assert _current_revision(scratch_database) == PHASE_2_HEAD


# ---------------------------------------------------------------------------
# CASE B - unexpected legacy session row
# ---------------------------------------------------------------------------


def test_case_b_existing_session_makes_the_migration_refuse(scratch_database):
    """The migration must stop rather than delete or fabricate a credential."""
    config = _alembic_config(scratch_database)
    command.upgrade(config, PHASE_1_HEAD)
    _insert_phase1_browser_session(scratch_database)
    assert _browser_session_count(scratch_database) == 1

    with pytest.raises(Exception) as excinfo:
        command.upgrade(config, "head")

    message = str(excinfo.value)
    assert "MIGRATION PRECONDITION FAILED" in message
    assert "session_token_hash" in message


def test_case_b_existing_session_row_is_preserved(scratch_database):
    """No silent deletion: the row survives the refused migration."""
    config = _alembic_config(scratch_database)
    command.upgrade(config, PHASE_1_HEAD)
    session_id = _insert_phase1_browser_session(scratch_database)

    with pytest.raises(Exception):
        command.upgrade(config, "head")

    engine = sa.create_engine(scratch_database)
    with engine.connect() as connection:
        surviving = connection.execute(
            sa.text("SELECT count(*) FROM browser_session WHERE id = :i"),
            {"i": session_id},
        ).scalar_one()
    engine.dispose()

    assert surviving == 1


def test_case_b_schema_is_not_left_half_migrated(scratch_database):
    """The refusal rolls back inside the revision's transaction."""
    config = _alembic_config(scratch_database)
    command.upgrade(config, PHASE_1_HEAD)
    _insert_phase1_browser_session(scratch_database)

    with pytest.raises(Exception):
        command.upgrade(config, "head")

    assert _current_revision(scratch_database) == PHASE_1_HEAD

    engine = sa.create_engine(scratch_database)
    with engine.connect() as connection:
        has_column = connection.execute(
            sa.text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name='browser_session' "
                "AND column_name='session_token_hash'"
            )
        ).scalar_one()
    engine.dispose()

    assert has_column == 0


def test_migration_contains_no_unconditional_session_delete():
    """Static guard against reintroducing the silent-deletion strategy."""
    import pathlib

    versions = pathlib.Path(REPO_ROOT) / "customer" / "migrations" / "versions"
    for path in versions.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        normalized = " ".join(text.lower().split())
        assert "delete from browser_session" not in normalized, path.name
