"""Today_Geenee service-level full run with generated images."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from admin_store import artifact_email_path, artifact_json_path, generate_run_id, save_run_artifact
from admin_urls import build_owner_review_admin_url
from orchestrator import OrchestrationResult, run_genie_job
from renderers import today_genie_email_inline_cid_pair
from service_full_run_contract import (
    ERROR_IMAGE_GENERATION_FAILED,
    SERVICE_FULL_RUN_TRIGGER,
    TodayGenieServiceImageBundle,
    build_service_artifact_fields,
)
from service_image_api import DEFAULT_VERTEX_IMAGE_MODEL, invoke_vertex_image_generation
from admin_cost_ledger import save_cost_record_best_effort
from genie_cost_estimate import estimate_genie_generation_cost

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent
_REF_IMAGE = _REPO / "static" / "email" / "GENIE_REF_today_genie_master_v1.jpg"
_OUTPUT_IMAGES = _REPO / "output" / "images" / "today_genie"

# Today_Geenee brand footer/watermark (restores f82dbd1 behavior; see
# today_genie_run_images.generate_today_genie_run_images orphaned at b843bc4).
WATERMARK_LABEL = "MirAI:ON"
WATERMARK_METHOD = "apply_today_genie_brand_footer"
WATERMARK_ISSUE_CODE = "TODAY_GENIE_IMAGE_WATERMARK_FAILED"


def _watermark_marker_path(image_path: Path) -> Path:
    return image_path.with_name(image_path.name + ".wm")


def apply_today_genie_footer_to_bundle(
    bundle: TodayGenieServiceImageBundle,
    *,
    label: str = WATERMARK_LABEL,
) -> None:
    """Apply the MirAI:ON brand footer to the generated top/bottom images in place.

    MUST be called only after BOTH images are generated. The bottom image uses the
    top image as its reference (see ``generate_today_genie_service_images``), so the
    footer must not be stamped onto the top image before bottom generation, or the
    model could replicate the footer text. Idempotent via a per-image ``.wm`` marker
    so re-processing the same path does not double-stamp. Records state on the bundle;
    never raises.
    """
    from genie_image_overlay import apply_today_genie_brand_footer

    applied: List[str] = []
    errors: List[str] = []
    for outcome in (bundle.top, bundle.bottom):
        rel = str(outcome.generated_image_path or "").strip()
        if not rel:
            continue
        path = Path(rel)
        if not path.is_absolute():
            path = _REPO / path
        if not path.is_file():
            errors.append(f"missing:{rel}")
            continue
        marker = _watermark_marker_path(path)
        if marker.exists():
            applied.append(rel)
            continue
        try:
            apply_today_genie_brand_footer(path, label=label)
        except Exception as exc:  # noqa: BLE001 - footer is best-effort post-process
            logger.warning("today_genie brand footer failed for %s: %s", rel, exc)
            errors.append(f"{rel}:{type(exc).__name__}")
            continue
        try:
            marker.write_text(label, encoding="utf-8")
        except OSError:
            pass
        applied.append(rel)

    bundle.watermark_label = label
    bundle.watermark_method = WATERMARK_METHOD
    bundle.watermark_paths = applied
    bundle.watermark_applied = bool(applied) and not errors
    bundle.watermark_error = "; ".join(errors) if errors else None
    applied_set = set(applied)
    for outcome in (bundle.top, bundle.bottom):
        outcome.image_locally_derived_asset_count = (
            1 if str(outcome.generated_image_path or "") in applied_set else 0
        )


def today_genie_watermark_meta(bundle: TodayGenieServiceImageBundle) -> Dict[str, Any]:
    """Artifact metadata proving brand footer/watermark application.

    Tolerant of bundle-like objects that predate the watermark fields (defaults).
    """
    fields: Dict[str, Any] = {
        "today_genie_image_watermark_applied": bool(getattr(bundle, "watermark_applied", False)),
        "today_genie_image_watermark_label": getattr(bundle, "watermark_label", ""),
        "today_genie_image_watermark_method": getattr(bundle, "watermark_method", ""),
        "today_genie_image_watermark_paths": list(getattr(bundle, "watermark_paths", []) or []),
    }
    error = getattr(bundle, "watermark_error", None)
    if error:
        fields["today_genie_image_watermark_error"] = error
    return fields


def _mood_prefix_for_image_prompts(data: Dict[str, Any]) -> str:
    mood = str(data.get("image_briefing_mood_state") or "").strip()
    basis = str(data.get("image_mood_basis") or "").strip()
    if not mood and not basis:
        return ""
    parts: List[str] = []
    if mood:
        parts.append(f"BRIEFING_MOOD_STATE={mood}")
    if basis:
        parts.append(f"MOOD_BASIS={basis}")
    return "[" + " | ".join(parts) + "]\n\n"


def generate_today_genie_service_images(
    data: Dict[str, Any],
    runtime_input: Dict[str, Any],
    *,
    run_id: str,
    generate_fn: Optional[Callable[..., Path]] = None,
) -> TodayGenieServiceImageBundle:
    from image_exec_suffixes import (
        today_genie_suffix_outdoor_daily,
        today_genie_suffix_studio_hero,
    )

    mood = _mood_prefix_for_image_prompts(data)
    top_base = str(data.get("image_prompt_studio") or "").strip()
    bot_base = str(data.get("image_prompt_outdoor") or "").strip()
    if not top_base or not bot_base:
        bundle = TodayGenieServiceImageBundle()
        bundle.top.error_code = ERROR_IMAGE_GENERATION_FAILED
        bundle.top.error_message = "missing image prompts"
        bundle.bottom.error_code = ERROR_IMAGE_GENERATION_FAILED
        return bundle

    out_dir = _OUTPUT_IMAGES / run_id
    top_out = out_dir / f"{run_id}_top.jpg"
    bot_out = out_dir / f"{run_id}_bottom.jpg"
    top_prompt = f"{mood}{top_base}\n\n{today_genie_suffix_studio_hero(run_id)}".strip()
    bot_prompt = f"{mood}{bot_base}\n\n{today_genie_suffix_outdoor_daily(runtime_input, variation_seed=run_id)}".strip()

    top = invoke_vertex_image_generation(
        prompt=top_prompt,
        output_path=top_out,
        reference_image_path=_REF_IMAGE if _REF_IMAGE.is_file() else None,
        generate_fn=generate_fn,
    )
    bottom = invoke_vertex_image_generation(
        prompt=bot_prompt,
        output_path=bot_out,
        reference_image_path=top_out if top.ok and top_out.is_file() else _REF_IMAGE if _REF_IMAGE.is_file() else None,
        generate_fn=generate_fn,
    )
    primary = top.generated_image_path if top.ok else None
    bundle = TodayGenieServiceImageBundle(top=top, bottom=bottom, primary_generated_image_path=primary)
    # Both images are now generated; apply the brand footer in place so the CID
    # inline parts attach the watermarked rasters. Must run after bottom generation
    # (which uses the top image as its reference).
    if bundle.ok:
        apply_today_genie_footer_to_bundle(bundle)
    return bundle


def inline_parts_from_today_genie_bundle(bundle: TodayGenieServiceImageBundle) -> List[Tuple[str, str, str]]:
    repo = _REPO
    cid_top, cid_bottom = today_genie_email_inline_cid_pair()
    top_path = repo / str(bundle.top.generated_image_path or "")
    bot_path = repo / str(bundle.bottom.generated_image_path or "")
    return [
        (str(top_path), cid_top, f"{top_path.name}"),
        (str(bot_path), cid_bottom, f"{bot_path.name}"),
    ]


def _inline_parts_from_bundle(bundle: TodayGenieServiceImageBundle) -> List[Tuple[str, str, str]]:
    return inline_parts_from_today_genie_bundle(bundle)


def _extract_issue_codes(result: OrchestrationResult) -> List[str]:
    payload = result.response_data if isinstance(result.response_data, dict) else {}
    codes = payload.get("issue_codes")
    if isinstance(codes, list):
        return [str(c) for c in codes]
    issues = payload.get("issues")
    if isinstance(issues, list):
        return [str(i.get("code")) for i in issues if isinstance(i, dict) and i.get("code")]
    return []


def _dedup_artifact_fields_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    runtime_input = payload.get("runtime_input") if isinstance(payload.get("runtime_input"), dict) else {}
    dedup = runtime_input.get("sent_news_dedup") if isinstance(runtime_input, dict) else None
    if not isinstance(dedup, dict) or not dedup.get("used_dedup_gate"):
        return {}
    selected = dedup.get("selected_items")
    rejected = dedup.get("rejected_items")
    summary = dedup.get("dedup_summary")
    return {
        "used_dedup_gate": True,
        "selected_items": selected if isinstance(selected, list) else [],
        "rejected_items": rejected if isinstance(rejected, list) else [],
        "dedup_summary": summary if isinstance(summary, dict) else {},
        "required_count": int(dedup.get("required_count") or 0),
        "selected_count": int(dedup.get("selected_count") or 0),
    }


def run_today_genie_service_full_run(
    *,
    trigger_source: str = SERVICE_FULL_RUN_TRIGGER,
    send_owner_email: bool = True,
    dry_run: bool = False,
    generate_fn: Optional[Callable[..., Path]] = None,
    send_fn: Optional[Callable[..., bool]] = None,
) -> Dict[str, Any]:
    """Service-level Today_Geenee full run: Gemini text, image API, admin artifact, SMTP."""
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "mode": "today_genie",
            "service_full_run": True,
            "would_run": True,
            "trigger_source": trigger_source,
        }

    result = run_genie_job("today_genie")
    payload = result.response_data if isinstance(result.response_data, dict) else {}
    validation_result = str(payload.get("validation_result") or "")
    workflow_status = str(payload.get("workflow_status") or "")
    issue_codes = _extract_issue_codes(result)
    run_id = generate_run_id("today_genie")

    if result.response_status != 200 or validation_result != "pass":
        meta = build_service_artifact_fields(
            run_id=run_id,
            mode="today_genie",
            trigger_source=trigger_source,
            validation_result=validation_result or "block",
            issue_codes=issue_codes,
            called_gemini=True,
            response_status=result.response_status,
            workflow_status=workflow_status,
            email_sent=False,
        )
        save_run_artifact(meta, email_html="")
        return {
            "ok": False,
            "run_id": run_id,
            "mode": "today_genie",
            "service_full_run": True,
            "validation_result": validation_result,
            "artifact_status": meta.get("artifact_status"),
            "email_sent": False,
            "error": "validation_blocked",
            "issue_codes": issue_codes,
        }

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    runtime_input = payload.get("runtime_input") if isinstance(payload.get("runtime_input"), dict) else {}
    image_bundle = generate_today_genie_service_images(
        data,
        runtime_input,
        run_id=run_id,
        generate_fn=generate_fn,
    )

    if not image_bundle.ok:
        err = image_bundle.top.error_code or image_bundle.bottom.error_code or ERROR_IMAGE_GENERATION_FAILED
        meta = build_service_artifact_fields(
            run_id=run_id,
            mode="today_genie",
            trigger_source=trigger_source,
            validation_result=validation_result,
            issue_codes=issue_codes + [err],
            called_gemini=True,
            image_bundle=image_bundle,
            response_status=result.response_status,
            workflow_status=workflow_status,
            email_sent=False,
            error_code=err,
        )
        save_run_artifact(meta, email_html="")
        return {
            "ok": False,
            "run_id": run_id,
            "mode": "today_genie",
            "service_full_run": True,
            "validation_result": validation_result,
            "called_gemini": True,
            "called_image_api": image_bundle.called_image_api,
            "image_generation_status": meta.get("image_generation_status"),
            "image_source": meta.get("image_source"),
            "generated_image_path": meta.get("generated_image_path"),
            "artifact_status": meta.get("artifact_status"),
            "email_sent": False,
            "error": err,
        }

    email_sent = False
    smtp_attempted = False
    email_html = ""
    if send_owner_email and result.decision.send_email and not result.decision.suppress_external:
        from main import build_today_genie_email_html_for_cid_mime_send
        from email_sender import send_genie_email

        admin_url = build_owner_review_admin_url(run_id)
        if not admin_url:
            meta = build_service_artifact_fields(
                run_id=run_id,
                mode="today_genie",
                trigger_source=trigger_source,
                validation_result=validation_result,
                issue_codes=issue_codes + ["missing_admin_url"],
                called_gemini=True,
                image_bundle=image_bundle,
                response_status=result.response_status,
                workflow_status=workflow_status,
                email_sent=False,
                error_code="missing_admin_url",
            )
            save_run_artifact(meta, email_html="")
            return {
                "ok": False,
                "run_id": run_id,
                "mode": "today_genie",
                "service_full_run": True,
                "validation_result": validation_result,
                "called_image_api": True,
                "image_generation_status": "generated",
                "image_source": "generated",
                "generated_image_path": image_bundle.primary_generated_image_path,
                "email_sent": False,
                "error": "missing_admin_url",
            }

        email_html = build_today_genie_email_html_for_cid_mime_send(
            data,
            validation_result=validation_result,
            run_id=run_id,
        )
        if "운영자 검수 화면 열기" not in email_html:
            meta = build_service_artifact_fields(
                run_id=run_id,
                mode="today_genie",
                trigger_source=trigger_source,
                validation_result=validation_result,
                issue_codes=issue_codes,
                called_gemini=True,
                image_bundle=image_bundle,
                response_status=result.response_status,
                workflow_status=workflow_status,
                email_sent=False,
                error_code="admin_review_link_missing_in_html",
            )
            save_run_artifact(meta, email_html=email_html)
            return {
                "ok": False,
                "run_id": run_id,
                "service_full_run": True,
                "email_sent": False,
                "error": "admin_review_link_missing_in_html",
            }

        drafts = data.get("channel_drafts") or {}
        subject = f"[운영자 검토] {drafts.get('email_subject') or '(Genie briefing)'}"
        inline_parts = _inline_parts_from_bundle(image_bundle)
        smtp_attempted = True
        sender = send_fn or send_genie_email
        os.environ.setdefault("GENIE_EMAIL_RICH_MODE", "1")
        email_sent = bool(
            sender(
                email_html,
                subject,
                inline_jpeg_parts=inline_parts,
                attachment_jpeg_parts=[],
            )
        )
    elif send_owner_email:
        logger.info("today_genie service_full_run: email skipped (policy send_email=False)")

    meta = build_service_artifact_fields(
        run_id=run_id,
        mode="today_genie",
        trigger_source=trigger_source,
        validation_result=validation_result,
        issue_codes=issue_codes,
        called_gemini=True,
        image_bundle=image_bundle,
        html_path=str(artifact_json_path(run_id)),
        owner_review_html_path=str(artifact_email_path(run_id)),
        smtp_attempted=smtp_attempted,
        email_sent=email_sent,
        response_status=result.response_status,
        workflow_status=workflow_status,
    )
    meta.update(_dedup_artifact_fields_from_payload(payload))
    if image_bundle.ok:
        meta["generated_image_paths"] = {
            "top": image_bundle.top.generated_image_path,
            "bottom": image_bundle.bottom.generated_image_path,
        }
        meta.update(today_genie_watermark_meta(image_bundle))
        if not getattr(image_bundle, "watermark_applied", False):
            meta["issue_codes"] = list(meta.get("issue_codes") or []) + [WATERMARK_ISSUE_CODE]
    meta["artifact_status"] = "emailed" if email_sent else "stored"

    # Best-effort cost estimate — text usage came from the /generate response
    # (main.py); fold in the image count generated in THIS step. Never affects
    # ok/validation_result/email_sent even if this fails.
    try:
        text_cost_estimate = payload.get("cost_estimate") if isinstance(payload.get("cost_estimate"), dict) else {}
        image_usage = {
            key: sum(int(outcome.cost_usage().get(key) or 0) for outcome in (image_bundle.top, image_bundle.bottom))
            for key in (
                "image_request_count",
                "image_successful_output_count",
                "image_failed_request_count",
                "image_retry_count",
                "image_discarded_output_count",
                "image_locally_derived_asset_count",
                "image_cache_reuse_count",
                "image_static_fallback_count",
                "image_output_tokens",
            )
        }
        image_usage.update(
            {
                "image_api_provider": image_bundle.top.image_api_provider,
                "image_model_raw": image_bundle.top.image_model_raw,
                "image_model_normalized": image_bundle.top.image_model_normalized,
                "image_pricing_mode": image_bundle.top.image_pricing_mode,
                "generated_image_count_semantics": "paid_successful_api_outputs",
                "image_evidence_confidence": image_bundle.top.cost_usage().get(
                    "image_evidence_confidence"
                ),
                "image_evidence_source": image_bundle.top.cost_usage().get(
                    "image_evidence_source"
                ),
            }
        )
        cost_estimate = estimate_genie_generation_cost(
            text_cost_estimate.get("usage"),
            service_family="today_genie",
            text_model=(text_cost_estimate.get("model") or {}).get("text_model")
            if isinstance(text_cost_estimate.get("model"), dict)
            else None,
            image_model=DEFAULT_VERTEX_IMAGE_MODEL,
            mode="today_genie",
            run_id=run_id,
            image_usage=image_usage,
        )
    except Exception:
        cost_estimate = None
    if cost_estimate is not None:
        meta["cost_estimate"] = cost_estimate
        meta.update(save_cost_record_best_effort(meta))
        try:
            logger.info(
                "today_genie_cost_estimate run_id=%s usage=%s total_cost_usd=%s pricing_source=%s",
                run_id,
                cost_estimate.get("usage"),
                cost_estimate.get("total_cost_usd"),
                cost_estimate.get("pricing_source"),
            )
        except Exception:
            pass

    save_run_artifact(meta, email_html=email_html)

    ok = image_bundle.ok and (not send_owner_email or email_sent)
    return {
        "ok": ok,
        "run_id": run_id,
        "mode": "today_genie",
        "service_full_run": True,
        "trigger_source": trigger_source,
        "validation_result": validation_result,
        "workflow_status": workflow_status,
        "called_gemini": True,
        "called_image_api": image_bundle.called_image_api,
        "cost_estimate": cost_estimate,
        "image_generation_status": meta.get("image_generation_status"),
        "image_source": meta.get("image_source"),
        "generated_image_path": meta.get("generated_image_path"),
        "generated_image_paths": {
            "top": image_bundle.top.generated_image_path,
            "bottom": image_bundle.bottom.generated_image_path,
        },
        "artifact_status": meta.get("artifact_status"),
        "owner_review_html_path": meta.get("owner_review_html_path"),
        "smtp_attempted": smtp_attempted,
        "email_sent": email_sent,
        "cost_record_path": meta.get("cost_record_path"),
        "cost_ledger_path": meta.get("cost_ledger_path"),
        "cost_record_saved": meta.get("cost_record_saved"),
        "cost_ledger_saved": meta.get("cost_ledger_saved"),
    }
