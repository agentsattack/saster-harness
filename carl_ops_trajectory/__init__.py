"""carl-ops trajectory record schema (saster.trajectory.v1).

Frozen corpus format for the carl-ops sweep. Descends from the
halctf.trajectory.v1 event-record schema (recorded in each record's
``derived_from``) and adds the per-trial trajectory record. See schema.py.
"""

from .schema import (
    DERIVED_FROM,
    DETECTION_ACTIONS,
    DETECTION_STATUSES,
    OUTCOMES,
    PLANES,
    POLICY_VERDICTS,
    RECORD_TYPES,
    REFUSAL_TYPES,
    SCHEMA_VERSION,
    TERMINAL_OUTCOMES,
    validate_jsonl,
    validate_record,
)

__all__ = [
    "SCHEMA_VERSION",
    "DERIVED_FROM",
    "RECORD_TYPES",
    "PLANES",
    "OUTCOMES",
    "REFUSAL_TYPES",
    "TERMINAL_OUTCOMES",
    "POLICY_VERDICTS",
    "DETECTION_ACTIONS",
    "DETECTION_STATUSES",
    "validate_record",
    "validate_jsonl",
]
