"""Budget accounting for the defense stack.

Blocking changes the run. When a blocking layer (L3, or L2, or the approval
gate) denies a pending call, the attacker does not simply stop — it reroutes
and consumes budget doing so. If budget accounting does not charge that
reroute, blocking layers look artificially strong (they'd block for free) and
the ablation is skewed. This ledger charges:

- ``base_cost`` for every action attempted (the action itself), and
- ``reroute_cost`` additionally whenever an attempt is blocked and the
  attacker has to find another route.

``stalls`` counts blocked attempts; ``repeats`` counts the agent resubmitting
the SAME action it was just blocked on — a reroute that did not route
anywhere. They were one counter incremented on one line (Stage 2 audit);
they are two facts and are charged separately. Both feed the frozen record's
``budget`` block.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BudgetLedger:
    cap: int
    base_cost: int = 1
    reroute_cost: int = 1
    consumed: int = 0
    stalls: int = 0
    repeats: int = 0

    def charge_action(self) -> None:
        """Charge for one attempted action."""
        self.consumed += self.base_cost

    def charge_block(self) -> None:
        """A blocking layer denied the attempt: the attacker stalls, then
        reroutes and pays for it. Charging this is what keeps a blocking layer
        from looking free."""
        self.stalls += 1
        self.consumed += self.reroute_cost

    def charge_repeat(self) -> None:
        """The agent resubmitted the action it was just blocked on. The
        attempt itself was already charged; this records that the reroute
        went nowhere."""
        self.repeats += 1

    # Kept for callers written against the single-counter ledger; it now
    # charges a block only. A repeat is a separate observation.
    def charge_block_and_reroute(self) -> None:
        self.charge_block()

    @property
    def exhausted(self) -> bool:
        return self.consumed >= self.cap

    def snapshot(self) -> dict[str, int]:
        """The frozen record's ``budget`` block."""
        return {
            "cap": self.cap,
            "consumed": self.consumed,
            "stalls": self.stalls,
            "repeats": self.repeats,
        }
