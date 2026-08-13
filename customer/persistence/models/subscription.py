"""Subscription contract, product membership, and conversion snapshot.

Canonical: docs/web/CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md sec. 1.1, 3, 4,
           6, 9, 10, 12, 13, 14

The single most important rule encoded here: a trial has NO paid plan. Card
registration is not consent to convert (Lifecycle sec. 4), so the subscription
row carries no contracted plan until a verified payment succeeds. The
customer's D-3 choice lives in `ConversionSnapshot` as a *pending* fact, and is
promoted onto the subscription only after the charge clears.

TRANSACTION BOUNDARIES (for the later service layer, not implemented here):
  - trial creation: subscription + delivery_email + trial entitlement rows
    commit together, or not at all.
  - conversion confirmation: conversion_snapshot + its product rows commit
    together (the deferred cardinality trigger fires at COMMIT).
  - payment success: billing_attempt -> succeeded, subscription contract
    fields, subscription_product rows, and the paid entitlement rows commit
    together.
  - The provider call itself MUST happen outside these transactions; an open
    DB transaction must never span a network charge.
"""

import datetime as dt
import uuid
from typing import List, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from customer.domain.catalog import CURRENCY_KRW
from customer.domain.enums import (
    ConversionSnapshotStatus,
    PlanCode,
    SubscriptionState,
)
from customer.persistence.base import (
    CustomerBase,
    created_at_column,
    enum_check,
    enum_column,
    updated_at_column,
    uuid_pk,
)

_TRIAL_PHASE_SQL = "('trialing', 'renewal_pending', 'conversion_scheduled')"
_PAID_CONTRACT_SQL = (
    "('active', 'past_due', 'suspended', 'cancellation_scheduled', "
    "'withdrawal_scheduled')"
)
_TERMINAL_SQL = "('trial_expired', 'canceled', 'withdrawn')"


