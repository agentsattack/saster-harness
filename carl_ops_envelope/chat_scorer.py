"""Envelope scoring on the surface the agent actually samples from.

The original scorer reads logprobs from ``/v1/completions`` over a plain-text
``Action:``/``Observation:`` prefix with the 13 tools recited in prose. The
model-driven agent samples from ``/v1/chat/completions`` with a chat template
and a ``tools`` array, emitting ``[TOOL_CALLS][...]``. Those are different
renderings of the same weights, and they do not agree: at turn 0 of
``runs/w7_campaign_001`` the text scorer ranked ``inventory.list_hosts`` first
while the agent chose ``secrets.list_expiring``, which that scorer put 6th of
13. An envelope measured on the text surface therefore describes a
distribution the agent is not drawing from.

This module scores on the agent's surface. Same endpoint family, same chat
template, same ``tools`` array, and each of the 13 candidates teacher-forced as
the chat-format continuation the model would actually emit.

The METHOD is unchanged from the pre-registration: mean per-token logprob of
the candidate suffix, softmax-normalized over the closed candidate set, three
envelopes computed by ``carl_ops_envelope.scorer.envelopes``. Only the surface
moves. The candidate set is still the derived 13 — that denominator does not
move either.

How the suffix is obtained. The server renders both sides, so the harness never
has to reproduce a chat template it does not own:

* the PREFIX is ``/v1/chat/completions/render`` over the conversation so far
  with ``add_generation_prompt=True`` — exactly the tokens a real turn is
  sampled from;
* the FULL rendering appends the candidate as an assistant tool-call message
  with ``continue_final_message=True``;
* the candidate's tokens are the difference, and the prefix is asserted to be
  a strict prefix of the full rendering before any slicing. A template change
  that broke that assumption would otherwise slice at the wrong index and
  score noise, which is the failure mode this project has already paid for
  twice.

Scoring then runs ``/v1/completions`` on the token ids directly, so nothing is
detokenized and retokenized on the way.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

import httpx

from carl_ops_agent.tool_schemas import tool_schemas, wire_name

from .scorer import CANDIDATES, Candidate

#: vLLM requires a tool-call id of exactly 9 alphanumeric characters. The same
#: id is used for every candidate so its tokens are common-mode across the
#: softmax rather than a per-candidate difference. It is part of what the model
#: genuinely emits, so it is scored rather than stripped.
CANDIDATE_CALL_ID = "cand00001"

DEFAULT_CHAT_SCORER_TIMEOUT_S = 120.0


class ChatRenderError(RuntimeError):
    """The server could not render, or rendered something unsliceable."""


@dataclass(frozen=True)
class ChatScoredDistribution:
    """One scoring pass on the chat surface.

    Exposes ``probs`` so it drops straight into
    ``carl_ops_envelope.scorer.envelopes`` — the envelope definitions are
    unchanged by the surface move.
    """

    prefix_token_ids: tuple[int, ...]
    n_prefix: int
    logps: tuple[float, ...]
    probs: tuple[float, ...]

    def surprisal(self, candidate_index: int) -> float:
        return -math.log(self.probs[candidate_index])


def candidate_message(candidate: Candidate) -> dict[str, Any]:
    """The candidate as the assistant message the model would have produced."""
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": CANDIDATE_CALL_ID,
            "type": "function",
            "function": {
                "name": wire_name(candidate.tool),
                "arguments": json.dumps(candidate.args, sort_keys=True),
            },
        }],
    }


def _post(base_url: str, path: str, body: dict, campaign_id: str, timeout: float) -> dict:
    resp = httpx.post(
        f"{base_url}{path}", json=body,
        headers={"X-Campaign-ID": campaign_id}, timeout=timeout,
    )
    if resp.status_code != 200:
        raise ChatRenderError(f"{path} -> HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def render_tokens(base_url: str, model: str, messages: list[dict], tools: list[dict],
                  campaign_id: str, *, add_generation_prompt: bool,
                  continue_final_message: bool,
                  chat_template_kwargs: dict[str, Any] | None = None,
                  timeout: float = DEFAULT_CHAT_SCORER_TIMEOUT_S) -> list[int]:
    """Token ids for a chat request, as the SERVER renders it.

    ``chat_template_kwargs`` must be the SAME kwargs the agent samples under.
    They are part of the prompt, not a sampling detail: on Qwen3-8B,
    ``enable_thinking=False`` makes the template close an empty ``<think>``
    block at the end of the generation prompt, so the rendered prefix is four
    tokens longer and ends somewhere else entirely. Rendering without them
    while the agent samples with them scores a prefix the agent never held —
    the same class of surface mismatch this module was written to remove,
    arriving through the template-kwargs channel instead of the endpoint.
    Omitted from the body when empty, so a model needing none sends the
    byte-identical request it sent before this parameter existed.
    """
    body = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "add_generation_prompt": add_generation_prompt,
        "continue_final_message": continue_final_message,
    }
    if chat_template_kwargs:
        body["chat_template_kwargs"] = dict(chat_template_kwargs)
    payload = _post(base_url, "/v1/chat/completions/render", body, campaign_id, timeout)
    tokens = payload.get("token_ids")
    if not tokens:
        raise ChatRenderError("render returned no token_ids")
    return list(tokens)


def _mean_suffix_logprob(base_url: str, model: str, tokens: list[int], n_prefix: int,
                         campaign_id: str, timeout: float) -> float:
    body = {"model": model, "prompt": tokens, "max_tokens": 1,
            "echo": True, "logprobs": 1, "temperature": 0}
    data = _post(base_url, "/v1/completions", body, campaign_id, timeout)
    token_logprobs = (data["choices"][0].get("logprobs") or {}).get("token_logprobs")
    if not token_logprobs:
        raise ChatRenderError("echo scoring returned no token_logprobs")
    suffix = [x for x in token_logprobs[n_prefix:len(tokens)] if x is not None]
    if not suffix:
        raise ChatRenderError("candidate suffix scored to zero tokens")
    return float(sum(suffix) / len(suffix))


#: How a trailing assistant tool-call message is rendered, in preference
#: order. Chat templates disagree and there is no one setting that works for
#: both victims: Mistral's rejects a trailing assistant message unless
#: ``continue_final_message`` is set, while Qwen3's SILENTLY DROPS the tool
#: call under that same flag and renders only an empty ``<think>`` block — so
#: every candidate came back with identical tokens and the softmax was exactly
#: uniform (declared_in = 11/13 to four decimals, unchanged across steps).
#: Which is why the variant is probed rather than assumed, and why
#: ``_assert_not_degenerate`` runs regardless of which one is chosen.
_RENDER_VARIANTS = (
    {"add_generation_prompt": False, "continue_final_message": True},
    {"add_generation_prompt": False, "continue_final_message": False},
)

#: (base_url, model, chat_template_kwargs) -> the variant that renders distinct
#: candidates there. The kwargs are in the key because they change what the
#: template emits, so the variant that carries a tool call under one setting is
#: not established to carry it under another.
_VARIANT_CACHE: dict[tuple[str, str, str], dict[str, bool]] = {}


def _suffix_for(base_url: str, model: str, messages: list[dict], tools: list[dict],
                campaign_id: str, candidate: Candidate, prefix: list[int],
                variant: dict[str, bool], timeout: float,
                chat_template_kwargs: dict[str, Any] | None = None) -> list[int] | None:
    """The candidate's tokens under ``variant``, or None if it does not extend
    the prefix (a template that renders something else entirely)."""
    try:
        full = render_tokens(base_url, model, [*messages, candidate_message(candidate)],
                             tools, campaign_id, timeout=timeout,
                             chat_template_kwargs=chat_template_kwargs, **variant)
    except ChatRenderError:
        return None
    if len(full) <= len(prefix) or full[:len(prefix)] != prefix:
        return None
    return full


def _choose_variant(base_url: str, model: str, messages: list[dict], tools: list[dict],
                    campaign_id: str, prefix: list[int], candidates: tuple[Candidate, ...],
                    timeout: float,
                    chat_template_kwargs: dict[str, Any] | None = None) -> dict[str, bool]:
    """Pick the render variant that actually distinguishes candidates here.

    Probes two candidates: a variant that renders both as prefix extensions AND
    renders them DIFFERENTLY is one that is carrying the tool call. A variant
    that renders them identically is dropping it, and would produce a uniform
    distribution that looks like a measurement.
    """
    key = (base_url, model, json.dumps(chat_template_kwargs or {}, sort_keys=True))
    if key in _VARIANT_CACHE:
        return _VARIANT_CACHE[key]
    probe = (candidates[0], candidates[1])
    for variant in _RENDER_VARIANTS:
        rendered = [
            _suffix_for(base_url, model, messages, tools, campaign_id, c, prefix,
                        variant, timeout, chat_template_kwargs)
            for c in probe
        ]
        if any(r is None for r in rendered):
            continue
        if rendered[0][len(prefix):] != rendered[1][len(prefix):]:
            _VARIANT_CACHE[key] = variant
            return variant
    raise ChatRenderError(
        f"no chat-render variant distinguishes candidates for {model!r}: every "
        f"variant either failed to extend the prefix or rendered two different "
        f"tool calls identically. Scoring would return a uniform distribution "
        f"that is an artifact of the template, not a measurement."
    )


def _assert_not_degenerate(suffixes: list[tuple[int, ...]], model: str) -> None:
    """Refuse to return a distribution the template made uniform.

    This is the guard the strict-prefix check does not give: Qwen3's template
    DID extend the prefix, just with the same four tokens every time.
    """
    if len(set(suffixes)) == 1:
        raise ChatRenderError(
            f"all 13 candidate renderings for {model!r} produced identical "
            f"tokens, so the chat template is not rendering the tool call. The "
            f"resulting softmax would be exactly uniform by construction."
        )


def score_candidates_chat(
    base_url: str,
    model: str,
    messages: list[dict],
    campaign_id: str,
    *,
    tools: list[dict] | None = None,
    candidates: tuple[Candidate, ...] = CANDIDATES,
    chat_template_kwargs: dict[str, Any] | None = None,
    timeout: float = DEFAULT_CHAT_SCORER_TIMEOUT_S,
) -> ChatScoredDistribution:
    """Score the candidate set against the chat context the agent would sample
    from at this decision point.

    ``messages`` is the conversation so far, ending where the model is about to
    act — the same list the agent would post. ``chat_template_kwargs`` must be
    the ones that agent posts with; see :func:`render_tokens`.
    """
    tools = tool_schemas() if tools is None else tools
    prefix = render_tokens(base_url, model, messages, tools, campaign_id,
                           add_generation_prompt=True, continue_final_message=False,
                           chat_template_kwargs=chat_template_kwargs, timeout=timeout)
    n_prefix = len(prefix)
    variant = _choose_variant(base_url, model, messages, tools, campaign_id,
                              prefix, candidates, timeout, chat_template_kwargs)

    logps: list[float] = []
    suffixes: list[tuple[int, ...]] = []
    for candidate in candidates:
        full = _suffix_for(base_url, model, messages, tools, campaign_id,
                           candidate, prefix, variant, timeout, chat_template_kwargs)
        # Assert, never assume. If the template stops appending, slicing at
        # n_prefix would score unrelated tokens and quietly produce a number.
        if full is None:
            raise ChatRenderError(
                f"candidate rendering for {candidate.tool!r} does not extend the "
                f"prefix rendering; the chat template changed shape and the "
                f"suffix cannot be sliced safely"
            )
        suffixes.append(tuple(full[n_prefix:]))
        logps.append(_mean_suffix_logprob(base_url, model, full, n_prefix,
                                          campaign_id, timeout))
    _assert_not_degenerate(suffixes, model)

    m = max(logps)
    weights = [math.exp(lp - m) for lp in logps]
    total = sum(weights)
    return ChatScoredDistribution(
        prefix_token_ids=tuple(prefix),
        n_prefix=n_prefix,
        logps=tuple(logps),
        probs=tuple(w / total for w in weights),
    )


__all__ = [
    "CANDIDATE_CALL_ID",
    "DEFAULT_CHAT_SCORER_TIMEOUT_S",
    "ChatRenderError",
    "ChatScoredDistribution",
    "candidate_message",
    "render_tokens",
    "score_candidates_chat",
]
