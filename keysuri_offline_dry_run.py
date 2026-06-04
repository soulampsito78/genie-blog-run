"""Kee-Suri offline dry-run orchestrator (staged pipeline — no Gemini, no live services)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from keysuri_generation_prompt import (
    ACTIVE_SCHEDULER_RULES,
    IDENTITY_TITLE,
    build_keysuri_generation_prompt,
    build_keysuri_generation_prompt_contract,
    parse_keysuri_generated_response,
)
from keysuri_generated_briefing import GENERATED_STATUS_REQUIRED
from keysuri_news_contract import KEYSURI_PROGRAM_IDS
from keysuri_prompt_input import build_keysuri_prompt_input
from keysuri_renderer import render_keysuri_owner_review_html
from keysuri_source_gate import GateIssue, GateResult, run_keysuri_source_gate

_REPO_ROOT = Path(__file__).resolve().parent
_FEEDS_DIR = _REPO_ROOT / "ops" / "feeds"

PROMPT_TEXT_PREVIEW_MAX = 600

RUNTIME_SIDE_EFFECTS: Dict[str, bool] = {
    "called_gemini": False,
    "fetched_live_news": False,
    "sent_email": False,
    "published_naver": False,
    "changed_scheduler": False,
}


def load_json_file(path: str) -> dict:
    """Load a JSON object from disk."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return data


def load_text_file(path: str) -> str:
    """Load a text file from disk."""
    return Path(path).read_text(encoding="utf-8")


def _issue(code: str, message: str, path: str) -> Dict[str, str]:
    return {"code": code, "message": message, "path": path}


def _gate_issues_to_dicts(gate_result: GateResult) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for item in gate_result.issues:
        if isinstance(item, GateIssue):
            out.append(
                _issue(
                    item.code,
                    item.message,
                    item.source_id or item.claim_id or "source_gate",
                )
            )
        elif isinstance(item, dict):
            out.append(
                _issue(
                    str(item.get("code", "source_gate_issue")),
                    str(item.get("message", "source gate issue")),
                    str(item.get("source_id") or item.get("claim_id") or "source_gate"),
                )
            )
    return out


def _top5_count(prompt_input: Optional[dict]) -> int:
    if not prompt_input:
        return 0
    top = prompt_input.get("top_5_news")
    if isinstance(top, dict) and isinstance(top.get("items"), list):
        return len(top["items"])
    return 0


def _prompt_text_preview(prompt_text: str) -> str:
    text = (prompt_text or "").strip()
    if len(text) <= PROMPT_TEXT_PREVIEW_MAX:
        return text
    return text[:PROMPT_TEXT_PREVIEW_MAX] + "\n... [truncated for dry-run report]"


def _prompt_contract_summary(contract: dict) -> Dict[str, Any]:
    sched = contract.get("scheduler_rules") if isinstance(contract.get("scheduler_rules"), dict) else {}
    return {
        "program_id": contract.get("program_id"),
        "news_scope": contract.get("news_scope"),
        "section_heading": contract.get("section_heading"),
        "allowed_source_id_count": len(contract.get("allowed_source_ids") or []),
        "active_programs": sched.get("active_programs") or ACTIVE_SCHEDULER_RULES,
        "retired_rules_count": len(sched.get("retired_rules") or []),
    }


