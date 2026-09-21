"""Loop parser: model text -> (declared_intent, tool, arguments, target).

Malformed output is expected and is treated as data, never as a crash. The
caller logs a `parse_failure` record with the raw text and continues; the
parse-failure rate per model is itself a measurement.

Expected model output is a single JSON object with keys:
    {"intent": str, "tool": str, "arguments": {..}, "target": str|null}
It may be wrapped in a ```json fence or embedded in prose; we extract the first
balanced object. `target` is optional (defaults to null / a local action).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass(frozen=True)
class ParseResult:
    ok: bool
    declared_intent: Optional[str] = None
    tool: Optional[str] = None
    arguments: Optional[dict] = None
    target: Optional[str] = None
    raw: str = ""
    error: Optional[str] = None


def _first_balanced_object(text: str) -> Optional[str]:
    """Return the first top-level {...} substring with balanced braces."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        start = text.find("{", start + 1)
    return None


def _extract_json(text: str) -> Optional[str]:
    m = _FENCE.search(text)
    if m:
        return m.group(1)
    return _first_balanced_object(text)


def parse(text: str) -> ParseResult:
    if text is None:
        return ParseResult(ok=False, raw="", error="empty model output")
    blob = _extract_json(text)
    if blob is None:
        return ParseResult(ok=False, raw=text, error="no JSON object found")
    try:
        obj = json.loads(blob)
    except json.JSONDecodeError as exc:
        return ParseResult(ok=False, raw=text, error=f"json decode error: {exc}")
    if not isinstance(obj, dict):
        return ParseResult(ok=False, raw=text, error="parsed value is not an object")

    intent = obj.get("intent")
    tool = obj.get("tool")
    args = obj.get("arguments", {})
    target = obj.get("target", None)

    if not isinstance(intent, str) or not intent.strip():
        return ParseResult(ok=False, raw=text, error="missing/empty 'intent' string")
    if not isinstance(tool, str) or not tool.strip():
        return ParseResult(ok=False, raw=text, error="missing/empty 'tool' string")
    if not isinstance(args, dict):
        return ParseResult(ok=False, raw=text, error="'arguments' must be an object")
    if target is not None and not isinstance(target, str):
        return ParseResult(ok=False, raw=text, error="'target' must be string or null")

    return ParseResult(
        ok=True,
        declared_intent=intent.strip(),
        tool=tool.strip(),
        arguments=args,
        target=target,
        raw=text,
    )
