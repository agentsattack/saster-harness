"""AgentDoG's own prompt templates and label taxonomy, vendored verbatim.

See ``PROVENANCE.md``. The three ``.txt`` files are byte-for-byte copies from
``AI45Lab/AgentDoG`` and are never edited here: a failure-mode label is only
comparable to AgentDoG's published fine-grained accuracy if the model is asked
the question it was trained and evaluated on, in the format it was trained and
evaluated in.

The fine-grained template has two placeholders, ``{taxonomy}`` and
``{trajectory}``, and upstream fills both. :func:`fine_grained_prompt` does the
same substitution and nothing else.

**Checkpoints.** AgentDoG 1.0 ships the binary and the fine-grained heads as
SEPARATE checkpoints — ``AgentDoG-Qwen3-4B`` answers the binary template,
``AgentDoG-FG-Qwen3-4B`` answers the fine-grained one — and the published
fine-grained accuracies (Risk Source 82.0 / Failure Mode 32.4 / Real-world Harm
58.4) are the FG checkpoint's. Asking the binary checkpoint for a fine-grained
label is out of distribution for it, and a corpus that does not record which
checkpoint answered cannot be read against that baseline. The observer model is
a config field and the manifest records it; :data:`FINE_GRAINED_CHECKPOINTS`
names the ones that were trained for this template so a run can say whether it
used one.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_HERE = Path(__file__).resolve().parent

TRAJECTORY_FINEGRAINED_PATH = _HERE / "trajectory_finegrained.txt"
TRAJECTORY_BINARY_PATH = _HERE / "trajectory_binary.txt"
TAXONOMY_FINEGRAINED_PATH = _HERE / "taxonomy_finegrained.txt"

#: Upstream provenance, recorded in the run manifest beside the hashes.
AGENTDOG_REPO = "https://github.com/AI45Lab/AgentDoG"
AGENTDOG_REVISION = "c8d803f"
AGENTDOG_PROMPT_VERSION = "v1.0"

#: Checkpoints trained on the fine-grained template. A run whose observer is
#: not one of these is asking a binary head for a label it was not trained to
#: emit — the answer may parse and still not be the quantity AgentDoG's
#: published fine-grained accuracy describes.
FINE_GRAINED_CHECKPOINTS = frozenset({
    "AI45Research/AgentDoG-FG-Qwen3-4B",
    "AI45Research/AgentDoG-FG-Qwen2.5-7B",
    "AI45Research/AgentDoG-FG-Llama3.1-8B",
})


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def taxonomy_text() -> str:
    return _read(TAXONOMY_FINEGRAINED_PATH)


def binary_prompt(trajectory: str) -> str:
    return _read(TRAJECTORY_BINARY_PATH).replace("{trajectory}", trajectory)


def fine_grained_prompt(trajectory: str) -> str:
    """The upstream fine-grained template with both placeholders filled.

    ``str.replace`` rather than ``str.format``: the trajectory is arbitrary
    JSON and is full of braces, so formatting would raise or silently consume
    them.
    """
    template = _read(TRAJECTORY_FINEGRAINED_PATH)
    return template.replace("{taxonomy}", taxonomy_text()).replace(
        "{trajectory}", trajectory
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_fine_grained_checkpoint(observer_model: str) -> bool:
    return observer_model in FINE_GRAINED_CHECKPOINTS


__all__ = [
    "AGENTDOG_PROMPT_VERSION",
    "AGENTDOG_REPO",
    "AGENTDOG_REVISION",
    "FINE_GRAINED_CHECKPOINTS",
    "TAXONOMY_FINEGRAINED_PATH",
    "TRAJECTORY_BINARY_PATH",
    "TRAJECTORY_FINEGRAINED_PATH",
    "binary_prompt",
    "fine_grained_prompt",
    "is_fine_grained_checkpoint",
    "sha256",
    "taxonomy_text",
]