def _base_result(
    *,
    dry_run_status: str,
    program_id: str,
    issues: List[Dict[str, str]],
    source_gate_result: Optional[str] = None,
    prompt_input: Optional[dict] = None,
    prompt_contract_summary: Optional[dict] = None,
    prompt_text_preview: str = "",
    parse_status: Optional[str] = None,
    rendered_html: Optional[str] = None,
    generated_status: Optional[str] = None,
) -> Dict[str, Any]:
    news_scope = None
    section_heading = None
    prompt_status = None
    operational_status = None
    top_5_count = 0

    if prompt_input:
        news_scope = prompt_input.get("news_scope")
        section_heading = prompt_input.get("section_heading")
        prompt_status = prompt_input.get("prompt_status")
        operational_status = prompt_input.get("operational_status")
        top_5_count = _top5_count(prompt_input)

    return {
        "dry_run_status": dry_run_status,
        "program_id": program_id,
        "news_scope": news_scope,
        "section_heading": section_heading,
        "source_gate_result": source_gate_result,
        "prompt_status": prompt_status,
        "parse_status": parse_status,
        "top_5_count": top_5_count,
        "generated_status": generated_status,
        "operational_status": operational_status,
        "issues": issues,
        "prompt_contract_summary": prompt_contract_summary or {},
        "prompt_text_preview": prompt_text_preview,
        "rendered_html": rendered_html,
        "identity_label": IDENTITY_TITLE,
        "runtime_side_effects": dict(RUNTIME_SIDE_EFFECTS),
    }


