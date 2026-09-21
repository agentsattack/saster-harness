"""HalCTF platform API client: flag submission and the completion signal.

The wire contract (paths, payload shape, where "correct" lives in the response)
is NOT invented here — it is fully parameterized from config so that tomorrow,
once the OpenAI API spec / Player Preview pins it down, it is a config edit
rather than a code change under time pressure.

Placeholders `{challenge_id}` and `{flag}` are substituted into the configured
payload templates. `correct_pointer` is a dot-path into the response JSON telling
us where the platform reports flag correctness (mandatory: never count a solve
without platform confirmation).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlsplit


class PlatformError(RuntimeError):
    pass


def _subst(template: Any, values: dict) -> Any:
    """Recursively substitute {placeholders} in a payload template."""
    if isinstance(template, str):
        out = template
        for k, v in values.items():
            out = out.replace("{" + k + "}", str(v))
        return out
    if isinstance(template, dict):
        return {k: _subst(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [_subst(v, values) for v in template]
    return template


def _dig(obj: Any, pointer: str) -> Any:
    """Follow a dot-path like 'data.correct' into nested JSON; None if absent."""
    cur = obj
    for part in pointer.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


@dataclass
class PlatformClient:
    base_url: str
    submit_flag_path: str = "/api/v1/flags"
    complete_path: str = "/api/v1/complete"
    api_key: Optional[str] = None
    timeout: float = 30.0
    headers: dict = field(default_factory=dict)
    # Payload templates (parameterized; adjust to the real spec via config).
    flag_payload: dict = field(default_factory=lambda: {"challenge_id": "{challenge_id}", "flag": "{flag}"})
    complete_payload: dict = field(default_factory=lambda: {"challenge_id": "{challenge_id}"})
    correct_pointer: str = "correct"
    _opener: Any = urllib.request.urlopen

    @property
    def host(self) -> Optional[str]:
        return urlsplit(self.base_url).hostname

    def _post(self, path: str, payload: dict) -> dict:
        url = self.base_url.rstrip("/") + path
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", **self.headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        started = time.monotonic()
        try:
            with self._opener(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                status = getattr(resp, "status", 200)
        except urllib.error.HTTPError as exc:
            raise PlatformError(f"HTTP {exc.code} from {url}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise PlatformError(f"transport error to {url}: {exc}") from exc
        latency_ms = round((time.monotonic() - started) * 1000.0, 3)
        try:
            parsed = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            parsed = {"_raw": body}
        return {"status": status, "latency_ms": latency_ms, "response": parsed}

    def submit_flag(self, challenge_id: str, flag: str) -> dict:
        payload = _subst(self.flag_payload, {"challenge_id": challenge_id, "flag": flag})
        result = self._post(self.submit_flag_path, payload)
        correct = _dig(result["response"], self.correct_pointer)
        result["correct"] = bool(correct) if correct is not None else None
        return result

    def signal_complete(self, challenge_id: str) -> dict:
        payload = _subst(self.complete_payload, {"challenge_id": challenge_id})
        return self._post(self.complete_path, payload)
