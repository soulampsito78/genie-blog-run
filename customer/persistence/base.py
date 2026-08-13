"""Declarative base, metadata, and shared column helpers.

PostgreSQL-first: timestamps are `TIMESTAMP WITH TIME ZONE`, identifiers are
UUIDs, and bounded metadata uses JSONB. SQLite is not a supported target for
this schema (the repository does not use SQLite for tests, and several
invariants here are partial indexes / deferred constraint triggers that SQLite
cannot express). Constraints are never weakened to accommodate a lesser
backend.
"""

import uuid
from typing import Any, Dict, Optional

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: Deterministic constraint names. Without this, Alembic autogenerate produces
#: backend-assigned names and every drift check reports phantom differences.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

customer_metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


class CustomerBase(DeclarativeBase):
    """Base for every customer-domain ORM model."""

    metadata = customer_metadata

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        pk = sa.inspect(self).identity
        return "<{0} {1}>".format(type(self).__name__, pk)


def uuid_pk() -> Mapped[uuid.UUID]:
    """Opaque UUID primary key, generated client-side so callers can build an
    object graph (subscription + products + snapshot) before flushing."""
    return mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


def created_at_column() -> Mapped[Any]:
    """Server-side creation timestamp (the DB clock is the audit clock)."""
    return mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def updated_at_column() -> Mapped[Any]:
    return mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


def json_metadata_column() -> Mapped[Dict[str, Any]]:
    """Bounded JSONB side-metadata.

    JSONB here is for genuinely open-shaped provider/context detail only. It
    MUST NOT be used to smuggle relational structure (product membership,
    state, prices) out of the schema, and MUST NOT contain card data, IDV
    payloads, tokens, or any other prohibited secret.
    """
    return mapped_column(
        postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )


def enum_check(column_name: str, enum_cls: Any, constraint_name: str) -> sa.CheckConstraint:
    """CHECK constraining a VARCHAR column to an application enum's values."""
    rendered = ", ".join(
        "'{0}'".format(value.replace("'", "''")) for value in enum_cls.values()
    )
    return sa.CheckConstraint(
        "{0} IN ({1})".format(column_name, rendered), name=constraint_name
    )


def enum_column(
    enum_cls: Any, *, nullable: bool = False, length: int = 40
) -> Mapped[Optional[str]]:
    """Constrained-string enum column (see customer.domain.enums rationale)."""
    return mapped_column(sa.String(length), nullable=nullable)
