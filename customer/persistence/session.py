"""Engine / session boundary for the customer database.

Phase 1 scope: enough wiring to prove models import, metadata registers, and a
transactional session boundary exists for future customer APIs. No FastAPI
routes, no application startup hooks, and no changes to `main.py`.

SAFETY:
  - There is NO default database URL. If `CUSTOMER_DATABASE_URL` is unset this
    module raises rather than guessing, so nothing can silently point at a
    developer's default local database - let alone production.
  - Only `postgresql+psycopg://` URLs are accepted. SQLite is rejected outright
    because several invariants in this schema are partial indexes and deferred
    constraint triggers that SQLite cannot enforce; permitting it would mean
    tests that pass against a weaker schema than production runs.
  - This module never issues DDL. Schema authority is Alembic only.
"""

import os
from typing import Iterator, Optional

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

#: Environment variable holding the customer database URL.
CUSTOMER_DATABASE_URL_ENV = "CUSTOMER_DATABASE_URL"

_SUPPORTED_URL_PREFIXES = ("postgresql+psycopg://", "postgresql://")

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


class CustomerDatabaseNotConfigured(RuntimeError):
    """Raised when the customer database URL is missing or unsupported."""


def customer_database_url() -> str:
    """Return the configured customer database URL.

    Raises rather than defaulting: an implicit URL is how a test run ends up
    talking to something it should not.
    """
    raw = os.environ.get(CUSTOMER_DATABASE_URL_ENV, "").strip()
    if not raw:
        raise CustomerDatabaseNotConfigured(
            "{0} is not set. The customer backend has no default database URL; "
            "set it explicitly to a local or test PostgreSQL instance.".format(
                CUSTOMER_DATABASE_URL_ENV
            )
        )
    if not raw.startswith(_SUPPORTED_URL_PREFIXES):
        raise CustomerDatabaseNotConfigured(
            "Unsupported customer database URL scheme. PostgreSQL is required; "
            "this schema relies on partial indexes and deferred constraint "
            "triggers that other backends cannot enforce."
        )
    return raw


def create_customer_engine(url: Optional[str] = None, **kwargs) -> Engine:
    """Build a new Engine. Callers own its lifecycle."""
    return sa.create_engine(url or customer_database_url(), future=True, **kwargs)


def customer_engine() -> Engine:
    """Process-wide lazily created Engine."""
    global _engine
    if _engine is None:
        _engine = create_customer_engine()
    return _engine


def customer_session_factory() -> sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=customer_engine(), expire_on_commit=False, future=True
        )
    return _session_factory


def customer_session() -> Iterator[Session]:
    """Transactional session scope.

    Commits on success, rolls back on any exception. Suitable as a FastAPI
    dependency for future customer routes.

    Deliberately does NOT wrap external provider calls: a PG charge, IDV
    round-trip, or ESP submission inside this boundary would hold a database
    transaction open across the network and make an irreversible external
    effect look rollback-able. Call the provider first, then record the result.
    """
    session = customer_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_customer_engine() -> None:
    """Dispose and clear the cached engine (tests / config reload)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
