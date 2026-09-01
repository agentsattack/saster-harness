"""carl-ops envelope-mass scorer — echo teacher-forcing (length-normalized)
over the 13 candidate model-facing tool actions, split into three envelopes:
declared_in / declared_out against the world-state scope block, and
prohibition_out against the oracle invariants. See scorer.py.

The prefix each decision point is scored against advances with the trajectory;
:mod:`carl_ops_envelope.context` is the single definition of that
construction, shared by the calibration script and the sweep driver."""

from __future__ import annotations

from .context import (
    SYSTEM,
    build_prefix,
    prefixes_along,
    render_step,
)
from .scorer import (
    CANDIDATES,
    DEFAULT_SCORER_TIMEOUT_S,
    ENVELOPE_COMPUTED,
    ENVELOPE_NOT_COMPUTED,
    ENVELOPE_NOT_COMPUTED_NOTE,
    SCORED_NOT_COMPUTED,
    SCORED_NOT_COMPUTED_NOTE,
    Candidate,
    ScoredDistribution,
    candidate_mean_logprob,
    envelope_mass,
    envelopes,
    envelopes_not_computed,
    in_declared_scope,
    introduces_violation,
    prefix_token_count,
    score_candidates,
)

__all__ = [
    "CANDIDATES",
    "DEFAULT_SCORER_TIMEOUT_S",
    "Candidate",
    "envelope_mass",
    "envelopes",
    "in_declared_scope",
    "introduces_violation",
    "candidate_mean_logprob",
    "prefix_token_count",
    "score_candidates",
    "ScoredDistribution",
    "ENVELOPE_COMPUTED",
    "ENVELOPE_NOT_COMPUTED",
    "ENVELOPE_NOT_COMPUTED_NOTE",
    "envelopes_not_computed",
    "SCORED_NOT_COMPUTED",
    "SCORED_NOT_COMPUTED_NOTE",
    "SYSTEM",
    "build_prefix",
    "prefixes_along",
    "render_step",
]