class Subscription(CustomerBase):
    """One subscription contract for one account."""

    __tablename__ = "subscription"

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("customer_account.id", ondelete="RESTRICT"),
        nullable=False,
    )

    state: Mapped[str] = enum_column(SubscriptionState)

    # --- trial ---------------------------------------------------------
    trial_start_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    trial_end_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # --- delivery ------------------------------------------------------
    #: Lifecycle sec. 3.1 / Delivery sec. 4: never the application day. The
    #: first eligible publication day on or after the next calendar day.
    delivery_start_date: Mapped[dt.date] = mapped_column(sa.Date, nullable=False)
    first_delivered_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # --- frozen paid contract (only after verified payment success) -----
    contracted_plan_code: Mapped[Optional[str]] = mapped_column(
        sa.String(40), nullable=True
    )
    contracted_price_krw: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True)
    contracted_price_version: Mapped[Optional[int]] = mapped_column(
        sa.Integer, nullable=True
    )
    contracted_currency: Mapped[Optional[str]] = mapped_column(sa.String(3), nullable=True)
    contracted_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # --- billing anchor and period (Lifecycle sec. 6) -------------------
    #: Preserved across short months; a February clamp must never permanently
    #: move the anchor.
    billing_anchor_day: Mapped[Optional[int]] = mapped_column(
        sa.SmallInteger, nullable=True
    )
    current_period_start: Mapped[Optional[dt.date]] = mapped_column(sa.Date, nullable=True)
    current_period_end: Mapped[Optional[dt.date]] = mapped_column(sa.Date, nullable=True)
    next_billing_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # --- scheduled endings (Lifecycle sec. 10, 12) ----------------------
    cancellation_requested_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    cancellation_effective_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    withdrawal_requested_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    withdrawal_effective_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[dt.datetime] = created_at_column()
    updated_at: Mapped[dt.datetime] = updated_at_column()

    products: Mapped[List["SubscriptionProduct"]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan"
    )
    conversion_snapshots: Mapped[List["ConversionSnapshot"]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan"
    )

    __table_args__ = (
        enum_check("state", SubscriptionState, "state_valid"),
        sa.CheckConstraint(
            "contracted_plan_code IS NULL OR contracted_plan_code IN ({0})".format(
                ", ".join("'{0}'".format(v) for v in PlanCode.values())
            ),
            name="contracted_plan_code_valid",
        ),
        # The frozen contract is all-or-nothing: a plan without its agreed
        # price/version is not a contract, it is a guess.
        sa.CheckConstraint(
            "(contracted_plan_code IS NULL AND contracted_price_krw IS NULL "
            " AND contracted_price_version IS NULL AND contracted_currency IS NULL "
            " AND contracted_at IS NULL) "
            "OR (contracted_plan_code IS NOT NULL AND contracted_price_krw IS NOT NULL "
            " AND contracted_price_version IS NOT NULL "
            " AND contracted_currency IS NOT NULL AND contracted_at IS NOT NULL)",
            name="contract_fields_all_or_none",
        ),
        sa.CheckConstraint(
            "contracted_price_krw IS NULL OR contracted_price_krw > 0",
            name="contracted_price_positive",
        ),
        sa.CheckConstraint(
            "contracted_currency IS NULL OR contracted_currency = '{0}'".format(
                CURRENCY_KRW
            ),
            name="contracted_currency_krw",
        ),
        # INVARIANT (Lifecycle sec. 1.1 / sec. 3): no paid plan may exist while
        # the subscription is still in the free trial, including after the
        # customer has confirmed conversion. `conversion_scheduled` carries a
        # PENDING snapshot, not a contract.
        sa.CheckConstraint(
            "state NOT IN {0} OR contracted_plan_code IS NULL".format(_TRIAL_PHASE_SQL),
            name="no_paid_plan_during_trial",
        ),
        # A trial that expired was never paid (Lifecycle sec. 7: no grace,
        # never-paid).
        sa.CheckConstraint(
            "state <> 'trial_expired' OR contracted_plan_code IS NULL",
            name="trial_expired_never_paid",
        ),
        # INVARIANT: paid states require an established contract and anchor.
        sa.CheckConstraint(
            "state NOT IN {0} OR (contracted_plan_code IS NOT NULL "
            "AND billing_anchor_day IS NOT NULL)".format(_PAID_CONTRACT_SQL),
            name="paid_states_require_contract",
        ),
        sa.CheckConstraint(
            "billing_anchor_day IS NULL "
            "OR (billing_anchor_day >= 1 AND billing_anchor_day <= 31)",
            name="billing_anchor_day_range",
        ),
        sa.CheckConstraint(
            "(trial_start_at IS NULL) = (trial_end_at IS NULL)",
            name="trial_bounds_all_or_none",
        ),
        sa.CheckConstraint(
            "trial_end_at IS NULL OR trial_end_at > trial_start_at",
            name="trial_range",
        ),
        # A trial-phase subscription must actually have trial bounds.
        sa.CheckConstraint(
            "state NOT IN {0} OR trial_start_at IS NOT NULL".format(_TRIAL_PHASE_SQL),
            name="trial_states_require_trial_bounds",
        ),
        sa.CheckConstraint(
            "current_period_end IS NULL OR current_period_start IS NULL "
            "OR current_period_end > current_period_start",
            name="period_range",
        ),
        sa.CheckConstraint(
            "state <> 'cancellation_scheduled' OR cancellation_effective_at IS NOT NULL",
            name="cancellation_scheduled_has_effective_at",
        ),
        sa.CheckConstraint(
            "state <> 'withdrawal_scheduled' OR withdrawal_effective_at IS NOT NULL",
            name="withdrawal_scheduled_has_effective_at",
        ),
        sa.CheckConstraint(
            "state NOT IN {0} OR ended_at IS NOT NULL".format(_TERMINAL_SQL),
            name="terminal_states_have_ended_at",
        ),
        # The frozen price must correspond to a real catalog version.
        sa.ForeignKeyConstraint(
            ["contracted_plan_code", "contracted_price_version"],
            ["plan_catalog.plan_code", "plan_catalog.price_version"],
            name="fk_subscription_contracted_plan_catalog",
            ondelete="RESTRICT",
        ),
        # INVARIANT: an account has at most one live subscription. Terminal
        # subscriptions accumulate as history (Lifecycle sec. 13
        # resubscription creates a NEW contract).
        sa.Index(
            "uq_subscription_active_account",
            "account_id",
            unique=True,
            postgresql_where=sa.text("state NOT IN {0}".format(_TERMINAL_SQL)),
        ),
        sa.Index("ix_subscription_next_billing_at", "next_billing_at"),
        sa.Index("ix_subscription_trial_end_at", "trial_end_at"),
    )


