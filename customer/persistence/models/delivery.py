"""Delivery email, entitlement, recipient snapshot, delivery event.

Canonical: docs/web/CUSTOMER_DELIVERY_ENTITLEMENT_CONTRACT_v1.md

This module encodes the required chain:

    subscription / payment state
      -> entitlement evaluation
      -> recipient snapshot
      -> customer delivery   (executed by the EXISTING approved pipeline)

Entitlement answers *who may receive which product on which publication date*.
It never answers *whether this briefing may be sent* - that remains owner
approval, outside this package entirely.
"""

import datetime as dt
import uuid
from typing import Any, Dict, List, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from customer.domain.enums import (
    DeliveryEmailStatus,
    DeliveryEventType,
    EntitlementSource,
    PlanCode,
    SubscriptionState,
    SuppressionReason,
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


class DeliveryEmail(CustomerBase):
    """A briefing delivery address for an account.

    INVARIANT (Delivery contract sec. 5): exactly one `active` row per account.
    A change inserts a `pending_verification` row; the old address stays
    `active` and keeps receiving until the new one verifies, at which point the
    old row becomes `superseded`. The two-row model is what makes
    "never duplicate the same publication to both addresses" expressible.

    Distinct from `CustomerAccount.account_email` even when the values are
    equal: transactional and security mail must keep flowing to the account
    address after a briefing suppression (Delivery contract sec. 14).
    """

    __tablename__ = "delivery_email"

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("customer_account.id", ondelete="RESTRICT"),
        nullable=False,
    )

    email: Mapped[str] = mapped_column(sa.String(320), nullable=False)
    status: Mapped[str] = enum_column(DeliveryEmailStatus)

    verified_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    suppression_reason: Mapped[Optional[str]] = mapped_column(
        sa.String(40), nullable=True
    )
    suppressed_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    deactivated_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[dt.datetime] = created_at_column()
    updated_at: Mapped[dt.datetime] = updated_at_column()

    __table_args__ = (
        enum_check("status", DeliveryEmailStatus, "status_valid"),
        sa.CheckConstraint(
            "suppression_reason IS NULL OR suppression_reason IN ({0})".format(
                ", ".join("'{0}'".format(v) for v in SuppressionReason.values())
            ),
            name="suppression_reason_valid",
        ),
        sa.CheckConstraint(
            "email = lower(email) AND position('@' in email) > 1",
            name="normalized",
        ),
        # An address may only be active once ownership is proven.
        sa.CheckConstraint(
            "status <> 'active' OR verified_at IS NOT NULL",
            name="active_requires_verified",
        ),
        sa.CheckConstraint(
            "(status = 'suppressed') = (suppression_reason IS NOT NULL)",
            name="suppression_reason_matches_status",
        ),
        sa.CheckConstraint(
            "status <> 'suppressed' OR suppressed_at IS NOT NULL",
            name="suppressed_at_present",
        ),
        # INVARIANT: 1 account = 1 active delivery_email.
        sa.Index(
            "uq_delivery_email_active_account",
            "account_id",
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
        ),
        # At most one replacement in flight, so "the pending address" is
        # unambiguous during a change.
        sa.Index(
            "uq_delivery_email_pending_account",
            "account_id",
            unique=True,
            postgresql_where=sa.text("status = 'pending_verification'"),
        ),
        sa.Index("ix_delivery_email_account_id", "account_id"),
    )


class Entitlement(CustomerBase):
    """The right to receive ONE product over a date range.

    One row per product, which is what makes the delivery question a direct
    lookup ("is this account entitled to `keysuri_korea` on 2026-08-12?") and
    makes trial-vs-paid product sets differ by row count rather than by parsing
    a blob.

    Trial entitlement is always three rows (Lifecycle sec. 3). Paid entitlement
    is exactly the contracted plan's product set, created only after verified
    payment success.

    Deliberately NOT coupled to email send success: an entitlement continues to
    exist while an address is bouncing. Suppression lives on `DeliveryEmail`.
    """

    __tablename__ = "entitlement"

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
    product_code: Mapped[str] = mapped_column(
        sa.String(40),
        sa.ForeignKey("product.code", ondelete="RESTRICT"),
        nullable=False,
    )

    source: Mapped[str] = enum_column(EntitlementSource)
    #: Paid entitlement records which plan/version granted it; trial does not,
    #: because a trial has no paid plan.
    plan_code: Mapped[Optional[str]] = mapped_column(sa.String(40), nullable=True)
    price_version: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True)

    #: Inclusive publication-date bounds. `effective_to` NULL means open-ended.
    effective_from: Mapped[dt.date] = mapped_column(sa.Date, nullable=False)
    effective_to: Mapped[Optional[dt.date]] = mapped_column(sa.Date, nullable=True)

    revoked_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[dt.datetime] = created_at_column()
    updated_at: Mapped[dt.datetime] = updated_at_column()

    __table_args__ = (
        enum_check("source", EntitlementSource, "source_valid"),
        sa.CheckConstraint(
            "plan_code IS NULL OR plan_code IN ({0})".format(
                ", ".join("'{0}'".format(v) for v in PlanCode.values())
            ),
            name="plan_code_valid",
        ),
        # Trial has no paid plan; paid entitlement must name the plan that
        # granted it.
        sa.CheckConstraint(
            "(source = 'trial' AND plan_code IS NULL AND price_version IS NULL) "
            "OR (source = 'paid' AND plan_code IS NOT NULL "
            "AND price_version IS NOT NULL)",
            name="plan_matches_source",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="effective_range",
        ),
        # One open entitlement per subscription+product: prevents stacking two
        # live grants for the same briefing.
        sa.Index(
            "uq_entitlement_open_subscription_product",
            "subscription_id",
            "product_code",
            unique=True,
            postgresql_where=sa.text("revoked_at IS NULL AND effective_to IS NULL"),
        ),
        sa.Index(
            "ix_entitlement_account_product_effective_from",
            "account_id",
            "product_code",
            "effective_from",
        ),
    )


