"""Envelope scoring on the agent's own surface.

The text scorer measured a distribution the agent was not drawing from: it
reads ``/v1/completions`` over a plain-text prefix with the tools recited in
prose, while the agent samples ``/v1/chat/completions`` with a chat template
and a ``tools`` array. This module scores through the server's own chat
rendering instead.

The tests that matter most are the slicing guards. The candidate's tokens are
obtained by differencing two server renderings, so if the template ever stops
appending — a version bump, a different tool parser — slicing at the prefix
length would score unrelated tokens and still return a plausible number.
That must raise, not compute.
"""

from __future__ import annotations

import json

import pytest

from carl_ops_agent.tool_schemas import canonical_name, model_facing_tools
from carl_ops_envelope import CANDIDATES, envelopes
from carl_ops_envelope import chat_scorer as cs
from carl_ops_state import TransitionRelation
from carl_ops_state.fixture import clean_environment, initial_state

MESSAGES = [{"role": "system", "content": "SYS"},
            {"role": "user", "content": "Begin."}]


class FakeServer:
    """Renders a prefix and appends a per-candidate suffix, like the real one."""

    def __init__(self, prefix_len=10, suffix_len=5, logprob=-1.0, extend=True):
        self.prefix = list(range(prefix_len))
        self.suffix_len = suffix_len
        self.logprob = logprob
        self.extend = extend
        self.render_bodies = []
        self.score_bodies = []

    def __call__(self, base_url, path, body, campaign_id, timeout):
        if path.endswith("/render"):
            self.render_bodies.append(body)
            if body.get("add_generation_prompt"):
                return {"token_ids": list(self.prefix)}
            name = body["messages"][-1]["tool_calls"][0]["function"]["name"]
            tail = [1000 + (len(name) % 7) + i for i in range(self.suffix_len)]
            base = list(self.prefix) if self.extend else [999] * len(self.prefix)
            return {"token_ids": base + tail}
        self.score_bodies.append(body)
        n = len(body["prompt"])
        return {"choices": [{"logprobs": {
            "token_logprobs": [None] + [self.logprob] * (n - 1) + [self.logprob]}}]}


@pytest.fixture
def server(monkeypatch):
    fake = FakeServer()
    monkeypatch.setattr(cs, "_VARIANT_CACHE", {})
    monkeypatch.setattr(cs, "_post", fake)
    return fake


# -- the candidate is rendered as the model would emit it -------------------


def test_candidate_message_uses_the_wire_name():
    msg = cs.candidate_message(CANDIDATES[3])
    call = msg["tool_calls"][0]
    assert msg["role"] == "assistant"
    assert canonical_name(call["function"]["name"]) == CANDIDATES[3].tool
    assert "." not in call["function"]["name"]


def test_candidate_arguments_are_deterministically_serialized():
    """Two runs must render byte-identically or the scored tokens differ for
    reasons that have nothing to do with the model."""
    a = cs.candidate_message(CANDIDATES[10])["tool_calls"][0]["function"]["arguments"]
    b = cs.candidate_message(CANDIDATES[10])["tool_calls"][0]["function"]["arguments"]
    assert a == b == json.dumps(CANDIDATES[10].args, sort_keys=True)


def test_every_candidate_uses_the_same_call_id():
    """The id is mandatory and 9 alphanumerics. Holding it constant makes its
    tokens common-mode across the softmax rather than a per-candidate
    difference."""
    ids = {cs.candidate_message(c)["tool_calls"][0]["id"] for c in CANDIDATES}
    assert ids == {cs.CANDIDATE_CALL_ID}
    assert len(cs.CANDIDATE_CALL_ID) == 9 and cs.CANDIDATE_CALL_ID.isalnum()


def test_the_candidate_set_is_still_the_derived_thirteen():
    """The surface moved; the denominator did not."""
    assert len(CANDIDATES) == 13
    assert {c.tool for c in CANDIDATES} == set(model_facing_tools())


# -- slicing guards ---------------------------------------------------------


def test_a_rendering_that_does_not_extend_the_prefix_raises(monkeypatch):
    monkeypatch.setattr(cs, "_VARIANT_CACHE", {})
    monkeypatch.setattr(cs, "_post", FakeServer(extend=False))
    with pytest.raises(cs.ChatRenderError, match="no chat-render variant"):
        cs.score_candidates_chat("http://x", "m", MESSAGES, "c")


class DegenerateServer(FakeServer):
    """A template that extends the prefix but drops the tool call — exactly
    what Qwen3's does under continue_final_message."""

    def __call__(self, base_url, path, body, campaign_id, timeout):
        if path.endswith("/render") and not body.get("add_generation_prompt"):
            self.render_bodies.append(body)
            return {"token_ids": list(self.prefix) + [7, 7, 7, 7]}
        return super().__call__(base_url, path, body, campaign_id, timeout)


def test_identical_candidate_renderings_raise_rather_than_score_uniform(monkeypatch):
    """The failure the strict-prefix guard does NOT catch. Qwen3 rendered every
    candidate as the same four tokens, giving declared_in = 11/13 to four
    decimals, unchanged across steps — a number that looks like a measurement
    and is an artifact of the template."""
    monkeypatch.setattr(cs, "_VARIANT_CACHE", {})
    monkeypatch.setattr(cs, "_post", DegenerateServer())
    with pytest.raises(cs.ChatRenderError, match="uniform"):
        cs.score_candidates_chat("http://x", "m", MESSAGES, "c")


