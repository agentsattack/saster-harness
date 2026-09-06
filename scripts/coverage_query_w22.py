#!/usr/bin/env python3
"""W22 — the declared-vs-enforced coverage query, printed and written out.

No attack and no model: at every world state along the two reference routes
(the grant/divergence route and the in-network firewall route), the whole
candidate action set is classified twice — DECLARED-prohibited by the oracle
invariants (``introduces_violation`` semantics) and ENFORCED-denied by the
per-action layers of each defense config in the instrument registry — and the
two are intersected. The GAP is what the oracle would flag and no active
per-action layer denies; the reverse column is what a layer denies and the
oracle would not flag. L4 is post hoc and takes no part (see
``saster_defense.coverage``).

Configs come from ``saster_instrument.DEFENSE_CONFIGS`` — whatever keys the
registry has (a later vendor-shaped cell is simply one more column).

Writes JSON to ``$W22_OUT`` (default ``runs/w22_coverage_query.json``,
relative paths resolved against the repo root) and refuses to overwrite an
existing file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from saster_defense.coverage import coverage_query, render_table, to_json  # noqa: E402

DEFAULT_OUT = "runs/w22_coverage_query.json"


def output_path() -> Path:
    out = Path(os.environ.get("W22_OUT", DEFAULT_OUT))
    return out if out.is_absolute() else REPO / out


def main() -> int:
    out = output_path()
    if out.exists():
        print(f"refusing to overwrite existing {out}; set W22_OUT to a new path", file=sys.stderr)
        return 2
    result = coverage_query()
    print(render_table(result))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_json(result) + "\n", encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
