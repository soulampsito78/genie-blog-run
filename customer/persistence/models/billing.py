"""Billing attempts and provider events.

Canonical: docs/web/CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md sec. 7, 8, 8.1
           docs/web/FRONTEND_API_CONTRACT_v1.md sec. 1 (idempotency)

The schema is shaped so that duplicate charging is hard rather than merely
discouraged:

  - `idempotency_key` is globally unique, so a retried command cannot create a
    second attempt row.
  - (subscription, purpose, billing_period_start, attempt_no) is unique, so the
    Day0 / Day+1 / Day+3 cadence cannot double-fire the same slot.
  - at most one SUCCEEDED attempt may exist per billing period, so a period
    cannot be charged twice even across purposes-in-error.
  - (provider, provider_transaction_reference) is unique, so replaying a
    provider webhook cannot fabricate a second settlement.

No retry scheduler, provider client, or charge execution exists in Phase 1.
"""

import datetime as dt
import uuid
from typing import Any, Dict, List, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from customer.domain.catalog import CURRENCY_KRW
from customer.domain.enums import (
    BillingAttemptPurpose,
    BillingAttemptStatus,
    PlanCode,
)
from customer.persistence.base import (
    CustomerBase,
    created_at_column,
    enum_check,
    enum_column,
    json_metadata_column,
    updated_at_column,
    uuid_pk,
)


class BillingAttempt(CustomerBase):
    """One attempt to charge one billing period."""

    __tablename__ = "billing_attempt"

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("customer_account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("subscription.id", ondelete="RESTRICT"),
        nullable=False,
    )
    #: The frozen customer choice this charge is executing, when it is the
    #: first conversion charge (Lifecycle sec. 1.1).
    conversion_snapshot_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("conversion_snapshot.id", ondelete="RESTRICT"),
        nullable=True,
    )
    #: Kept RESTRICT-nullable: a card may be revoked after the attempt, but the
    #: attempt's evidence must not vanish.
    payment_method_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("payment_method.id", ondelete="RESTRICT"),
        nullable=True,
    )

    purpose: Mapped[str] = enum_column(BillingAttemptPurpose)
    status: Mapped[str] = enum_column(BillingAttemptStatus)

    #: Retry slot within the period. Lifecycle sec. 8 fixes the cadence at
    #: Day 0 / Day +1 / Day +3 for paid renewals; a never-paid first
    #: conversion charge has no automatic retry at all.
    attempt_no: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    retry_offset_day: Mapped[Optional[int]] = mapped_column(
        sa.SmallInteger, nullable=True
    )

    billing_period_start: Mapped[dt.date] = mapped_column(sa.Date, nullable=False)
    billing_period_end: Mapped[dt.date] = mapped_column(sa.Date, nullable=False)

    #: Amount actually charged, frozen from the contract/snapshot - never read
    #: from the live catalog at charge time (Lifecycle sec. 1.1).
    amount_krw: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        sa.String(3), nullable=False, server_default=sa.text("'KRW'")
    )
    plan_code: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    price_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    #: Command-level idempotency for the charge itself.
    idempotency_key: Mapped[str] = mapped_column(sa.String(200), nullable=False)

    provider: Mapped[Optional[str]] = mapped_column(sa.String(64), nullable=True)
    provider_transaction_reference: Mapped[Optional[str]] = mapped_column(
        sa.String(255), nullable=True
    )
    failure_code: Mapped[Optional[str]] = mapped_column(sa.String(80), nullable=True)
    failure_message: Mapped[Optional[str]] = mapped_column(sa.String(500), nullable=True)

    scheduled_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    attempted_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    settled_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[dt.datetime] = created_at_column()
    updated_at: Mapped[dt.datetime] = updated_at_column()

    events: Mapped[List["BillingEvent"]] = relationship(
        back_populates="billing_attempt", cascade="all, delete-orphan"
    )

    __table_args__ = (
        enum_check("purpose", BillingAttemptPurpose, "purpose_valid"),
        enum_check("status", BillingAttemptStatus, "status_valid"),
        sa.CheckConstraint(
            "plan_code IN ({0})".format(
                ", ".join("'{0}'".format(v) for v in PlanCode.values())
            ),
            name="plan_code_valid",
        ),
        sa.CheckConstraint("amount_krw > 0", name="amount_positive"),
        sa.CheckConstraint(
            "currency = '{0}'".format(CURRENCY_KRW),
            name="currency_krw",
        ),
        sa.CheckConstraint(
            "attempt_no >= 1", name="attempt_no_positive"
        ),
        sa.CheckConstraint(
            "billing_period_end > billing_period_start",
            name="period_range",
        ),
        sa.CheckConstraint(
            "status <> 'succeeded' OR (settled_at IS NOT NULL "
            "AND provider_transaction_reference IS NOT NULL)",
            name="succeeded_requires_settlement",
        ),
        sa.CheckConstraint(
            "status <> 'failed' OR failure_code IS NOT NULL",
            name="failed_requires_code",
        ),
        # The first conversion charge must point at the frozen customer choice.
        sa.CheckConstraint(
            "purpose <> 'first_conversion_charge' OR conversion_snapshot_id IS NOT NULL",
            name="first_charge_requires_snapshot",
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_billing_attempt_idempotency_key"
        ),
        sa.UniqueConstraint(
            "subscription_id",
            "purpose",
            "billing_period_start",
            "attempt_no",
            name="uq_billing_attempt_subscription_purpose_period_attempt",
        ),
        # INVARIANT: one billing period is settled at most once.
        sa.Index(
            "uq_billing_attempt_succeeded_period",
            "subscription_id",
            "billing_period_start",
            unique=True,
            postgresql_where=sa.text("status = 'succeeded'"),
        ),
        sa.Index(
            "uq_billing_attempt_provider_transaction",
            "provider",
            "provider_transaction_reference",
            unique=True,
            postgresql_where=sa.text("provider_transaction_reference IS NOT NULL"),
        ),
        sa.Index("ix_billing_attempt_subscription_id", "subscription_id"),
        sa.Index("ix_billing_attempt_scheduled_at", "scheduled_at"),
    )


class BillingEvent(CustomerBase):
    """Append-oriented provider/state history for a billing attempt.

    `provider_event_reference` is uniquely indexed so that a re-delivered
    provider webhook is a no-op rather than a second state transition.
    """

    __tablename__ = "billing_event"

    id: Mapped[uuid.UUID] = uuid_pk()
    billing_attempt_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("billing_attempt.id", ondelete="CASCADE"),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    occurred_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    provider_event_reference: Mapped[Optional[str]] = mapped_column(
        sa.String(255), nullable=True
    )
    #: Bounded, non-secret provider detail. MUST NOT contain card data or
    #: authentication payloads.
    detail: Mapped[Dict[str, Any]] = json_metadata_column()

    created_at: Mapped[dt.datetime] = created_at_column()

    billing_attempt: Mapped[BillingAttempt] = relationship(back_populates="events")

    __table_args__ = (
        sa.Index(
            "uq_billing_event_provider_event_reference",
            "provider_event_reference",
            unique=True,
            postgresql_where=sa.text("provider_event_reference IS NOT NULL"),
        ),
        sa.Index(
            "ix_billing_event_billing_attempt_id_occurred_at",
            "billing_attempt_id",
            "occurred_at",
        ),
    )
