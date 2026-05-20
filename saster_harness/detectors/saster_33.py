"""SASTER-33 — Context Stripping (Tier 4, Infrastructure & Recon).

Canonical definition (from SASTER.md):

    Attack:
        The attacker probes the agent with prompts that strip expected
        contextual scaffolding — system role markers, conversation history
        references, declared persona cues, tool-availability preambles —
        to observe how the agent's behavior degrades or shifts when its
        operational context is partially absent.

    Detection:
        Structural anomaly detection against a baseline of turn-shape
        statistics — token counts, role marker presence, persona-cue
        density, expected boilerplate. Sudden absence of expected context
        elements in an inbound prompt, paired with the agent's continued
        attempt to respond authoritatively, fires the pattern. Often
        co-occurs with SASTER-22 (Cross-Model Compositional) and SASTER-26
        (Recon-Gated Injection) during active reconnaissance.

Operational shape at the wire level
-----------------------------------
At the wire level Context Stripping shows up as a chat-completion
request missing the ``role: "system"`` message that the session has
otherwise been consistently sending. The detector tracks a per-session
boolean ("does this session expect a system message?") and fires when
a turn violates the established baseline.

The baseline requires a minimum number of consistent observations
before locking in the expectation — sessions that vary their system
prompt naturally (RAG agents with per-query system content) never lock
in a "should have system" baseline and therefore never fire.

The detector reads :attr:`TurnData.has_system_message`, which the
adapter populates from the captured request shape. Adapters that can't
determine system-message presence (non-chat protocols, opaque request
bodies) set the field to ``None`` and the detector skips the turn.

Simplification vs ProxyGAP
--------------------------
ProxyGAP's ``_check_structural_anomaly`` is the source of this logic.
The harness version keeps the per-session baseline machinery intact
(min turns, consistency threshold) and skips the embedding-drift fusion
ProxyGAP does at the dashboard level — that fusion is a deployment
concern, not a detector concern.

Tunables
--------
- ``min_turns`` (default 3): a session must accumulate this many
  chat-shape observations before the expectation can lock in. Below
  the threshold, the detector returns ``None`` even on a violation.
- ``consistency_threshold`` (default 0.7): fraction of observations
  that must follow the same pattern (with-system or without-system)
  before the expectation locks in.

False-positive cases
--------------------
- RAG agents that synthesize fresh system prompts per query — handled
  by the consistency-threshold baseline (mixed sessions never lock in).
- Multi-modal endpoints that occasionally accept structured tool
  messages instead of chat messages — handled by ``TurnData.has_system_message``
  being ``None`` for non-chat shapes.
- Sessions that switch system prompts mid-conversation for legitimate
  reasons (persona change, context window rotation) — will produce a
  burst of false positives until the baseline re-locks. Mitigation:
  call :meth:`reset_session` when an authorized persona change occurs.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from ..detector import SasterDetector
from ..event import DetectionEvent, TurnData


@dataclass
class _StructuralBaseline:
    turns_seen: int = 0
    with_system: int = 0
    without_system: int = 0
    expects_system: bool | None = None


class ContextStrippingDetector(SasterDetector):
    saster_id = "SASTER-33"
    pattern_name = "Context Stripping"
    tier = 4
    co_fires_with = ("SASTER-26",)

    def __init__(
        self,
        min_turns: int = 3,
        consistency_threshold: float = 0.7,
    ) -> None:
        super().__init__()
        self._min_turns = min_turns
        self._consistency_threshold = consistency_threshold
        self._baselines: dict[str, _StructuralBaseline] = {}
        self._lock = threading.Lock()

    def needs_baseline(self) -> bool:
        # The detector maintains its own structural baseline; it does NOT
        # need the embedding baseline (which has its own 10-turn warmup).
        # Returning False lets SASTER-33 fire from the first eligible turn.
        return False

    def reset_session(self, session_id: str) -> None:
        """Drop the structural baseline for a session. Useful when an
        authorised persona change has just occurred — the detector will
        re-learn the new expectation rather than firing on every turn
        until the new baseline locks in."""
        with self._lock:
            self._baselines.pop(session_id, None)

    def export_state(self) -> dict[str, dict[str, object]]:
        """Return a JSON-serialisable snapshot of per-session
        structural baselines. Used by the v0.3 persistence layer to
        save SASTER-33 state across harness restarts."""
        out: dict[str, dict[str, object]] = {}
        with self._lock:
            for session_id, state in self._baselines.items():
                out[session_id] = {
                    "turns_seen": state.turns_seen,
                    "with_system": state.with_system,
                    "without_system": state.without_system,
                    "expects_system": state.expects_system,
                }
        return out

    def import_state(self, snapshot: dict[str, dict[str, object]]) -> None:
        """Restore per-session structural baselines from a previous
        :meth:`export_state` snapshot."""
        with self._lock:
            for session_id, payload in snapshot.items():
                expects = payload.get("expects_system")
                state = _StructuralBaseline(
                    turns_seen=int(payload.get("turns_seen", 0)),  # type: ignore[arg-type]
                    with_system=int(payload.get("with_system", 0)),  # type: ignore[arg-type]
                    without_system=int(payload.get("without_system", 0)),  # type: ignore[arg-type]
                    expects_system=(
                        bool(expects) if isinstance(expects, bool) else None
                    ),
                )
                self._baselines[session_id] = state

    def evaluate(self, turn: TurnData) -> DetectionEvent | None:
        # ``None`` means the adapter could not determine system-message
        # presence — skip rather than guess.
        if turn.has_system_message is None:
            return None

        with self._lock:
            baseline = self._baselines.setdefault(turn.session_id, _StructuralBaseline())
            baseline.turns_seen += 1
            if turn.has_system_message:
                baseline.with_system += 1
            else:
                baseline.without_system += 1

            # Lock in expectation once we have enough observations.
            if baseline.turns_seen >= self._min_turns:
                ratio_with = baseline.with_system / baseline.turns_seen
                ratio_without = baseline.without_system / baseline.turns_seen
                if ratio_with >= self._consistency_threshold:
                    baseline.expects_system = True
                elif ratio_without >= self._consistency_threshold:
                    baseline.expects_system = False
                else:
                    baseline.expects_system = None

            should_fire = (
                baseline.expects_system is True and not turn.has_system_message
            )

        if not should_fire:
            return None

        return self._build_event(
            turn,
            evidence={
                "signal": "structural_anomaly",
                "detail": (
                    "Session baseline expects a role:system message; this turn does not "
                    "carry one. The agent is responding to a partially-stripped request "
                    "stack, characteristic of side-channel calls that bypass the agent's "
                    "established conversational context."
                ),
                "baseline_turns": baseline.turns_seen,
                "with_system_ratio": round(
                    baseline.with_system / baseline.turns_seen, 3
                ),
            },
        )


DETECTOR = ContextStrippingDetector()
