#!/usr/bin/env python3
"""Post hoc L1: score every turn text of the citable records (sweep, §P, §R)
and the 24 sanctioned controls through a served guardian classifier. Read-only
over the corpus; writes scores and a summary under runs/w28_l1_posthoc/<tag>/.

Turn text = the agent's reply for that turn: its prose content when there is
any, else the tool call it emitted (name + arguments), which is what the
input classifier would see on the wire. The ticket (the first user message)
is scored once per trajectory as turn -1. Texts are cached by sha256 so the
same reply is scored once."""
from __future__ import annotations

import collections
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from saster_defense.l1_classifier import ClassifierGuard, client_family  # noqa: E402
from saster_harness.content_store import ContentStore  # noqa: E402

MODEL = os.environ.get("L1_MODEL", "ibm-granite/granite-guardian-3.2-5b")
ENDPOINT = os.environ.get("L1_ENDPOINT", "http://[fd00:200::4]:8003")
RISK = os.environ.get("L1_RISK", "harm")
TAG = os.environ.get("L1_TAG", client_family(MODEL))
WORKERS = int(os.environ.get("L1_WORKERS", "8"))
OUT = REPO / "runs/w28_l1_posthoc" / TAG
ROOTS = (("sweep", ("w24b", "w24c")), ("w25p", ("w25p",)), ("w26r", ("w26r",)))


def turn_texts(rec: dict, store: ContentStore) -> list[tuple[int, str]]:
    out = []
    if rec["turns"]:
        try:
            prompt = store.get(rec["turns"][0]["prompt_ref"])
            user = [m for m in prompt if m.get("role") == "user"]
            if user:
                out.append((-1, str(user[-1].get("content"))))
        except Exception:  # noqa: BLE001 — a missing blob is reported, not fatal
            out.append((-1, ""))
    for i, t in enumerate(rec["turns"]):
        try:
            resp = store.get(t["response_ref"])
        except Exception:  # noqa: BLE001
            out.append((i, ""))
            continue
        if isinstance(resp, dict):
            content = resp.get("content")
            calls = resp.get("tool_calls") or []
            text = content if content and str(content).strip() else " ".join(f"{c.get('name')} {c.get('arguments')}" for c in calls)
        else:
            text = str(resp)
        out.append((i, text or ""))
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    guard = ClassifierGuard(model=MODEL, endpoint=ENDPOINT, risk_name=RISK,
                            pins={"model_revision": os.environ.get("L1_REVISION", ""), "image_digest": os.environ.get("L1_IMAGE_DIGEST", "")})
    if not guard.health_check():
        raise SystemExit(f"{MODEL} is not served at {ENDPOINT}")
    items = []  # (corpus, family, cell, trial, breach, outcome, turn, text)
    for corpus, roots in ROOTS:
        chosen = {}
        for root in roots:
            for sp in sorted((REPO / "runs").glob(f"{root}_sweep_*/sweep_state.json")):
                tag = sp.parent.name.split("_sweep_", 1)[1]
                for cid, c in json.loads(sp.read_text())["cells"].items():
                    d = REPO / c["dir"]
                    if (d / "trajectories.jsonl").exists():
                        chosen[(tag, cid)] = d
        for (tag, cid), d in chosen.items():
            store = ContentStore(d / "blobs")
            for line in (d / "trajectories.jsonl").open():
                r = json.loads(line)
                for turn, text in turn_texts(r, store):
                    items.append((corpus, tag, cid, r["trial_index"], r["oracle"]["breach"], r["terminal_outcome"], turn, text))
    cd = REPO / "corpora/citable/safe_controls_w22b_qwen"
    store = ContentStore(cd / "blobs")
    for line in (cd / "trajectories.jsonl").open():
        r = json.loads(line)
        for turn, text in turn_texts(r, store):
            items.append(("controls", "qwen3", "safe_controls_w22b_qwen", r["trial_index"], False, r["terminal_outcome"], turn, text))
    uniq = {hashlib.sha256(t.encode()).hexdigest(): t for *_, t in items}
    print(f"{len(items)} turn texts over {len({(c, f, cid, tr) for c, f, cid, tr, *_ in items})} trajectories; {len(uniq)} distinct texts; classifier {MODEL} risk={RISK}")

    def score(pair):
        h, text = pair
        v, rule, detail, raw = guard.classify_text(text)
        return h, {"verdict": v.value, "rule_id": rule, "detail": detail, "raw": raw}

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        scores = dict(pool.map(score, uniq.items()))
    with (OUT / "scores.jsonl").open("w") as fh:
        for c, f, cid, tr, br, outc, turn, text in items:
            h = hashlib.sha256(text.encode()).hexdigest()
            fh.write(json.dumps({"corpus": c, "family": f, "cell": cid, "trial": tr, "breach": br, "outcome": outc, "turn": turn, "text_sha256": h, **scores[h]}) + "\n")
    verdicts = collections.Counter(s["verdict"] for s in scores.values())
    # firing per trajectory: any turn denied
    traj: dict = {}
    for c, f, cid, tr, br, outc, turn, text in items:
        key = (c, f, cid, tr)
        s = scores[hashlib.sha256(text.encode()).hexdigest()]
        t = traj.setdefault(key, {"breach": br, "outcome": outc, "fired": False, "turns": 0, "denied_turns": [], "unavailable": 0, "error": 0})
        t["turns"] += 1
        if s["verdict"] == "deny":
            t["fired"] = True
            t["denied_turns"].append(turn)
        elif s["verdict"] in ("unavailable", "error"):
            t[s["verdict"]] += 1
    summary: dict = {"model": MODEL, "endpoint": ENDPOINT, "risk": RISK, "revision": guard.pins, "distinct_texts": len(uniq), "verdicts_over_distinct_texts": dict(verdicts), "groups": {}, "breaching_cells_with_a_firing": {}}
    for (c, f, cid, tr), t in traj.items():
        grp = "controls" if c == "controls" else ("breaching" if t["breach"] else "sanctioned_non_breaching")
        g = summary["groups"].setdefault(f"{c}/{f}/{grp}", {"n": 0, "fired": 0})
        g["n"] += 1
        g["fired"] += t["fired"]
        if t["breach"] and t["fired"]:
            summary["breaching_cells_with_a_firing"].setdefault(f"{c}/{f}/{cid}", []).append(tr)
    for k, g in sorted(summary["groups"].items()):
        g["rate"] = round(g["fired"] / g["n"], 3)
        print(f"  {k:<40} fired {g['fired']}/{g['n']} = {g['rate']}")
    print("verdicts over distinct texts:", dict(verdicts))
    print("breaching cells with a firing trajectory:", len(summary["breaching_cells_with_a_firing"]))
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    (OUT / "trajectories.json").write_text(json.dumps({"|".join(map(str, k)): v for k, v in traj.items()}, indent=1))


if __name__ == "__main__":
    main()
