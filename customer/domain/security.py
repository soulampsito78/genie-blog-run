"""Token and verification-code primitives.

The distinction this module exists to enforce (Auth spec sec. 7; the browser is
untrusted and holds only opaque material):

    IDENTIFIER  - a row's `id`. Safe to log, safe to expose, NOT a credential.
    SECRET      - the bearer token handed to the browser. High entropy, shown
                  exactly once, stored only as a one-way verifier.

Nothing here ever returns a secret from the database, because no secret is
stored there.
"""

import hashlib
import hmac
import os
import secrets
from typing import Optional, Tuple

from customer.domain.auth_policy import (
    CHALLENGE_CODE_DIGITS,
    CHALLENGE_CODE_KDF_ITERATIONS,
    SESSION_TOKEN_BYTES,
)

#: Sentinel distinguishing "caller passed no pepper" from "caller passed None".
_UNSET = object()


# --- session tokens --------------------------------------------------------


def generate_session_token() -> str:
    """Cryptographically secure opaque session token.

    Not a UUID: a UUID4 is an identifier with 122 bits from a generator that is
    not guaranteed to be cryptographic, and it is routinely logged. Bearer
    material gets its own generator and never appears in a log line.
    """
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """One-way verifier stored in place of the token.

    A plain SHA-256 is correct here precisely because the input is 256 bits of
    uniform randomness - there is no dictionary to iterate, so a slow KDF would
    buy nothing and cost latency on every request.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_token_matches(token: str, stored_hash: str) -> bool:
    """Constant-time comparison of a presented token against its verifier."""
    return hmac.compare_digest(hash_session_token(token), stored_hash)


# --- verification codes ----------------------------------------------------


def generate_verification_code(digits: int = CHALLENGE_CODE_DIGITS) -> str:
    """Numeric verification code, uniformly random and zero-padded.

    Uses `secrets.randbelow` over the whole range rather than concatenating
    per-digit draws, so every code including leading-zero codes is equally
    likely.
    """
    upper = 10 ** digits
    return str(secrets.randbelow(upper)).zfill(digits)


#: Optional server-side pepper. When set, the verifier is HMAC'd with a key
#: that lives OUTSIDE the database, so a read-only database compromise yields
#: nothing crackable. Not provisioned in this phase; the boundary exists so
#: adding one later is configuration, not a schema change.
#:
#: Operational note: rotating or introducing the pepper invalidates every
#: in-flight challenge. That is harmless in practice - challenges live 5
#: minutes and customers simply request a new code.
CUSTOMER_AUTH_CODE_PEPPER_ENV = "CUSTOMER_AUTH_CODE_PEPPER"


def current_code_pepper() -> Optional[str]:
    """Read the configured pepper, or None when unset."""
    value = os.environ.get(CUSTOMER_AUTH_CODE_PEPPER_ENV, "").strip()
    return value or None


def hash_verification_code(
    code: str, salt: str, pepper: Optional[str] = _UNSET
) -> str:
    """Salted, deliberately slow verifier for a low-entropy code.

    A 6-digit code has ~20 bits of entropy, so an unsalted fast hash in a
    leaked database is reversible instantly. PBKDF2 plus a per-challenge salt
    makes an offline sweep cost real time, while the attempt limit and
    5-minute TTL bound the online attack.

    PBKDF2 alone does not make a 10^6 keyspace unreachable to a determined
    attacker with GPUs and a database dump - it makes it slow relative to the
    challenge's 5-minute validity. The pepper is what removes that residual
    risk entirely, by keeping key material out of the database.
    """
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        code.encode("utf-8"),
        bytes.fromhex(salt),
        CHALLENGE_CODE_KDF_ITERATIONS,
    )
    if pepper is _UNSET:
        pepper = current_code_pepper()
    if pepper:
        return hmac.new(
            pepper.encode("utf-8"), derived, hashlib.sha256
        ).hexdigest()
    return derived.hex()


def new_code_salt() -> str:
    """Per-challenge random salt (hex)."""
    return secrets.token_bytes(16).hex()


def issue_verification_code() -> Tuple[str, str, str]:
    """Return (plaintext_code, salt, verifier).

    The plaintext is returned to the caller for delivery and is never persisted
    by any code path in this package.
    """
    code = generate_verification_code()
    salt = new_code_salt()
    return code, salt, hash_verification_code(code, salt)


def verification_code_matches(
    code: str, salt: str, stored_hash: str, pepper: Optional[str] = _UNSET
) -> bool:
    """Constant-time comparison of a presented code against its verifier."""
    return hmac.compare_digest(
        hash_verification_code(code, salt, pepper), stored_hash
    )
