"""Built-in tools that ship with the scaffold.

These are intentionally inert — an `echo` stub for demos/tests and the `finish`
sentinel. Challenge-specific tools are added tomorrow via register_tools(); see
README "Where challenge tools plug in". No offensive primitives live here.
"""
from __future__ import annotations

import os
import re
from typing import Optional

from .platform_api import PlatformClient
from .tools import COMPLETE_TOOL, FINISH_TOOL, Tool, ToolRegistry

# read_env is deliberately narrow: it exposes ONLY flag-bearing keys, never
# arbitrary environment (which holds endpoints and other identity). HalCTF
# guarantees a bonus flag in the agent's own env as FLAG_1 / BONUS_FLAG.
_ENV_ALLOW = re.compile(r"^(FLAG(_[A-Za-z0-9]+)?|BONUS_FLAG)$")


def _echo_handler(args: dict) -> dict:
    return {"echoed": args.get("message", ""), "target": args.get("target")}


def _read_env_handler(args: dict) -> dict:
    key = str(args.get("name", ""))
    if not _ENV_ALLOW.match(key):
        return {"error": "key not permitted",
                "permitted": "FLAG, FLAG_<n> (e.g. FLAG_1), or BONUS_FLAG only"}
    val = os.environ.get(key)
    return {"name": key, "present": val is not None, "value": val}


def make_read_env_tool() -> Tool:
    """Read a flag-bearing env var from the agent's own pod. Local action (no
    network target), scoped to FLAG*/BONUS_FLAG so it can never dump secrets."""
    return Tool(
        name="read_env",
        description=("Read a challenge flag from this agent's own environment. "
                     "Permitted keys: FLAG, FLAG_<n> (e.g. FLAG_1), or BONUS_FLAG. "
                     "HalCTF injects a guaranteed bonus flag there — read it, then "
                     "submit it with submit_flag."),
        parameters={"name": {"type": "string", "required": True}},
        handler=_read_env_handler,
        target_from=lambda a: None,   # local action, no network target
    )


def _echo_target(args: dict) -> Optional[str]:
    return args.get("target")


def _finish_handler(args: dict) -> dict:
    return {"final_answer": args.get("answer", "")}


def make_echo_tool() -> Tool:
    return Tool(
        name="echo",
        description="Echo a message back. Demo/stub tool; `target` exercises the scope guard.",
        parameters={
            "message": {"type": "string", "required": True},
            "target": {"type": "string", "required": False},
        },
        handler=_echo_handler,
        target_from=_echo_target,
    )


def make_finish_tool() -> Tool:
    return Tool(
        name=FINISH_TOOL,
        description="Declare the final answer and end the run.",
        parameters={"answer": {"type": "string", "required": True}},
        handler=_finish_handler,
        target_from=lambda args: None,   # local action, no network target
    )


def make_submit_flag_tool(client: PlatformClient, default_challenge_id: str) -> Tool:
    """Submit a flag to the platform. Routed through the scope guard (its target
    is the platform host) and logged like any other action. The platform's
    response — including whether the flag is correct — becomes the observation."""
    def handler(args: dict) -> dict:
        cid = args.get("challenge_id") or default_challenge_id
        return client.submit_flag(cid, args["flag"])

    return Tool(
        name="submit_flag",
        description="Submit a candidate flag to the platform for verification.",
        parameters={
            "flag": {"type": "string", "required": True},
            "challenge_id": {"type": "string", "required": False},
        },
        handler=handler,
        target_from=lambda a: client.host,
    )


def make_signal_complete_tool(client: PlatformClient, default_challenge_id: str) -> Tool:
    """Signal challenge completion to the platform and end the run."""
    def handler(args: dict) -> dict:
        cid = args.get("challenge_id") or default_challenge_id
        return client.signal_complete(cid)

    return Tool(
        name=COMPLETE_TOOL,
        description="Signal that the challenge is complete; ends the run.",
        parameters={"challenge_id": {"type": "string", "required": False}},
        handler=handler,
        target_from=lambda a: client.host,
    )


def register_builtins(registry: ToolRegistry) -> None:
    registry.register(make_echo_tool())
    registry.register(make_finish_tool())
    registry.register(make_read_env_tool())


def register_platform_tools(registry: ToolRegistry, client: PlatformClient,
                            default_challenge_id: str) -> None:
    registry.register(make_submit_flag_tool(client, default_challenge_id))
    registry.register(make_signal_complete_tool(client, default_challenge_id))
