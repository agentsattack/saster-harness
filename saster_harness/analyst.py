"""Analyst backend descriptor and hosting determination (W6).

The reasoning-loop analyst (``asagap``'s ``LLMAnalyst``, see that repo's
``asagap/engine/reasoning_loop.py``) hardcodes a hosted Anthropic model and
constructs its client at ``__init__``. W6 asks one question about it: can it
be pointed at the local cluster over the same OpenAI-compatible path the
campaign runner uses?

**Determination: yes — no capability gap.** Recorded here as data so the
answer travels with the corpus instead of living in a commit message.

What the analyst actually asks of a serving backend, read off its one call
site (``max_tokens=800``, a ``system`` string, a single user turn, free text
back):

- a system prompt and one user message — both are plain OpenAI chat roles;
- ~800 completion tokens of free text;
- a short context. Every input is truncated before it is sent: the target
  response to 500 chars, the challenge description to 400, and the history to
  the last five turns at 120 chars each. The assembled prompt is a few
  thousand tokens, nowhere near a local context limit.

What it does **not** ask for, which is what makes the answer "yes": no tool or
function calling, no JSON/structured-output mode, no vision, no streaming, no
logprobs, and no Anthropic-specific feature beyond SDK surface. The only
hosted-API couplings are mechanical: the ``system=`` kwarg becomes a
``{"role": "system"}`` message, and ``msg.content[0].text`` becomes
``choices[0].message.content``.

So the gap is not capability. It is **fidelity**, and it is worth recording
because of how the analyst's output is consumed. ``_parse_analyst_output``
pulls eight fixed uppercase section headers out of free text with a lenient
regex, and every field falls back to a safe default when its header is missing
— ``defense_pattern="unknown"``, ``progress_score=0``, ``tier="note"``. A
model that follows the eight-section format less rigidly therefore does not
crash the loop; it quietly produces empty analysis that looks like a
low-information turn. For a measurement harness that silent-degradation mode
is the dangerous one, so :func:`section_completeness` scores each analyst
response against the expected headers and the campaign records the score.
Degraded local analysis is then visible in the record rather than
indistinguishable from a genuinely uninformative turn.

Nothing here calls the analyst or reimplements it; this module describes the
backend and checks response shape so the manifest can be honest about which
analyst produced a corpus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The eight section headers :func:`_parse_analyst_output` looks for. Order
#: matches the analyst system prompt.
ANALYST_SECTIONS: tuple[str, ...] = (
    "WHAT REVEALED",
    "DEFENSE PATTERN",
    "PROGRESS",
    "PROGRESS SCORE",
    "HYPOTHESIS",
    "RECOMMENDED NEXT",
    "NUMERIC SIGNAL",
    "TIER",
)

#: Capabilities the analyst requires of a serving backend. Every one of these
#: is satisfied by an OpenAI-compatible vLLM endpoint, which is why the
#: hosting determination is "local is sufficient".
ANALYST_REQUIRED_CAPABILITIES: tuple[str, ...] = (
    "chat_completions",
    "system_role",
    "max_tokens>=800",
)

#: Capabilities the analyst does **not** use. Listed explicitly because the
#: determination turns on their absence: any one of them present would have
#: made the local path a question of model support rather than fidelity.
ANALYST_UNUSED_CAPABILITIES: tuple[str, ...] = (
    "tool_calling",
    "structured_output",
    "vision",
    "streaming",
    "logprobs",
    "long_context",
)

#: Recorded in the manifest as the W6 determination.
HOSTING_DETERMINATION = (
    "local-sufficient: the analyst needs chat completions with a system role "
    "and ~800 free-text tokens; it uses no tool calling, structured output, "
    "vision, streaming or long context. Porting is mechanical (system kwarg "
    "-> system message; content[0].text -> choices[0].message.content). The "
    "residual risk is section-header fidelity, not capability, and is "
    "measured by section_completeness()."
)


def section_completeness(text: str) -> float:
    """Fraction of :data:`ANALYST_SECTIONS` present in an analyst response.

    The analyst's parser defaults every missing field to a safe value, so a
    model that drifts from the eight-section format degrades silently into
    what looks like an uninformative turn. Scoring the response makes that
    drift visible: ``1.0`` is full compliance, ``0.0`` means the parser found
    nothing and every field will have taken its default.

    Matching mirrors the parser: case-insensitive, header followed by a colon
    or whitespace. ``PROGRESS`` is matched so that ``PROGRESS SCORE`` does not
    also satisfy it.
    """
    if not text:
        return 0.0
    found = 0
    for header in ANALYST_SECTIONS:
        # Require the header not be immediately followed by another word
        # character run that would make it a *different* header (PROGRESS vs
        # PROGRESS SCORE).
        pattern = re.compile(rf"\b{re.escape(header)}\b(?!\s+SCORE\b)[:\s]", re.I)
        if pattern.search(text):
            found += 1
    return found / len(ANALYST_SECTIONS)


@dataclass(frozen=True)
class AnalystBackend:
    """Which analyst produced a run, recorded in the run manifest.

    ``hosted`` is the load-bearing field: a corpus analysed by a hosted model
    and one analysed by a local 70B are not interchangeable, and the record
    has to say which it was without the reader consulting a config file.
    """

    model: str
    endpoint: str | None = None
    backend: str = "local_openai_compatible"
    hosted: bool = False
    role: str = "reasoning_loop_analyst"

    @classmethod
    def local(cls, model: str, endpoint: str) -> AnalystBackend:
        """Analyst served by the local cluster over the OpenAI-compatible
        path — the same serving layer the campaign runner uses."""
        return cls(model=model, endpoint=endpoint,
                   backend="local_openai_compatible", hosted=False)

    @classmethod
    def hosted_anthropic(cls, model: str) -> AnalystBackend:
        """The analyst's stock configuration: a hosted Anthropic model."""
        return cls(model=model, endpoint=None,
                   backend="anthropic_hosted", hosted=True)

    @classmethod
    def none(cls) -> AnalystBackend:
        """No analyst ran. Recorded distinctly so an absent analyst can never
        be mistaken for one that ran and found nothing."""
        return cls(model="", endpoint=None, backend="none", hosted=False)

    @property
    def ran(self) -> bool:
        return self.backend != "none"

    def as_manifest_block(self) -> dict[str, object]:
        """The run manifest's ``analyst`` block."""
        return {
            "role": self.role,
            "backend": self.backend,
            "model": self.model,
            "endpoint": self.endpoint,
            "hosted": self.hosted,
            "ran": self.ran,
            "determination": HOSTING_DETERMINATION,
            "required_capabilities": list(ANALYST_REQUIRED_CAPABILITIES),
            "unused_capabilities": list(ANALYST_UNUSED_CAPABILITIES),
        }
