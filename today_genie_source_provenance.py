"""Offline input-link binding only; never fetch, infer, or certify article facts."""
from __future__ import annotations

import ipaddress
import re
from typing import Any, Mapping
from urllib.parse import parse_qsl, unquote, urlsplit

SOURCE_PROVENANCE_ISSUE = "customer_surface_source_provenance_incomplete"

_CREDENTIAL_KEYS = frozenset({
    "accesstoken", "refreshtoken", "idtoken", "apikey", "password", "passwd",
    "auth", "authorization", "clientsecret", "secret", "token", "sessiontoken",
    "signature", "sig", "xamzsignature", "xgoogsignature", "xamzcredential",
    "xgoogcredential", "xamzsecuritytoken", "xgoogsecuritytoken", "awsaccesskeyid",
})


def _credential_component(component: str) -> bool:
    # Decode only for inspection. Never remove values or publish a sanitized
    # substitute URL. Include named credentials in SPA callback fragments.
    decoded = component
    for _ in range(3):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    for part in (decoded, decoded.rsplit("?", 1)[-1]):
        for key, _value in parse_qsl(part.replace(";", "&"), keep_blank_values=True):
            normalized = re.sub(r"[-_\s]", "", key).casefold()
            if normalized in _CREDENTIAL_KEYS:
                return True
    return False


def input_article_url(item: Mapping[str, Any]) -> str:
    """Prefer the untouched input link to a dedup-normalized canonical URL."""
    for key in ("source_url", "url", "link", "canonical_url"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value  # Do not normalize query, case, or encoding.
    return ""


def article_url_issue(value: Any) -> str:
    """Lexical safe article-shaped URL, not proof of original/article/rights."""
    if not isinstance(value, str) or not value:
        return "missing_original_source_url"
    if value != value.strip() or re.search(r"[\s\x00-\x1f\x7f\\]", value):
        return "invalid_original_source_url"
    try:
        p = urlsplit(value)
        if p.scheme.lower() not in ("https", "http") or not p.netloc or not p.hostname:
            return "invalid_original_source_url"
        if p.username is not None or p.password is not None or "@" in p.netloc:
            return "credential_source_url"
        if _credential_component(p.query) or _credential_component(p.fragment):
            return "credential_source_url"
        _ = p.port
        host = p.hostname.encode("idna").decode("ascii")
        if "." not in host or not re.fullmatch(r"[a-zA-Z0-9.-]+", host):
            return "invalid_original_source_url"
        if len(host) > 253 or any(not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label) for label in host.split(".")):
            return "invalid_original_source_url"
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return "non_article_source_url"
        if host.endswith((".localhost", ".local", ".internal")):
            return "non_article_source_url"
        if not p.path.strip("/") or p.path.rstrip("/").lower() in ("/search", "/news", "/latest", "/rss", "/feed", "/home", "/index.html", "/index.htm", "/index.php"):
            return "non_article_source_url"
    except (ValueError, UnicodeError):
        return "invalid_original_source_url"
    return ""


def input_source_fields(item: Mapping[str, Any]) -> dict[str, Any]:
    url = input_article_url(item)
    origin = str(item.get("source_url_origin") or "").strip().lower()
    inferred = item.get("source_url_inferred") is True or origin in ("inferred", "generated", "search_result", "publisher_homepage")
    issue = "inferred_original_source_url" if inferred else article_url_issue(url)
    published = next((item[k] for k in ("published_at", "published", "pubDate") if isinstance(item.get(k), str) and item[k]), "")
    source = item.get("source") or item.get("source_name") or ""
    if isinstance(source, Mapping):
        source = source.get("source_name") or source.get("name") or ""
    return {
        "source_url": url if not issue else "",
        "source_name": source,
        "source_published_at": published,
        "source_date": item.get("date") or "",
        "source_publication_status": "INPUT_VALUE_UNVERIFIED" if published else "UNAVAILABLE",
        "source_provenance_status": "INPUT_URL_BOUND_NOT_FACT_PASS" if not issue else "INCOMPLETE",
        "source_provenance_issue": issue,
    }


def watchpoint_source_issue(item: Mapping[str, Any], selected: Mapping[str, Any] | None, *, allow_market_feed: bool = False) -> str:
    """Customer boundary verifies input binding even if a marker is removed."""
    if allow_market_feed and item.get("source_kind") == "market_feed" and not item.get("news_id"):
        return ""  # Not a selected factual news article; unchanged feed contract.
    if selected is None:
        return "unbound_original_source_input"
    expected = input_source_fields(selected)
    if expected["source_provenance_issue"]:
        return str(expected["source_provenance_issue"])
    for key in ("source_url", "source_name", "source_published_at", "source_date"):
        if item.get(key) != expected[key]:
            return "original_source_projection_mismatch"
    return ""
