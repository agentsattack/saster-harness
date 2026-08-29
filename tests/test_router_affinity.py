"""Session-affinity router — model-aware backend selection.

The W6c pilot's Qwen3-8B canary failed 10/10 with an upstream 404 ("The model
`Qwen/Qwen3-8B` does not exist.") while Ministral passed 10/10 through the same
router. The cause was not the models or the nodes: the router hashed campaigns
across EVERY backend and never looked at the requested model, so a campaign
whose key landed on the wrong replica asked a node for a model it did not host.
Ministral passed by luck of the hash, and the pilot's campaign id carries a
comment saying it was chosen to hash onto the right replica — a hand-tuned
workaround for a routing defect.

These tests pin both halves of the resolution: the model constrains which
backends are candidates, and the affinity key still pins a campaign to exactly
one of them for its whole life (the prefix-cache guarantee the router exists
for).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "saster_router", Path(__file__).resolve().parents[1] / "scripts" / "saster_router.py"
)
saster_router = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(saster_router)

Router = saster_router.Router
ANY_MODEL = saster_router.ANY_MODEL

QWEN_NODE = "http://192.168.1.228:8000"
MINISTRAL_NODE = "http://192.168.1.208:8000"
QWEN = "Qwen/Qwen3-8B"
MINISTRAL = "mistralai/Ministral-8B-Instruct-2410"


def two_node_router() -> Router:
    """The W6c serving layout: two backends, one model each."""
    r = Router([QWEN_NODE, MINISTRAL_NODE])
    r.set_backend_models({QWEN_NODE: [QWEN], MINISTRAL_NODE: [MINISTRAL]})
    return r


# -- the regression ---------------------------------------------------------


def test_every_key_routes_to_a_backend_that_serves_the_model():
    """The defect, stated as a property. Under the old router this fails for
    roughly half of all keys."""
    r = two_node_router()
    for i in range(500):
        for model, expected in ((QWEN, QWEN_NODE), (MINISTRAL, MINISTRAL_NODE)):
            assert r.pick(f"campaign-{i}", model) == expected


def test_the_exact_w6c_canary_keys_now_resolve_correctly():
    """The two keys that produced 10/10 failure and 10/10 success."""
    r = two_node_router()
    assert r.pick(f"canary::{QWEN}", QWEN) == QWEN_NODE
    assert r.pick(f"canary::{MINISTRAL}", MINISTRAL) == MINISTRAL_NODE


def test_the_qwen_canary_key_used_to_land_on_the_ministral_node():
    """Pins the cause, so nobody re-derives it. The Qwen canary key hashes
    onto the Ministral backend on a model-blind ring over both nodes — that
    ring is what the old router used for every request."""
    r = two_node_router()
    model_blind = r.rings[ANY_MODEL]

    def pick_blind(key: str) -> str:
        h = int.from_bytes(
            saster_router.hashlib.blake2b(key.encode(), digest_size=8).digest(), "big"
        )
        for point, backend in model_blind:
            if point >= h:
                return backend
        return model_blind[0][1]

    assert pick_blind(f"canary::{QWEN}") == MINISTRAL_NODE      # the 404
    assert r.pick(f"canary::{QWEN}", QWEN) == QWEN_NODE          # the fix


def test_pilot_campaign_still_lands_on_ministral():
    """w6c-pilot-003 was hand-picked to hash onto the Ministral replica. The
    fix must not move it, or the kept pilot output would no longer describe
    the path a re-run takes."""
    r = two_node_router()
    assert r.pick("w6c-pilot-003", MINISTRAL) == MINISTRAL_NODE


# -- affinity is preserved --------------------------------------------------


def test_a_campaign_pins_to_one_backend_across_repeated_calls():
    """The prefix-cache guarantee: every call for one campaign lands on the
    same replica."""
    r = Router(["http://a:8000", "http://b:8000", "http://c:8000"])
    r.set_backend_models({n: [QWEN] for n in r.backends})
    picks = {r.pick("campaign-42", QWEN) for _ in range(50)}
    assert len(picks) == 1


def test_campaigns_spread_across_replicas_of_the_same_model():
    """Affinity must not collapse every campaign onto one node when a model
    has several replicas."""
    r = Router(["http://a:8000", "http://b:8000", "http://c:8000"])
    r.set_backend_models({n: [QWEN] for n in r.backends})
    picks = {r.pick(f"campaign-{i}", QWEN) for i in range(200)}
    assert len(picks) == 3


def test_ring_is_stable_across_router_restarts():
    """Two routers with the same configuration must agree, or a restart would
    scatter a campaign's trials across replicas mid-run."""
    a, b = two_node_router(), two_node_router()
    for i in range(100):
        assert a.pick(f"c{i}", QWEN) == b.pick(f"c{i}", QWEN)


