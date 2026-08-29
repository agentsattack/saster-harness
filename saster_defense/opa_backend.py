"""Real OPA backend for L2.

Runs the authored ``policy.rego`` through the ``opa`` binary. The policy is the
single source of truth for the L2 decision; the Python evaluator in
``l2_policy`` is retained only as a test oracle that must agree with OPA on
every case (divergences are reported, not silently reconciled).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

_POLICY_PATH = Path(__file__).with_name("policy.rego")
_DECISION_QUERY = "data.saster.carlops.decision"


@lru_cache(maxsize=1)
def find_opa() -> str | None:
    """Locate the opa binary: an explicit ``SASTER_OPA`` env var, a repo-local
    ``.tools/opa``, or one on PATH."""
    env = os.environ.get("SASTER_OPA")
    if env and Path(env).exists():
        return env
    local = Path(__file__).resolve().parents[1] / ".tools" / "opa"
    if local.exists():
        return str(local)
    return shutil.which("opa")


def opa_available() -> bool:
    return find_opa() is not None and _POLICY_PATH.exists()


def evaluate_opa(
    tool: str,
    args: dict,
    rules: list[str],
    networks: list[str],
    roles_assignable: list[str],
) -> dict:
    """Evaluate one action through real OPA. Returns the decision object
    ``{"verdict": ..., "rule_id": ...}``. Raises if opa is unavailable."""
    opa = find_opa()
    if opa is None:
        raise RuntimeError("opa binary not found")
    input_doc = {"tool": tool, "args": args}
    data_doc = {
        "config": {"rules": rules},
        "scope": {"networks": networks, "roles_assignable": roles_assignable},
    }
    proc = subprocess.run(
        [
            opa, "eval",
            "-d", str(_POLICY_PATH),
            "--stdin-input",
            "--data", _write_data(data_doc),
            "--format", "json",
            _DECISION_QUERY,
        ],
        input=json.dumps(input_doc),
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(proc.stdout)
    result = out.get("result")
    if not result:
        return {"verdict": "allow", "rule_id": None}
    value: dict = result[0]["expressions"][0]["value"]
    return value


def _write_data(data_doc: dict) -> str:
    """Write the data document to a stable temp file keyed by content, so
    repeated evaluations with the same scope/rules reuse it."""
    import hashlib
    import tempfile

    blob = json.dumps(data_doc, sort_keys=True)
    digest = hashlib.sha256(blob.encode()).hexdigest()[:16]
    path = Path(tempfile.gettempdir()) / f"saster_opa_data_{digest}.json"
    if not path.exists():
        path.write_text(blob, encoding="utf-8")
    return str(path)
