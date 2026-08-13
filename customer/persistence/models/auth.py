"""Authentication challenge and identity-verification records.

Canonical: docs/web/CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md

Two tables only. Security *events* are not given a third table: the Phase 1
`audit_event` foundation already provides an append-only, UPDATE-blocked
history with actor/subject/payload, and a parallel auth-history table would be
a second audit system with its own drift.

PROHIBITED DATA - neither table has, or may gain, a column for: a plaintext
verification code, a raw session token, a raw IDV provider payload, a resident
registration number, or a full date of birth.
"""

import datetime as dt
import uuid
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from customer.domain.enums import (
    AuthChallengeChannel,
    AuthChallengePurpose,
    AuthChallengeStatus,
    IdentityVerificationPurpose,
    IdentityVerificationStatus,
)
from customer.persistence.base import (
    CustomerBase,
    created_at_column,
    enum_check,
    enum_column,
    updated_at_column,
    uuid_pk,
)


class AuthChallenge(CustomerBase):
    """A single-use verification challenge (email code, SMS OTP, step-up).

    Provider-neutral: this row is the whole state machine, and delivery is
    somebody else's job. `purpose` is bound into the row and re-checked at
    verification time, so a code issued for `login` can never be spent on
    `withdrawal` (Auth spec sec. 5.1 lists those as different risk tiers).

    The code itself is stored only as a salted PBKDF2 verifier; see
    customer/domain/security.py for why a slow KDF is used here and a fast one
    for session tokens.
    """

    __tablename__ = "auth_challenge"

    id: Mapped[uuid.UUID] = uuid_pk()

    #: NULL before an account exists (signup-time email ownership proof).
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("customer_account.id", ondelete="CASCADE"),
        nullable=True,
    )

    purpose: Mapped[str] = enum_column(AuthChallengePurpose)
    channel: Mapped[str] = enum_column(AuthChallengeChannel)

    #: Destination the code was sent to (email address or E.164 number).
    #: Bound into verification so a code cannot be redirected to another
    #: contact belonging to the same account.
    target: Mapped[str] = mapped_column(sa.String(320), nullable=False)

    code_hash: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    code_salt: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    status: Mapped[str] = enum_column(AuthChallengeStatus)

    attempt_count: Mapped[int] = mapped_column(
        sa.SmallInteger, nullable=False, server_default=sa.text("0")
    )
    max_attempts: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)

    expires_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    verified_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    consumed_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    locked_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[dt.datetime] = created_at_column()
    updated_at: Mapped[dt.datetime] = updated_at_column()

    __table_args__ = (
        enum_check("purpose", AuthChallengePurpose, "purpose_valid"),
        enum_check("channel", AuthChallengeChannel, "channel_valid"),
        enum_check("status", AuthChallengeStatus, "status_valid"),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= max_attempts",
            name="attempt_count_within_limit",
        ),
        sa.CheckConstraint("max_attempts >= 1", name="max_attempts_positive"),
        sa.CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        # A challenge cannot claim to be verified/consumed/locked without the
        # timestamp that proves when it happened.
        sa.CheckConstraint(
            "status <> 'verified' OR verified_at IS NOT NULL",
            name="verified_at_present",
        ),
        sa.CheckConstraint(
            "status <> 'consumed' OR (verified_at IS NOT NULL AND consumed_at IS NOT NULL)",
            name="consumed_after_verified",
        ),
        sa.CheckConstraint(
            "status <> 'locked' OR locked_at IS NOT NULL", name="locked_at_present"
        ),
        # INVARIANT: at most one live challenge per contact+purpose. Prevents
        # parallel codes for the same action, which would multiply an
        # attacker's guessing budget.
        sa.Index(
            "uq_auth_challenge_pending_target_purpose",
            "target",
            "purpose",
            unique=True,
            postgresql_where=sa.text("status = 'pending'"),
        ),
        sa.Index("ix_auth_challenge_account_id", "account_id"),
        sa.Index("ix_auth_challenge_expires_at", "expires_at"),
    )


class IdentityVerification(CustomerBase):
    """One provider-neutral identity-verification attempt.

    Records only what policy needs to keep (Auth spec sec. 1): the adult
    eligibility result, the stable person key, and a provider reference for
    re-audit. There is deliberately no birthdate, no name, and no raw payload
    column.

    `purpose` matters because the same verification machinery serves signup,
    phone change, recovery, and withdrawal, and those have different
    consequences: a signup verification must never be replayed to authorize a
    phone change.
    """

    __tablename__ = "identity_verification"

    id: Mapped[uuid.UUID] = uuid_pk()

    purpose: Mapped[str] = enum_column(IdentityVerificationPurpose)
    status: Mapped[str] = enum_column(IdentityVerificationStatus)

    provider: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    provider_reference: Mapped[str] = mapped_column(sa.String(255), nullable=False)

    #: Populated only on a verified result. This is the DI-equivalent key that
    #: account uniqueness and trial eligibility key on.
    idv_stable_key: Mapped[Optional[str]] = mapped_column(sa.String(255), nullable=True)

    #: Tri-state on purpose: NULL while pending, then the provider's answer.
    adult_verified: Mapped[Optional[bool]] = mapped_column(sa.Boolean, nullable=True)

    #: The number proven by this verification (used by phone change).
    mobile_e164: Mapped[Optional[str]] = mapped_column(sa.String(20), nullable=True)

    #: NULL at signup, since no account exists yet.
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("customer_account.id", ondelete="SET NULL"),
        nullable=True,
    )
    person_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("person_identity.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: Set when a verified result has been spent, so one verification cannot
    #: authorize two identity-destructive actions.
    consumed_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[dt.datetime] = created_at_column()
    completed_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[dt.datetime] = updated_at_column()

    __table_args__ = (
        enum_check("purpose", IdentityVerificationPurpose, "purpose_valid"),
        enum_check("status", IdentityVerificationStatus, "status_valid"),
        sa.UniqueConstraint(
            "provider",
            "provider_reference",
            name="uq_identity_verification_provider_reference",
        ),
        # INVARIANT (Auth spec sec. 1-2): a verified result must carry adult
        # eligibility AND the stable person key. Without both it cannot create
        # an account, so it must not be storable as "verified".
        sa.CheckConstraint(
            "status <> 'verified' OR ("
            " idv_stable_key IS NOT NULL AND adult_verified IS TRUE"
            " AND completed_at IS NOT NULL)",
            name="verified_requires_adult_and_stable_key",
        ),
        # An under-19 outcome is recorded as exactly that, never as a success.
        sa.CheckConstraint(
            "status <> 'age_not_eligible' OR adult_verified IS FALSE",
            name="age_not_eligible_is_not_adult",
        ),
        sa.CheckConstraint(
            "mobile_e164 IS NULL OR mobile_e164 ~ '^\\+[1-9][0-9]{7,14}$'",
            name="mobile_e164_format",
        ),
        sa.Index("ix_identity_verification_stable_key", "idv_stable_key"),
        sa.Index("ix_identity_verification_account_id", "account_id"),
    )
