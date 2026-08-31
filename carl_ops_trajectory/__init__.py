"""carl-ops trajectory record schema (saster.trajectory.v1).

Frozen corpus format for the carl-ops sweep. Descends from the
halctf.trajectory.v1 event-record schema (recorded in each record's
``derived_from``) and adds the per-trial trajectory record. See schema.py.
"""

from .schema import (
    CLOCK_KINDS,
    DERIVED_FROM,
    DETECTION_ACTIONS,
    DETECTION_STATUSES,
    MARKER_INDEX_SPACES,
    ONSET_STATUSES,
    ORACLE_INDEX_SPACE,
    OUTCOMES,
    PLANES,
    POLICY_VERDICTS,
    RECORD_TYPES,
    REFUSAL_TYPES,
    SCHEMA_VERSION,
    SCORED_STATUSES,
    TERMINAL_OUTCOMES,
    WIDENING_ROUTES,
    first_finding_step,
    to_action_index,
    validate_jsonl,
    validate_record,
)

__all__ = [
    "SCHEMA_VERSION",
    "DERIVED_FROM",
    "CLOCK_KINDS",
    "RECORD_TYPES",
    "PLANES",
    "OUTCOMES",
    "ONSET_STATUSES",
    "SCORED_STATUSES",
    "REFUSAL_TYPES",
    "TERMINAL_OUTCOMES",
    "POLICY_VERDICTS",
    "WIDENING_ROUTES",
    "DETECTION_ACTIONS",
    "DETECTION_STATUSES",
    "MARKER_INDEX_SPACES",
    "ORACLE_INDEX_SPACE",
    "first_finding_step",
    "to_action_index",
    "validate_record",
    "validate_jsonl",
]
