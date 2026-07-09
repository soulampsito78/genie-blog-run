"""Kee-Suri text generation via Vertex Gemini (text only — no image API)."""
from __future__ import annotations

import os
from typing import Any, Dict, MutableMapping, Optional, Tuple

import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel

DEFAULT_VERTEX_LOCATION = "global"
DEFAULT_VERTEX_MODEL = "gemini-2.5-flash"
KEYSURI_BODY_GEMINI_MODEL_ENV = "KEYSURI_BODY_GEMINI_MODEL"
KEE_SURI_BODY_MODEL_ENV = "KEE_SURI_BODY_MODEL"
KEYSURI_GEMINI_MODE = "keysuri_generation"

# Body generation output budgets. Global Tech (gemini-3-flash-preview) can burn
# most of a shared budget on thoughts and return MAX_TOKENS with empty parts —
# give Global a higher default without raising Korea's budget.
KEYSURI_DEFAULT_BODY_MAX_OUTPUT_TOKENS = 12288
KEYSURI_GLOBAL_BODY_MAX_OUTPUT_TOKENS = 16384
KEYSURI_GLOBAL_BODY_MAX_OUTPUT_TOKENS_RETRY = 16384

# Program-specific body-model overrides. These take priority over the shared
# KEYSURI_BODY_GEMINI_MODEL so Global Tech (working on gemini-3-flash-preview)
# and Korea Tech (needing a different model after a gemini-3-flash-preview
# MAX_TOKENS/no-parts production incident) can each run their own model
# without touching Today_Geenee's VERTEX_MODEL or the image model path.
KEYSURI_GLOBAL_TECH_BODY_GEMINI_MODEL_ENV = "KEYSURI_GLOBAL_TECH_BODY_GEMINI_MODEL"
KEYSURI_BODY_GEMINI_MODEL_GLOBAL_ENV = "KEYSURI_BODY_GEMINI_MODEL_GLOBAL"
KEYSURI_KOREA_TECH_BODY_GEMINI_MODEL_ENV = "KEYSURI_KOREA_TECH_BODY_GEMINI_MODEL"
KEYSURI_BODY_GEMINI_MODEL_KOREA_ENV = "KEYSURI_BODY_GEMINI_MODEL_KOREA"

_GLOBAL_PROGRAM_ENV_NAMES: Tuple[str, ...] = (
    KEYSURI_GLOBAL_TECH_BODY_GEMINI_MODEL_ENV,
    KEYSURI_BODY_GEMINI_MODEL_GLOBAL_ENV,
)
_KOREA_PROGRAM_ENV_NAMES: Tuple[str, ...] = (
    KEYSURI_KOREA_TECH_BODY_GEMINI_MODEL_ENV,
    KEYSURI_BODY_GEMINI_MODEL_KOREA_ENV,
)


