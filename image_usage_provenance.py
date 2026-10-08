"""Additive image-token provenance; no pricing, provider or usage collection."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Mapping, Optional, Sequence

UNKNOWN = "UNKNOWN"
CALCULATED = "successful_output_count_times_fixed_tokens_per_output"


def image_token_provenance(
    recorded_tokens: Optional[int], *, calculated_tokens: Optional[int] = None,
    tokens_per_output: Optional[int] = None,
    response_measured_tokens: Optional[int] = None,
    response_usage_source: str = UNKNOWN,
) -> Dict[str, Any]:
    """Keep calculation and response measurement independent, including zero."""
    return {
        "recorded_output_tokens": recorded_tokens,
        "recorded_output_tokens_source": (
            CALCULATED if calculated_tokens is not None and recorded_tokens == calculated_tokens
            else UNKNOWN
        ),
        "calculated_output_tokens": calculated_tokens,
        "fixed_tokens_per_output": tokens_per_output,
        "response_measured_output_tokens": response_measured_tokens,
        "response_measured_usage_source": (
            response_usage_source if response_measured_tokens is not None
            and isinstance(response_usage_source, str)
            and response_usage_source.startswith("response_usage_metadata.") else UNKNOWN
        ),
    }


def merge_image_token_provenance(
    components: Sequence[Mapping[str, Any]], recorded_tokens: Optional[int],
) -> Dict[str, Any]:
    """A missing component is unknown, never a zero-valued measurement."""
    rows = [deepcopy(dict(row)) for row in components]
    calculated_complete = bool(rows) and all(
        row.get("calculated_output_tokens") is not None
        and row.get("recorded_output_tokens_source") == CALCULATED for row in rows
    )
    measured_complete = bool(rows) and all(
        row.get("response_measured_output_tokens") is not None
        and isinstance(row.get("response_measured_usage_source"), str)
        and row.get("response_measured_usage_source").startswith("response_usage_metadata.") for row in rows
    )
    calculated = sum(row["calculated_output_tokens"] for row in rows) if calculated_complete else None
    measured = sum(row["response_measured_output_tokens"] for row in rows) if measured_complete else None
    result = image_token_provenance(recorded_tokens, calculated_tokens=calculated,
                                   response_measured_tokens=measured,
                                   response_usage_source="response_usage_metadata.complete_components")
    result["components"] = rows
    return result
