"""A content-addressed store for prompts and responses (Stage 2).

The record forbids inline prompt and response content and carries
``prompt_ref`` / ``response_ref`` instead — but nothing stored what the refs
named (Stage 2 audit): a ref was a hash of something that no longer existed
anywhere, and the two envelope modes hashed different objects under the
same field. This store makes a ref resolvable: ``put`` writes the object
under its own sha256 and returns the ref, ``get`` reads it back, and a
ref that resolves to bytes with a different hash is refused.

One store per cell directory (``<cell>/blobs/``). Objects are JSON; the
hash is over the canonical JSON bytes (sorted keys, no whitespace).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class RefMismatch(ValueError):
    """The bytes under a ref do not hash to that ref."""


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def ref_of(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


class ContentStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, ref: str) -> Path:
        if not ref.startswith("sha256:") or len(ref) != 7 + 64:
            raise ValueError(f"not a content ref: {ref!r}")
        return self.root / f"{ref[7:]}.json"

    def put(self, obj: Any) -> str:
        """Store ``obj`` and return its ref. Idempotent: the same object maps
        to the same file, and an existing file is never rewritten."""
        blob = canonical_bytes(obj)
        ref = "sha256:" + hashlib.sha256(blob).hexdigest()
        path = self._path(ref)
        if not path.exists():
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(blob)
            tmp.replace(path)
        return ref

    def get(self, ref: str) -> Any:
        path = self._path(ref)
        blob = path.read_bytes()
        if "sha256:" + hashlib.sha256(blob).hexdigest() != ref:
            raise RefMismatch(f"{path} does not hash to {ref}")
        return json.loads(blob)

    def has(self, ref: str) -> bool:
        return self._path(ref).exists()

    def __len__(self) -> int:
        return sum(1 for _ in self.root.glob("*.json"))


__all__ = ["ContentStore", "RefMismatch", "canonical_bytes", "ref_of"]
