"""Process-wide network/SMTP kill switch for the DevOps recovery harness."""
from __future__ import annotations

import os
import smtplib
import socket
from pathlib import Path

_COUNTER_ROOT = Path(os.environ.get("GENIE_HARNESS_COUNTER_ROOT", "/tmp"))


def _record(name: str) -> None:
    _COUNTER_ROOT.mkdir(parents=True, exist_ok=True)
    path = _COUNTER_ROOT / name
    with path.open("ab") as handle:
        handle.write(b"1\n")


_original_connect = socket.socket.connect
_original_create_connection = socket.create_connection


def _blocked_connect(self, address):
    # AF_UNIX is local IPC. Every internet-capable socket is forbidden.
    if self.family in {socket.AF_INET, socket.AF_INET6}:
        _record("external_network_attempts.log")
        raise OSError("external network disabled by Genie DevOps harness")
    return _original_connect(self, address)


def _blocked_create_connection(*args, **kwargs):
    _record("external_network_attempts.log")
    raise OSError("external network disabled by Genie DevOps harness")


class _BlockedSMTP:
    def __init__(self, *args, **kwargs):
        _record("smtp_attempts.log")
        raise OSError("SMTP disabled by Genie DevOps harness")


socket.socket.connect = _blocked_connect
socket.create_connection = _blocked_create_connection
smtplib.SMTP = _BlockedSMTP
smtplib.SMTP_SSL = _BlockedSMTP


if os.environ.get("GENIE_HARNESS_ACTIVE") == "1":
    try:
        from google.cloud import storage as _gcs_storage

        class _BlockedStorageClient:
            def __init__(self, *args, **kwargs):
                _record("gcs_client_attempts.log")
                raise RuntimeError("real GCS client disabled by Genie DevOps harness")

        _gcs_storage.Client = _BlockedStorageClient
    except ImportError:
        pass

    try:
        import google.auth as _google_auth

        def _blocked_google_auth_default(*args, **kwargs):
            _record("credential_attempts.log")
            raise RuntimeError("actual credential discovery disabled by Genie DevOps harness")

        _google_auth.default = _blocked_google_auth_default
    except ImportError:
        pass
