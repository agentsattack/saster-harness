"""Runtime configuration: a config file overlaid with environment variables.

The allowlist is intentionally NOT part of this object — it is loaded separately
from a runtime-mounted path (see scope_guard.load_allowlist) so it is never
baked into the image. Config only carries the *path* to it.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional


def _as_bool(env_val: Optional[str], default: bool) -> bool:
    if env_val is None:
        return bool(default)
    return env_val.strip().lower() in ("1", "true", "yes", "on")


def _hal_targets(env: dict) -> list:
    """Network targets from HalCTF's injected HAL_TARGET_* env, for the scope
    guard. Port 0 / missing IP (dry-run placeholders) contribute nothing."""
    ip = (env.get("HAL_TARGET_IP") or "").strip()
    return [ip] if ip else []


def _hal_briefing(env: dict) -> Optional[str]:
    """Compose a per-challenge briefing from HalCTF's HAL_* env so the agent's
    first turn knows the task, target, and submission id instead of "unknown"."""
    name = (env.get("HAL_CHALLENGE_NAME") or "").strip()
    cat = (env.get("HAL_CHALLENGE_CATEGORY") or "").strip()
    desc = (env.get("HAL_CHALLENGE_DESCRIPTION") or "").strip()
    cid = (env.get("HAL_CHALLENGE_ID") or "").strip()
    ip = (env.get("HAL_TARGET_IP") or "").strip()
    port = (env.get("HAL_TARGET_PORT") or "").strip()
    parts = []
    if name:
        parts.append(f"Challenge: {name}" + (f" [{cat}]" if cat else ""))
    if desc:
        parts.append(f"Description: {desc}")
    if ip and port and port not in ("", "0"):
        parts.append(f"Target: {ip}:{port}")
    elif ip:
        parts.append(f"Target host: {ip}")
    if cid:
        parts.append(f"When you find the flag, submit it with the submit_flag "
                     f"tool for challenge_id {cid!r}.")
    return "\n".join(parts) if parts else None


@dataclass
class BackendConfig:
    kind: str = "stub"                 # "stub" | "openai_compatible"
    base_url: Optional[str] = None
    model: str = "stub-1"
    api_key_env: Optional[str] = None  # name of env var holding the key
    timeout: float = 60.0
    script: list[str] = field(default_factory=list)   # stub only
    chat_path: str = "/v1/chat/completions"           # openai_compatible only


@dataclass
class PlatformConfig:
    """Flag-submission / completion endpoints. Everything is parameterized so
    the exact HalCTF wire contract is a config edit, not a code change."""
    base_url: str
    submit_flag_path: str = "/api/v1/flags"
    complete_path: str = "/api/v1/complete"
    api_key_env: Optional[str] = None
    timeout: float = 30.0
    headers: dict = field(default_factory=dict)
    flag_payload: dict = field(default_factory=lambda: {"challenge_id": "{challenge_id}", "flag": "{flag}"})
    complete_payload: dict = field(default_factory=lambda: {"challenge_id": "{challenge_id}"})
    correct_pointer: str = "correct"


@dataclass
class Config:
    run_id: str
    challenge_id: str
    allowlist_path: str
    telemetry_path: str = "/data/trajectory.jsonl"
    checkpoint_path: str = "/data/checkpoint.json"
    max_steps: int = 25
    wall_clock_seconds: float = 900.0
    # Hard token ceiling for the run (0 = unlimited). Halts cleanly with a
    # budget_exhausted record rather than dying mid-run when a shared Model
    # Service quota is in play. Per-run; the per-team quota is operational.
    token_budget: int = 0
    # Mirror every telemetry record to stdout as pure JSONL — a fallback egress
    # sink for when the mounted volume belongs to the platform.
    telemetry_stdout: bool = True
    # Strict telemetry validation. True (dev/demo default) surfaces scaffolding
    # bugs by halting on a schema-invalid record. In a hosted submission the log
    # IS the deliverable, so the image ships HALAGENT_STRICT=0: a bad record is
    # wrapped into an error record and the run continues rather than truncating
    # the trajectory. See TelemetryWriter(strict=...).
    telemetry_strict: bool = True
    truncate_len: int = 4096
    max_retries: int = 2
    backoff_base: float = 0.5
    # Per-challenge targets to authorize at challenge start (from challenge
    # metadata onsite). Populated into the scope guard and logged as scope_grant.
    challenge_targets: list = field(default_factory=list)
    model_params: dict = field(default_factory=lambda: {"temperature": 0.0, "max_tokens": 512})
    backend: BackendConfig = field(default_factory=BackendConfig)
    platform: Optional[PlatformConfig] = None
    system_prompt: Optional[str] = None
    # Per-challenge briefing injected into the agent's first turn (from HAL_* env
    # in a HalCTF pod). Without it the agent reasons blind about "unknown".
    challenge_description: Optional[str] = None

    @staticmethod
    def load(path: Optional[str] = None, env: Optional[dict] = None) -> "Config":
        env = dict(os.environ if env is None else env)
        path = path or env.get("HALAGENT_CONFIG")
        data: dict[str, Any] = {}
        if path:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)

        backend_data = data.get("backend", {}) or {}
        openai_base = env.get("OPENAI_BASE_URL")
        explicit_backend = env.get("HALAGENT_BACKEND") or backend_data.get("kind")
        if explicit_backend is None and openai_base:
            # HalCTF runtime: the sidecar injects an OpenAI-compatible endpoint as
            # OPENAI_BASE_URL and the API key ("not-needed" — sidecar supplies it).
            # OpenAI-SDK semantics append "/chat/completions" to that base_url.
            backend = BackendConfig(
                kind="openai_compatible",
                base_url=openai_base,
                model=env.get("HALAGENT_MODEL", backend_data.get("model", "llama-3.1-8b")),
                timeout=float(backend_data.get("timeout", 60.0)),
                chat_path=backend_data.get("chat_path", "/chat/completions"),
            )
        else:
            backend = BackendConfig(
                kind=env.get("HALAGENT_BACKEND", backend_data.get("kind", "stub")),
                base_url=env.get("HALAGENT_BASE_URL", backend_data.get("base_url")),
                model=env.get("HALAGENT_MODEL", backend_data.get("model", "stub-1")),
                api_key_env=backend_data.get("api_key_env"),
                timeout=float(backend_data.get("timeout", 60.0)),
                script=backend_data.get("script", []),
                chat_path=backend_data.get("chat_path", "/v1/chat/completions"),
            )

        platform = None
        pdata = data.get("platform")
        if pdata:
            platform = PlatformConfig(
                base_url=env.get("HALAGENT_PLATFORM_URL", pdata["base_url"]),
                submit_flag_path=pdata.get("submit_flag_path", "/api/v1/flags"),
                complete_path=pdata.get("complete_path", "/api/v1/complete"),
                api_key_env=pdata.get("api_key_env"),
                timeout=float(pdata.get("timeout", 30.0)),
                headers=pdata.get("headers", {}),
                flag_payload=pdata.get("flag_payload", {"challenge_id": "{challenge_id}", "flag": "{flag}"}),
                complete_payload=pdata.get("complete_payload", {"challenge_id": "{challenge_id}"}),
                correct_pointer=pdata.get("correct_pointer", "correct"),
            )
        elif env.get("OPENAI_BASE_URL") or env.get("MCP_ENDPOINT"):
            # HalCTF in-pod with no config file: the sidecar exposes flag
            # submission at 127.0.0.1:9000/submit and graceful-done at /done.
            # Default the platform client to those so submit_flag / signal_complete
            # exist and hit the real endpoints. Override with HALAGENT_PLATFORM_URL.
            platform = PlatformConfig(
                base_url=env.get("HALAGENT_PLATFORM_URL", "http://127.0.0.1:9000"),
                submit_flag_path="/submit",
                complete_path="/done",
                flag_payload={"challenge_id": "{challenge_id}", "flag": "{flag}"},
                complete_payload={},
                correct_pointer="correct",
            )

        cfg = Config(
            run_id=env.get("HALAGENT_RUN_ID") or env.get("HAL_RUN_ID") or data.get("run_id", "run-local"),
            challenge_id=(env.get("HALAGENT_CHALLENGE_ID") or env.get("HAL_CHALLENGE_ID")
                          or data.get("challenge_id", "unknown")),
            allowlist_path=env.get("HALAGENT_ALLOWLIST", data.get("allowlist_path", "/config/allowlist.json")),
            telemetry_path=env.get("HALAGENT_TELEMETRY", data.get("telemetry_path", "/data/trajectory.jsonl")),
            checkpoint_path=env.get("HALAGENT_CHECKPOINT", data.get("checkpoint_path", "/data/checkpoint.json")),
            max_steps=int(env.get("HALAGENT_MAX_STEPS", data.get("max_steps", 25))),
            wall_clock_seconds=float(env.get("HALAGENT_WALL_CLOCK", data.get("wall_clock_seconds", 900.0))),
            token_budget=int(env.get("HALAGENT_TOKEN_BUDGET", data.get("token_budget", 0))),
            telemetry_stdout=_as_bool(env.get("HALAGENT_STDOUT"), data.get("telemetry_stdout", True)),
            telemetry_strict=_as_bool(env.get("HALAGENT_STRICT"), data.get("telemetry_strict", True)),
            truncate_len=int(env.get("HALAGENT_TRUNCATE", data.get("truncate_len", 4096))),
            max_retries=int(env.get("HALAGENT_MAX_RETRIES", data.get("max_retries", 2))),
            backoff_base=float(data.get("backoff_base", 0.5)),
            challenge_targets=data.get("challenge_targets") or _hal_targets(env),
            model_params=data.get("model_params", {"temperature": 0.0, "max_tokens": 512}),
            backend=backend,
            platform=platform,
            system_prompt=data.get("system_prompt"),
            challenge_description=data.get("challenge_description") or _hal_briefing(env),
        )
        return cfg

    def resolved_api_key(self, env: Optional[dict] = None) -> Optional[str]:
        env = dict(os.environ if env is None else env)
        if self.backend.api_key_env:
            return env.get(self.backend.api_key_env)
        return None

    def resolved_platform_api_key(self, env: Optional[dict] = None) -> Optional[str]:
        env = dict(os.environ if env is None else env)
        if self.platform and self.platform.api_key_env:
            return env.get(self.platform.api_key_env)
        return None
