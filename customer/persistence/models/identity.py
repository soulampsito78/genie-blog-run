"""Person identity, customer account, browser session, trial eligibility.

Canonical: docs/web/CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md
           docs/web/CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md sec. 3.2
"""

import datetime as dt
import uuid
from typing import List, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from customer.domain.enums import AccountStatus, AuthAssuranceLevel, SessionRevokeReason
from customer.persistence.base import (
    CustomerBase,
    created_at_column,
    enum_check,
    enum_column,
    updated_at_column,
    uuid_pk,
)


class PersonIdentity(CustomerBase):
    """A verified natural person, as attested by the IDV provider.

    This is deliberately NOT the account. One verified person owns at most one
    active `CustomerAccount` (Auth spec sec. 2); a second signup attempt with
    the same stable key must be routed to recovery, never to a new account.

    Stored minimally on purpose (Auth spec sec. 1): there is no birthdate
    column and no IDV payload column. Adult eligibility is reduced to a boolean
    plus the timestamp and the provider reference needed to re-audit it.
    """

    __tablename__ = "person_identity"

    id: Mapped[uuid.UUID] = uuid_pk()

    #: DI or equivalent provider-stable person key. This - not phone, not
    #: email, not card - is what trial eligibility and account uniqueness key
    #: on (Auth spec sec. 2; Lifecycle sec. 3.2).
    idv_stable_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    idv_provider: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    idv_reference: Mapped[Optional[str]] = mapped_column(sa.String(255), nullable=True)

    adult_verified: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    adult_verified_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[dt.datetime] = created_at_column()
    updated_at: Mapped[dt.datetime] = updated_at_column()

    accounts: Mapped[List["CustomerAccount"]] = relationship(
        back_populates="person", cascade="save-update, merge"
    )

    __table_args__ = (
        sa.UniqueConstraint("idv_stable_key", name="uq_person_identity_idv_stable_key"),
        # A claimed adult verification without its timestamp is unauditable.
        sa.CheckConstraint(
            "adult_verified IS FALSE OR adult_verified_at IS NOT NULL",
            name="adult_verified_at_present",
        ),
    )


class CustomerAccount(CustomerBase):
    """The customer's operational account.

    Separate from `PersonIdentity` because the person outlives the account:
    withdrawal ends the account, while trial-eligibility evidence for the
    person survives independently for a year.
    """

    __tablename__ = "customer_account"

    id: Mapped[uuid.UUID] = uuid_pk()

    person_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("person_identity.id", ondelete="RESTRICT"),
        nullable=False,
    )

    #: Login / transactional address. Distinct from the briefing
    #: `delivery_email` (Delivery contract sec. 5) even when the values match.
    account_email: Mapped[str] = mapped_column(sa.String(320), nullable=False)

    #: Registered mobile, E.164. Changeable under policy; explicitly NOT the
    #: person identity (Auth spec sec. 2).
    mobile_e164: Mapped[Optional[str]] = mapped_column(sa.String(20), nullable=True)

    status: Mapped[str] = enum_column(AccountStatus)
    withdrawn_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[dt.datetime] = created_at_column()
    updated_at: Mapped[dt.datetime] = updated_at_column()

    person: Mapped[PersonIdentity] = relationship(back_populates="accounts")

    __table_args__ = (
        enum_check("status", AccountStatus, "status_valid"),
        sa.CheckConstraint(
            "status <> 'withdrawn' OR withdrawn_at IS NOT NULL",
            name="withdrawn_at_present",
        ),
        sa.CheckConstraint(
            "mobile_e164 IS NULL OR mobile_e164 ~ '^\\+[1-9][0-9]{7,14}$'",
            name="mobile_e164_format",
        ),
        sa.CheckConstraint(
            "account_email = lower(account_email) AND position('@' in account_email) > 1",
            name="email_normalized",
        ),
        # INVARIANT (Auth spec sec. 2): 1 verified person = 1 active account.
        # Enforced as a partial unique index so that withdrawn accounts may
        # accumulate against the same person without blocking re-registration.
        sa.Index(
            "uq_customer_account_active_person",
            "person_id",
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
        ),
        # Two simultaneously active accounts sharing a login address would make
        # passwordless email login ambiguous.
        sa.Index(
            "uq_customer_account_active_email",
            "account_email",
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
        ),
    )


