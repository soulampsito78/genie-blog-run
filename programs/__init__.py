"""GENIE program registry package."""
from programs.registry import (
    LEGACY_MODE_ALIASES,
    PROGRAMS,
    ProgramSpec,
    UnknownProgramError,
    get_program,
    list_programs,
    resolve_program_id,
)

__all__ = [
    "LEGACY_MODE_ALIASES",
    "PROGRAMS",
    "ProgramSpec",
    "UnknownProgramError",
    "get_program",
    "list_programs",
    "resolve_program_id",
]
