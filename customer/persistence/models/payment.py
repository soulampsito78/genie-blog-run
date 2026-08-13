"""Payment method reference.

Canonical: docs/web/CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md sec. 5

PROHIBITED DATA - this table has no column for, and must never gain a column
for: full PAN / card number, CVV / CVC, card password, or any raw card
authentication payload. The provider vaults the card; this service stores only
a billing-key reference plus minimal safe display metadata. The test
`test_customer_payment_method_stores_no_raw_card_data` asserts this at the
schema level.
"""

import datetime as dt
import uuid
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from customer.domain.enums import PaymentMethodStatus
from customer.persistence.base import (
    CustomerBase,
    created_at_column,
    enum_check,
    enum_column,
    updated_at_column,
    uuid_pk,
)


class PaymentMethod(CustomerBase):
    """A provider billing key registered to the account.

    Lifecycle sec. 5.2: while a future billing obligation exists, a valid
    default method must always exist, and a new card is added BEFORE the old
    one is deleted. Temporary multiples are therefore legal; exactly one
    default is not.
    """

    __tablename__ = "payment_method"

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("customer_account.id", ondelete="RESTRICT"),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    #: Opaque provider billing key / token reference. NOT card data.
    billing_key_reference: Mapped[str] = mapped_column(sa.String(255), nullable=False)

    # --- minimal safe display metadata only ---
    card_brand: Mapped[Optional[str]] = mapped_column(sa.String(40), nullable=True)
    card_last4: Mapped[Optional[str]] = mapped_column(sa.String(4), nullable=True)
    display_label: Mapped[Optional[str]] = mapped_column(sa.String(120), nullable=True)

    #: Own-name verification (Lifecycle sec. 3.0 / sec. 5.1). The mechanism is
    #: a vendor capability; only its result and reference are persisted.
    own_name_verified: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    own_name_verified_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    own_name_verification_reference: Mapped[Optional[str]] = mapped_column(
        sa.String(255), nullable=True
    )

    status: Mapped[str] = enum_column(PaymentMethodStatus)
    is_default: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    revoked_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[dt.datetime] = created_at_column()
    updated_at: Mapped[dt.datetime] = updated_at_column()

    __table_args__ = (
        enum_check("status", PaymentMethodStatus, "status_valid"),
        sa.UniqueConstraint(
            "provider",
            "billing_key_reference",
            name="uq_payment_method_provider_billing_key_reference",
        ),
        sa.CheckConstraint(
            "card_last4 IS NULL OR card_last4 ~ '^[0-9]{4}$'",
            name="card_last4_format",
        ),
        sa.CheckConstraint(
            "own_name_verified IS FALSE OR own_name_verified_at IS NOT NULL",
            name="own_name_verified_at_present",
        ),
        sa.CheckConstraint(
            "status <> 'revoked' OR revoked_at IS NOT NULL",
            name="revoked_at_present",
        ),
        # A revoked or invalid method must not remain the default.
        sa.CheckConstraint(
            "is_default IS FALSE OR status = 'active'",
            name="default_must_be_active",
        ),
        # INVARIANT (Lifecycle sec. 5.2): at most one default per account.
        sa.Index(
            "uq_payment_method_default_account",
            "account_id",
            unique=True,
            postgresql_where=sa.text("is_default IS TRUE"),
        ),
        sa.Index("ix_payment_method_account_id", "account_id"),
    )
