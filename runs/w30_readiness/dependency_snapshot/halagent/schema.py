"""Trajectory record schema and a dependency-free validator.

One JSONL record == one event on one plane. A logical *step* is a group of
records sharing the same (run_id, step_index): typically one or more model-plane
records (the model call, plus one per retry) followed by one tool-plane record
(the dispatch). This is a deliberate reading of "one record per step" — see
README and the report notes. Group by (run_id, step_index) to reconstruct steps.

The validator is hand-written (no jsonschema dependency) so the image stays
stdlib-only. It returns a list of human-readable error strings; empty == valid.
"""
from __future__ import annotations

from typing import Any

from . import SCHEMA_VERSION

# record_type — the finer-grained kind of event. `step` and `model_call` are the
# workhorses; the rest are event markers.
RECORD_TYPES = {
    "run_start",
    "runtime_recon",  # startup snapshot of the injected runtime contract (endpoints/env)
    "scope_grant",    # allowlist populated (base or per-challenge) — what was authorized
    "model_call",     # one model backend call (one per attempt, incl. retries)
    "parse_failure",  # model output could not be parsed into an action
    "step",           # a tool dispatch (the intent/action/observation triple)
    "scope_refusal",  # convenience alias surfaced as a step w/ refused_by_scope
    "budget_exhausted",
    "run_end",
    "error",
}

PLANES = {"tool", "model"}

# The four canonical action outcomes named in the spec, plus three flagged
# extensions used by non-action event records. See report notes.
OUTCOMES = {
    "dispatched",         # spec
    "refused_by_scope",   # spec
    "refused_by_model",   # spec
    "error",              # spec
    # --- extensions (flagged) ---
    "parse_failure",
    "budget_exhausted",
    "ok",                 # informational records (run_start / run_end)
}

REFUSAL_TYPES = {"hard_refusal", "hedge", "partial_compliance", "deflection"}

# Fields required on every record regardless of kind.
_CORE_REQUIRED = (
    "schema_version",
    "record_type",
    "run_id",
    "challenge_id",
    "step_index",
    "timestamp_utc",
    "plane",
    "outcome",
)


def _is_str(v: Any) -> bool:
    return isinstance(v, str)


def _err(errors: list, path: str, msg: str) -> None:
    errors.append(f"{path}: {msg}")


def _validate_action(action: Any, errors: list) -> None:
    if action is None:
        return
    if not isinstance(action, dict):
        _err(errors, "action", "must be object or null")
        return
    if not _is_str(action.get("tool")):
        _err(errors, "action.tool", "required string")
    if not isinstance(action.get("arguments"), dict):
        _err(errors, "action.arguments", "required object")
    target = action.get("target", None)
    if target is not None and not _is_str(target):
        _err(errors, "action.target", "must be string or null")


def _validate_observation(obs: Any, errors: list) -> None:
    if obs is None:
        return
    if not isinstance(obs, dict):
        _err(errors, "observation", "must be object or null")
        return
    if "content" not in obs:
        _err(errors, "observation.content", "required")
    if not isinstance(obs.get("truncated"), bool):
        _err(errors, "observation.truncated", "required bool")
    ol = obs.get("original_length", None)
    if ol is not None and not isinstance(ol, int):
        _err(errors, "observation.original_length", "must be int or null")


def _validate_model(model: Any, errors: list) -> None:
    if model is None:
        return
    if not isinstance(model, dict):
        _err(errors, "model", "must be object or null")
        return
    if not _is_str(model.get("backend")):
        _err(errors, "model.backend", "required string")
    if not _is_str(model.get("name")):
        _err(errors, "model.name", "required string")
    if not isinstance(model.get("params"), dict):
        _err(errors, "model.params", "required object")
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        v = model.get(k, None)
        if v is not None and not isinstance(v, int):
            _err(errors, f"model.{k}", "must be int or null")
    lat = model.get("latency_ms", None)
    if lat is not None and not isinstance(lat, (int, float)):
        _err(errors, "model.latency_ms", "must be number or null")


def _validate_refusal(ref: Any, errors: list) -> None:
    if ref is None:
        return
    if not isinstance(ref, dict):
        _err(errors, "refusal", "must be object or null")
        return
    if ref.get("refusal_type") not in REFUSAL_TYPES:
        _err(errors, "refusal.refusal_type", f"must be one of {sorted(REFUSAL_TYPES)}")
    conf = ref.get("confidence")
    if not isinstance(conf, (int, float)) or not (0.0 <= float(conf) <= 1.0):
        _err(errors, "refusal.confidence", "must be number in [0,1]")
    if not _is_str(ref.get("span", "")):
        _err(errors, "refusal.span", "must be string")


def validate_record(rec: Any) -> list[str]:
    """Return a list of validation errors for one record. Empty == valid."""
    errors: list[str] = []
    if not isinstance(rec, dict):
        return ["record: must be a JSON object"]

    for key in _CORE_REQUIRED:
        if key not in rec:
            _err(errors, key, "required")

    if rec.get("schema_version") != SCHEMA_VERSION:
        _err(errors, "schema_version", f"must equal {SCHEMA_VERSION!r}")
    if rec.get("record_type") not in RECORD_TYPES:
        _err(errors, "record_type", f"must be one of {sorted(RECORD_TYPES)}")
    if rec.get("plane") not in PLANES:
        _err(errors, "plane", f"must be one of {sorted(PLANES)}")
    if rec.get("outcome") not in OUTCOMES:
        _err(errors, "outcome", f"must be one of {sorted(OUTCOMES)}")
    if not _is_str(rec.get("run_id", None)):
        _err(errors, "run_id", "required string")
    if not _is_str(rec.get("challenge_id", None)):
        _err(errors, "challenge_id", "required string")
    if not isinstance(rec.get("step_index", None), int):
        _err(errors, "step_index", "required int")
    elif rec["step_index"] < 0:
        _err(errors, "step_index", "must be >= 0")
    if not _is_str(rec.get("timestamp_utc", None)):
        _err(errors, "timestamp_utc", "required string")

    di = rec.get("declared_intent", None)
    if di is not None and not _is_str(di):
        _err(errors, "declared_intent", "must be string or null")

    _validate_action(rec.get("action", None), errors)
    _validate_observation(rec.get("observation", None), errors)
    _validate_model(rec.get("model", None), errors)
    _validate_refusal(rec.get("refusal", None), errors)

    err = rec.get("error", None)
    if err is not None:
        if not isinstance(err, dict):
            _err(errors, "error", "must be object or null")
        else:
            if not _is_str(err.get("type", "")):
                _err(errors, "error.type", "must be string")
            if not _is_str(err.get("message", "")):
                _err(errors, "error.message", "must be string")

    return errors


def validate_jsonl(path: str) -> tuple[int, list[str]]:
    """Validate an entire JSONL file end to end.

    Returns (n_records, errors). A blank line or bad JSON is itself an error.
    """
    import json

    errors: list[str] = []
    n = 0
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if line.strip() == "":
                errors.append(f"line {lineno}: blank line (not allowed in JSONL)")
                continue
            n += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {lineno}: invalid JSON: {exc}")
                continue
            for e in validate_record(rec):
                errors.append(f"line {lineno}: {e}")
    return n, errors
