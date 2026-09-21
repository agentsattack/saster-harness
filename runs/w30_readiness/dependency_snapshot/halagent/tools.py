"""Tool registry and the dispatch path.

The dispatcher is where the scope guard lives: every resolved action passes
through scope_guard.check(target) after tool/argument resolution and before the
tool handler is ever invoked. A refusal short-circuits to a `refused_by_scope`
step record and the handler is never called.

Tools register a name, a JSON-ish parameter schema, and a handler. A tool may
declare `target_from(arguments) -> str|None` to tell the guard which network
destination the call will reach. Network tools MUST return a concrete target;
returning None marks a purely-local action.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .scope_guard import ScopeDecision, ScopeGuard
from .telemetry import TelemetryWriter, base_record, observation_record

Handler = Callable[[dict], Any]
TargetFrom = Callable[[dict], Optional[str]]

# Distinguished tool names the loop treats as "we are done" once dispatched.
FINISH_TOOL = "finish"                 # local sentinel (no network)
COMPLETE_TOOL = "signal_complete"      # platform completion signal (network)
RUN_ENDING_TOOLS = {FINISH_TOOL, COMPLETE_TOOL}


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict          # {arg_name: {"type": "string"|"number"|..., "required": bool}}
    handler: Handler
    target_from: Optional[TargetFrom] = None

    def resolve_target(self, arguments: dict, explicit: Optional[str]) -> Optional[str]:
        if explicit is not None:
            return explicit
        if self.target_from is not None:
            return self.target_from(arguments)
        return None

    def validate_args(self, arguments: dict) -> list[str]:
        errors: list[str] = []
        for arg, spec in self.parameters.items():
            required = spec.get("required", False)
            if arg not in arguments:
                if required:
                    errors.append(f"missing required argument '{arg}'")
                continue
            want = spec.get("type")
            val = arguments[arg]
            if want and not _type_ok(val, want):
                errors.append(f"argument '{arg}' should be {want}")
        return errors


def _type_ok(val: Any, want: str) -> bool:
    return {
        "string": lambda v: isinstance(v, str),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
    }.get(want, lambda v: True)(val)


@dataclass
class ToolRegistry:
    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict]:
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self._tools.values()
        ]


@dataclass
class DispatchResult:
    outcome: str                 # dispatched | refused_by_scope | error
    observation: str             # text fed back to the model
    finished: bool = False
    record: Optional[dict] = None


class Dispatcher:
    def __init__(
        self,
        registry: ToolRegistry,
        scope_guard: ScopeGuard,
        telemetry: TelemetryWriter,
        truncate_len: int = 4096,
    ):
        self.registry = registry
        self.scope_guard = scope_guard
        self.telemetry = telemetry
        self.truncate_len = truncate_len

    def dispatch(
        self,
        *,
        run_id: str,
        challenge_id: str,
        step_index: int,
        declared_intent: str,
        tool_name: str,
        arguments: dict,
        target: Optional[str],
    ) -> DispatchResult:
        action = {"tool": tool_name, "arguments": arguments, "target": target}

        def emit(outcome: str, observation: Optional[dict], **kw) -> dict:
            rec = base_record(
                record_type="step",
                run_id=run_id,
                challenge_id=challenge_id,
                step_index=step_index,
                plane="tool",
                outcome=outcome,
                declared_intent=declared_intent,
                action=action,
                observation=observation,
                **kw,
            )
            return self.telemetry.write(rec)

        tool = self.registry.get(tool_name)
        if tool is None:
            obs = observation_record(f"unknown tool: {tool_name}", self.truncate_len)
            rec = emit("error", obs, error={"type": "unknown_tool", "message": tool_name})
            return DispatchResult("error", obs["content"], record=rec)

        arg_errors = tool.validate_args(arguments)
        if arg_errors:
            msg = "; ".join(arg_errors)
            obs = observation_record(f"invalid arguments: {msg}", self.truncate_len)
            rec = emit("error", obs, error={"type": "invalid_arguments", "message": msg})
            return DispatchResult("error", obs["content"], record=rec)

        resolved_target = tool.resolve_target(arguments, target)
        action["target"] = resolved_target

        # ---- SCOPE ENFORCEMENT POINT -------------------------------------
        decision: ScopeDecision = self.scope_guard.check(resolved_target)
        if not decision.allowed:
            obs = observation_record(
                f"refused by scope guard ({decision.reason}): target {resolved_target!r} "
                f"is not in the allowlist",
                self.truncate_len,
            )
            rec = emit(
                "refused_by_scope",
                obs,
                meta={"scope_reason": decision.reason, "target": resolved_target},
            )
            return DispatchResult("refused_by_scope", obs["content"], record=rec)
        # ------------------------------------------------------------------

        try:
            result = tool.handler(arguments)
        except Exception as exc:  # handler faults are data, not crashes
            obs = observation_record(f"{type(exc).__name__}: {exc}", self.truncate_len)
            rec = emit("error", obs, error={"type": type(exc).__name__, "message": str(exc)})
            return DispatchResult("error", obs["content"], record=rec)

        finished = tool_name in RUN_ENDING_TOOLS
        obs = observation_record(result, self.truncate_len)
        rec = emit("dispatched", obs, meta={"scope_reason": decision.reason,
                                            "scope_matched": decision.matched,
                                            "run_ending": finished})
        return DispatchResult("dispatched", obs["content"], finished=finished, record=rec)
