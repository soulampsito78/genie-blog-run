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
        code="global_contract_scaffold_fabricated_top5",
        program="global",
        stage="generation",
        severity=SEVERITY_REPAIR,
        repairability=REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        notes=(
            "Scaffold had to graft the whole TOP5 — the model contributed no "
            "article prose. Buys the one budgeted corrective generation call."
        ),
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
    # --- Global visible-surface gate (2026-08-14 remediation) ---
    IssueCodeEntry(
        code="global_visible_subject_integrity_blocked",
        program="global",
        stage="post_render_visible_text",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        notes="Subject/title cut mid-quote or on dangling punctuation.",
    ),
    IssueCodeEntry(
        code="global_visible_internal_template_leak_blocked",
        program="global",
        stage="post_render_visible_text",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_MODEL_CORRECTIVE_RETRY,
        notes="Source-pack scaffolding text reached the customer surface.",
    ),
    IssueCodeEntry(
        code="global_selection_below_quality_floor",
        program="global",
        stage="selection",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_TERMINAL_BLOCK,
        notes=(
            "TOP5 contains cards the scorer classified reject. Filling five "
            "slots is not a reason to publish an article that did not clear the "
            "product quality floor."
        ),
    ),
    IssueCodeEntry(
        code="global_visible_raw_english_prose_blocked",
        program="global",
        stage="post_render_visible_text",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_MODEL_CORRECTIVE_RETRY,
        notes="Raw English source prose inside a Korean explanatory field.",
    ),
    IssueCodeEntry(
        code="global_visible_semantic_truncation_blocked",
        program="global",
        stage="post_render_visible_text",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_TERMINAL_BLOCK,
        notes="Feed excerpt cut mid-sentence but ending on valid punctuation.",
    ),
    IssueCodeEntry(
        code="global_visible_repeated_template_skeleton_blocked",
        program="global",
        stage="post_render_visible_text",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_MODEL_CORRECTIVE_RETRY,
        notes="One padding template skeleton reused across 3+ TOP5 items.",
    ),
    IssueCodeEntry(
        code="global_visible_deep_dive_duplication_blocked",
        program="global",
        stage="post_render_visible_text",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_MODEL_CORRECTIVE_RETRY,
        notes="Deep dive restates opening_lead/TOP5 instead of synthesizing.",
    ),
    IssueCodeEntry(
        code="global_visible_category_grounding_mismatch",
        program="global",
        stage="post_render_visible_text",
        severity=SEVERITY_WARN,
        repairability=REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        notes="Rendered category contradicts the item's own category evidence.",
    ),
    IssueCodeEntry(
        code="keysuri_korean_particle_repaired",
        program="global",
        stage="post_render_visible_text",
        severity=SEVERITY_REPAIR,
        repairability=REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        notes="Hangul particle agreement corrected deterministically before adjudication.",
    ),
    IssueCodeEntry(
        code="global_visible_korean_particle_defect",
        program="global",
        stage="post_render_visible_text",
        severity=SEVERITY_WARN,
        repairability=REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        notes="Assembled subject particle disagrees with preceding jongseong.",
    ),
    IssueCodeEntry(
        code="keysuri_visible_text_quality_blocked",
        program="shared",
        stage="visible_text_quality",
        severity=SEVERITY_BLOCK,
        repairability=REPAIRABILITY_TERMINAL_BLOCK,
        notes="Visible-text walker reported block for a non-ellipsis reason.",
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


# ---------------------------------------------------------------------------
# KeeSuri graded owner-review adjudication policy
# ---------------------------------------------------------------------------

FINDING_SEVERITY_INFO = "INFO"
FINDING_SEVERITY_REVIEW = "REVIEW"
FINDING_SEVERITY_BLOCK = "BLOCK"

SAFETY_FAMILY_STRUCTURAL = "STRUCTURAL_UNUSABILITY"
SAFETY_FAMILY_GROUNDING = "FACTUAL_GROUNDING_UNSAFETY"
SAFETY_FAMILY_SEMANTIC = "SEMANTIC_CORRUPTION"
SAFETY_FAMILY_SECURITY = "SECURITY_PRIVACY"
SAFETY_FAMILY_DELIVERY_AUTHORITY = "DELIVERY_AUTHORITY"
SAFETY_FAMILY_EDITORIAL = "EDITORIAL_QUALITY"


@dataclass(frozen=True)
class GradedIssuePolicy:
    """Registry-owned meaning of a KeeSuri finding.

    Historical code spelling (including ``*_blocked``) is deliberately not
    consulted.  Only this registry entry may assign canonical severity.
    """

    code: str
    severity: str
    family: str
    label_ko: str


_GRADED_BLOCK_POLICIES: Dict[str, GradedIssuePolicy] = {
    # Structural execution/content preconditions.
    "gemini_json_missing_required_keys": GradedIssuePolicy(
        "gemini_json_missing_required_keys", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_STRUCTURAL, "필수 생성 구조 누락",
    ),
    "gemini_json_schema_validation_failed": GradedIssuePolicy(
        "gemini_json_schema_validation_failed", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_STRUCTURAL, "생성 구조 검증 실패",
    ),
    "top_5_news_missing": GradedIssuePolicy(
        "top_5_news_missing", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_STRUCTURAL, "TOP5 구조 누락",
    ),
    "top_5_item_count_invalid": GradedIssuePolicy(
        "top_5_item_count_invalid", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_STRUCTURAL, "TOP5 항목 수 오류",
    ),
    "top5_item_count": GradedIssuePolicy(
        "top5_item_count", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_STRUCTURAL, "TOP5 항목 수 오류",
    ),
    "generated_status_invalid": GradedIssuePolicy(
        "generated_status_invalid", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_STRUCTURAL, "생성 계약 상태 오류",
    ),
    "operational_status_invalid": GradedIssuePolicy(
        "operational_status_invalid", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_STRUCTURAL, "필수 운영 구조 오류",
    ),
    "deep_dive_missing": GradedIssuePolicy(
        "deep_dive_missing", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_STRUCTURAL, "필수 딥다이브 구조 누락",
    ),
    "one_line_checkpoint_missing": GradedIssuePolicy(
        "one_line_checkpoint_missing", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_STRUCTURAL, "필수 체크포인트 누락",
    ),
    "closing_sources_missing": GradedIssuePolicy(
        "closing_sources_missing", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_STRUCTURAL, "필수 출처 구조 누락",
    ),
    "rendering_impossible": GradedIssuePolicy(
        "rendering_impossible", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_STRUCTURAL, "최종 표면 렌더링 불가",
    ),
    # Grounding/factual safety.
    "unsupported_claim": GradedIssuePolicy(
        "unsupported_claim", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_GROUNDING, "근거 없는 주장",
    ),
    "item_source_missing": GradedIssuePolicy(
        "item_source_missing", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_GROUNDING, "항목 출처 누락",
    ),
    "source_list_incomplete": GradedIssuePolicy(
        "source_list_incomplete", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_GROUNDING, "출처 목록 불완전",
    ),
    "korea_ungrounded_event_context": GradedIssuePolicy(
        "korea_ungrounded_event_context", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_GROUNDING, "TOP5에 없는 사건을 종합문에 사용",
    ),
    "keysuri_year_span_duration_blocked": GradedIssuePolicy(
        "keysuri_year_span_duration_blocked", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_GROUNDING, "근거 없는 기간 계산",
    ),
    # Semantic corruption that cannot be grounded or repaired.
    "keysuri_ungrounded_semantic_truncation": GradedIssuePolicy(
        "keysuri_ungrounded_semantic_truncation", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_SEMANTIC, "근거 복구가 불가능한 의미 단절",
    ),
    "global_visible_text_truncated_deep_dive": GradedIssuePolicy(
        "global_visible_text_truncated_deep_dive", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_SEMANTIC, "딥다이브 의미 단절",
    ),
    "korea_visible_text_truncated_follow_item": GradedIssuePolicy(
        "korea_visible_text_truncated_follow_item", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_SEMANTIC, "후속 확인 문장 의미 단절",
    ),
    "korea_truncated_headline_fragment": GradedIssuePolicy(
        "korea_truncated_headline_fragment", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_SEMANTIC, "제목 조각 의미 단절",
    ),
    "korea_incomplete_sentence_ending": GradedIssuePolicy(
        "korea_incomplete_sentence_ending", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_SEMANTIC, "문장 의미가 완결되지 않음",
    ),
    # Explicit security/privacy findings.  Generic template wording is REVIEW.
    "keysuri_secret_exposure": GradedIssuePolicy(
        "keysuri_secret_exposure", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_SECURITY, "비밀정보 노출",
    ),
    "keysuri_private_recipient_exposure": GradedIssuePolicy(
        "keysuri_private_recipient_exposure", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_SECURITY, "개인 수신자 정보 노출",
    ),
    **{
        code: GradedIssuePolicy(
            code,
            FINDING_SEVERITY_BLOCK,
            SAFETY_FAMILY_SECURITY,
            "샘플·검증용 표식 노출",
        )
        for code in (
            "example_corp",
            "example_com",
            "staged_sample",
            "sample_source_pack",
            "sample_only",
            "do_not_treat_verified",
            "no_live_fetch",
            "no_gemini_call",
            "generated_sample",
            "fixture_source_id_global_t0",
            "fixture_source_id_market_wire",
            "fixture_source_id_semi_wire",
            "fixture_source_pack_path",
            "fixture_source_pack_path_korea",
            "keysuri_smoke_sample_marker",
        )
    },
    # Delivery authority/snapshot safety.
    "customer_send_ambiguity_blocked": GradedIssuePolicy(
        "customer_send_ambiguity_blocked", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_DELIVERY_AUTHORITY, "고객 발송 결과 불명확",
    ),
    "smtp_outcome_ambiguous": GradedIssuePolicy(
        "smtp_outcome_ambiguous", FINDING_SEVERITY_BLOCK,
        SAFETY_FAMILY_DELIVERY_AUTHORITY, "SMTP 결과 불명확",
    ),
}


# Exact allowlist of non-dangerous residuals.  These findings can lower the
# editorial verdict, but can never suppress the owner-review quality circuit.
_GRADED_REVIEW_CODES = frozenset(
    {
        "keysuri_korean_connector_ellipsis_blocked",
        "keysuri_dangling_quoted_title_fragment_blocked",
        "keysuri_korea_token_duplication_blocked",
        "keysuri_visible_text_quality_blocked",
        "keysuri_global_post_render_qa_blocked",
        "keysuri_korea_post_render_qa_blocked",
        "global_visible_subject_integrity_blocked",
        "global_visible_internal_template_leak_blocked",
        "global_selection_below_quality_floor",
        "global_visible_raw_english_prose_blocked",
        # The legacy heuristic detects clipped source prose, but does not prove
        # an ungrounded meaning change.  Proven ungrounded truncation uses the
        # explicit hard-block code above.
        "global_visible_semantic_truncation_blocked",
        "global_visible_repeated_template_skeleton_blocked",
        "global_visible_deep_dive_duplication_blocked",
        "global_visible_repeated_low_information_label",
        "global_visible_category_grounding_mismatch",
        "global_visible_korean_particle_defect",
        "generation_pending",
        "source_led_cards_only",
        "generation_stage_placeholder",
        "live_source_led_notice",
        "gemini_pending_notice",
        "forbidden_generation_pending",
        "forbidden_source_led_placeholder",
        "forbidden_generation_stage_placeholder",
        "forbidden_live_source_led_notice",
        "forbidden_gemini_pending_notice",
        "ai_only_framing",
        "duplicate_implication",
        "duplicate_sentence_in_visible_block",
        "english_rss_leakage",
        "forbidden_phrase",
        "generic_ai_filler",
        "generic_business_implication",
        "generic_closing",
        "global_abstract_filler_no_specifics",
        "global_category_next_watch_mismatch",
        "global_post_render_badge_spacing_broken",
        "global_repeated_common_filler",
        "global_repeated_selection_reason_template",
        "global_signal_distribution_visible_text_broken",
        "global_visible_label_accumulation",
        "global_visible_text_typo_artifact",
        "hype_warning_missing",
        "internal_validation_marker_visible",
        "invalid_judgment_label",
        "korea_checkpoint_lacks_confirm_and_hold",
        "korea_checkpoint_strategy_too_generic",
        "keysuri_cross_field_context_mismatch",
        "korea_closing_internal_label_leak",
        "korea_closing_memo_too_thin",
        "korea_closing_paragraph_too_long",
        "korea_closing_repeats_title_only",
        "korea_closing_structure_incomplete",
        "korea_closing_warm_farewell_missing",
        "korea_deep_block_too_long",
        "korea_deep_dive_forbidden_labels",
        "korea_deep_dive_missing_blocks",
        "korea_deep_dive_repeats_top5_recap",
        "korea_deep_dive_wall_text",
        "korea_defensive_market_phrase_overused",
        "korea_duplicate_angle_missing",
        "korea_emphasis_line_missing_text",
        "korea_evening_memo_missing_actions",
        "korea_everyday_impact_lens_thin",
        "korea_global_impact_missing_bridge",
        "korea_global_label_leak",
        "korea_global_layer_label_leak",
        "korea_hold_field_duplicate_judgment",
        "korea_impact_phrase_duplicate",
        "korea_judgment_label_duplicated",
        "korea_lens_terms_missing",
        "korea_market_lens_thin",
        "korea_memo_action_line_too_long",
        "korea_news_summary_cliche_overused",
        "korea_next_watch_arrow_duplicate",
        "korea_next_watch_list_repr",
        "korea_owner_name_overused",
        "korea_pr_hype_unframed",
        "korea_risk_lacks_hold_criteria",
        "korea_risk_section_question_style",
        "korea_section_label_not_user_facing",
        "korea_signal_distribution_badge_fragment",
        "korea_static_lesson_section_overused",
        "korea_stock_digest_tone",
        "korea_tech_category_bleed",
        "korea_tech_scope_global_leak",
        "korea_tech_scope_non_tech_local_economy",
        "korea_tech_scope_weak_startup_support_overpromoted",
        "korea_uncertainty_list_repr",
        "korea_upper_layer_only_without_everyday_lens",
        "korea_visible_rationale_not_user_facing",
        "korea_visible_text_awkward_memo_phrase",
        "korea_visible_text_customer_slash_label_artifact",
        "korea_visible_text_double_ending_artifact",
        "korea_visible_text_hamnida_yeobu_artifact",
        "korea_visible_text_modal_noun_glue_artifact",
        "korea_visible_text_slash_taxonomy_artifact",
        "marketing_case_study_unframed",
        "missing_next_watch_depth",
        "missing_owner_angle",
        "missing_selection_reason",
        "missing_selection_score",
        "raw_field_label_leak",
        "source_detail_insufficient",
        "sponsored_warning_missing",
        "top5_insufficient_detail",
        "visible_internal_score_leak",
        "visible_python_list_repr",
        "visible_snake_case_token",
        "weak_checkpoint",
        "weak_deep_dive",
        "weak_source_unmarked",
    }
)

_GRADED_REPAIRED_CODES = frozenset(
    {
        "keysuri_korean_connector_ellipsis_repaired",
        "keysuri_korean_repeated_token_repaired",
        "keysuri_year_span_duration_repaired",
    }
)


def get_graded_issue_policy(code: str) -> Optional[GradedIssuePolicy]:
    """Return the canonical graded policy; unknown means INCONCLUSIVE.

    This exact-code registry intentionally replaces suffix-based classification.
    """
    key = str(code or "").strip()
    if not key:
        return None
    if key in _GRADED_BLOCK_POLICIES:
        return _GRADED_BLOCK_POLICIES[key]
    if key in _GRADED_REVIEW_CODES:
        return GradedIssuePolicy(
            key,
            FINDING_SEVERITY_REVIEW,
            SAFETY_FAMILY_EDITORIAL,
            "운영자 검토 필요",
        )
    if key in _GRADED_REPAIRED_CODES:
        return GradedIssuePolicy(
            key,
            FINDING_SEVERITY_INFO,
            SAFETY_FAMILY_EDITORIAL,
            "자동 수정 완료",
        )
    return None
