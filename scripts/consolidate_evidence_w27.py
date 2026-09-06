#!/usr/bin/env python3
"""GrrCON wrap: one manifest over every evidence store — the pre-sweep archive,
w24/w24b/w24c, the §P and §R arms — with both mirror roots and a single
top-level hash. Read-only over the stores; writes only MANIFEST.json at the
evidence root. Run on spark1; run with --verify-only on the mirror to
recompute and compare."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path.home() / "evidence"
STORES = ["pre-sweep"] + sorted(p.name for p in (ROOT / "sweep").iterdir() if p.is_dir()) if (ROOT / "sweep").exists() else ["pre-sweep"]
WHY = {
    "pre-sweep": "Stage 0 archive of every pre-sweep artifact; tag pre-sweep-2026-09",
    "w24_sweep_qwen3": "first Stage 4 launch, halted by the operator on D12 after two cells; kept",
    "w24_sweep_ministral": "first Stage 4 launch, halted by the operator on D12 after two cells; kept",
    "w24b_sweep_qwen3": "the full matrix, 48 cells; 20 cells short on D13/D14",
    "w24b_sweep_ministral": "the full matrix, 48 cells; 14 cells short on D13/D14",
    "w24c_sweep_qwen3": "re-run of the 20 lost cells under a new run id",
    "w24c_sweep_ministral": "re-run of the 14 lost cells under a new run id",
    "w25p_sweep_qwen3": "addendum §P: Qwen under tool_choice required on the 30 cells where Ministral breached",
    "w26r_sweep_qwen3": "addendum §R: R6 on l2, all and vendor-shaped",
    "w26r_sweep_ministral": "addendum §R: R6 on l2, all and vendor-shaped",
}


def store_digest(store: Path) -> tuple[str, int, int]:
    """sha256 over the store's own SHA256SUMS lines (path + hash), sorted;
    returns (digest, files, mismatches) after re-verifying every file."""
    sums = store / "SHA256SUMS"
    lines = sorted(line.strip() for line in sums.read_text().splitlines() if line.strip())
    mismatches = 0
    for line in lines:
        h, _, rel = line.partition("  ")
        p = store / rel
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != h:
            mismatches += 1
    return hashlib.sha256("\n".join(lines).encode()).hexdigest(), len(lines), mismatches


def main() -> None:
    verify_only = "--verify-only" in sys.argv
    entries = {}
    for name in STORES:
        store = ROOT / name if name == "pre-sweep" else ROOT / "sweep" / name
        if not (store / "SHA256SUMS").exists():
            continue
        d, n, mm = store_digest(store)
        entries[name] = {"path": str(store.relative_to(ROOT)), "files": n, "store_sha256": d, "mismatches": mm, "why": WHY.get(name, "")}
    top = hashlib.sha256("\n".join(f"{k}  {v['store_sha256']}" for k, v in sorted(entries.items())).encode()).hexdigest()
    print(f"stores {len(entries)} files {sum(v['files'] for v in entries.values())} mismatches {sum(v['mismatches'] for v in entries.values())}")
    for k, v in sorted(entries.items()):
        print(f"  {k:<24} files {v['files']:>5} sha256 {v['store_sha256'][:16]} mismatches {v['mismatches']}")
    print("TOP-LEVEL sha256:", top)
    if verify_only:
        existing = json.loads((ROOT / "MANIFEST.json").read_text()) if (ROOT / "MANIFEST.json").exists() else {}
        print("matches MANIFEST.json:", existing.get("top_level_sha256") == top)
        return
    manifest = {"written_utc": datetime.now(UTC).isoformat(), "roots": {"primary": "spark1:~/evidence", "mirror": "spark8:~/evidence"},
                "definition": "store_sha256 = sha256 over the store's sorted SHA256SUMS lines; top_level_sha256 = sha256 over 'name  store_sha256' lines sorted by name",
                "stores": entries, "top_level_sha256": top}
    (ROOT / "MANIFEST.json").write_text(json.dumps(manifest, indent=1))
    print("wrote", ROOT / "MANIFEST.json")


if __name__ == "__main__":
    main()