def test_ring_does_not_depend_on_discovery_order():
    """Discovery is concurrent, so the mapping may arrive in any order; the
    ring must not."""
    ordered = two_node_router()
    shuffled = Router([QWEN_NODE, MINISTRAL_NODE])
    shuffled.set_backend_models({MINISTRAL_NODE: [MINISTRAL], QWEN_NODE: [QWEN]})
    for i in range(100):
        assert ordered.pick(f"c{i}", QWEN) == shuffled.pick(f"c{i}", QWEN)


def test_removing_a_replica_remaps_only_its_share():
    """Consistent hashing, still: dropping one of three replicas must not
    reshuffle the campaigns pinned to the other two."""
    three = Router(["http://a:8000", "http://b:8000", "http://c:8000"])
    three.set_backend_models({n: [QWEN] for n in three.backends})
    two = Router(["http://a:8000", "http://b:8000"])
    two.set_backend_models({n: [QWEN] for n in two.backends})

    keys = [f"campaign-{i}" for i in range(300)]
    survivors = [k for k in keys if three.pick(k, QWEN) != "http://c:8000"]
    assert all(three.pick(k, QWEN) == two.pick(k, QWEN) for k in survivors)


# -- honest failure ---------------------------------------------------------


def test_unknown_model_returns_none_rather_than_a_wrong_backend():
    """The router must not answer 'some backend' for a model nothing serves —
    that is precisely how the defect stayed invisible."""
    r = two_node_router()
    assert r.pick("any-campaign", "meta-llama/Llama-3-70B") is None


def test_unreachable_backend_owns_no_models():
    """A backend that failed discovery must not receive traffic on a guess."""
    r = Router([QWEN_NODE, MINISTRAL_NODE])
    r.set_backend_models({MINISTRAL_NODE: [MINISTRAL]})  # Qwen node was down
    assert r.pick("c", MINISTRAL) == MINISTRAL_NODE
    assert r.pick("c", QWEN) is None


def test_model_free_requests_still_route():
    """Health probes and the like name no model and must keep working."""
    r = two_node_router()
    assert r.pick("default", ANY_MODEL) in (QWEN_NODE, MINISTRAL_NODE)


def test_a_backend_serving_several_models_joins_every_matching_ring():
    r = Router(["http://multi:8000"])
    r.set_backend_models({"http://multi:8000": [QWEN, MINISTRAL]})
    assert r.pick("c", QWEN) == "http://multi:8000"
    assert r.pick("c", MINISTRAL) == "http://multi:8000"


def test_known_models_reports_what_is_routable():
    assert two_node_router().known_models() == sorted([MINISTRAL, QWEN])


# -- request parsing --------------------------------------------------------


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"model": QWEN}, QWEN),
        ({"model": ""}, ANY_MODEL),
        ({}, ANY_MODEL),
        (None, ANY_MODEL),
        ("not-a-dict", ANY_MODEL),
        ({"model": 7}, ANY_MODEL),
    ],
)
def test_requested_model_extraction(body, expected):
    assert Router.requested_model(body) == expected


def test_affinity_key_prefers_the_campaign_header():
    key, how = Router.affinity_key({"X-Campaign-ID": "camp-1"}, {"user": "u"})
    assert (key, how) == ("camp-1", "header")


def test_affinity_key_is_unchanged_by_the_model_fix():
    """The key derivation is untouched; only what it is resolved against
    changed. Pinned so the two concerns stay separable."""
    assert Router.affinity_key({}, {"user": "u"}) == ("u", "user-field")
    assert Router.affinity_key({}, {})[1] == "fallback"
    assert Router.affinity_key({}, {"messages": [{"content": "hi"}]})[1] == "prefix-hash"
    assert Router.affinity_key({}, {"prompt": "hi"})[1] == "prompt-hash"
