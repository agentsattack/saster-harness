"""Entrypoint. Wires config -> backend -> router -> loop and runs.

Two modes:
  python -m halagent                 # real run, driven by HALAGENT_* / config file
  python -m halagent --demo [--out D] # offline demo: stub backend + stub tool

The allowlist is always loaded from a runtime path (never baked in). If it is
empty or unparseable the process halts before any step runs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from .config import BackendConfig, Config
from .loop import AgentLoop
from .platform_api import PlatformClient
from .refusal import RefusalClassifier
from .router import ModelRouter, OpenAICompatibleBackend, StubBackend
from .scope_guard import ScopeConfigError, ScopeGuard, load_allowlist
from .telemetry import TelemetryWriter, base_record, emit_scope_grant
from .tools import Dispatcher, ToolRegistry
from .tools_builtin import register_builtins, register_platform_tools
from .tools_recon import register_recon_tools


def _build_backend(cfg: Config):
    b: BackendConfig = cfg.backend
    if b.kind == "stub":
        return StubBackend(model=b.model or "stub-1", script=list(b.script))
    if b.kind == "openai_compatible":
        if not b.base_url:
            raise SystemExit("openai_compatible backend requires backend.base_url")
        return OpenAICompatibleBackend(
            base_url=b.base_url, model=b.model,
            # HalCTF's sidecar injects the real key; "not-needed" is the documented
            # placeholder so we still send an Authorization header.
            api_key=cfg.resolved_api_key() or "not-needed",
            timeout=b.timeout, chat_path=b.chat_path,
        )
    raise SystemExit(f"unknown backend kind: {b.kind}")


DEFAULT_ALLOWLIST_PATH = os.path.join(os.path.dirname(__file__), "default_allowlist.json")


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")

# Runtime-contract keys the platform injects at detonation. Logged verbatim on
# startup so a single run reveals the real wiring (endpoints, injected flags)
# instead of us inferring it from docs. These are this pod's own injected values.
_RECON_KEYS = ("OPENAI_BASE_URL", "MCP_ENDPOINT", "FLAG_1", "BONUS_FLAG")


def _emit_runtime_recon(telemetry: TelemetryWriter, cfg: Config) -> None:
    env = os.environ
    contract = {k: env.get(k) for k in _RECON_KEYS if env.get(k) is not None}
    hal_vars = {k: v for k, v in env.items() if k.startswith("HAL_")}
    telemetry.write(base_record(
        record_type="runtime_recon", run_id=cfg.run_id,
        challenge_id=cfg.challenge_id, step_index=0, plane="tool", outcome="ok",
        meta={
            "contract": contract,
            "hal_vars": hal_vars,
            "env_keys": sorted(env.keys()),
            "backend_kind": cfg.backend.kind,
            "backend_base_url": cfg.backend.base_url,
            "backend_model": cfg.backend.model,
            "platform_base_url": cfg.platform.base_url if cfg.platform else None,
        },
    ))


def build_and_run(cfg: Config, backend=None, platform_client=None) -> int:
    # Allowlist resolution. A runtime-mounted allowlist is still preferred and is
    # honored exactly as before when present. But when NO allowlist is mounted at
    # cfg.allowlist_path — e.g. a hosted sandbox that never supplied one — fall
    # back to the bundled default so the agent RUNS and emits telemetry instead of
    # fail-closing to a dead two-line run. Crucially, a mount that EXISTS but is
    # empty or malformed still halts below: that is an explicit misconfiguration,
    # not an absent policy, so the fail-closed contract is preserved for it.
    allowlist_path = cfg.allowlist_path
    allowlist_source = "base_allowlist"
    if not os.path.exists(allowlist_path):
        allowlist_path = DEFAULT_ALLOWLIST_PATH
        allowlist_source = "baked_default_allowlist"
        print(f"[halagent] no runtime allowlist at {cfg.allowlist_path!r}; "
              f"using bundled default {DEFAULT_ALLOWLIST_PATH!r}", file=sys.stderr)
    try:
        allowlist = load_allowlist(allowlist_path)
        guard = ScopeGuard(allowlist)
    except ScopeConfigError as exc:
        # Fail closed and loud. Nothing runs.
        print(f"[halagent] HALT: scope guard misconfigured: {exc}", file=sys.stderr)
        return 2

    mirror = sys.stdout if cfg.telemetry_stdout else None
    telemetry = TelemetryWriter(cfg.telemetry_path, strict=cfg.telemetry_strict, mirror=mirror)

    # Snapshot the injected runtime contract first, so even a run that later fails
    # still discloses exactly how the platform wired this pod.
    _emit_runtime_recon(telemetry, cfg)

    # Startup verification runs sandboxed with NO network — the model/MCP
    # endpoints are offline and any connection attempt fails the lint gate. When
    # HAL_DRY_RUN is set we prove identity + contract and exit cleanly WITHOUT
    # opening the network. The real run (HAL_DRY_RUN unset) runs the full loop.
    if _env_flag("HAL_DRY_RUN"):
        telemetry.write(base_record(
            record_type="run_end", run_id=cfg.run_id, challenge_id=cfg.challenge_id,
            step_index=0, plane="tool", outcome="ok",
            meta={"finished": True, "finish_reason": "dry_run_no_network",
                  "steps_taken": 0}))
        telemetry.close()
        print("[halagent] HAL_DRY_RUN set — startup verification only; "
              "not opening the network.", file=sys.stderr)
        return 0

    def grant(entries, source):
        emit_scope_grant(telemetry, run_id=cfg.run_id, challenge_id=cfg.challenge_id,
                         step_index=0, granted=list(entries), source=source,
                         effective_size=guard.effective_size())

    # Record the base authorization the agent starts with, and whether it came
    # from a runtime mount or the bundled default.
    grant(allowlist, allowlist_source)

    registry = ToolRegistry()
    register_builtins(registry)

    # Generic scope-gated recon: port_scan, http_probe, api_discover. Every
    # destination they touch is re-checked against `guard`, so default-deny holds
    # even though a single call may probe many ports/paths.
    register_recon_tools(registry, guard)

    # Platform integration: flag submission + completion signal. The platform's
    # own host is authorized as infrastructure (in code, logged) so submit_flag
    # passes the scope guard like any other action.
    client = platform_client
    if client is None and cfg.platform:
        client = PlatformClient(
            base_url=cfg.platform.base_url,
            submit_flag_path=cfg.platform.submit_flag_path,
            complete_path=cfg.platform.complete_path,
            api_key=cfg.resolved_platform_api_key(),
            timeout=cfg.platform.timeout,
            headers=cfg.platform.headers,
            flag_payload=cfg.platform.flag_payload,
            complete_payload=cfg.platform.complete_payload,
            correct_pointer=cfg.platform.correct_pointer,
        )
    if client is not None:
        register_platform_tools(registry, client, cfg.challenge_id)
        if client.host:
            grant(guard.populate([client.host], "platform_infrastructure"),
                  "platform_infrastructure")

    # Per-challenge scope: populated from challenge metadata at challenge start.
    # Tomorrow this list comes from the challenge spec; today it is config-driven.
    if cfg.challenge_targets:
        grant(guard.populate(cfg.challenge_targets, "challenge_metadata"),
              "challenge_metadata")

    router = ModelRouter(
        backend=backend or _build_backend(cfg),
        telemetry=telemetry,
        classifier=RefusalClassifier(),
        max_retries=cfg.max_retries,
        backoff_base=cfg.backoff_base,
    )
    dispatcher = Dispatcher(registry, guard, telemetry, truncate_len=cfg.truncate_len)
    loop = AgentLoop(cfg, router, dispatcher, registry, telemetry)
    try:
        state = loop.run()
    finally:
        telemetry.close()
    print(f"[halagent] done: {state.step_index} steps, "
          f"finished={state.finished} reason={state.finish_reason}", file=sys.stderr)
    print(f"[halagent] telemetry -> {cfg.telemetry_path}", file=sys.stderr)
    return 0


DEMO_SCRIPT = [
    # 0: valid action against a per-challenge ALLOWED target -> dispatched
    json.dumps({"intent": "Echo a probe at the in-scope challenge host to confirm reachability.",
                "tool": "echo", "arguments": {"message": "hello", "target": "challenge.local"},
                "target": "challenge.local"}),
    # 1: a model refusal (also unparseable) -> refused_by_model + parse_failure
    "I'm sorry, but I can't help with that request.",
    # 2: valid action against an OUT-OF-SCOPE target -> refused_by_scope
    json.dumps({"intent": "Try an out-of-scope host to verify the guard blocks it.",
                "tool": "echo", "arguments": {"message": "knock", "target": "evil.example.com"},
                "target": "evil.example.com"}),
    # 3: malformed prose, no JSON -> parse_failure
    "Let me think about this. I will probably call echo next, but here are my thoughts...",
    # 4: submit a flag -> platform confirms correctness (canned in the demo)
    json.dumps({"intent": "Submit the captured flag for platform verification.",
                "tool": "submit_flag", "arguments": {"flag": "HALCTF{demo_flag}"},
                "target": "api.halctf.local"}),
    # 5: signal completion -> dispatched, ends the run
    json.dumps({"intent": "Signal the challenge is complete.",
                "tool": "signal_complete", "arguments": {}, "target": "api.halctf.local"}),
]


class _CannedResponse:
    """Minimal urlopen stand-in so the demo exercises submit_flag offline."""
    def __init__(self, body: str):
        self._body = body.encode("utf-8")
        self.status = 200
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False


def run_demo(out_dir: str) -> int:
    os.makedirs(out_dir, exist_ok=True)
    allowlist_path = os.path.join(out_dir, "allowlist.json")
    # Base allowlist = platform infrastructure only. Challenge targets are added
    # per-challenge (below) to demonstrate default-deny + logged population.
    with open(allowlist_path, "w", encoding="utf-8") as fh:
        json.dump(["api.halctf.local"], fh)

    cfg = Config(
        run_id="demo-run",
        challenge_id="demo-echo",
        allowlist_path=allowlist_path,
        telemetry_path=os.path.join(out_dir, "trajectory.jsonl"),
        checkpoint_path=os.path.join(out_dir, "checkpoint.json"),
        max_steps=10,
        wall_clock_seconds=60.0,
        challenge_targets=["challenge.local", "*.ctf.local", "10.0.0.0/30"],
        backend=BackendConfig(kind="stub", model="stub-demo", script=DEMO_SCRIPT),
    )
    for p in (cfg.telemetry_path, cfg.checkpoint_path):
        if os.path.exists(p):
            os.remove(p)
    backend = StubBackend(model="stub-demo", script=DEMO_SCRIPT, fault_on={0: 1})
    # Offline platform client: canned "correct" response, no real network.
    demo_client = PlatformClient(
        base_url="http://api.halctf.local",
        _opener=lambda req, timeout=None: _CannedResponse('{"correct": true, "message": "accepted"}'),
    )
    rc = build_and_run(cfg, backend=backend, platform_client=demo_client)
    print(f"[halagent] demo telemetry: {cfg.telemetry_path}", file=sys.stderr)
    return rc


def main(argv: Optional[list] = None) -> int:
    # Platform startup handshake: the HalCTF verifier boots the container and
    # greps stdout for this exact line before running the agent. Printed first,
    # flushed, before any config load or network. The id is the platform's own
    # injected HAL_USER_ID (authoritative per run); HALAGENT_USER_ID overrides for
    # local testing; the literal is only a last-resort fallback.
    print("USER ID: "
          f"{os.environ.get('HALAGENT_USER_ID') or os.environ.get('HAL_USER_ID') or 'lsutoops'}",
          flush=True)

    ap = argparse.ArgumentParser(prog="halagent")
    ap.add_argument("--config", help="path to config JSON (else $HALAGENT_CONFIG)")
    ap.add_argument("--demo", action="store_true", help="run the offline stub demo")
    ap.add_argument("--out", default="_demo", help="demo output dir (with --demo)")
    args = ap.parse_args(argv)

    if args.demo:
        return run_demo(args.out)
    cfg = Config.load(args.config)
    return build_and_run(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