def run_keysuri_offline_dry_run(
    program_id: str,
    source_pack: dict,
    raw_response_text: str,
) -> dict:
    """Run the full staged Kee-Suri pipeline offline using a fixture raw model response."""
    issues: List[Dict[str, str]] = []
    pid = (program_id or "").strip()

    if pid not in KEYSURI_PROGRAM_IDS:
        issues.append(
            _issue("unsupported_program_id", f"Unsupported program_id: {program_id!r}", "program_id")
        )
        return _base_result(
            dry_run_status="block",
            program_id=pid or str(program_id),
            issues=issues,
            source_gate_result=None,
        )

    if not isinstance(source_pack, dict):
        issues.append(_issue("source_pack_invalid", "source_pack must be a dict", "source_pack"))
        return _base_result(dry_run_status="block", program_id=pid, issues=issues)

    gate_result = run_keysuri_source_gate(source_pack)
    source_gate_result = gate_result.verdict
    issues.extend(_gate_issues_to_dicts(gate_result))

    if gate_result.verdict == "block":
        return _base_result(
            dry_run_status="block",
            program_id=pid,
            issues=issues,
            source_gate_result=source_gate_result,
        )

    prompt_input: Optional[dict] = None
    prompt_contract_summary: Optional[dict] = None
    prompt_text_preview = ""

    try:
        prompt_input = build_keysuri_prompt_input(pid, source_pack, gate_result)
    except ValueError as exc:
        issues.append(_issue("prompt_input_build_failed", str(exc), "prompt_input"))
        return _base_result(
            dry_run_status="block",
            program_id=pid,
            issues=issues,
            source_gate_result=source_gate_result,
        )

    prompt_status = str(prompt_input.get("prompt_status") or "").strip()

    if prompt_status == "hold_review_required":
        prompt_contract_summary = {
            "program_id": pid,
            "news_scope": prompt_input.get("news_scope"),
            "section_heading": prompt_input.get("section_heading"),
            "allowed_source_id_count": 0,
            "active_programs": ACTIVE_SCHEDULER_RULES,
            "retired_rules_count": 0,
            "hold_reason": "top_5_selection_hold",
        }
        prompt_text_preview = ""
        for sel_issue in prompt_input.get("top_5_selection_result", {}).get("issues") or []:
            if isinstance(sel_issue, dict):
                issues.append(
                    _issue(
                        str(sel_issue.get("code", "top5_selection_issue")),
                        str(sel_issue.get("message", "TOP 5 selection issue")),
                        "top_5_selection_result",
                    )
                )
        try:
            rendered_html = render_keysuri_owner_review_html(prompt_input, None)
        except ValueError as exc:
            issues.append(_issue("render_failed", str(exc), "rendered_html"))
            rendered_html = None
        return _base_result(
            dry_run_status="hold_review_required",
            program_id=pid,
            issues=issues,
            source_gate_result=source_gate_result,
            prompt_input=prompt_input,
            prompt_contract_summary=prompt_contract_summary,
            prompt_text_preview=prompt_text_preview,
            parse_status="skipped_hold",
            rendered_html=rendered_html,
        )

    contract = build_keysuri_generation_prompt_contract(prompt_input)
    prompt_contract_summary = _prompt_contract_summary(contract)
    prompt_text_preview = _prompt_text_preview(build_keysuri_generation_prompt(prompt_input))

    parse_result = parse_keysuri_generated_response(raw_response_text, pid, prompt_input)
    parse_status = str(parse_result.get("parse_status") or "")
    for parse_issue in parse_result.get("issues") or []:
        if isinstance(parse_issue, dict):
            issues.append(
                _issue(
                    str(parse_issue.get("code", "parse_issue")),
                    str(parse_issue.get("message", "parse issue")),
                    str(parse_issue.get("path", "parse")),
                )
            )

    if parse_status == "parsed_valid":
        generated_briefing = parse_result.get("generated_briefing")
        try:
            rendered_html = render_keysuri_owner_review_html(prompt_input, generated_briefing)
        except ValueError as exc:
            issues.append(_issue("render_failed", str(exc), "rendered_html"))
            return _base_result(
                dry_run_status="parsed_invalid",
                program_id=pid,
                issues=issues,
                source_gate_result=source_gate_result,
                prompt_input=prompt_input,
                prompt_contract_summary=prompt_contract_summary,
                prompt_text_preview=prompt_text_preview,
                parse_status=parse_status,
                rendered_html=None,
            )
        return _base_result(
            dry_run_status="pass",
            program_id=pid,
            issues=issues,
            source_gate_result=source_gate_result,
            prompt_input=prompt_input,
            prompt_contract_summary=prompt_contract_summary,
            prompt_text_preview=prompt_text_preview,
            parse_status=parse_status,
            rendered_html=rendered_html,
            generated_status=GENERATED_STATUS_REQUIRED,
        )

    rendered_html: Optional[str] = None
    if prompt_input is not None:
        try:
            rendered_html = render_keysuri_owner_review_html(prompt_input, None)
        except ValueError as exc:
            issues.append(_issue("render_placeholder_failed", str(exc), "rendered_html"))

    if parse_status == "parse_failed":
        return _base_result(
            dry_run_status="parse_failed",
            program_id=pid,
            issues=issues,
            source_gate_result=source_gate_result,
            prompt_input=prompt_input,
            prompt_contract_summary=prompt_contract_summary,
            prompt_text_preview=prompt_text_preview,
            parse_status=parse_status,
            rendered_html=rendered_html,
        )

    return _base_result(
        dry_run_status="parsed_invalid",
        program_id=pid,
        issues=issues,
        source_gate_result=source_gate_result,
        prompt_input=prompt_input,
        prompt_contract_summary=prompt_contract_summary,
        prompt_text_preview=prompt_text_preview,
        parse_status=parse_status,
        rendered_html=rendered_html,
    )


def run_keysuri_global_offline_dry_run() -> dict:
    """Run offline dry-run for Kee-Suri Global Tech using staged fixtures."""
    pack = load_json_file(str(_FEEDS_DIR / "keysuri_global_sources.sample.json"))
    raw = load_text_file(str(_FEEDS_DIR / "keysuri_global_raw_response.valid.sample.txt"))
    return run_keysuri_offline_dry_run("keysuri_global_tech", pack, raw)


def run_keysuri_korea_offline_dry_run() -> dict:
    """Run offline dry-run for Kee-Suri Korea Tech using staged fixtures."""
    pack = load_json_file(str(_FEEDS_DIR / "keysuri_korea_sources.sample.json"))
    raw = load_text_file(str(_FEEDS_DIR / "keysuri_korea_raw_response.valid.sample.txt"))
    return run_keysuri_offline_dry_run("keysuri_korea_tech", pack, raw)


def dry_run_report_for_json(result: dict) -> dict:
    """Return a JSON-serializable report without duplicating full rendered HTML."""
    report = dict(result)
    html = report.pop("rendered_html", None)
    report["rendered_html_included"] = html is not None
    report["rendered_html_length"] = len(html) if isinstance(html, str) else 0
    return report