class BrowserSession(CustomerBase):
    """A revocable, server-authoritative browser session (Auth spec sec. 4, 6).

    The row's `id` is an IDENTIFIER; the bearer credential is a separate
    high-entropy token stored only as `session_token_hash`. Presenting the id
    alone authenticates nothing, which is why the id may safely appear in
    session lists, audit records, and logs.

    The short-lived access credential is intentionally NOT this row: a 30-day
    browser session must never be a 30-day bearer token (Auth spec sec. 4.2).
    An access context is minted per request window from a still-valid session;
    see customer/services/session_service.py.

    Fresh auth is tracked here rather than inferred from session age, because
    Auth spec sec. 5 requires recent reauthentication for sensitive actions
    *even when* "Keep me signed in" is ON - a 29-day-old remembered session is
    authenticated but never fresh.
    """

    __tablename__ = "browser_session"

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("customer_account.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: SHA-256 of the opaque bearer token. The token itself is returned to the
    #: caller exactly once at creation and is never persisted anywhere.
    session_token_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    #: "Keep me signed in". Default OFF (Auth spec sec. 4).
    remember_login: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )

    absolute_expires_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    inactivity_expires_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[dt.datetime] = created_at_column()
    revoked_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    revoke_reason: Mapped[Optional[str]] = mapped_column(sa.String(40), nullable=True)

    #: Most recent reauthentication and how strong it was. Evaluated against
    #: FRESH_AUTH_WINDOW independently of session validity.
    last_fresh_auth_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    fresh_auth_assurance: Mapped[Optional[str]] = mapped_column(
        sa.String(40), nullable=True
    )

    #: Coarse UA description only. Auth spec sec. 6 forbids building excessive
    #: permanent device fingerprinting.
    user_agent_summary: Mapped[Optional[str]] = mapped_column(
        sa.String(200), nullable=True
    )

    #: Minimised network metadata, for the customer's own session list only.
    #: Auth spec sec. 6: a session MUST NOT be terminated solely because the IP
    #: changed, so these are descriptive - never part of authentication.
    created_ip: Mapped[Optional[str]] = mapped_column(sa.String(45), nullable=True)
    last_seen_ip: Mapped[Optional[str]] = mapped_column(sa.String(45), nullable=True)

    created_at: Mapped[dt.datetime] = created_at_column()

    __table_args__ = (
        sa.CheckConstraint(
            "inactivity_expires_at <= absolute_expires_at",
            name="expiry_ordering",
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoke_reason IS NULL)",
            name="revoke_reason_matches_revoked_at",
        ),
        sa.CheckConstraint(
            "revoke_reason IS NULL OR revoke_reason IN ({0})".format(
                ", ".join("'{0}'".format(v) for v in SessionRevokeReason.values())
            ),
            name="revoke_reason_valid",
        ),
        sa.CheckConstraint(
            "(last_fresh_auth_at IS NULL) = (fresh_auth_assurance IS NULL)",
            name="fresh_auth_fields_all_or_none",
        ),
        sa.CheckConstraint(
            "fresh_auth_assurance IS NULL OR fresh_auth_assurance IN ({0})".format(
                ", ".join("'{0}'".format(v) for v in AuthAssuranceLevel.values())
            ),
            name="fresh_auth_assurance_valid",
        ),
        # The bearer verifier identifies exactly one session.
        sa.UniqueConstraint(
            "session_token_hash", name="uq_browser_session_session_token_hash"
        ),
        sa.Index("ix_browser_session_account_id", "account_id"),
    )


class TrialEligibilityBlock(CustomerBase):
    """Evidence that a verified person already consumed a free trial.

    Lifecycle sec. 3.2 requires this evidence to be *separated* from
    operational membership data and retained for one year. That is why this
    table stores the stable key as a value and deliberately carries NO foreign
    key to `person_identity`: withdrawing an account, or deleting the identity
    row, must not silently restore free-trial eligibility.
    """

    __tablename__ = "trial_eligibility_block"

    id: Mapped[uuid.UUID] = uuid_pk()

    idv_stable_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)

    trial_started_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    trial_ended_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    #: One year from trial end (Lifecycle sec. 3.2). After this instant the
    #: row is deletable by the retention job and the person may trial again.
    block_expires_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )

    created_at: Mapped[dt.datetime] = created_at_column()

    __table_args__ = (
        sa.UniqueConstraint(
            "idv_stable_key", name="uq_trial_eligibility_block_idv_stable_key"
        ),
        sa.CheckConstraint(
            "trial_ended_at >= trial_started_at",
            name="trial_range",
        ),
        sa.CheckConstraint(
            "block_expires_at > trial_ended_at",
            name="expiry_after_end",
        ),
        sa.Index("ix_trial_eligibility_block_block_expires_at", "block_expires_at"),
    )
