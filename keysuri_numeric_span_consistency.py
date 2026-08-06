"""Year-span / duration consistency checks for Kee-Suri visible prose."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# "2025년부터 2032년까지 6년간" / "2025–2032년 6년"
_YEAR_SPAN_DURATION_RE = re.compile(
    r"(?P<source>(?P<start>20\d{2})\s*년?\s*(?:부터|~|-|–|—)\s*(?P<end>20\d{2})\s*년?\s*"
    r"(?:까지\s*)?(?P<duration>\d+)\s*년(?:간)?)"
)

_EXPLICIT_BASIS_MARKERS = (
    "회계연도",
    "사업연도",
    "영업일",
    "제외",
    "미포함",
    "inclusive",
    "exclusive",
)


def compute_year_spans(start: int, end: int) -> Dict[str, int]:
    return {
        "inclusive": end - start + 1,
        "exclusive": end - start,
    }


def analyze_year_span_claim(text: str) -> Optional[Dict[str, Any]]:
    """Return mismatch diagnostics when endpoint years and a duration disagree."""
    blob = str(text or "")
    match = _YEAR_SPAN_DURATION_RE.search(blob)
    if not match:
        return None
    start = int(match.group("start"))
    end = int(match.group("end"))
    duration = int(match.group("duration"))
    spans = compute_year_spans(start, end)
    if duration in (spans["inclusive"], spans["exclusive"]):
        return {
            "mismatch": False,
            "source_value": match.group("source"),
            "generated_value": match.group("source"),
            "start_year": start,
            "end_year": end,
            "claimed_duration": duration,
            "computed_span": spans,
            "resolution": "consistent",
            "decision_critical": False,
        }
    window = blob[max(0, match.start() - 40) : match.end() + 40]
    has_basis = any(marker in window for marker in _EXPLICIT_BASIS_MARKERS)
    if has_basis:
        return {
            "mismatch": False,
            "source_value": match.group("source"),
            "generated_value": match.group("source"),
            "start_year": start,
            "end_year": end,
            "claimed_duration": duration,
            "computed_span": spans,
            "resolution": "explicit_basis_accepted",
            "decision_critical": False,
        }
    return {
        "mismatch": True,
        "source_value": f"{start}년–{end}년",
        "generated_value": match.group("source"),
        "start_year": start,
        "end_year": end,
        "claimed_duration": duration,
        "computed_span": spans,
        "resolution": "pending",
        "decision_critical": False,
    }


def repair_year_span_duration(
    text: str,
    *,
    decision_critical: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    """Remove an irreconcilable derived duration; keep sourced endpoints.

    When ``decision_critical`` is True and a mismatch remains unrepaired,
    diagnostics mark ``resolution=blocked``.
    """
    analysis = analyze_year_span_claim(text)
    if not analysis:
        return str(text or ""), {
            "mismatch": False,
            "resolution": "not_applicable",
            "source_value": "",
            "generated_value": "",
            "computed_span": {},
        }
    if not analysis.get("mismatch"):
        return str(text or ""), analysis

    def _repl(match: re.Match[str]) -> str:
        start = match.group("start")
        end = match.group("end")
        return f"{start}년부터 {end}년까지"

    repaired = _YEAR_SPAN_DURATION_RE.sub(_repl, str(text or ""), count=1)
    analysis = dict(analysis)
    analysis["generated_value"] = repaired
    if decision_critical and analyze_year_span_claim(repaired):
        # Still mismatched somehow — block.
        analysis["resolution"] = "blocked"
        analysis["decision_critical"] = True
        return str(text or ""), analysis
    analysis["resolution"] = "removed_derived_duration"
    analysis["decision_critical"] = bool(decision_critical)
    return repaired, analysis


def scan_and_repair_year_spans(root: Any) -> Tuple[Any, List[Dict[str, Any]]]:
    """Walk nested briefing structures and repair mismatched year durations."""
    diagnostics: List[Dict[str, Any]] = []

    def _walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: _walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(v) for v in value]
        if isinstance(value, str):
            repaired, diag = repair_year_span_duration(value)
            if diag.get("mismatch") or diag.get("resolution") == "removed_derived_duration":
                diagnostics.append(diag)
            return repaired
        return value

    return _walk(root), diagnostics
