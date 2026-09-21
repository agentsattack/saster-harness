"""Model router — a narrow, swappable abstraction over inference backends.

This is shared infrastructure meant to outlive the CTF, so the surface is
deliberately small: a Backend implements `generate(messages, params)` and returns
a ModelResponse. The Router adds retries-with-backoff (every attempt logged as
its own model-plane record) and refusal classification per call.

Two backends ship here:
  * OpenAICompatibleBackend — stdlib urllib POST to /v1/chat/completions. Works
    for local inference servers (vLLM on the Sparks) and hosted APIs alike.
  * StubBackend — deterministic scripted responses. Exercises the interface,
    enables a fully-offline laptop demo, and can be told to fault to drive the
    retry path.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .refusal import RefusalClassifier, RefusalResult
from .telemetry import TelemetryWriter, base_record

Message = dict  # {"role": "system"|"user"|"assistant", "content": str}


class TransportError(RuntimeError):
    """A retryable backend/transport failure (network, 5xx, timeout)."""


class RateLimitError(TransportError):
    """HTTP 429 from a shared Model Service. Retryable, honoring Retry-After."""
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class NonRetryableError(RuntimeError):
    """A 4xx (other than 429) — retrying won't help; record and move on."""


@dataclass
class ModelResponse:
    text: str
    backend: str
    model: str
    params: dict
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    latency_ms: Optional[float] = None
    raw: Any = None

    def model_field(self) -> dict:
        return {
            "backend": self.backend,
            "name": self.model,
            "params": self.params,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
        }


class Backend:
    name: str = "base"

    def generate(self, messages: list[Message], params: dict) -> ModelResponse:
        raise NotImplementedError


