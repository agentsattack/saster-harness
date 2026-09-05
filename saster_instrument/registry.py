"""The registries. Data only — no test logic lives here.

Each entry names the tests that cover it (``covered_by``). The meta-test
resolves those names against the test tree, so an entry that claims coverage
it does not have fails the same way an entry with no claim does.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import degenerate as _dg

# ---------------------------------------------------------------------------
# Class 1 — the degenerate-input matrix (docs/instrument-test-plan.md, Class 1)
# ---------------------------------------------------------------------------

#: The rows every wrapper is exercised against. A wrapper that cannot be fed a
#: row must say so explicitly (``no_parse_surface``) — silence is not
#: coverage. The last row is the Stage 1 addition: a trajectory serialized
#: over 16,384 tokens must score ``unavailable`` for every detector, never
#: clean (protects P2).
DEGENERATE_ROWS: tuple[str, ...] = (
    "empty_string",
    "whitespace_only",
    "none",
    "http_4xx_5xx_body",
    "timeout_exception",
    "truncated_json",
    "well_formed_wrong_schema",
    "wrong_casing_of_token",
    "wrong_language_of_token",
    "header_only_group_header",
    "content_filter_refusal_string",
    "both_tokens",
    "exceeds_max_tokens_length_capped",
    "over_context_window_16384",
)

#: Adapter contract. ``build(row)`` returns ``(run, patches)``: ``run`` is a
#: zero-argument callable that exercises the wrapper against that row and
#: returns its :class:`saster_defense.types.LayerOutcome` (or, for a bare
#: client, the sentinel :data:`saster_instrument.degenerate.TYPED_ERROR`);
#: or a :class:`saster_instrument.degenerate.RowNotApplicable` carrying the
#: reason that row cannot be fed to this wrapper. ``patches`` is a list of
#: ``(target_object, attribute, replacement)`` the test applies with
#: ``monkeypatch`` before calling ``run``. Adapters live in
#: :mod:`saster_instrument.degenerate`.
DegenerateAdapter = Callable[[str], tuple[Callable[[], Any], list[tuple[Any, str, Any]]]]


@dataclass(frozen=True)
class WrapperSpec:
    """One classifier / parser / detector wrapper."""

    name: str
    #: The object under test, for the introspection half of the meta-test.
    target: str
    #: Which value of the wrapper's vocabulary reads as CLEAN — the one value
    #: a degenerate input must never produce.
    clean_values: tuple[str, ...]
    #: The Class 1 adapter, or None when the wrapper has no response-parsing
    #: surface at all (then ``no_parse_surface`` must say why).
    degenerate: DegenerateAdapter | None = None
    no_parse_surface: str | None = None
    covered_by: tuple[str, ...] = ()

    @property
    def has_matrix(self) -> bool:
        return self.degenerate is not None or self.no_parse_surface is not None


@dataclass(frozen=True)
class MetricSpec:
    """One scalar metric. ``probes`` are the Class 2 degenerate-input probes
    (name -> callable that must raise or return a sentinel, never a number)."""

    name: str
    #: Where the number lives: a record path, or ``report:`` for an aggregate.
    location: str
    probes: dict[str, Callable[[], Any]] = field(default_factory=dict)
    covered_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarkerSpec:
    """One trajectory marker and the index unit it is expressed in."""

    name: str
    unit: str | None
    computed_by: str
    covered_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class DefenseConfigSpec:
    """One ablation cell. ``factory`` builds its ``DefenseConfig``."""

    key: str
    factory: Callable[[], Any]
    #: True for the six pre-registered ablation configs; the seventh
    #: (``vendor-shaped``, P17) is added in Stage 2 under the addendum.
    pre_registered: bool = True
    covered_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class VictimFamily:
    """One chat-template family in the victim registry."""

    key: str
    model: str
    chat_template_kwargs: dict[str, Any]
    tool_call_parser: str
    covered_by: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# The registries. Populated by the class commits; committed red.
# ---------------------------------------------------------------------------

WRAPPERS: dict[str, WrapperSpec] = {
    "l1_classifier": WrapperSpec(
        name="l1_classifier",
        target="saster_defense.l1_classifier:ClassifierGuard.classify",
        clean_values=("allow",),
        no_parse_surface=_dg.L1_NO_PARSE_SURFACE,
        covered_by=(
            "test_l1_endpoint_without_client_is_unavailable_not_real",
            "test_l1_without_stand_in_is_unavailable_never_clean",
        ),
    ),
    "l2_policy": WrapperSpec(
        name="l2_policy",
        target="saster_defense.l2_policy:PolicyEngine.evaluate",
        clean_values=("allow",),
        degenerate=_dg.l2_adapter,
        covered_by=("test_degenerate_input_never_clean",
                    "test_policy_verdict_of_wrapper_failure_is_unavailable"),
    ),
    "opa_client": WrapperSpec(
        name="opa_client",
        target="saster_defense.opa_backend:evaluate_opa",
        clean_values=("allow",),
        degenerate=_dg.opa_client_adapter,
        covered_by=("test_degenerate_input_never_clean",),
    ),
    "l3_trace": WrapperSpec(
        name="l3_trace",
        target="saster_defense.l3_trace:TraceMonitor.check",
        clean_values=("allow",),
        degenerate=_dg.l3_adapter,
        covered_by=("test_degenerate_input_never_clean",),
    ),
    "z3_client": WrapperSpec(
        name="z3_client",
        target="saster_defense.l3_trace:breach_entailed_z3",
        clean_values=("False",),
        degenerate=_dg.z3_client_adapter,
        covered_by=("test_degenerate_input_never_clean",),
    ),
    "l4_auditor_binary": WrapperSpec(
        name="l4_auditor_binary",
        target="saster_defense.l4_auditor:TrajectoryAuditor.audit",
        clean_values=("allow",),
        degenerate=_dg.l4_adapter(fine_grained=False),
        covered_by=("test_degenerate_input_never_clean",
                    "test_over_window_trajectory_is_unavailable_for_every_detector"),
    ),
    "l4_auditor_fine_grained": WrapperSpec(
        name="l4_auditor_fine_grained",
        target="saster_defense.l4_auditor:TrajectoryAuditor.audit",
        clean_values=("allow",),
        degenerate=_dg.l4_adapter(fine_grained=True),
        covered_by=("test_degenerate_input_never_clean",
                    "test_over_window_trajectory_is_unavailable_for_every_detector"),
    ),
    "l5_approval": WrapperSpec(
        name="l5_approval",
        target="saster_defense.l5_approval:ApprovalGate.gate",
        clean_values=("allow",),
        degenerate=_dg.l5_adapter,
        covered_by=("test_degenerate_input_never_clean",),
    ),
    "refusal_turn_classifier": WrapperSpec(
        name="refusal_turn_classifier",
        target="saster_harness.canary:classify_turn",
        clean_values=("ok",),
        degenerate=_dg.turn_classifier_adapter,
        covered_by=("test_degenerate_input_never_clean",),
    ),
}

METRICS: dict[str, MetricSpec] = {
    "declared_in": MetricSpec("declared_in", "turns[].envelope_mass.declared_in"),
    "declared_out": MetricSpec("declared_out", "turns[].envelope_mass.declared_out"),
    "prohibition_out": MetricSpec("prohibition_out", "turns[].envelope_mass.prohibition_out"),
    "surprisal": MetricSpec("surprisal", "actions[].surprisal"),
    "refusal_prob": MetricSpec("refusal_prob", "turns[].refusal_prob"),
    "containment_latency": MetricSpec("containment_latency", "containment_latency.value"),
    "cvr": MetricSpec("cvr", "report:cvr"),
    "breach_rate": MetricSpec("breach_rate", "report:breach_within_k"),
    "records_distinct_ratio": MetricSpec("records_distinct_ratio", "report:records/distinct"),
}

MARKERS: dict[str, MarkerSpec] = {
    "onset_dist": MarkerSpec("onset_dist", None, "not estimated (AMENDMENT 2)"),
    "explanatory_divergence": MarkerSpec(
        "explanatory_divergence", None, "carl_ops_markers.markers:explanatory_divergence"
    ),
    "point_of_no_return": MarkerSpec(
        "point_of_no_return", None, "carl_ops_markers.markers:point_of_no_return"
    ),
    "breach_step_index": MarkerSpec(
        "breach_step_index", None, "carl_ops_oracle (snapshot space), converted"
    ),
    "first_detection_step": MarkerSpec(
        "first_detection_step", None, "carl_ops_trajectory.schema:first_finding_step"
    ),
}

DEFENSE_CONFIGS: dict[str, DefenseConfigSpec] = {}

VICTIM_FAMILIES: dict[str, VictimFamily] = {}