class KeysuriGeminiError(RuntimeError):
    """Raised when Kee-Suri Gemini/Vertex text generation fails."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics: Dict[str, Any] = dict(diagnostics or {})


def is_max_tokens_no_text_error(exc: BaseException) -> bool:
    """True when Gemini hit MAX_TOKENS before emitting any usable text."""
    return "keysuri_gemini_max_tokens_no_text" in str(exc)


def resolve_vertex_project_id(project_id: Optional[str] = None) -> str:
    pid = (
        (project_id or "").strip()
        or os.getenv("PROJECT_ID", "").strip()
        or os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    )
    if not pid:
        raise KeysuriGeminiError("PROJECT_ID or GOOGLE_CLOUD_PROJECT is required for Gemini generation")
    return pid


def _program_specific_env_names(program_id: Optional[str]) -> Tuple[str, ...]:
    pid = (program_id or "").strip()
    if pid == "keysuri_global_tech" or pid.startswith("keysuri_global"):
        return _GLOBAL_PROGRAM_ENV_NAMES
    if pid == "keysuri_korea_tech" or pid.startswith("keysuri_korea"):
        return _KOREA_PROGRAM_ENV_NAMES
    return ()


def resolve_keysuri_body_model(
    model: Optional[str] = None,
    *,
    program_id: Optional[str] = None,
) -> str:
    """Resolve Kee-Suri text model without changing shared Today VERTEX_MODEL behavior.

    Priority: explicit model arg > program-specific env (Global or Korea) >
    shared KEYSURI_BODY_GEMINI_MODEL > KEE_SURI_BODY_MODEL alias > VERTEX_MODEL >
    DEFAULT_VERTEX_MODEL. program_id is optional — omitting it preserves the
    original (pre-routing) fallback chain exactly.
    """
    explicit = (model or "").strip()
    if explicit:
        return explicit

    for env_name in _program_specific_env_names(program_id):
        value = os.getenv(env_name, "").strip()
        if value:
            return value

    return (
        os.getenv(KEYSURI_BODY_GEMINI_MODEL_ENV, "").strip()
        or os.getenv(KEE_SURI_BODY_MODEL_ENV, "").strip()
        or os.getenv("VERTEX_MODEL", "").strip()
        or DEFAULT_VERTEX_MODEL
    )


def resolve_keysuri_body_max_output_tokens(
    program_id: Optional[str] = None,
    *,
    max_output_tokens: Optional[int] = None,
) -> int:
    """Resolve body generation max_output_tokens for a Kee-Suri program.

    Priority: explicit arg > GENIE_MAX_OUTPUT_TOKENS env > Global program default
    (KEYSURI_GLOBAL_BODY_MAX_OUTPUT_TOKENS) > shared default
    (KEYSURI_DEFAULT_BODY_MAX_OUTPUT_TOKENS). Korea keeps the shared default.
    """
    if max_output_tokens is not None:
        return int(max_output_tokens)
    env_raw = os.getenv("GENIE_MAX_OUTPUT_TOKENS", "").strip()
    if env_raw:
        return int(env_raw)
    pid = (program_id or "").strip()
    if pid == "keysuri_global_tech" or pid.startswith("keysuri_global"):
        return KEYSURI_GLOBAL_BODY_MAX_OUTPUT_TOKENS
    return KEYSURI_DEFAULT_BODY_MAX_OUTPUT_TOKENS


def _finish_reason_name(candidate: object) -> str:
    reason = getattr(candidate, "finish_reason", None)
    if reason is None:
        return ""
    name = getattr(reason, "name", None)
    return str(name if name is not None else reason)


def _extract_gemini_text_safe(response: object) -> str:
    """Extract response text as a KeysuriGeminiError instead of a raw SDK ValueError.

    Production incident: Gemini 3 Flash Preview returned finish_reason=MAX_TOKENS
    with an empty candidate (no content parts) — the Vertex SDK's ``response.text``
    property itself raises ``ValueError`` in that case, which a bare
    ``getattr(response, "text", None)`` does not suppress (getattr only catches
    AttributeError). That raw ValueError propagated all the way to the FastAPI
    endpoint as an uncaught exception (HTTP 500) instead of a safe-fail result.
    This checks candidates/parts up front and always raises KeysuriGeminiError
    with a clear issue code baked into the message.
    """
    candidates = getattr(response, "candidates", None) or []
    candidate_count = len(candidates) if hasattr(candidates, "__len__") else 0
    if not candidates:
        raise KeysuriGeminiError(
            "keysuri_gemini_response_no_parts: Gemini response has no candidates",
            diagnostics={
                "finish_reason": "",
                "text_length": 0,
                "candidate_count": 0,
            },
        )

    candidate = candidates[0]
    finish_reason = _finish_reason_name(candidate)
    content = getattr(candidate, "content", None)
    parts = getattr(content, "parts", None) if content is not None else None
    base_diag: Dict[str, Any] = {
        "finish_reason": finish_reason or "",
        "text_length": 0,
        "candidate_count": candidate_count,
    }

    if not parts:
        if "MAX_TOKENS" in finish_reason:
            raise KeysuriGeminiError(
                "keysuri_gemini_max_tokens_no_text: Gemini hit max_output_tokens "
                f"before producing any text (finish_reason={finish_reason})",
                diagnostics=base_diag,
            )
        raise KeysuriGeminiError(
            "keysuri_gemini_response_no_parts: Gemini response candidate has no "
            f"content parts (finish_reason={finish_reason or 'unknown'})",
            diagnostics=base_diag,
        )

    try:
        text = response.text
    except ValueError as exc:
        if "MAX_TOKENS" in finish_reason:
            raise KeysuriGeminiError(
                f"keysuri_gemini_max_tokens_no_text: {exc}",
                diagnostics=base_diag,
            ) from exc
        raise KeysuriGeminiError(
            f"keysuri_gemini_response_no_parts: {exc}",
            diagnostics=base_diag,
        ) from exc

    if not text or not str(text).strip():
        empty_diag = dict(base_diag)
        empty_diag["text_length"] = 0
        if "MAX_TOKENS" in finish_reason:
            raise KeysuriGeminiError(
                "keysuri_gemini_max_tokens_no_text: Gemini hit max_output_tokens "
                f"before producing any text (finish_reason={finish_reason})",
                diagnostics=empty_diag,
            )
        raise KeysuriGeminiError(
            "Gemini returned empty text response",
            diagnostics=empty_diag,
        )
    return str(text)


def extract_gemini_usage_metadata(response: object) -> Dict[str, Optional[int]]:
    """Best-effort token-usage extraction from a Vertex generate_content response.

    Never raises — usage_metadata shape/availability can vary by model/SDK
    version, and a missing usage breakdown must not affect generation itself.
    """
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return {
            "prompt_token_count": None,
            "candidates_token_count": None,
            "thoughts_token_count": None,
            "total_token_count": None,
        }
    out: Dict[str, Optional[int]] = {}
    for field in (
        "prompt_token_count",
        "candidates_token_count",
        "thoughts_token_count",
        "total_token_count",
    ):
        try:
            value = getattr(usage, field, None)
            out[field] = int(value) if value is not None else None
        except Exception:
            out[field] = None
    return out


def call_keysuri_gemini_text(
    prompt: str,
    *,
    project_id: Optional[str] = None,
    model: Optional[str] = None,
    location: Optional[str] = None,
    max_output_tokens: Optional[int] = None,
    program_id: Optional[str] = None,
    usage_sink: Optional[MutableMapping[str, Any]] = None,
) -> str:
    """Call Vertex Gemini for Kee-Suri JSON briefing generation.

    program_id (optional) selects a program-specific body model override —
    see resolve_keysuri_body_model. Omitting it preserves prior behavior.

    usage_sink (optional): if provided, populated in place with the resolved
    model name and best-effort token usage counts for cost-estimate logging
    (see keysuri_cost_estimate.py). Never raises — a usage_sink populate
    failure must not affect text generation.
    """
    pid = resolve_vertex_project_id(project_id)
    loc = (location or os.getenv("VERTEX_LOCATION") or DEFAULT_VERTEX_LOCATION).strip()
    model_name = resolve_keysuri_body_model(model, program_id=program_id)
    max_out = resolve_keysuri_body_max_output_tokens(
        program_id, max_output_tokens=max_output_tokens
    )

    try:
        vertexai.init(project=pid, location=loc)
        generative_model = GenerativeModel(model_name)
        response = generative_model.generate_content(
            prompt,
            generation_config=GenerationConfig(
                temperature=0.3,
                top_p=0.9,
                max_output_tokens=max_out,
                response_mime_type="application/json",
            ),
        )
    except KeysuriGeminiError:
        raise
    except Exception as exc:
        raise KeysuriGeminiError(f"Vertex Gemini call failed: {exc}") from exc

    if usage_sink is not None:
        try:
            usage_sink["model"] = model_name
            usage_sink["max_output_tokens"] = max_out
            usage_sink["program_id"] = (program_id or "").strip() or None
            usage_sink.update(extract_gemini_usage_metadata(response))
        except Exception:
            pass

    try:
        return _extract_gemini_text_safe(response)
    except KeysuriGeminiError as exc:
        # Attach generation budget to diagnostics without exposing raw response.
        try:
            diag = dict(getattr(exc, "diagnostics", None) or {})
            diag.setdefault("max_output_tokens", max_out)
            diag.setdefault("program_id", (program_id or "").strip() or None)
            exc.diagnostics = diag
        except Exception:
            pass
        raise
    except Exception as exc:
        raise KeysuriGeminiError(f"Vertex Gemini text extraction failed: {exc}") from exc
