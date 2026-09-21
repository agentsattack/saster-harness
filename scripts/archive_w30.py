#!/usr/bin/env python3
"""Seal a new W30 evidence snapshot and mirror it without modifying older stores."""
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
ROOT=REPO / "runs/w30_readiness"
DEST=Path("/home/lbsuto/evidence/w30-readiness")
MIRROR="/home/lbsuto/evidence/w30-readiness"


def main():
    assert (ROOT / "analysis/results.json").is_file(), "Analyze the completed experiment first"
    assert len(list((ROOT / "support").glob("*/result.json"))) == 220
    assert len(list((ROOT / "full5").glob("*.status.json"))) == 8
    assert (ROOT / "full5_controls_v2/summary.json").is_file()
    assert not DEST.exists(), "Never overwrite an existing evidence store"
    subprocess.run(["ssh","spark8",f"test ! -e {MIRROR}"],check=True)
    shutil.copytree(ROOT,DEST)
    supplemental=DEST / "deliverables"
    supplemental.mkdir()
    paths=[*REPO.glob("scripts/*w30*.py"), *REPO.glob("docs/w30-*.md"),
           REPO / "docs/w30-followup-results.md", REPO / "docs/grrcon-readiness-review-2026-09-06.md",
           REPO / "tests/test_followup_w30.py"]
    for p in paths:
        target=supplemental / p.relative_to(REPO)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,target)
    files={str(p.relative_to(DEST)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(DEST.rglob("*")) if p.is_file()}
    old=Path("/home/lbsuto/evidence/MANIFEST.json")
    manifest={"created_utc":datetime.now(timezone.utc).isoformat(),"files":files,"file_count":len(files),
              "file_map_sha256":hashlib.sha256(json.dumps(files,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
              "prior_manifest_sha256":hashlib.sha256(old.read_bytes()).hexdigest(),
              "prior_manifest_unchanged":True,"human_comparison":"recorded" if (ROOT / "callback/human_result.json").exists() else "pending; no human decision fabricated"}
    (DEST / "MANIFEST.json").open("x").write(json.dumps(manifest,indent=2)+"\n")
    checksums=dict(files)
    checksums["MANIFEST.json"]=hashlib.sha256((DEST / "MANIFEST.json").read_bytes()).hexdigest()
    (DEST / "SHA256SUMS").open("x").write("".join(f"{h}  {p}\n" for p,h in sorted(checksums.items())))
    local=subprocess.run(["sha256sum","--quiet","-c","SHA256SUMS"],cwd=DEST,capture_output=True,text=True,check=True)
    subprocess.run(["ssh","spark8",f"mkdir {MIRROR}"],check=True)
    subprocess.run(["rsync","-a",str(DEST)+"/",f"spark8:{MIRROR}/"],check=True)
    remote=subprocess.run(["ssh","spark8",f"cd {MIRROR} && sha256sum --quiet -c SHA256SUMS && sha256sum MANIFEST.json SHA256SUMS"],capture_output=True,text=True,check=True)
    proof={"local":str(DEST),"mirror":"spark8:"+MIRROR,"files_verified":len(checksums),
           "manifest_sha256":checksums["MANIFEST.json"],"local_check":local.stdout,"remote_check":remote.stdout,
           "verified_utc":datetime.now(timezone.utc).isoformat()}
    (ROOT / "archive_verification.json").open("x").write(json.dumps(proof,indent=2)+"\n")
    print(json.dumps(proof,indent=2))


if __name__ == "__main__":
    main()