class RecipientSnapshot(CustomerBase):
    """A frozen decision that one account receives one product on one date.

    Delivery contract sec. 7-8. The snapshot copies the delivery address as a
    VALUE, not merely as a foreign key, so that send time never re-reads a
    mutable "current email" row. Changes after freezing apply to the NEXT
    snapshot; the migration installs an UPDATE-blocking trigger
    (`recipient_snapshot_immutable`) to enforce that rather than trusting
    callers.

    The uniqueness of (account_id, product_code, publication_date) IS the
    canonical customer delivery idempotency key.
    """

    __tablename__ = "recipient_snapshot"

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
    product_code: Mapped[str] = mapped_column(
        sa.String(40),
        sa.ForeignKey("product.code", ondelete="RESTRICT"),
        nullable=False,
    )
    publication_date: Mapped[dt.date] = mapped_column(sa.Date, nullable=False)

    #: Frozen literal address used for this publication.
    delivery_email: Mapped[str] = mapped_column(sa.String(320), nullable=False)
    #: Evidence pointer back to the row that supplied it.
    delivery_email_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("delivery_email.id", ondelete="RESTRICT"),
        nullable=False,
    )

    entitlement_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("entitlement.id", ondelete="RESTRICT"),
        nullable=False,
    )
    entitlement_source: Mapped[str] = enum_column(EntitlementSource)
    plan_code: Mapped[Optional[str]] = mapped_column(sa.String(40), nullable=True)
    price_version: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True)

    #: State evidence at freeze time, so a past delivery can be explained
    #: without replaying the whole subscription history.
    subscription_state_at_snapshot: Mapped[str] = enum_column(SubscriptionState)
    billing_state_at_snapshot: Mapped[Optional[str]] = mapped_column(
        sa.String(40), nullable=True
    )

    frozen_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    events: Mapped[List["DeliveryEvent"]] = relationship(
        back_populates="recipient_snapshot", cascade="all, delete-orphan"
    )

    __table_args__ = (
        enum_check(
            "entitlement_source", EntitlementSource, "entitlement_source_valid"
        ),
        enum_check(
            "subscription_state_at_snapshot",
            SubscriptionState,
            "state_valid",
        ),
        sa.CheckConstraint(
            "plan_code IS NULL OR plan_code IN ({0})".format(
                ", ".join("'{0}'".format(v) for v in PlanCode.values())
            ),
            name="plan_code_valid",
        ),
        sa.CheckConstraint(
            "delivery_email = lower(delivery_email) "
            "AND position('@' in delivery_email) > 1",
            name="delivery_email_normalized",
        ),
        # INVARIANT (Delivery contract sec. 8): the customer delivery key.
        sa.UniqueConstraint(
            "account_id",
            "product_code",
            "publication_date",
            name="uq_recipient_snapshot_account_product_publication_date",
        ),
        sa.Index(
            "ix_recipient_snapshot_publication_date_product",
            "publication_date",
            "product_code",
        ),
    )


class DeliveryEvent(CustomerBase):
    """Append-oriented delivery history for one recipient snapshot.

    Delivery contract sec. 17 vocabulary. `provider_accepted` is explicitly NOT
    customer receipt - `delivered_evidence` is a separate event type, and
    `unknown_after_submit` must be reconciled rather than resent
    (Delivery contract sec. 8).

    `incident_key` groups the provider's own retries of a single bounce
    incident, which is what lets the later SMS policy send one notification per
    incident instead of one per retry (Delivery contract sec. 9).
    """

    __tablename__ = "delivery_event"

    id: Mapped[uuid.UUID] = uuid_pk()
    recipient_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("recipient_snapshot.id", ondelete="CASCADE"),
        nullable=False,
    )

    event_type: Mapped[str] = enum_column(DeliveryEventType)
    occurred_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    provider: Mapped[Optional[str]] = mapped_column(sa.String(64), nullable=True)
    provider_event_reference: Mapped[Optional[str]] = mapped_column(
        sa.String(255), nullable=True
    )
    incident_key: Mapped[Optional[str]] = mapped_column(sa.String(120), nullable=True)
    detail: Mapped[Dict[str, Any]] = json_metadata_column()

    created_at: Mapped[dt.datetime] = created_at_column()

    recipient_snapshot: Mapped[RecipientSnapshot] = relationship(back_populates="events")

    __table_args__ = (
        enum_check("event_type", DeliveryEventType, "event_type_valid"),
        # Webhook replay must not append a duplicate event.
        sa.Index(
            "uq_delivery_event_provider_event_reference",
            "provider_event_reference",
            unique=True,
            postgresql_where=sa.text("provider_event_reference IS NOT NULL"),
        ),
        sa.Index(
            "ix_delivery_event_snapshot_occurred_at",
            "recipient_snapshot_id",
            "occurred_at",
        ),
    )
