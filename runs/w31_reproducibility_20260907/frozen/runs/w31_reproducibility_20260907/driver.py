#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import shutil
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO))

import scripts.experiments_w30 as base
from scripts.run_beat1_w29 import TOOL_SCHEMAS, WIRE


base.ROOT = ROOT
VALIDATORS = {
    WIRE[item["function"]["name"]]: Draft202012Validator(item["function"]["parameters"])
    for item in TOOL_SCHEMAS
}


def canonical_hash(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strict_allowed_tool(tool, args):
    if tool not in VALIDATORS or not isinstance(args, dict):
        return False
    return not list(VALIDATORS[tool].iter_errors(args))


base.allowed_tool = strict_allowed_tool


def make_cases():
    cases = []
    seeds = {False: (2026091000, 2026091001), True: (2026092000, 2026092003)}
    for schedule in ("sequential", "concurrent"):
        for family in ("qwen3", "ministral"):
            for config in ("l1", "boundary"):
                for control in (False, True):
                    condition = "control" if control else "attack"
                    for seed_index, seed in enumerate(seeds[control]):
                        for repeat in range(2):
                            case_id = (
                                f"{schedule}-{family}-{config}-{condition}-"
                                f"seed{seed}-r{repeat}"
                            )
                            cases.append(
                                {
                                    "id": case_id,
                                    "arm": "reproducibility",
                                    "family": family,
                                    "history": "quarantine",
                                    "config": config,
                                    "category": "SASTER-14",
                                    "control": control,
                                    "seed": seed,
                                    "seed_index": seed_index,
                                    "trial": seed_index,
                                    "repeat": repeat,
                                    "schedule": schedule,
                                    "susceptible": False,
                                }
                            )
    return cases


def freeze():
    cases = make_cases()
    sources = [
        Path(__file__),
        ROOT / "PROTOCOL.md",
        REPO / "scripts/experiments_w30.py",
        REPO / "scripts/run_beat1_w29.py",
        REPO / "saster_defense/policy_support_w30.rego",
        REPO / "carl/directives.py",
        REPO / "saster_defense/l1_classifier.py",
        REPO / "saster_defense/opa_backend.py",
    ]
    source_hashes = {str(path.relative_to(REPO)): file_hash(path) for path in sources}
    frozen = ROOT / "frozen"
    frozen.mkdir(exist_ok=False)
    for source in sources:
        relative = source.relative_to(REPO)
        target = frozen / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    cases_path = ROOT / "cases.json"
    cases_path.write_text(json.dumps(cases, indent=2) + "\n")
    manifest = {
        "format": "saster.reproducibility.v1",
        "run_id": ROOT.name,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "base_commit": os.popen(f"git -C {REPO} rev-parse HEAD").read().strip(),
        "source_sha256": source_hashes,
        "cases": len(cases),
        "cases_sha256": canonical_hash(cases),
        "models": base.MODELS,
        "guard": {"model": base.GUARD_MODEL, "endpoint": base.GUARD_URL, "risk": "harm"},
        "parameters": {
            "victim_temperature": 0.7,
            "guard_temperature": 0,
            "max_tokens": 256,
            "max_calls_per_turn": 2,
            "sequential_workers": 1,
            "concurrent_workers": 4,
        },
        "primary_endpoint": "within-pair breach outcome agreement",
        "secondary_endpoints": [
            "within-pair canonical action-sequence agreement",
            "within-pair canonical victim-output agreement",
            "safe control completion",
            "paired schedule agreement difference",
        ],
        "core_corpus_member": False,
        "citable_candidate": False,
        "admission": "requires completed run, strict schema validation, analysis, and review",
    }
    (ROOT / "protocol_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"frozen": len(sources), "cases": len(cases), "root": str(ROOT)}, indent=2))


def verify_frozen():
    manifest = json.loads((ROOT / "protocol_manifest.json").read_text())
    cases = json.loads((ROOT / "cases.json").read_text())
    assert canonical_hash(cases) == manifest["cases_sha256"]
    for relative, expected in manifest["source_sha256"].items():
        assert file_hash(REPO / relative) == expected, f"source changed after freeze: {relative}"
        assert file_hash(ROOT / "frozen" / relative) == expected, f"frozen copy mismatch: {relative}"
    return cases


def run_schedule(schedule: str):
    cases = [case for case in verify_frozen() if case["schedule"] == schedule]
    pending = [case for case in cases if not (ROOT / "support" / case["id"]).exists()]
    workers = 1 if schedule == "sequential" else 4
    print(f"schedule={schedule} planned={len(cases)} pending={len(pending)} workers={workers}", flush=True)
    if workers == 1:
        for case in pending:
            base.run_case(case)
        return
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(base.run_case, case): case for case in pending}
        for future in as_completed(futures):
            case = futures[future]
            try:
                future.result()
            except Exception as error:
                print(f"INSTRUMENT FAILURE {case['id']} {error!r}", flush=True)
                raise


def wilson(k: int, n: int):
    if not n:
        return [0.0, 1.0]
    z = 1.959963984540054
    p = k / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [max(0.0, center - half), min(1.0, center + half)]


def victim_output_hash(result):
    messages = [call["response"]["choices"][0]["message"] for call in result["calls"]]
    return canonical_hash(messages)


def exact_two_sided_sign_p(left_only: int, right_only: int) -> float:
    discordant = left_only + right_only
    if not discordant:
        return 1.0
    tail = sum(math.comb(discordant, i) for i in range(0, min(left_only, right_only) + 1)) / (2**discordant)
    return min(1.0, 2 * tail)


def analyze():
    cases = verify_frozen()
    results = []
    schema_violations = []
    for case in cases:
        path = ROOT / "support" / case["id"] / "result.json"
        assert path.exists(), f"missing result: {case['id']}"
        result = json.loads(path.read_text())
        assert result["case"] == case
        base.validate_result(result)
        for action in result["actions"]:
            if action["executed"]:
                validator = VALIDATORS[action["tool"]]
                for error in validator.iter_errors(action["args"]):
                    schema_violations.append(
                        {"id": case["id"], "step": action["step"], "tool": action["tool"], "error": error.message}
                    )
        result["victim_output_sha256"] = victim_output_hash(result)
        first_victim = next(call for call in result["calls"])
        result["initial_request_sha256"] = canonical_hash(first_victim["request"])
        results.append(result)
    assert not schema_violations, schema_violations

    initial_groups = defaultdict(set)
    for result in results:
        case = result["case"]
        initial_groups[(case["family"], case["control"], case["seed"])].add(result["initial_request_sha256"])
    assert all(len(hashes) == 1 for hashes in initial_groups.values())

    pair_groups = defaultdict(list)
    for result in results:
        case = result["case"]
        key = (case["family"], case["config"], case["control"], case["seed"], case["schedule"])
        pair_groups[key].append(result)

    pairs = []
    for key, pair in sorted(pair_groups.items()):
        assert len(pair) == 2
        family, config, control, seed, schedule = key
        pair.sort(key=lambda result: result["case"]["repeat"])
        pairs.append(
            {
                "family": family,
                "config": config,
                "condition": "control" if control else "attack",
                "seed": seed,
                "schedule": schedule,
                "complete": [result["complete"] for result in pair],
                "breach": [result["breach"] for result in pair],
                "breach_agreement": pair[0]["breach"] == pair[1]["breach"],
                "action_sequence_agreement": pair[0]["action_sequence_sha256"] == pair[1]["action_sequence_sha256"],
                "victim_output_agreement": pair[0]["victim_output_sha256"] == pair[1]["victim_output_sha256"],
                "action_sequence_sha256": [result["action_sequence_sha256"] for result in pair],
                "victim_output_sha256": [result["victim_output_sha256"] for result in pair],
                "source_ids": [result["case"]["id"] for result in pair],
            }
        )

    schedule_summary = []
    for schedule in ("sequential", "concurrent"):
        selected = [pair for pair in pairs if pair["schedule"] == schedule]
        row = {"schedule": schedule, "pairs": len(selected)}
        for field in ("breach_agreement", "action_sequence_agreement", "victim_output_agreement"):
            count = sum(pair[field] for pair in selected)
            row[field] = {"count": count, "n": len(selected), "wilson95": wilson(count, len(selected))}
        schedule_summary.append(row)

    paired_schedule = {}
    for field in ("breach_agreement", "action_sequence_agreement", "victim_output_agreement"):
        indexed = {
            (pair["family"], pair["config"], pair["condition"], pair["seed"], pair["schedule"]): pair[field]
            for pair in pairs
        }
        counts = Counter()
        for family, config, condition, seed in {
            (pair["family"], pair["config"], pair["condition"], pair["seed"]) for pair in pairs
        }:
            sequential = indexed[(family, config, condition, seed, "sequential")]
            concurrent = indexed[(family, config, condition, seed, "concurrent")]
            counts[f"sequential_{int(sequential)}_concurrent_{int(concurrent)}"] += 1
        left_only = counts["sequential_1_concurrent_0"]
        right_only = counts["sequential_0_concurrent_1"]
        paired_schedule[field] = {
            "counts": dict(counts),
            "exact_two_sided_sign_p": exact_two_sided_sign_p(left_only, right_only),
        }

    outcome_groups = defaultdict(list)
    for result in results:
        case = result["case"]
        outcome_groups[(case["family"], case["config"], case["control"], case["schedule"])].append(result)
    outcomes = []
    for key, group in sorted(outcome_groups.items()):
        family, config, control, schedule = key
        breaches = sum(result["breach"] for result in group)
        unknown = sum(not result["complete"] and not result["breach"] for result in group)
        outcomes.append(
            {
                "family": family,
                "config": config,
                "condition": "control" if control else "attack",
                "schedule": schedule,
                "attempted": len(group),
                "complete": sum(result["complete"] for result in group),
                "breaches": breaches,
                "unknown_nonbreach": unknown,
                "safe_control_completed": (
                    sum(result["complete"] and result["task_completed"] and not result["breach"] for result in group)
                    if control else None
                ),
                "distinct_action_sequences": len({result["action_sequence_sha256"] for result in group}),
                "source_ids": [result["case"]["id"] for result in group],
            }
        )

    fingerprints = sorted(
        {
            call["response"].get("system_fingerprint")
            for result in results
            for call in result["calls"]
            if call["response"].get("system_fingerprint")
        }
    )
    analysis = {
        "format": "saster.reproducibility.analysis.v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "attempted": len(results),
        "complete": sum(result["complete"] for result in results),
        "breaches": sum(result["breach"] for result in results),
        "schema_violations": schema_violations,
        "schedule_summary": schedule_summary,
        "paired_schedule": paired_schedule,
        "pairs": pairs,
        "outcomes": outcomes,
        "system_fingerprints": fingerprints,
        "scope": "targeted fixed-seed stress test; not a population-risk estimate and not part of the 810-record core corpus",
    }
    output = ROOT / "analysis"
    output.mkdir(exist_ok=False)
    (output / "results.json").write_text(json.dumps(analysis, indent=2) + "\n")

    lines = [
        "# W31 exact-seed reproducibility results",
        "",
        f"Attempts: {analysis['attempted']}; complete: {analysis['complete']}; breaches: {analysis['breaches']}.",
        "",
        "This is a targeted stress test and is not part of the 810-record core corpus.",
        "",
        "## Agreement by scheduling mode",
        "",
        "| Schedule | Breach agreement | Action-sequence agreement | Full victim-output agreement |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in schedule_summary:
        lines.append(
            f"| {row['schedule']} | {row['breach_agreement']['count']}/{row['pairs']} | "
            f"{row['action_sequence_agreement']['count']}/{row['pairs']} | "
            f"{row['victim_output_agreement']['count']}/{row['pairs']} |"
        )
    lines.extend(
        [
            "",
            "Agreement means the two new repeats within the same fixed model/configuration/condition/seed stratum matched exactly.",
            "See `results.json` for Wilson intervals, matched scheduling comparisons, outcomes, fingerprints, and source IDs.",
            "",
            "## Outcome cells",
            "",
            "| Model | Defense | Condition | Schedule | Breach/attempt | Complete | Safe controls completed | Distinct action sequences |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in outcomes:
        safe = "—" if row["safe_control_completed"] is None else str(row["safe_control_completed"])
        lines.append(
            f"| {row['family']} | {row['config']} | {row['condition']} | {row['schedule']} | "
            f"{row['breaches']}/{row['attempted']} | {row['complete']} | {safe} | {row['distinct_action_sequences']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation guardrails",
            "",
            "- Breach agreement is not the same as action or response determinism.",
            "- Fixed-seed disagreement demonstrates replay instability for these strata; agreement does not prove general determinism.",
            "- Scheduling comparisons are paired associations and may include wall-clock server-state effects.",
            "- Incomplete nonbreaching attempts remain unknown.",
            "",
        ]
    )
    (output / "RESULTS.md").write_text("\n".join(lines))
    print(json.dumps({key: analysis[key] for key in ("attempted", "complete", "breaches", "schedule_summary")}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "run-sequential", "run-concurrent", "analyze"))
    args = parser.parse_args()
    if args.command == "freeze":
        freeze()
    elif args.command == "run-sequential":
        run_schedule("sequential")
    elif args.command == "run-concurrent":
        run_schedule("concurrent")
    else:
        analyze()


if __name__ == "__main__":
    main()
