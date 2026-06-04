"""Kee-Suri source pack schema and source gate (foundation — not wired to runtime)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Set, Tuple

GateVerdict = Literal["pass", "hold", "block"]
IssueSeverity = Literal["block", "hold"]

SOURCE_TIERS = frozenset(
    {
        "T0_OFFICIAL_PRIMARY",
        "T1_OFFICIAL_SECONDARY",
        "T2_TIER1_WIRE",
        "T3_QUALITY_PRESS",
        "T4_AGGREGATOR_BLOG",
        "T5_SOCIAL_UNVERIFIED",
    }
)

CLAIM_TYPES = frozenset(
    {
        "general",
        "numeric",
        "date",
        "law_policy",
        "executive_order",
        "funding",
        "revenue",
        "product_spec",
        "forecast",
        "interpretation",
    }
)

CONFIDENCE_LABELS = frozenset(
    {"confirmed", "reported", "claimed", "estimated", "unverified"}
)

NUMERIC_LIKE_CLAIM_TYPES = frozenset(
    {"numeric", "funding", "revenue", "product_spec"}
)

LEGAL_CLAIM_TYPES = frozenset({"law_policy", "executive_order"})

DATE_ALLOWED_TIERS = frozenset(
    {
        "T0_OFFICIAL_PRIMARY",
        "T1_OFFICIAL_SECONDARY",
        "T2_TIER1_WIRE",
        "T3_QUALITY_PRESS",
    }
)

NEWS_LIKE_CLAIM_TYPES = frozenset(
    {
        "general",
        "numeric",
        "date",
        "funding",
        "revenue",
        "product_spec",
        "forecast",
    }
)

_ESTIMATED_WORDING_RE = re.compile(
    r"\b(estimate|estimated|approximately|roughly|about|around|projected|projection|"
    r"circa|~|≈)\b",
    re.IGNORECASE,
)

_STALE_HOURS = 72


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    source_name: str
    source_url: str
    source_tier: str
    fetched_at: str
    title: Optional[str] = None
    publisher: Optional[str] = None
    snippet: Optional[str] = None


@dataclass(frozen=True)
class ClaimRef:
    claim_id: str
    statement: str
    claim_type: str
    source_ids: Tuple[str, ...]
    confidence_label: str


@dataclass(frozen=True)
class SourcePack:
    program_id: str
    generated_at: str
    sources: Tuple[SourceRef, ...]
    claims: Tuple[ClaimRef, ...] = field(default_factory=tuple)
    notes: Optional[str] = None


@dataclass(frozen=True)
class GateIssue:
    code: str
    message: str
    severity: IssueSeverity
    source_id: Optional[str] = None
    claim_id: Optional[str] = None


@dataclass(frozen=True)
class GateResult:
    verdict: GateVerdict
    issues: Tuple[GateIssue, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.verdict == "pass"


def _tier_rank(tier: str) -> int:
    order = {
        "T0_OFFICIAL_PRIMARY": 0,
        "T1_OFFICIAL_SECONDARY": 1,
        "T2_TIER1_WIRE": 2,
        "T3_QUALITY_PRESS": 3,
        "T4_AGGREGATOR_BLOG": 4,
        "T5_SOCIAL_UNVERIFIED": 5,
    }
    return order.get(tier, 99)


def _worst_verdict(verdicts: Iterable[GateVerdict]) -> GateVerdict:
    items = list(verdicts)
    if "block" in items:
        return "block"
    if "hold" in items:
        return "hold"
    return "pass"


def _issues_verdict(issues: Sequence[GateIssue]) -> GateVerdict:
    if not issues:
        return "pass"
    return _worst_verdict(i.severity for i in issues)


def _parse_dt(value: str) -> Optional[datetime]:
    raw = (value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _coerce_now(now: Optional[datetime]) -> datetime:
    if now is not None:
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now
    return datetime.now(timezone.utc)


def _valid_deep_link(url: str) -> bool:
    u = (url or "").strip().lower()
    return u.startswith("http://") or u.startswith("https://")


def _source_map(sources: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for src in sources:
        if not isinstance(src, dict):
            continue
        sid = str(src.get("source_id") or "").strip()
        if sid:
            out[sid] = src
    return out


def _tiers_for_source_ids(
    source_ids: Sequence[str],
    smap: Dict[str, Dict[str, Any]],
) -> List[str]:
    tiers: List[str] = []
    for sid in source_ids:
        src = smap.get(sid)
        if src is None:
            continue
        tier = str(src.get("source_tier") or "").strip()
        if tier:
            tiers.append(tier)
    return tiers


def _has_tier(tiers: Sequence[str], allowed: Set[str]) -> bool:
    return any(t in allowed for t in tiers)


def _count_tier(tiers: Sequence[str], tier: str) -> int:
    return sum(1 for t in tiers if t == tier)


def _estimated_non_factual_wording(statement: str) -> bool:
    return bool(_ESTIMATED_WORDING_RE.search(statement or ""))


def _freshness_issues(
    source: Dict[str, Any],
    *,
    now: datetime,
) -> List[GateIssue]:
    sid = str(source.get("source_id") or "")
    fetched_raw = source.get("fetched_at")
    if fetched_raw is None or str(fetched_raw).strip() == "":
        return [
            GateIssue(
                code="source_fetched_at_missing",
                message="Source fetched_at is missing",
                severity="hold",
                source_id=sid or None,
            )
        ]
    fetched = _parse_dt(str(fetched_raw))
    if fetched is None:
        return [
            GateIssue(
                code="source_fetched_at_invalid",
                message="Source fetched_at is invalid",
                severity="hold",
                source_id=sid or None,
            )
        ]
    age = now - fetched.astimezone(timezone.utc)
    if age > timedelta(hours=_STALE_HOURS):
        return [
            GateIssue(
                code="source_stale",
                message=f"Source fetched_at is older than {_STALE_HOURS} hours",
                severity="hold",
                source_id=sid or None,
            )
        ]
    return []


def validate_source_pack(
    source_pack: dict,
    *,
    now: Optional[datetime] = None,
) -> GateResult:
    """Validate source pack structure, tiers, deep links, and freshness."""
    issues: List[GateIssue] = []
    ref_now = _coerce_now(now)

    if not isinstance(source_pack, dict):
        return GateResult(
            verdict="block",
            issues=(
                GateIssue(
                    code="invalid_source_pack",
                    message="Source pack must be a dict",
                    severity="block",
                ),
            ),
        )

    sources = source_pack.get("sources")
    if not isinstance(sources, list) or len(sources) == 0:
        issues.append(
            GateIssue(
                code="source_pack_empty",
                message="Source pack has no sources",
                severity="block",
            )
        )
        return GateResult(verdict="block", issues=tuple(issues))

    seen_ids: Set[str] = set()
    for src in sources:
        if not isinstance(src, dict):
            issues.append(
                GateIssue(
                    code="invalid_source_entry",
                    message="Source entry must be a dict",
                    severity="block",
                )
            )
            continue

        sid = str(src.get("source_id") or "").strip()
        if not sid:
            issues.append(
                GateIssue(
                    code="source_id_missing",
                    message="Source source_id is required",
                    severity="block",
                )
            )
            continue
        if sid in seen_ids:
            issues.append(
                GateIssue(
                    code="duplicate_source_id",
                    message=f"Duplicate source_id: {sid}",
                    severity="block",
                    source_id=sid,
                )
            )
        seen_ids.add(sid)

        url = str(src.get("source_url") or "").strip()
        if not _valid_deep_link(url):
            issues.append(
                GateIssue(
                    code="source_url_invalid",
                    message="Source source_url must begin with http:// or https://",
                    severity="block",
                    source_id=sid,
                )
            )

        tier = str(src.get("source_tier") or "").strip()
        if tier not in SOURCE_TIERS:
            issues.append(
                GateIssue(
                    code="source_tier_unknown",
                    message=f"Unknown source_tier: {tier!r}",
                    severity="block",
                    source_id=sid,
                )
            )

        issues.extend(_freshness_issues(src, now=ref_now))

    return GateResult(verdict=_issues_verdict(issues), issues=tuple(issues))


def audit_claims(
    source_pack: dict,
    claims: list[dict],
    *,
    now: Optional[datetime] = None,
) -> GateResult:
    """Audit claims against source tiers, confidence labels, and freshness."""
    _ = _coerce_now(now)
    issues: List[GateIssue] = []

    sources = source_pack.get("sources") if isinstance(source_pack, dict) else []
    if not isinstance(sources, list):
        sources = []
    smap = _source_map(sources)

    if not claims:
        issues.append(
            GateIssue(
                code="claims_missing",
                message="No claims provided for audit",
                severity="hold",
            )
        )
        return GateResult(verdict="hold", issues=tuple(issues))

    for claim in claims:
        if not isinstance(claim, dict):
            issues.append(
                GateIssue(
                    code="invalid_claim_entry",
                    message="Claim entry must be a dict",
                    severity="block",
                )
            )
            continue

        cid = str(claim.get("claim_id") or "").strip()
        claim_type = str(claim.get("claim_type") or "").strip()
        confidence = str(claim.get("confidence_label") or "").strip()
        statement = str(claim.get("statement") or "").strip()
        raw_ids = claim.get("source_ids")
        source_ids: List[str] = []
        if isinstance(raw_ids, list):
            source_ids = [str(x).strip() for x in raw_ids if str(x).strip()]

        if claim_type not in CLAIM_TYPES:
            issues.append(
                GateIssue(
                    code="claim_type_unknown",
                    message=f"Unknown claim_type: {claim_type!r}",
                    severity="block",
                    claim_id=cid or None,
                )
            )
            continue

        if confidence not in CONFIDENCE_LABELS:
            issues.append(
                GateIssue(
                    code="confidence_label_unknown",
                    message=f"Unknown confidence_label: {confidence!r}",
                    severity="block",
                    claim_id=cid or None,
                )
            )
            continue

        if confidence == "estimated" and claim_type in LEGAL_CLAIM_TYPES:
            issues.append(
                GateIssue(
                    code="estimated_not_allowed_for_legal",
                    message="estimated confidence must not be used for law_policy or executive_order",
                    severity="block",
                    claim_id=cid or None,
                )
            )

        tiers = _tiers_for_source_ids(source_ids, smap)
        missing_sources = [sid for sid in source_ids if sid not in smap]
        if missing_sources:
            issues.append(
                GateIssue(
                    code="claim_source_id_unknown",
                    message=f"Claim references unknown source_ids: {', '.join(missing_sources)}",
                    severity="block",
                    claim_id=cid or None,
                )
            )

        if not source_ids:
            if claim_type == "date":
                issues.append(
                    GateIssue(
                        code="date_claim_no_source",
                        message="Date claim requires source_ids",
                        severity="block",
                        claim_id=cid or None,
                    )
                )
            elif claim_type in NUMERIC_LIKE_CLAIM_TYPES:
                issues.append(
                    GateIssue(
                        code="numeric_claim_no_source",
                        message="Numeric-like claim requires supporting sources",
                        severity="block",
                        claim_id=cid or None,
                    )
                )
            elif claim_type in LEGAL_CLAIM_TYPES:
                issues.append(
                    GateIssue(
                        code="legal_claim_no_source",
                        message="Legal/policy claim requires supporting sources",
                        severity="block",
                        claim_id=cid or None,
                    )
                )
            continue

        # T5 cannot support customer-facing factual claims (all audited claims).
        if tiers and all(t == "T5_SOCIAL_UNVERIFIED" for t in tiers):
            issues.append(
                GateIssue(
                    code="t5_only_factual_claim",
                    message="T5_SOCIAL_UNVERIFIED alone cannot support factual claims",
                    severity="block",
                    claim_id=cid or None,
                )
            )

        # Numeric-like claims
        if claim_type in NUMERIC_LIKE_CLAIM_TYPES:
            has_t0_t2 = _has_tier(tiers, {"T0_OFFICIAL_PRIMARY", "T2_TIER1_WIRE"})
            has_t3 = _has_tier(tiers, {"T3_QUALITY_PRESS"})
            has_t4_t5 = _has_tier(
                tiers,
                {"T4_AGGREGATOR_BLOG", "T5_SOCIAL_UNVERIFIED"},
            )
            t4_only = has_t4_t5 and not _has_tier(
                tiers,
                {
                    "T0_OFFICIAL_PRIMARY",
                    "T1_OFFICIAL_SECONDARY",
                    "T2_TIER1_WIRE",
                    "T3_QUALITY_PRESS",
                },
            )

            if confidence == "estimated" and _estimated_non_factual_wording(statement):
                pass  # allowed with explicit non-factual wording
            elif has_t0_t2:
                pass  # strong numeric support
            elif has_t3 and not t4_only:
                issues.append(
                    GateIssue(
                        code="numeric_claim_t3_only",
                        message="Numeric-like claim supported by T3 only; requires T0/T2 or estimated wording",
                        severity="hold",
                        claim_id=cid or None,
                    )
                )
            else:
                issues.append(
                    GateIssue(
                        code="numeric_claim_insufficient_tier",
                        message="Numeric-like claim lacks T0/T2 support",
                        severity="block",
                        claim_id=cid or None,
                    )
                )

            if confidence == "unverified":
                issues.append(
                    GateIssue(
                        code="unverified_numeric_claim",
                        message="Unverified numeric-like claim is not allowed",
                        severity="block",
                        claim_id=cid or None,
                    )
                )

        # Date claims
        if claim_type == "date":
            if not _has_tier(tiers, DATE_ALLOWED_TIERS):
                issues.append(
                    GateIssue(
                        code="date_claim_insufficient_tier",
                        message="Date claim requires T0, T1, T2, or T3 source",
                        severity="block",
                        claim_id=cid or None,
                    )
                )

        # Law / policy / executive order
        if claim_type in LEGAL_CLAIM_TYPES:
            has_t0 = _has_tier(tiers, {"T0_OFFICIAL_PRIMARY"})
            has_t2_t3 = _has_tier(tiers, {"T2_TIER1_WIRE", "T3_QUALITY_PRESS"})
            t4_t5_only = tiers and all(
                t in {"T4_AGGREGATOR_BLOG", "T5_SOCIAL_UNVERIFIED"} for t in tiers
            )

            if t4_t5_only:
                issues.append(
                    GateIssue(
                        code="legal_claim_t4_t5_only",
                        message="Law/policy claims cannot rely on T4/T5 sources alone",
                        severity="block",
                        claim_id=cid or None,
                    )
                )
            elif confidence == "confirmed" and not has_t0:
                if has_t2_t3:
                    issues.append(
                        GateIssue(
                            code="legal_confirmed_missing_t0",
                            message="Confirmed legal/policy claim requires T0 official source",
                            severity="hold",
                            claim_id=cid or None,
                        )
                    )
                else:
                    issues.append(
                        GateIssue(
                            code="legal_confirmed_no_official",
                            message="Confirmed legal/policy claim lacks official source",
                            severity="block",
                            claim_id=cid or None,
                        )
                    )
            elif confidence == "reported" and not has_t2_t3 and not has_t0:
                issues.append(
                    GateIssue(
                        code="legal_reported_insufficient_tier",
                        message="Reported legal/policy claim requires T0, T2, or T3 source",
                        severity="block",
                        claim_id=cid or None,
                    )
                )

        # Confidence label enforcement
        t0 = _count_tier(tiers, "T0_OFFICIAL_PRIMARY")
        t1 = _count_tier(tiers, "T1_OFFICIAL_SECONDARY")
        t2 = _count_tier(tiers, "T2_TIER1_WIRE")
        t3 = _count_tier(tiers, "T3_QUALITY_PRESS")
        t4 = _count_tier(tiers, "T4_AGGREGATOR_BLOG")
        t5 = _count_tier(tiers, "T5_SOCIAL_UNVERIFIED")

        if confidence == "confirmed":
            if not (t0 >= 1 or t2 >= 2):
                issues.append(
                    GateIssue(
                        code="confirmed_insufficient_support",
                        message="confirmed requires T0 or at least two independent T2 sources",
                        severity="hold" if t2 >= 1 or t3 >= 1 else "block",
                        claim_id=cid or None,
                    )
                )
        elif confidence == "reported":
            if t2 + t3 + t0 + t1 == 0:
                issues.append(
                    GateIssue(
                        code="reported_insufficient_support",
                        message="reported requires at least one T2 or T3 source",
                        severity="block",
                        claim_id=cid or None,
                    )
                )
        elif confidence == "claimed":
            if t3 + t4 + t2 + t0 + t1 == 0:
                issues.append(
                    GateIssue(
                        code="claimed_insufficient_support",
                        message="claimed requires at least T3 or T4 source",
                        severity="block",
                        claim_id=cid or None,
                    )
                )
        elif confidence == "unverified":
            t5_only = tiers and all(t == "T5_SOCIAL_UNVERIFIED" for t in tiers)
            if claim_type in NUMERIC_LIKE_CLAIM_TYPES or claim_type in LEGAL_CLAIM_TYPES:
                issues.append(
                    GateIssue(
                        code="unverified_sensitive_claim",
                        message="Unverified numeric or legal claim is blocked",
                        severity="block",
                        claim_id=cid or None,
                    )
                )
            elif t5_only:
                issues.append(
                    GateIssue(
                        code="unverified_t5_only",
                        message="Unverified claim with T5-only sources is blocked",
                        severity="block",
                        claim_id=cid or None,
                    )
                )
            else:
                issues.append(
                    GateIssue(
                        code="unverified_claim_hold",
                        message="Unverified claim requires additional verification",
                        severity="hold",
                        claim_id=cid or None,
                    )
                )

        # T4 alone cannot support sensitive claim types
        if claim_type in NUMERIC_LIKE_CLAIM_TYPES | LEGAL_CLAIM_TYPES | frozenset({"date"}):
            if tiers and all(t == "T4_AGGREGATOR_BLOG" for t in tiers):
                issues.append(
                    GateIssue(
                        code="t4_only_sensitive_claim",
                        message="T4_AGGREGATOR_BLOG alone cannot support this claim type",
                        severity="block",
                        claim_id=cid or None,
                    )
                )

        # Stale sources for news-like claims
        if claim_type in NEWS_LIKE_CLAIM_TYPES:
            for sid in source_ids:
                src = smap.get(sid)
                if not src:
                    continue
                stale = _freshness_issues(src, now=_coerce_now(now))
                for s_issue in stale:
                    issues.append(
                        GateIssue(
                            code=f"claim_{s_issue.code}",
                            message=f"Claim {cid}: {s_issue.message}",
                            severity=s_issue.severity,
                            claim_id=cid or None,
                            source_id=sid,
                        )
                    )

    return GateResult(verdict=_issues_verdict(issues), issues=tuple(issues))


def run_keysuri_source_gate(
    source_pack: dict,
    claims: list[dict] | None = None,
    *,
    now: Optional[datetime] = None,
) -> GateResult:
    """Run full Kee-Suri source gate: pack validation plus claim audit."""
    pack_result = validate_source_pack(source_pack, now=now)
    if pack_result.verdict == "block":
        return pack_result

    if claims is None:
        raw_claims = source_pack.get("claims") if isinstance(source_pack, dict) else None
        claims = raw_claims if isinstance(raw_claims, list) else []

    claim_result = audit_claims(source_pack, claims, now=now)
    combined_issues = pack_result.issues + claim_result.issues
    return GateResult(
        verdict=_worst_verdict((pack_result.verdict, claim_result.verdict)),
        issues=combined_issues,
    )
