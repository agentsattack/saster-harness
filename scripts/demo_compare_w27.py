#!/usr/bin/env python3
"""Compare a replay's action sequence with the recorded demo beat, byte for byte."""
from __future__ import annotations

import hashlib
import json
import sys


def seq_hash(rec: dict) -> str:
    return hashlib.sha256(json.dumps([(a["tool"], a["args"]) for a in rec["actions"]], sort_keys=True).encode()).hexdigest()


def main() -> None:
    with open(sys.argv[1]) as fh:
        replay = [json.loads(line) for line in fh if line.strip()][0]
    with open(sys.argv[2]) as fh:
        recorded = json.load(fh)["record"]
    a, b = seq_hash(replay), seq_hash(recorded)
    print(f"replay   {a[:16]} steps {len(replay['actions'])} outcome {replay['terminal_outcome']}")
    print(f"recorded {b[:16]} steps {len(recorded['actions'])} outcome {recorded['terminal_outcome']}")
    print("BYTE-IDENTICAL action sequence" if a == b else "DIFFERS")
    sys.exit(0 if a == b else 3)


if __name__ == "__main__":
    main()
