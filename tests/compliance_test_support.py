"""Explicit, test-only ownership for compliance-ready customer-send paths."""
from __future__ import annotations

import os
from contextlib import contextmanager
from functools import wraps
from typing import Iterator
from unittest import mock


TEST_COMPLIANCE_ENV = {
    "GENIE_PRIVACY_POLICY_URL": "https://c1-verification.invalid/privacy",
    "GENIE_TERMS_URL": "https://c1-verification.invalid/terms",
    "GENIE_UNSUBSCRIBE_URL": "https://c1-verification.invalid/unsubscribe",
    "GENIE_UNSUBSCRIBE_SIGNING_SECRET": "c1-test-only-signing-secret",
    "GENIE_UNSUBSCRIBE_HANDLER_CONTRACT": "v1_run_token_identity_confirmation",
}


@contextmanager
def compliance_ready_environment() -> Iterator[None]:
    """Temporarily install a complete non-production compliance contract."""
    with mock.patch.dict(os.environ, TEST_COMPLIANCE_ENV, clear=False):
        yield


def explicit_compliance_ready(test_method):
    """Opt one customer-send test into the complete test-only contract."""
    @wraps(test_method)
    def wrapped(*args, **kwargs):
        with compliance_ready_environment():
            return test_method(*args, **kwargs)

    return wrapped
