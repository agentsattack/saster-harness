#!/usr/bin/env python3
"""Build the public evidence snapshot: copy ~/evidence (never edited in place) into a staging tree,
rewrite private node addresses, host names and home paths to role names in text files, add the W38
beat-1 store from runs/w38_beat1_clean, recompute per-store SHA256SUMS and a top-level manifest, and
write a scrub log that names every rewritten file with its private and public hashes.

Usage: build_public_evidence.py <staging_dir>   (refuses to overwrite)
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = Path.home() / "evidence"
W38 = REPO / "runs/w38_beat1_clean"
DEST = Path(sys.argv[1]).resolve()
if DEST.exists():
    raise SystemExit(f"refusing to overwrite {DEST}")
TEXT_EXT = {".json", ".jsonl", ".md", ".log", ".txt", ".py", ".sh", ".typescript", ".timing", ".toml", ".rego", ".csv", ".svg", ""}

#: Role-name rewrites. Order matters: longer/more specific first.
RULES = [
    (re.compile(r"fd00:200::/64"), lambda m: "the-fabric/64"),
    (re.compile(r"fd00:200::N\b"), lambda m: "node-N"),
    (re.compile(r"fd00:200::([0-9a-fA-F]+)"), lambda m: f"node-{int(m.group(1), 16)}"),
    (re.compile(r"192\.168\.1\.x\b"), lambda m: "lan-node-x"),
    (re.compile(r"192\.168\.1\.(\d+)"), lambda m: f"lan-node-{m.group(1)}"),
    (re.compile(r"spark(\d+)"), lambda m: f"node{m.group(1)}"),
    (re.compile(r"spark1-saster-push"), lambda m: "push-key"),
    (re.compile(r"/home/lbsuto"), lambda m: "/home/user"),
    (re.compile(r"\blbsuto\b"), lambda m: "user"),
]
RULE_TEXT = ["IPv6 node addresses on the private fabric -> node-<n>", "IPv4 LAN addresses -> lan-node-<n>",
             "host names spark<n> -> node<n>", "the operator's home directory -> /home/user", "the operator's login name -> user"]

def sha(b: bytes) -> str: return hashlib.sha256(b).hexdigest()

def scrub_bytes(b: bytes) -> tuple[bytes, bool]:
    try: s = b.decode("utf-8")
    except UnicodeDecodeError: return b, False
    t = s
    for rx, fn in RULES: t = rx.sub(fn, t)
    return (t.encode("utf-8"), t != s)

# ---- 1. copy the private tree, scrubbing text files
scrub_log = []; withheld = []; store_files: dict[str, dict[str, str]] = {}
WITHHOLD = {"session-transcript.md", "cluster-bringup.md", "cluster-audit-2026-08-31.md", "atbench_test.json", "atbench_unsafe497.json"}
WHY = {"atbench_test.json": "third-party dataset (ATBench, AI45Lab); obtain it from its source; the remeasurement results that cite it are published", "atbench_unsafe497.json": "third-party dataset (ATBench, AI45Lab); obtain it from its source"}
private_manifest = json.loads((SRC / "MANIFEST.json").read_text())
stores_in = dict(private_manifest["stores"])
for extra in sorted((SRC / "sweep").iterdir()):  # stores archived after the private manifest was written
    if extra.is_dir() and extra.name not in stores_in:
        stores_in[extra.name] = {"path": f"sweep/{extra.name}", "store_sha256": None,
                                 "why": "archived after the private manifest was written (2026-09-08): the DeepSeek-V4.1-Flash third-lineage sweep, addendum §AB, finding F29" if "deepseek" in extra.name else "archived after the private manifest was written"}
for store, meta in stores_in.items():
    src_dir = SRC / meta["path"]; dst_dir = DEST / meta["path"]
    for p in sorted(src_dir.rglob("*")):
        if not p.is_file(): continue
        if p.name == "login.txt": raise SystemExit(f"credentials file present in the evidence tree: {p}")
        rel = p.relative_to(src_dir); out = dst_dir / rel; out.parent.mkdir(parents=True, exist_ok=True)
        raw = p.read_bytes()
        if p.name in ("SHA256SUMS",): continue  # regenerated below
        if p.name in WITHHOLD:
            withheld.append({"store": store, "file": str(rel), "private_sha256": sha(raw), "why": WHY.get(p.name, "operational notes about the private cluster (host keys, bring-up); the procedure is described in the harness repository")}); continue
        new, changed = scrub_bytes(raw) if p.suffix.lower() in TEXT_EXT else (raw, False)
        out.write_bytes(new)
        if changed: scrub_log.append({"store": store, "file": str(rel), "private_sha256": sha(raw), "public_sha256": sha(new)})
        store_files.setdefault(store, {})[str(rel)] = sha(new)

# ---- 2. the W38 store from runs/ (completed runs only: a trajectories.jsonl exists)
w38_dir = DEST / "w38_beat1_clean"; w38_dir.mkdir(parents=True)
n_runs = 0
for run in sorted(W38.glob("w38-*")):
    if not (run / "trajectories.jsonl").is_file(): continue
    n_runs += 1
    for p in sorted(run.rglob("*")):
        if not p.is_file(): continue
        rel = p.relative_to(W38); out = w38_dir / rel; out.parent.mkdir(parents=True, exist_ok=True)
        raw = p.read_bytes(); new, changed = scrub_bytes(raw) if p.suffix.lower() in TEXT_EXT else (raw, False)
        out.write_bytes(new)
        if changed: scrub_log.append({"store": "w38_beat1_clean", "file": str(rel), "private_sha256": sha(raw), "public_sha256": sha(new)})
        store_files.setdefault("w38_beat1_clean", {})[str(rel)] = sha(new)
for extra in ["batch.sh", "batch2.sh", "heads/heads_posthoc.json"]:
    p = W38 / extra
    if p.is_file():
        raw = p.read_bytes(); new, _ = scrub_bytes(raw); out = w38_dir / extra; out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(new)
        store_files["w38_beat1_clean"][extra] = sha(new)
deliv = w38_dir / "deliverables"; deliv.mkdir()
for name in ("run_beat1_clean_w38.py", "analyze_w38.py", "heads_w38.py"):
    raw = (REPO / "scripts" / name).read_bytes(); new, _ = scrub_bytes(raw); (deliv / name).write_bytes(new); store_files["w38_beat1_clean"][f"deliverables/{name}"] = sha(new)
w38_summary = W38 / "summary.json"
if w38_summary.is_file():
    raw = w38_summary.read_bytes(); new, _ = scrub_bytes(raw); (w38_dir / "summary.json").write_bytes(new); store_files["w38_beat1_clean"]["summary.json"] = sha(new)

# ---- 3. per-store SHA256SUMS and the public manifest
stores_out = {}
for store, files in store_files.items():
    path = stores_in[store]["path"] if store in stores_in else "w38_beat1_clean"
    lines = sorted(f"{h}  {f}\n" for f, h in files.items())
    (DEST / path / "SHA256SUMS").write_text("".join(lines))
    store_sha = sha("".join(lines).encode())
    entry = {"path": path, "files": len(files), "store_sha256": store_sha}
    if store in stores_in:
        entry["private_store_sha256"] = stores_in[store]["store_sha256"]; entry["why"] = stores_in[store].get("why")
        entry["files_rewritten"] = sum(1 for e in scrub_log if e["store"] == store)
    else:
        entry["why"] = f"W38: carl-support under the stock brief (no planted weakness), Granite Guardian on every message and tool call with quarantine, model-driven and scripted attackers; {n_runs} completed runs as of the snapshot; finding F31"
        entry["files_rewritten"] = sum(1 for e in scrub_log if e["store"] == store)
    stores_out[store] = entry
top = sha("".join(f"{n}  {stores_out[n]['store_sha256']}\n" for n in sorted(stores_out)).encode())
manifest = {"written_utc": datetime.now(UTC).isoformat(), "kind": "public snapshot",
            "definition": private_manifest["definition"],
            "private_top_level_sha256": private_manifest["top_level_sha256"], "private_manifest_written_utc": private_manifest["written_utc"],
            "scrub_rules": RULE_TEXT, "files_rewritten": len(scrub_log), "files_withheld": withheld, "stores": stores_out, "top_level_sha256": top,
            "total_files": sum(e["files"] for e in stores_out.values())}
(DEST / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n")
(DEST / "SCRUB_LOG.json").write_text(json.dumps({"rules": RULE_TEXT, "rewritten": scrub_log}, indent=1) + "\n")
print(json.dumps({k: v for k, v in manifest.items() if k != "stores"}, indent=1))
for n, e in stores_out.items(): print(f"{n:24s} files {e['files']:5d} rewritten {e['files_rewritten']:4d} {e['store_sha256'][:16]}")
