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

from .types import POLICY_VERDICT_VALUES

_POLICY_PATH = Path(__file__).with_name("policy.rego")
_DECISION_QUERY = "data.saster.carlops.decision"

#: Bound on one ``opa eval``. Unbounded, a hung binary hangs the cell; the
#: layer reports unavailable instead (Stage 1 defect D1).
DEFAULT_OPA_TIMEOUT_S = 30.0


class OpaBackendError(RuntimeError):
    """The opa binary did not produce a decision — it was absent, exited
    non-zero, timed out, or answered with something that is not JSON. The
    layer maps this to ``unavailable``; it is never a verdict."""


class OpaUndefinedDecision(OpaBackendError):
    """The decision query evaluated to UNDEFINED (an empty ``result``). Before
    Stage 1 this returned ``{"verdict": "allow"}`` — a silent default on the
    one layer whose whole prediction (P3) is about what it declines to see."""


class OpaMalformedDecision(OpaBackendError):
    """opa answered, but not in the closed verdict vocabulary or not in the
    decision shape. The layer maps this to ``error`` — it ran and its answer
    is unusable — never to a verdict guessed from the text."""


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
    timeout: float = DEFAULT_OPA_TIMEOUT_S,
    ops_principals: list[str] | None = None,
) -> dict:
    """Evaluate one action through real OPA against ``policy.rego`` (L2).
    Returns the decision object ``{"verdict": ..., "rule_id": ...}`` with
    ``verdict`` in the closed vocabulary, or raises :class:`OpaBackendError`
    (a subclass for undefined and malformed). It never returns a default:
    every path that is not a conforming decision raises."""
    data_doc = {
        "config": {"rules": rules},
        "scope": {"networks": networks, "roles_assignable": roles_assignable,
                  "ops_principals": list(ops_principals or ["ops-agent"])},
    }
    return evaluate_policy(_POLICY_PATH, _DECISION_QUERY,
                           {"tool": tool, "args": args}, data_doc, timeout)


def evaluate_policy(
    policy_path: Path,
    query: str,
    input_doc: dict,
    data_doc: dict,
    timeout: float = DEFAULT_OPA_TIMEOUT_S,
) -> dict:
    """One ``opa eval`` of ``query`` over ``policy_path`` with the given
    input and data documents. Shared by L2 (``policy.rego``) and the
    vendor-shaped scope lock (``scope_lock.rego``); the decision shape and
    every failure rule are the same for both."""
    opa = find_opa()
    if opa is None:
        raise OpaBackendError("opa binary not found")
    try:
        proc = subprocess.run(
            [
                opa, "eval",
                "-d", str(policy_path),
                "--stdin-input",
                "--data", _write_data(data_doc),
                "--format", "json",
                query,
            ],
            input=json.dumps(input_doc),
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise OpaBackendError(f"opa eval timed out after {timeout}s") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "")[:300] if isinstance(exc.stderr, str) else ""
        raise OpaBackendError(f"opa eval exited {exc.returncode}: {stderr!r}") from exc
    except OSError as exc:
        raise OpaBackendError(f"opa eval could not start: {exc}") from exc

    stdout = getattr(proc, "stdout", None)
    if not isinstance(stdout, str) or not stdout.strip():
        raise OpaBackendError("opa eval produced no output")
    try:
        out = json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise OpaBackendError(f"opa eval output is not JSON: {stdout[:120]!r}") from exc
    if not isinstance(out, dict):
        raise OpaMalformedDecision(f"opa eval output is not an object: {stdout[:120]!r}")
    result = out.get("result")
    if not result:
        # UNDEFINED. policy.rego declares a default decision, so this means
        # the policy did not evaluate at all — a load error, a wrong package,
        # a type error in a rule body. Nothing here is evidence of allow.
        raise OpaUndefinedDecision(
            "the decision query is undefined (empty result); refusing to "
            "default to allow"
        )
    try:
        value = result[0]["expressions"][0]["value"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpaMalformedDecision(
            f"opa eval result is not in the decision shape: {stdout[:160]!r}"
        ) from exc
    if not isinstance(value, dict) or "verdict" not in value:
        raise OpaMalformedDecision(f"decision carries no verdict: {value!r}"[:200])
    verdict = value.get("verdict")
    if verdict not in POLICY_VERDICT_VALUES:
        raise OpaMalformedDecision(
            f"verdict {verdict!r} is outside the closed vocabulary "
            f"{sorted(POLICY_VERDICT_VALUES)}"
        )
    rule_id = value.get("rule_id")
    if rule_id is not None and not isinstance(rule_id, str):
        raise OpaMalformedDecision(f"rule_id {rule_id!r} is not a string or null")
    return {"verdict": verdict, "rule_id": rule_id}


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