def test_the_render_variant_is_probed_not_assumed(monkeypatch):
    """Mistral needs continue_final_message=True; Qwen3 needs it False. A
    hardcoded flag silently degenerates on one of the two victims."""
    monkeypatch.setattr(cs, "_VARIANT_CACHE", {})

    class OnlySecondVariant(FakeServer):
        def __call__(self, base_url, path, body, campaign_id, timeout):
            if (path.endswith("/render")
                    and not body.get("add_generation_prompt")
                    and body.get("continue_final_message")):
                raise cs.ChatRenderError("template rejects a trailing assistant")
            return super().__call__(base_url, path, body, campaign_id, timeout)

    monkeypatch.setattr(cs, "_post", OnlySecondVariant())
    dist = cs.score_candidates_chat("http://x", "m", MESSAGES, "c")
    assert len(dist.probs) == 13


def test_an_empty_suffix_raises_rather_than_scoring_nothing(monkeypatch):
    monkeypatch.setattr(cs, "_VARIANT_CACHE", {})
    monkeypatch.setattr(cs, "_post", FakeServer(suffix_len=0))
    with pytest.raises(cs.ChatRenderError):
        cs.score_candidates_chat("http://x", "m", MESSAGES, "c")


def test_a_render_without_token_ids_raises(monkeypatch):
    monkeypatch.setattr(cs, "_VARIANT_CACHE", {})
    monkeypatch.setattr(cs, "_post", lambda *a, **k: {"token_ids": []})
    with pytest.raises(cs.ChatRenderError, match="no token_ids"):
        cs.score_candidates_chat("http://x", "m", MESSAGES, "c")


def test_only_the_suffix_is_scored(server):
    """The prefix is shared by every candidate; including it would wash out
    the differences the softmax exists to expose."""
    cs.score_candidates_chat("http://x", "m", MESSAGES, "c")
    for body in server.score_bodies:
        assert len(body["prompt"]) == len(server.prefix) + server.suffix_len


# -- the request is the agent's ---------------------------------------------


def test_the_prefix_is_rendered_with_a_generation_prompt(server):
    cs.score_candidates_chat("http://x", "m", MESSAGES, "c")
    prefix_renders = [b for b in server.render_bodies if b.get("add_generation_prompt")]
    assert len(prefix_renders) == 1
    assert prefix_renders[0]["continue_final_message"] is False


def test_every_candidate_is_rendered_under_one_chosen_variant(server):
    """13 candidate renders, plus the 2-candidate probe that selects the
    variant. All of them carry a trailing assistant tool-call message."""
    cs.score_candidates_chat("http://x", "m", MESSAGES, "c")
    cand_renders = [b for b in server.render_bodies if not b.get("add_generation_prompt")]
    assert len(cand_renders) == 13 + 2
    assert all(b["messages"][-1]["role"] == "assistant" for b in cand_renders)
    assert len({b["continue_final_message"] for b in cand_renders}) == 1


def test_the_tools_array_is_sent_on_every_render(server):
    cs.score_candidates_chat("http://x", "m", MESSAGES, "c")
    assert all(len(b["tools"]) == 13 for b in server.render_bodies)


def test_scoring_is_deterministic_prompt_only_echo(server):
    cs.score_candidates_chat("http://x", "m", MESSAGES, "c")
    for body in server.score_bodies:
        assert body["echo"] is True
        assert body["max_tokens"] == 1
        assert body["temperature"] == 0


# -- the distribution -------------------------------------------------------


def test_probabilities_are_a_distribution_over_the_candidate_set(server):
    dist = cs.score_candidates_chat("http://x", "m", MESSAGES, "c")
    assert len(dist.probs) == 13
    assert pytest.approx(sum(dist.probs), abs=1e-9) == 1.0
    assert all(p > 0 for p in dist.probs)


def test_surprisal_is_read_off_the_same_distribution(server):
    import math
    dist = cs.score_candidates_chat("http://x", "m", MESSAGES, "c")
    assert dist.surprisal(3) == pytest.approx(-math.log(dist.probs[3]))


def test_envelopes_consume_the_chat_distribution_unchanged():
    """The surface moved; the envelope definitions did not. This asserts the
    chat result is accepted by the same envelopes() the text scorer feeds."""

    class Dist:
        probs = tuple([1 / 13] * 13)

    t0 = initial_state(clean_environment())
    em = envelopes(Dist(), t0.scope, t0, t0, TransitionRelation())
    assert set(em) == {"declared_in", "declared_out", "scored",
                       "scored_status", "scored_note", "prohibition_out"}
    assert em["declared_in"] + em["declared_out"] == pytest.approx(1.0)
    assert em["scored"] is None  # AMENDMENT 3 still governs


def test_prefix_token_ids_are_reported_for_audit(server):
    dist = cs.score_candidates_chat("http://x", "m", MESSAGES, "c")
    assert dist.n_prefix == len(server.prefix)
    assert dist.prefix_token_ids == tuple(server.prefix)