class SubscriptionProduct(CustomerBase):
    """The product set of the subscription's CURRENT paid contract.

    Empty while trialing - trial entitlement is all three products by policy
    and is expressed in `entitlement`, not as a purchased product set.

    Cardinality against `contracted_plan_code` is enforced by the deferred
    constraint trigger `subscription_product_cardinality` created in the
    initial migration: exactly one product for a single-product plan, exactly
    two distinct products for `package_two`, exactly three for `full_set`.
    """

    __tablename__ = "subscription_product"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("subscription.id", ondelete="CASCADE"),
        primary_key=True,
    )
    product_code: Mapped[str] = mapped_column(
        sa.String(40),
        sa.ForeignKey("product.code", ondelete="RESTRICT"),
        primary_key=True,
    )
    created_at: Mapped[dt.datetime] = created_at_column()

    subscription: Mapped[Subscription] = relationship(back_populates="products")


class ConversionSnapshot(CustomerBase):
    """The customer's explicit D-3 paid-plan choice, frozen (Lifecycle sec. 1.1).

    This is the authority for the first charge at `trial_end_at`. The charge
    MUST read this row, never the live catalog. Promotion to
    `Subscription.contracted_*` happens only after provider/server-verified
    payment success; a browser redirect is not success (Lifecycle sec. 7).
    """

    __tablename__ = "conversion_snapshot"

    id: Mapped[uuid.UUID] = uuid_pk()
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("subscription.id", ondelete="CASCADE"),
        nullable=False,
    )

    plan_code: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    price_krw: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    price_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        sa.String(3), nullable=False, server_default=sa.text("'KRW'")
    )

    #: When the customer explicitly confirmed conversion (Lifecycle sec. 4.1A).
    confirmed_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = enum_column(ConversionSnapshotStatus)
    applied_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[dt.datetime] = created_at_column()
    updated_at: Mapped[dt.datetime] = updated_at_column()

    subscription: Mapped[Subscription] = relationship(
        back_populates="conversion_snapshots"
    )
    products: Mapped[List["ConversionSnapshotProduct"]] = relationship(
        back_populates="conversion_snapshot", cascade="all, delete-orphan"
    )

    __table_args__ = (
        enum_check("status", ConversionSnapshotStatus, "status_valid"),
        sa.CheckConstraint(
            "plan_code IN ({0})".format(
                ", ".join("'{0}'".format(v) for v in PlanCode.values())
            ),
            name="plan_code_valid",
        ),
        sa.CheckConstraint(
            "price_krw > 0", name="price_positive"
        ),
        sa.CheckConstraint(
            "currency = '{0}'".format(CURRENCY_KRW),
            name="currency_krw",
        ),
        sa.CheckConstraint(
            "status <> 'applied' OR applied_at IS NOT NULL",
            name="applied_at_present",
        ),
        sa.ForeignKeyConstraint(
            ["plan_code", "price_version"],
            ["plan_catalog.plan_code", "plan_catalog.price_version"],
            name="fk_conversion_snapshot_plan_catalog",
            ondelete="RESTRICT",
        ),
        # At most one pending conversion choice per subscription: a later
        # choice must abandon the earlier one, so the first charge can never be
        # ambiguous about which plan the customer agreed to.
        sa.Index(
            "uq_conversion_snapshot_pending_subscription",
            "subscription_id",
            unique=True,
            postgresql_where=sa.text("status = 'pending'"),
        ),
    )


class ConversionSnapshotProduct(CustomerBase):
    """Products selected in a conversion snapshot.

    Required for `package_two` (the customer picks two of three) and populated
    for every plan so the frozen snapshot is self-describing. Cardinality is
    enforced by the deferred constraint trigger
    `conversion_snapshot_product_cardinality`.
    """

    __tablename__ = "conversion_snapshot_product"

    conversion_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("conversion_snapshot.id", ondelete="CASCADE"),
        primary_key=True,
    )
    product_code: Mapped[str] = mapped_column(
        sa.String(40),
        sa.ForeignKey("product.code", ondelete="RESTRICT"),
        primary_key=True,
    )

    conversion_snapshot: Mapped[ConversionSnapshot] = relationship(
        back_populates="products"
    )
