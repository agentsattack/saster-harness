"""Append-only JSONL telemetry writer plus record builders.

Durability: every write is flushed and fsync'd so a crashed run still yields a
complete, valid trajectory up to the last completed step. Builders construct
schema-valid records; the writer validates before writing (strict by default)
so a scaffolding bug surfaces immediately instead of producing ragged logs.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from . import SCHEMA_VERSION
from .schema import validate_record


def now_utc() -> str:
    """ISO-8601 UTC timestamp with a trailing Z, millisecond precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def truncate(content: Any, limit: int) -> tuple[str, bool, int]:
    """Coerce content to text and truncate to `limit` chars.

    Returns (text, truncated, original_length). We record the flag and original
    length rather than silently cutting. limit <= 0 disables truncation.
    """
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, default=str)
    original_length = len(content)
    if limit and limit > 0 and original_length > limit:
        return content[:limit], True, original_length
    return content, False, original_length


class TelemetryError(RuntimeError):
    pass


class TelemetryWriter:
    """One writer per run. Thread-safe; safe to share across the router+loop.

    Two sinks: the append-only file (durable, fsync'd) and an optional `mirror`
    stream (typically stdout). The mirror exists because in a platform-hosted
    sandbox the mounted volume may be theirs — if only stdout is returned, the
    mirror is the trajectory's way out. The mirror carries PURE JSONL (identical
    records); all human-readable logs go to stderr, so stdout stays parseable.
    """

    def __init__(self, path: str, strict: bool = True, mirror: Any = None):
        self.path = path
        self.strict = strict
        self.mirror = mirror
        self._lock = threading.Lock()
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        # line-buffered append; created if absent, never truncated.
        self._fh = open(path, "a", encoding="utf-8", buffering=1)

    def write(self, record: dict) -> dict:
        errors = validate_record(record)
        if errors:
            msg = f"telemetry record failed schema validation: {errors}"
            if self.strict:
                raise TelemetryError(msg)
            # Non-strict: never lose the run over a bad record — wrap and note it.
            record = _violation_record(record, errors)
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()
            os.fsync(self._fh.fileno())
            if self.mirror is not None:
                try:
                    self.mirror.write(line + "\n")
                    self.mirror.flush()
                except (OSError, ValueError):
                    pass  # a broken mirror must never take down the run
        return record

    def close(self) -> None:
        with self._lock:
            try:
                self._fh.flush()
                os.fsync(self._fh.fileno())
            finally:
                self._fh.close()

    def __enter__(self) -> "TelemetryWriter":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _violation_record(bad: Any, errors: list[str]) -> dict:
    return base_record(
        record_type="error",
        run_id=str(bad.get("run_id", "unknown")) if isinstance(bad, dict) else "unknown",
        challenge_id=str(bad.get("challenge_id", "unknown")) if isinstance(bad, dict) else "unknown",
        step_index=int(bad.get("step_index", 0)) if isinstance(bad, dict) and isinstance(bad.get("step_index"), int) else 0,
        plane="tool",
        outcome="error",
        error={"type": "schema_violation", "message": "; ".join(errors)[:2000]},
        meta={"offending_record": json.dumps(bad, default=str)[:4000]},
    )


# --------------------------------------------------------------------------
# Record builders. Each returns a plain dict; the writer validates on write.
# --------------------------------------------------------------------------

def base_record(
    *,
    record_type: str,
    run_id: str,
    challenge_id: str,
    step_index: int,
    plane: str,
    outcome: str,
    declared_intent: Optional[str] = None,
    action: Optional[dict] = None,
    observation: Optional[dict] = None,
    model: Optional[dict] = None,
    refusal: Optional[dict] = None,
    error: Optional[dict] = None,
    attempt: Optional[int] = None,
    meta: Optional[dict] = None,
) -> dict:
    rec: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "record_type": record_type,
        "run_id": run_id,
        "challenge_id": challenge_id,
        "step_index": step_index,
        "timestamp_utc": now_utc(),
        "plane": plane,
        "outcome": outcome,
        "declared_intent": declared_intent,
        "action": action,
        "observation": observation,
        "model": model,
        "refusal": refusal,
        "error": error,
    }
    if attempt is not None:
        rec["attempt"] = attempt
    if meta is not None:
        rec["meta"] = meta
    return rec


def observation_record(content: Any, truncate_len: int) -> dict:
    text, was_truncated, original = truncate(content, truncate_len)
    return {"content": text, "truncated": was_truncated, "original_length": original}


def emit_scope_grant(
    telemetry: "TelemetryWriter",
    *,
    run_id: str,
    challenge_id: str,
    step_index: int,
    granted: list,
    source: str,
    effective_size: int,
) -> dict:
    """Log what the agent was authorized to reach, and from where. Worth having
    in the corpus independently of any solve."""
    return telemetry.write(base_record(
        record_type="scope_grant",
        run_id=run_id, challenge_id=challenge_id, step_index=step_index,
        plane="tool", outcome="ok",
        meta={"granted": granted, "source": source, "effective_size": effective_size},
    ))
