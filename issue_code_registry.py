"""Minimal hard-block issue-code registry (Today / Global / Korea / shared).

Offline classification only — no network, mail, or deploy side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional

REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE = "DETERMINISTICALLY_REPAIRABLE"
REPAIRABILITY_MODEL_CORRECTIVE_RETRY = "MODEL_CORRECTIVE_RETRY"
REPAIRABILITY_TERMINAL_BLOCK = "TERMINAL_BLOCK"

SEVERITY_BLOCK = "block"
SEVERITY_REPAIR = "repair"
SEVERITY_WARN = "warn"

_VALID_REPAIRABILITIES = frozenset(
    {
        REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        REPAIRABILITY_MODEL_CORRECTIVE_RETRY,
        REPAIRABILITY_TERMINAL_BLOCK,
    }
)
_VALID_SEVERITIES = frozenset({SEVERITY_BLOCK, SEVERITY_REPAIR, SEVERITY_WARN})


@dataclass(frozen=True)
class IssueCodeEntry:
    code: str
    program: str  # today | global | korea | shared
    stage: str
    severity: str  # block | repair | warn
    repairability: str
    notes: str = ""

    def __post_init__(self) -> None:
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(f"invalid severity for {self.code!r}: {self.severity!r}")
        if self.repairability not in _VALID_REPAIRABILITIES:
            raise ValueError(
                f"invalid repairability for {self.code!r}: {self.repairability!r}"
            )


ISSUE_CODE_REGISTRY: tuple[IssueCodeEntry, ...] = (
    # --- Visible-text / connector ellipsis (deterministic repair path) ---
    IssueCodeEntry(
        code="keysuri_korean_connector_ellipsis_blocked",
        program="shared",
        stage="visible_text_quality",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        notes="Connector ellipsis; deterministic repair precedes residual block.",
    ),
    IssueCodeEntry(
        code="keysuri_korean_connector_ellipsis_repaired",
        program="shared",
        stage="visible_text_quality",
        severity=SEVERITY_REPAIR,
        repairability=REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        notes="Connector ellipsis successfully rewritten.",
    ),
    # --- Global display-shell / missing contract keys (scaffold salvage) ---
    IssueCodeEntry(
        code="gemini_json_missing_required_keys",
        program="global",
        stage="generation_validation",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        notes="Display-shell / partial contract; Global scaffold grafts trusted TOP5.",
    ),
    IssueCodeEntry(
        code="top_5_news_missing",
        program="global",
        stage="generation_validation",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        notes="Scaffold from frozen prompt_input TOP5 when display-shell signal present.",
    ),
    IssueCodeEntry(
        code="deep_dive_missing",
        program="global",
        stage="generation_validation",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        notes="Scaffold from opening_lead + TOP5 prose.",
    ),
    IssueCodeEntry(
        code="one_line_checkpoint_missing",
        program="global",
        stage="generation_validation",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        notes="Scaffold from selected_title / opening_lead.",
    ),
    IssueCodeEntry(
        code="closing_sources_missing",
        program="global",
        stage="generation_validation",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        notes="Scaffold closing_sources from prompt source pack + closing_message.",
    ),
    IssueCodeEntry(
        code="generated_status_invalid",
        program="shared",
        stage="generation_validation",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        notes="Program-deterministic status constant can be grafted when blank.",
    ),
    IssueCodeEntry(
        code="operational_status_invalid",
        program="shared",
        stage="generation_validation",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        notes="Program-deterministic status constant can be grafted when blank.",
    ),
    IssueCodeEntry(
        code="keysuri_global_contract_scaffold_applied",
        program="global",
        stage="parse_repair",
        severity=SEVERITY_REPAIR,
        repairability=REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        notes="Internal marker that Global contract scaffold salvaged the payload.",
    ),
    IssueCodeEntry(
        code="gemini_json_schema_validation_failed",
        program="shared",
        stage="generation_validation",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_MODEL_CORRECTIVE_RETRY,
        notes="Residual schema failure after salvage; bounded model corrective retry.",
    ),
    IssueCodeEntry(
        code="top_5_item_count_invalid",
        program="shared",
        stage="generation_validation",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_MODEL_CORRECTIVE_RETRY,
        notes="Wrong TOP5 cardinality is not silently rewritten to invent items.",
    ),
    # --- Genuine truncation (do not invent closure) ---
    IssueCodeEntry(
        code="global_visible_text_truncated_deep_dive",
        program="global",
        stage="post_render_visible_text",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_TERMINAL_BLOCK,
        notes="Genuine deep-dive truncation; scaffold must not invent sentence closure.",
    ),
    IssueCodeEntry(
        code="korea_visible_text_truncated_follow_item",
        program="korea",
        stage="post_render_visible_text",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_TERMINAL_BLOCK,
        notes="Genuine Korea follow/checkpoint truncation; terminal before SMTP.",
    ),
    IssueCodeEntry(
        code="keysuri_global_post_render_qa_blocked",
        program="global",
        stage="post_render_visible_text",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_TERMINAL_BLOCK,
        notes="Owner-review SMTP gate after Global post-render QA failure.",
    ),
    IssueCodeEntry(
        code="keysuri_korea_post_render_qa_blocked",
        program="korea",
        stage="post_render_visible_text",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_TERMINAL_BLOCK,
        notes="Owner-review SMTP gate after Korea post-render QA failure.",
    ),
    # --- Customer / SMTP ambiguity (retry side-effect safety) ---
    IssueCodeEntry(
        code="customer_send_ambiguity_blocked",
        program="shared",
        stage="retry_actionability",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_TERMINAL_BLOCK,
        notes="Customer may already have been sent; RETRY_BLOCKED.",
    ),
    IssueCodeEntry(
        code="smtp_outcome_ambiguous",
        program="shared",
        stage="retry_actionability",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_TERMINAL_BLOCK,
        notes="Owner-review SMTP outcome ambiguous; RETRY_BLOCKED.",
    ),
    # --- Today natural-slot invalid match ---
    IssueCodeEntry(
        code="invalid_natural_slot_match",
        program="today",
        stage="natural_slot_duplicate_gate",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_TERMINAL_BLOCK,
        notes="QA/manual/canary artifact must not satisfy natural 06:30 slot.",
    ),
    IssueCodeEntry(
        code="invalid_natural_slot_duplicate_match",
        program="today",
        stage="natural_slot_duplicate_gate",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_TERMINAL_BLOCK,
        notes="Reject invalid duplicate match; fail closed.",
    ),
    IssueCodeEntry(
        code="qa_consumed_natural_slot",
        program="today",
        stage="natural_slot_duplicate_gate",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_TERMINAL_BLOCK,
        notes="Watchdog: QA/manual path incorrectly treated as natural completer.",
    ),
)


def _by_code() -> Dict[str, IssueCodeEntry]:
    out: Dict[str, IssueCodeEntry] = {}
    for entry in ISSUE_CODE_REGISTRY:
        if entry.code in out:
            raise ValueError(f"duplicate issue code in registry: {entry.code!r}")
        out[entry.code] = entry
    return out


_REGISTRY_BY_CODE: Dict[str, IssueCodeEntry] = _by_code()

HARD_BLOCK_CODES: FrozenSet[str] = frozenset(
    entry.code for entry in ISSUE_CODE_REGISTRY if entry.severity == SEVERITY_BLOCK
)


def get_issue_code(code: str) -> Optional[IssueCodeEntry]:
    return _REGISTRY_BY_CODE.get(str(code or "").strip())


def list_issue_codes(*, program: Optional[str] = None) -> List[IssueCodeEntry]:
    rows = list(ISSUE_CODE_REGISTRY)
    if program is not None:
        want = str(program).strip()
        rows = [e for e in rows if e.program == want or e.program == "shared"]
    return rows


def classify_repairability(code: str) -> str:
    """Return repairability class for a known code.

    Unknown codes fail closed as TERMINAL_BLOCK so callers never treat
    unrecognized hard failures as silently repairable.
    """
    entry = get_issue_code(code)
    if entry is None:
        return REPAIRABILITY_TERMINAL_BLOCK
    return entry.repairability


def iter_hard_block_codes() -> Iterable[str]:
    return sorted(HARD_BLOCK_CODES)
