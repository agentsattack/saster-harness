"""carl-ops trajectory record schema (halctf.trajectory.v2).

Frozen corpus format for the carl-ops sweep. Extends the halctf.trajectory.v1
event-record schema with the per-trial trajectory record. See schema.py.
"""

from .schema import (
    DETECTION_ACTIONS,
    DETECTION_STATUSES,
    OUTCOMES,
    PLANES,
    RECORD_TYPES,
    REFUSAL_TYPES,
    SCHEMA_VERSION,
    TERMINAL_OUTCOMES,
    validate_jsonl,
    validate_record,
)

__all__ = [
    "SCHEMA_VERSION",
    "RECORD_TYPES",
    "PLANES",
    "OUTCOMES",
    "REFUSAL_TYPES",
    "TERMINAL_OUTCOMES",
    "DETECTION_ACTIONS",
    "DETECTION_STATUSES",
    "validate_record",
    "validate_jsonl",
]
