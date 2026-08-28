"""VictimAgent — the shared base for saster-harness victim fixtures.

One persona, several deployments. A *deployment* is a concrete agent the
sweep drives (``carl-support``, ``carl-ops``); the base exists so that every
deployment exposes the same three **observation planes** in the same way,
and so a detector's ``requires_planes`` resolves identically no matter which
deployment produced the trajectory. Cross-beat trajectories are only
comparable if the plane a detector needs means the same thing on each side.

Planes (defined in :mod:`saster_harness.instrumentation`, reused verbatim
here):

- ``tool``    — the agent's tool/network calls.
- ``model``   — the model's own completions (the reasoning signal).
- ``process`` — in-agent hooks, via a :class:`ProcessPlaneAdapter`.

Honest scope note. Every detector shipped today declares ``requires_planes =
(TOOL,)`` — the wire plane only. The base activates and records the model and
process planes, and the availability logic distinguishes an *unavailable*
plane from a *clean* one, but no shipped detector requires a non-tool plane,
so the unavailable-plane branch is not exercised by any current detector. The
three-plane model here is design rationale for cross-beat comparability, not
a demonstrated detection result; do not read it as one.

Dispatch integrity. A tool call is recorded as agent behaviour only when it
is bound to a model completion that authorized it (see
:meth:`VictimAgent.dispatch_tool`). A well-formed tool payload that arrives
without such a binding is refused and recorded as an integrity event, never
as a normal step — otherwise a spoofed call would be indistinguishable from
real agent behaviour in every trajectory the sweep produces.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from carl_ops_trajectory import DERIVED_FROM, SCHEMA_VERSION

from .instrumentation import (
    CallbackProcessPlaneAdapter,
    InstrumentationProfile,
    InstrumentationState,
    ObservationPlane,
    ProcessPlaneAdapter,
    detector_required_planes,
    resolve_profile,
)


class UnboundToolDispatchError(RuntimeError):
    """A tool dispatch was not bound to a model completion that authorized it.

    Raised by :meth:`VictimAgent.dispatch_tool` when the supplied completion
    token is unknown, or when the token is valid but did not authorize this
    tool. The attempt is recorded as an integrity event, not as a step."""


@dataclass(frozen=True)
class CompletionToken:
    """An opaque handle to a recorded model completion. Only a token minted by
    :meth:`VictimAgent.record_completion` can authorize a tool dispatch."""

    value: str


@dataclass
class _Completion:
    token: CompletionToken
    step_index: int
    text: str
    authorized_tools: tuple[str, ...]


def _logical_clock() -> Callable[[], str]:
    """A deterministic, wall-clock-free timestamp source. The sweep must be
    reproducible, so the default 'clock' is a monotonic logical counter, not
    ``datetime.now``. Callers that want real time can inject their own."""
    counter = itertools.count()
    return lambda: f"t{next(counter)}"


@dataclass
class VictimAgent:
    """Base for a victim deployment.

    Subclasses implement :meth:`_execute_tool` to perform a tool against
    whatever world the deployment owns (carl-ops wires it to the state
    store's tool session) and return the observation content. Everything
    about planes, model-completion binding, and record emission lives here so
    it is identical across deployments.
    """

    run_id: str
    challenge_id: str
    persona: str = "carl"
    deployment: str = "base"
    profile_name: str = "standard"
    custom_profiles: Mapping[str, list[str]] | None = None
    process_adapter: ProcessPlaneAdapter | None = None
    clock: Callable[[], str] = field(default_factory=_logical_clock)

    def __post_init__(self) -> None:
        profile: InstrumentationProfile = resolve_profile(
            self.profile_name, self.custom_profiles
        )
        self._instr = InstrumentationState(profile, self.custom_profiles)
        if self.process_adapter is None:
            self.process_adapter = CallbackProcessPlaneAdapter()
        self._completions: dict[str, _Completion] = {}
        self._records: list[dict[str, Any]] = []
        self._step = itertools.count()
        self._token_seq = itertools.count()

    # -- plane exposure ----------------------------------------------------

    def active_planes(self) -> frozenset[ObservationPlane]:
        return self._instr.active_planes

    def plane_active(self, plane: ObservationPlane) -> bool:
        return plane in self._instr.active_planes

    def detector_available(self, detector: object) -> bool:
        """A detector is available iff all its required planes are active —
        the same resolution used everywhere, so it is identical across
        deployments. An unavailable detector is *not* a clean one."""
        return self._instr.is_available(detector)

    def required_planes(self, detector: object) -> frozenset[ObservationPlane]:
        return detector_required_planes(detector)

    # -- model plane -------------------------------------------------------

    def record_completion(
        self,
        text: str,
        authorized_tools: tuple[str, ...] = (),
        *,
        backend: str = "scripted",
        model_name: str = "scripted-victim",
        params: Mapping[str, Any] | None = None,
    ) -> CompletionToken:
        """Record one model completion on the model plane and mint the token
        that can authorize the tool calls it names. Returns the token."""
        step_index = next(self._step)
        token = CompletionToken(f"cmp-{next(self._token_seq)}")
        self._completions[token.value] = _Completion(
            token, step_index, text, tuple(authorized_tools)
        )
        if self.plane_active(ObservationPlane.MODEL):
            self._emit(
                record_type="model_call",
                step_index=step_index,
                plane="model",
                outcome="ok",
                model={
                    "backend": backend,
                    "name": model_name,
                    "params": dict(params or {}),
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "total_tokens": None,
                    "latency_ms": None,
                },
                declared_intent=text,
            )
        return token

    # -- tool plane (dispatch integrity) -----------------------------------

    def dispatch_tool(
        self,
        tool: str,
        token: CompletionToken | None,
        target: str | None = None,
        **args: Any,
    ) -> Any:
        """Execute a tool ONLY when it is bound to a completion that
        authorized it, and record it as a step. An unbound or unauthorized
        call raises :class:`UnboundToolDispatchError` and is recorded as an
        integrity event — it never enters the trace as agent behaviour."""
        completion = self._completions.get(token.value) if token else None
        if completion is None or tool not in completion.authorized_tools:
            reason = (
                "no completion token" if token is None
                else "unknown completion token" if completion is None
                else "tool not authorized by the bound completion"
            )
            self._emit(
                record_type="error",
                step_index=next(self._step),
                plane="tool",
                outcome="error",
                action={"tool": tool, "arguments": dict(args), "target": target},
                error={"type": "unbound_tool_dispatch", "message": reason},
            )
            raise UnboundToolDispatchError(f"{tool}: {reason}")

        observation = self._execute_tool(tool, target=target, **args)
        content = "" if observation is None else str(observation)
        self._emit(
            record_type="step",
            step_index=next(self._step),
            plane="tool",
            outcome="dispatched",
            action={"tool": tool, "arguments": dict(args), "target": target},
            observation={
                "content": content,
                "truncated": False,
                "original_length": None,
            },
            declared_intent=completion.text,
        )
        return observation

    def _execute_tool(self, tool: str, target: str | None = None, **args: Any) -> Any:
        raise NotImplementedError("a deployment must implement _execute_tool")

    # -- process plane -----------------------------------------------------

    def emit_process_event(self, event: Mapping[str, object]) -> None:
        """Forward an in-agent hook event to the process-plane adapter. A
        no-op when the process plane is not active or the adapter is idle."""
        if not self.plane_active(ObservationPlane.PROCESS):
            return
        adapter = self.process_adapter
        if isinstance(adapter, CallbackProcessPlaneAdapter):
            adapter.emit(event)

    # -- records -----------------------------------------------------------

    def _emit(self, *, record_type: str, step_index: int, plane: str, outcome: str,
              **fields: Any) -> None:
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "derived_from": DERIVED_FROM,
            "record_type": record_type,
            "run_id": self.run_id,
            "challenge_id": self.challenge_id,
            "step_index": step_index,
            "timestamp_utc": self.clock(),
            "plane": plane,
            "outcome": outcome,
        }
        record.update(fields)
        self._records.append(record)

    def records(self) -> list[dict[str, Any]]:
        """The emitted event records, in order — each a saster.trajectory.v1
        event record (validate with ``carl_ops_trajectory.validate_record``)."""
        return list(self._records)
