"""Kee-Suri text generation via Vertex Gemini (text only — no image API)."""
from __future__ import annotations

import os
from typing import Optional

import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel

DEFAULT_VERTEX_LOCATION = "global"
DEFAULT_VERTEX_MODEL = "gemini-2.5-flash"
KEYSURI_BODY_GEMINI_MODEL_ENV = "KEYSURI_BODY_GEMINI_MODEL"
KEE_SURI_BODY_MODEL_ENV = "KEE_SURI_BODY_MODEL"
KEYSURI_GEMINI_MODE = "keysuri_generation"


class KeysuriGeminiError(RuntimeError):
    """Raised when Kee-Suri Gemini/Vertex text generation fails."""


def resolve_vertex_project_id(project_id: Optional[str] = None) -> str:
    pid = (
        (project_id or "").strip()
        or os.getenv("PROJECT_ID", "").strip()
        or os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    )
    if not pid:
        raise KeysuriGeminiError("PROJECT_ID or GOOGLE_CLOUD_PROJECT is required for Gemini generation")
    return pid


def resolve_keysuri_body_model(model: Optional[str] = None) -> str:
    """Resolve Kee-Suri text model without changing shared Today VERTEX_MODEL behavior."""
    return (
        (model or "").strip()
        or os.getenv(KEYSURI_BODY_GEMINI_MODEL_ENV, "").strip()
        or os.getenv(KEE_SURI_BODY_MODEL_ENV, "").strip()
        or os.getenv("VERTEX_MODEL", "").strip()
        or DEFAULT_VERTEX_MODEL
    )


def call_keysuri_gemini_text(
    prompt: str,
    *,
    project_id: Optional[str] = None,
    model: Optional[str] = None,
    location: Optional[str] = None,
    max_output_tokens: Optional[int] = None,
) -> str:
    """Call Vertex Gemini for Kee-Suri JSON briefing generation."""
    pid = resolve_vertex_project_id(project_id)
    loc = (location or os.getenv("VERTEX_LOCATION") or DEFAULT_VERTEX_LOCATION).strip()
    model_name = resolve_keysuri_body_model(model)
    max_out = max_output_tokens or int(os.getenv("GENIE_MAX_OUTPUT_TOKENS", "12288"))

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

    text = getattr(response, "text", None)
    if not text or not str(text).strip():
        raise KeysuriGeminiError("Gemini returned empty text response")
    return str(text)
