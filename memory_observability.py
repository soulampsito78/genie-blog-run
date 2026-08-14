"""Small, payload-free process-memory evidence for long-running requests.

Linux ``/proc/self/status`` is authoritative in Cloud Run.  A stdlib-only
``resource`` fallback keeps local tests useful on platforms without ``/proc``.
Only numeric KiB values and allowlisted stage names are retained.
"""
from __future__ import annotations

import logging
import resource
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, Optional

logger = logging.getLogger(__name__)

MEMORY_STAGE_NAMES = frozenset(
    {
        "request_start",
        "after_source_selection",
        "after_model_generation",
        "after_render",
        "after_image_generation",
        "before_owner_smtp",
        "request_end",
        "route_start",
        "after_projection",
        "after_template",
        "route_end",
    }
)
MAX_MEMORY_STAGES = len(MEMORY_STAGE_NAMES)


def configured_memory_limit_kib() -> int:
    """Best-effort cgroup limit; zero means the runtime did not expose one."""
    for path in (
        Path("/sys/fs/cgroup/memory.max"),
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    ):
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not raw.isdigit():
            continue
        value = int(raw)
        # cgroup v1 may expose an enormous sentinel instead of a real limit.
        if 0 < value < (1 << 60):
            return value // 1024
    return 0


def configured_memory_limit_gib(*, fallback_gib: float = 0.5) -> float:
    """Return the runtime limit in GiB, falling back only when cgroups hide it."""
    limit_kib = configured_memory_limit_kib()
    if limit_kib <= 0:
        return float(fallback_gib)
    return float(limit_kib) / float(1024 * 1024)


def _proc_status_memory_kib(path: Path = Path("/proc/self/status")) -> Optional[Dict[str, int]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    values: Dict[str, int] = {}
    for line in lines:
        key, separator, raw = line.partition(":")
        if not separator or key not in {"VmRSS", "VmHWM"}:
            continue
        parts = raw.strip().split()
        if parts and parts[0].isdigit():
            values[key] = int(parts[0])
    if "VmRSS" not in values:
        return None
    rss = max(0, int(values["VmRSS"]))
    return {
        "rss_kib": rss,
        "hwm_kib": max(rss, int(values.get("VmHWM", rss))),
    }


def read_process_memory_kib() -> Dict[str, object]:
    """Return bounded numeric RSS/HWM evidence without inspecting payloads."""
    proc = _proc_status_memory_kib()
    if proc is not None:
        return {"source": "proc_status", **proc}

    # Linux reports KiB while Darwin reports bytes for ru_maxrss.
    raw = max(0, int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
    import sys

    hwm_kib = raw // 1024 if sys.platform == "darwin" else raw
    return {
        "source": "resource_getrusage",
        "rss_kib": hwm_kib,
        "hwm_kib": hwm_kib,
    }


@dataclass
class MemoryEvidenceRecorder:
    """Per-request recorder; never caches request bodies, HTML, or images."""

    stages: Dict[str, Dict[str, int]] = field(default_factory=dict)
    source: str = "unavailable"

    def has_stage(self, stage: str) -> bool:
        return stage in self.stages

    def record(self, stage: str) -> Dict[str, int]:
        if stage not in MEMORY_STAGE_NAMES:
            raise ValueError(f"unsupported memory stage: {stage}")
        sample = read_process_memory_kib()
        self.source = str(sample.get("source") or "unavailable")
        numeric = {
            "rss_kib": max(0, int(sample.get("rss_kib") or 0)),
            "hwm_kib": max(0, int(sample.get("hwm_kib") or 0)),
        }
        if len(self.stages) < MAX_MEMORY_STAGES or stage in self.stages:
            self.stages[stage] = numeric
        logger.info(
            "process_memory stage=%s rss_kib=%d hwm_kib=%d",
            stage,
            numeric["rss_kib"],
            numeric["hwm_kib"],
        )
        return dict(numeric)

    def record_numeric_sample(
        self, stage: str, *, rss_kib: object, hwm_kib: object, source: str = "upstream"
    ) -> Dict[str, int]:
        """Merge an allowlisted sample returned by a bounded internal request."""
        if stage not in MEMORY_STAGE_NAMES:
            raise ValueError(f"unsupported memory stage: {stage}")
        numeric = {
            "rss_kib": max(0, int(rss_kib or 0)),
            "hwm_kib": max(0, int(hwm_kib or 0)),
        }
        if len(self.stages) < MAX_MEMORY_STAGES or stage in self.stages:
            self.stages[stage] = numeric
        self.source = str(source or "upstream")[:80]
        logger.info(
            "process_memory stage=%s rss_kib=%d hwm_kib=%d source=%s",
            stage,
            numeric["rss_kib"],
            numeric["hwm_kib"],
            self.source,
        )
        return dict(numeric)

    def evidence(self) -> Dict[str, object]:
        rows = {key: dict(value) for key, value in self.stages.items()}
        peak = max((row["hwm_kib"] for row in rows.values()), default=0)
        limit = configured_memory_limit_kib()
        return {
            "source": self.source,
            "unit": "KiB",
            "stage_count": len(rows),
            "peak_hwm_kib": peak,
            "configured_limit_kib": limit,
            "headroom_kib": max(0, limit - peak) if limit else 0,
            "stages": rows,
        }


_CURRENT_RECORDER: ContextVar[Optional[MemoryEvidenceRecorder]] = ContextVar(
    "genie_memory_evidence_recorder", default=None
)


@contextmanager
def memory_evidence_scope() -> Iterator[MemoryEvidenceRecorder]:
    recorder = MemoryEvidenceRecorder()
    token = _CURRENT_RECORDER.set(recorder)
    try:
        yield recorder
    finally:
        _CURRENT_RECORDER.reset(token)


def current_memory_recorder() -> Optional[MemoryEvidenceRecorder]:
    return _CURRENT_RECORDER.get()


def record_memory_stage(stage: str) -> Dict[str, int]:
    recorder = current_memory_recorder()
    if recorder is None:
        sample = read_process_memory_kib()
        numeric = {
            "rss_kib": max(0, int(sample.get("rss_kib") or 0)),
            "hwm_kib": max(0, int(sample.get("hwm_kib") or 0)),
        }
        logger.info(
            "process_memory stage=%s rss_kib=%d hwm_kib=%d",
            stage,
            numeric["rss_kib"],
            numeric["hwm_kib"],
        )
        return numeric
    return recorder.record(stage)


def record_memory_stage_if_absent(stage: str) -> Dict[str, int]:
    """Keep the first, phase-accurate sample when a wrapper adds a fallback."""
    recorder = current_memory_recorder()
    if recorder is not None and recorder.has_stage(stage):
        return dict(recorder.stages[stage])
    return record_memory_stage(stage)


def record_memory_stage_from_evidence(
    stage: str, evidence: object
) -> Dict[str, int]:
    """Use an exact upstream phase sample, falling back to a local sample."""
    recorder = current_memory_recorder()
    if recorder is not None and isinstance(evidence, dict):
        stages = evidence.get("stages")
        sample = stages.get(stage) if isinstance(stages, dict) else None
        if isinstance(sample, dict):
            try:
                return recorder.record_numeric_sample(
                    stage,
                    rss_kib=sample.get("rss_kib"),
                    hwm_kib=sample.get("hwm_kib"),
                    source=f"upstream:{str(evidence.get('source') or 'unknown')[:60]}",
                )
            except (TypeError, ValueError, OverflowError):
                pass
    return record_memory_stage(stage)
