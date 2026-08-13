"""Customer authentication and session policy constants.

Canonical: docs/web/CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md sec. 1, 4, 5, 9

Values marked CANONICAL are fixed by an approved policy document and MUST NOT
be changed here without changing that document first. Values marked
IMPLEMENTATION are not specified by any canonical document; they are exposed as
named constants so a later policy decision has one obvious place to land.
"""

import datetime as dt

# --- CANONICAL: adult gate (Auth spec sec. 1) ------------------------------

#: Absolute minimum age. No guardian exception exists.
MINIMUM_AGE = 19

# --- CANONICAL: browser session lifetimes (Auth spec sec. 4) ---------------

#: "Keep me signed in" defaults to OFF.
REMEMBER_LOGIN_DEFAULT = False

#: Remember OFF: normal browser session.
SESSION_ABSOLUTE_TTL_REMEMBER_OFF = dt.timedelta(hours=12)
SESSION_INACTIVITY_TTL_REMEMBER_OFF = dt.timedelta(hours=2)

#: Remember ON: persistent browser session.
SESSION_ABSOLUTE_TTL_REMEMBER_ON = dt.timedelta(days=30)
SESSION_INACTIVITY_TTL_REMEMBER_ON = dt.timedelta(days=7)

#: Short-lived access context minted from a valid browser session. A long-lived
#: browser session MUST NOT be a long-lived bearer token (Auth spec sec. 4.2).
ACCESS_CONTEXT_TTL = dt.timedelta(minutes=15)

# --- CANONICAL: step-up (Auth spec sec. 5) ---------------------------------

#: Sensitive actions require reauthentication within this window, even when
#: "Keep me signed in" is ON.
FRESH_AUTH_WINDOW = dt.timedelta(minutes=10)

# --- IMPLEMENTATION: challenge hardening -----------------------------------
# No canonical document fixes these. They are deliberately conservative and
# exist so OTP brute force, replay, and challenge flooding are bounded from the
# start rather than retrofitted.

#: How long an issued verification code remains usable.
CHALLENGE_TTL = dt.timedelta(minutes=5)

#: Wrong-code attempts allowed before the challenge locks permanently.
CHALLENGE_MAX_ATTEMPTS = 5

#: Minimum interval between issuing challenges for the same target+purpose.
CHALLENGE_ISSUE_COOLDOWN = dt.timedelta(seconds=60)

#: Digits in a numeric verification code.
CHALLENGE_CODE_DIGITS = 6

#: PBKDF2 iterations for challenge-code verifiers. A 6-digit code is
#: low-entropy, so a fast hash would be trivially reversible from a database
#: dump; the attempt limit and short TTL bound the online risk, this bounds the
#: offline one.
CHALLENGE_CODE_KDF_ITERATIONS = 120_000

#: Bytes of entropy in opaque session tokens.
SESSION_TOKEN_BYTES = 32


def session_ttls(remember_login: bool):
    """Return (absolute_ttl, inactivity_ttl) for the remember-login choice."""
    if remember_login:
        return (SESSION_ABSOLUTE_TTL_REMEMBER_ON, SESSION_INACTIVITY_TTL_REMEMBER_ON)
    return (SESSION_ABSOLUTE_TTL_REMEMBER_OFF, SESSION_INACTIVITY_TTL_REMEMBER_OFF)
