"""Append-oriented audit event and command idempotency.

Audit covers the sensitive lifecycle surface: identity, subscription state,
conversion confirmation, payment-method change, billing state, delivery-email
change, cancellation, withdrawal, and later operator-sensitive actions.

PROHIBITED CONTENT - `payload` MUST NOT carry card data, IDV payloads,
provider secrets, session tokens, or billing keys. It is bounded contextual
metadata (what changed, from which value to which value, by whom).
"""

import datetime as dt
import uuid
from typing import Any, Dict, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from customer.domain.enums import AuditActorType, CommandIdempotencyStatus
from customer.persistence.base import (
    CustomerBase,
    created_at_column,
    enum_check,
    enum_column,
    json_metadata_column,
    updated_at_column,
    uuid_pk,
)


class AuditEvent(CustomerBase):
    """One immutable audit record.

    A monotonic bigint identity is used instead of a UUID so that append order
    is readable directly from the key. The migration installs an
    UPDATE-blocking trigger (`audit_event_immutable`); DELETE is left available
    for statutory retention jobs only.
    """

    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(), primary_key=True)

    occurred_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    actor_type: Mapped[str] = enum_column(AuditActorType)
    #: Set when the actor is the customer acting on their own account.
    actor_account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("customer_account.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: Opaque operator reference. Deliberately not a FK: operator identity
    #: lives in the separate operator trust domain, not in the customer DB.
    actor_operator_reference: Mapped[Optional[str]] = mapped_column(
        sa.String(120), nullable=True
    )

    #: Subject of the event.
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("customer_account.id", ondelete="SET NULL"),
        nullable=True,
    )
    subscription_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("subscription.id", ondelete="SET NULL"),
        nullable=True,
    )

    event_type: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(sa.String(80), nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(sa.String(80), nullable=True)

    payload: Mapped[Dict[str, Any]] = json_metadata_column()

    __table_args__ = (
        enum_check("actor_type", AuditActorType, "actor_type_valid"),
        sa.CheckConstraint(
            "actor_type <> 'customer' OR actor_account_id IS NOT NULL",
            name="customer_actor_has_account",
        ),
        sa.CheckConstraint(
            "actor_type <> 'operator' OR actor_operator_reference IS NOT NULL",
            name="operator_actor_has_reference",
        ),
        sa.Index("ix_audit_event_account_id_occurred_at", "account_id", "occurred_at"),
        sa.Index("ix_audit_event_event_type_occurred_at", "event_type", "occurred_at"),
    )


class CommandIdempotency(CustomerBase):
    """Replay protection for customer commands that have no natural key.

    Most idempotency in this schema is carried by unique BUSINESS keys, which
    are stronger and simpler: the delivery key on `recipient_snapshot`, the
    period/attempt keys on `billing_attempt`, and the provider-reference keys
    on `billing_event` / `delivery_event`. This table exists only for the
    remainder - `trial/start`, `conversion/accept`, `cancellation`,
    `withdrawal` and similar - which the API contract (sec. 1) requires to
    accept an `Idempotency-Key` but which have no unique business tuple of
    their own.

    It is deliberately narrow: no generic request/response body storage, no
    cross-service registry.
    """

    __tablename__ = "command_idempotency"

    id: Mapped[uuid.UUID] = uuid_pk()

    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("customer_account.id", ondelete="CASCADE"),
        nullable=True,
    )
    command: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.String(200), nullable=False)

    #: Hash of the request parameters, so a reused key with different arguments
    #: can be rejected instead of silently replaying the wrong result.
    request_fingerprint: Mapped[str] = mapped_column(sa.String(128), nullable=False)

    status: Mapped[str] = enum_column(CommandIdempotencyStatus)
    #: Identifier of whatever the command produced (e.g. a subscription id).
    result_reference: Mapped[Optional[str]] = mapped_column(sa.String(120), nullable=True)

    created_at: Mapped[dt.datetime] = created_at_column()
    updated_at: Mapped[dt.datetime] = updated_at_column()
    completed_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        enum_check(
            "status", CommandIdempotencyStatus, "status_valid"
        ),
        sa.UniqueConstraint(
            "command", "idempotency_key", name="uq_command_idempotency_command_key"
        ),
        sa.CheckConstraint(
            "status <> 'completed' OR completed_at IS NOT NULL",
            name="completed_at_present",
        ),
    )
