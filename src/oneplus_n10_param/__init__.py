"""Offline OnePlus Nord N10 Metro param inspection and patch generation."""

from .core import (
    GLOBAL_SWID,
    METRO_SWID,
    PARAM_SIZE,
    PROC_TRIGGER,
    SID_OFFSETS,
    Inspection,
    ParamValidationError,
    PatchResult,
    atomic_write,
    build_trigger,
    derive_aes_key,
    inspect_param,
    read_param_file,
)

__all__ = [
    "GLOBAL_SWID",
    "METRO_SWID",
    "PARAM_SIZE",
    "PROC_TRIGGER",
    "SID_OFFSETS",
    "Inspection",
    "ParamValidationError",
    "PatchResult",
    "atomic_write",
    "build_trigger",
    "derive_aes_key",
    "inspect_param",
    "read_param_file",
]
