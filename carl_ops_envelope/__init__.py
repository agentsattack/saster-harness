"""carl-ops envelope-mass scorer — echo teacher-forcing (length-normalized)
over the 13 candidate model-facing tool actions, split into three envelopes:
declared_in / declared_out against the world-state scope block, and
prohibition_out against the oracle invariants. See scorer.py."""

from __future__ import annotations

from .scorer import (
    CANDIDATES,
    Candidate,
    candidate_mean_logprob,
    envelope_mass,
    in_declared_scope,
    introduces_violation,
    prefix_token_count,
)

__all__ = [
    "CANDIDATES",
    "Candidate",
    "envelope_mass",
    "in_declared_scope",
    "introduces_violation",
    "candidate_mean_logprob",
    "prefix_token_count",
]
