"""Canonical Customer email normalization and minimal format validation."""


def normalize_email(value: str) -> str:
    """Preserve the accepted Customer contract: trim and lowercase."""
    return str(value or "").strip().lower()


def is_valid_email(value: str) -> bool:
    """Validate an already-normalized address without provider assumptions."""
    local, separator, domain = value.partition("@")
    return bool(separator and local and domain and "." in domain and " " not in value)