def _approx_tokens(text: str) -> int:
    # Cheap, backend-agnostic estimate when a server omits usage.
    return max(1, len(text) // 4)


@dataclass
class StubBackend(Backend):
    """Deterministic backend. `script` is a list of assistant strings; once
    exhausted it repeats the last entry. Steps listed in `fault_on` raise a
    TransportError the given number of times to exercise retries."""

    name: str = "stub"
    model: str = "stub-1"
    script: list[str] = field(default_factory=list)
    fault_on: dict[int, int] = field(default_factory=dict)  # call_index -> times to fault
    _calls: int = 0

    def generate(self, messages: list[Message], params: dict) -> ModelResponse:
        idx = self._calls
        if self.fault_on.get(idx, 0) > 0:
            self.fault_on[idx] -= 1
            raise TransportError(f"stub induced transport fault at call {idx}")
        self._calls += 1
        text = self.script[idx] if idx < len(self.script) else (self.script[-1] if self.script else "{}")
        prompt = _approx_tokens(" ".join(m.get("content", "") for m in messages))
        completion = _approx_tokens(text)
        return ModelResponse(
            text=text,
            backend=self.name,
            model=self.model,
            params=dict(params),
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
            latency_ms=0.1,
            raw={"stub_call_index": idx},
        )


@dataclass
class OpenAICompatibleBackend(Backend):
    base_url: str
    model: str
    api_key: Optional[str] = None
    timeout: float = 60.0
    name: str = "openai_compatible"
    # Completions path appended to base_url. Default keeps the historical
    # "/v1/chat/completions". HalCTF's sidecar follows OpenAI-SDK semantics, where
    # the client appends "/chat/completions" to OPENAI_BASE_URL (which already
    # carries any version prefix), so the sidecar wire-up sets chat_path there.
    chat_path: str = "/v1/chat/completions"
    _opener: Callable[..., Any] = urllib.request.urlopen

    def generate(self, messages: list[Message], params: dict) -> ModelResponse:
        url = self.base_url.rstrip("/") + "/" + self.chat_path.lstrip("/")
        body = {"model": self.model, "messages": messages}
        body.update(params or {})
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        started = time.monotonic()
        try:
            with self._opener(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                ra = None
                try:
                    ra = float(exc.headers.get("Retry-After")) if exc.headers else None
                except (TypeError, ValueError):
                    ra = None
                raise RateLimitError(f"HTTP 429 (rate limited) from {url}", retry_after=ra) from exc
            if exc.code >= 500:
                raise TransportError(f"HTTP {exc.code} from {url}") from exc
            # Other 4xx is a caller error — retrying won't help.
            raise NonRetryableError(f"HTTP {exc.code} from {url}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise TransportError(f"transport error to {url}: {exc}") from exc
        latency_ms = (time.monotonic() - started) * 1000.0

        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise TransportError(f"unexpected response shape from {url}: {exc}") from exc
        usage = payload.get("usage", {}) or {}
        return ModelResponse(
            text=text if isinstance(text, str) else json.dumps(text),
            backend=self.name,
            model=payload.get("model", self.model),
            params=dict(params or {}),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_ms=round(latency_ms, 3),
            raw=payload,
        )


@dataclass
class RoutedResult:
    response: Optional[ModelResponse]
    refusal: RefusalResult
    attempts: int
    error: Optional[str] = None


class ModelRouter:
    def __init__(
        self,
        backend: Backend,
        telemetry: TelemetryWriter,
        classifier: Optional[RefusalClassifier] = None,
        max_retries: int = 2,
        backoff_base: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.backend = backend
        self.telemetry = telemetry
        self.classifier = classifier or RefusalClassifier()
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._sleep = sleep

    def generate(
        self,
        *,
        run_id: str,
        challenge_id: str,
        step_index: int,
        messages: list[Message],
        params: dict,
    ) -> RoutedResult:
        last_error: Optional[str] = None

        def _error_record(attempt: int, etype: str, message: str) -> None:
            self.telemetry.write(base_record(
                record_type="model_call",
                run_id=run_id, challenge_id=challenge_id, step_index=step_index,
                plane="model", outcome="error",
                model={
                    "backend": getattr(self.backend, "name", "unknown"),
                    "name": getattr(self.backend, "model", "unknown"),
                    "params": dict(params or {}),
                    "prompt_tokens": None, "completion_tokens": None,
                    "total_tokens": None, "latency_ms": None,
                },
                error={"type": etype, "message": message},
                attempt=attempt,
            ))

        for attempt in range(self.max_retries + 1):
            try:
                resp = self.backend.generate(messages, params)
            except NonRetryableError as exc:
                # A 4xx: retrying won't help. Record and stop.
                last_error = str(exc)
                _error_record(attempt, "NonRetryableError", last_error)
                return RoutedResult(response=None, refusal=RefusalResult(False),
                                    attempts=attempt + 1, error=last_error)
            except TransportError as exc:
                last_error = str(exc)
                etype = type(exc).__name__          # TransportError | RateLimitError
                _error_record(attempt, etype, last_error)
                if attempt < self.max_retries:
                    # Honor Retry-After on 429, else exponential backoff.
                    retry_after = getattr(exc, "retry_after", None)
                    delay = retry_after if retry_after else self.backoff_base * (2 ** attempt)
                    self._sleep(delay)
                    continue
                return RoutedResult(response=None, refusal=RefusalResult(False),
                                    attempts=attempt + 1, error=last_error)

            refusal = self.classifier.classify(resp.text)
            outcome = "refused_by_model" if refusal.is_refusal else "dispatched"
            self.telemetry.write(base_record(
                record_type="model_call",
                run_id=run_id,
                challenge_id=challenge_id,
                step_index=step_index,
                plane="model",
                outcome=outcome,
                model=resp.model_field(),
                refusal=refusal.as_record(),
                attempt=attempt,
                meta={"response_chars": len(resp.text)},
            ))
            return RoutedResult(response=resp, refusal=refusal, attempts=attempt + 1)

        return RoutedResult(response=None, refusal=RefusalResult(False),
                            attempts=self.max_retries + 1, error=last_error)
