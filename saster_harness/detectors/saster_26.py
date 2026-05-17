"""SASTER-26 — Recon-Gated Injection / RGI (Tier 4, Infrastructure & Recon).

Canonical definition (from SASTER.md):

    Attack:
        Attacker fingerprints the target model family and defense architecture
        through behavioral probing before selecting an injection strategy.
        Narrows the attack surface to techniques known to be effective
        against the identified model.

    Detection:
        Systematic boundary probing with no apparent task objective. Probes
        designed to elicit formatting, refusal style, or knowledge cutoff
        responses rather than task completion.

    Example:
        Sending knowledge cutoff probes, refusal style analysis prompts, and
        capability boundary tests before launching the actual attack — using
        the fingerprint to select model-family-specific jailbreak techniques.

Operational shape at the wire level
-----------------------------------
RGI manifests as out-of-task questions about the deployment's defense
architecture — credentials, network topology, identity provider,
observability stack — embedded in otherwise-normal traffic. The detector
is a tuned regex over those vocabulary classes, organised by recon
surface:

- **Compute / network:** cloud provider, region, k8s, VPC, service mesh
- **Identity:** IAM, credentials, secrets management, OAuth, environment
  variables
- **Pipeline:** CI/CD, deployment pipeline, image registry, artifact repo
- **Observability:** SIEM, audit logs, log retention, security events

The detector inspects ``user_message`` because the most common attack
shape under monitoring is a rogue agent (or a compromised one) probing
its upstream LLM. For monitoring an LLM-as-product deployment where the
attack would arrive from a real user, flip the inspection target by
subclassing this detector and overriding :meth:`extract_probe_text`.

Co-firing with SASTER-33
------------------------
SASTER.md's notes on SASTER-33 explicitly pair it with SASTER-26 during
active reconnaissance — recon side-channels frequently drop the
``role:system`` message, so structural anomaly detection lights up the
same turn. The ``co_fires_with`` class attribute documents this for
downstream correlation.

Simplification vs ProxyGAP
--------------------------
ProxyGAP's ``_RE_INTERVAL_RECON`` is the source of this regex. The harness
version drops a few Carl-specific anchors (e.g. the literal string
"deployment pipeline" qualifier that was tuned against a specific demo
prompt) and keeps only language patterns generic enough to fire on
arbitrary deployment recon.

False-positive cases
--------------------
- Legitimate platform-onboarding questions ("which cloud do you run
  on", asked by a prospect doing compliance due diligence) — fires on
  a single match. Mitigation in production: require two or more recon
  surfaces in the same session before escalating to the alert webhook.
- DevRel / support agents that intentionally answer infrastructure
  questions — they emit recon-vocabulary in assistant responses, not
  user prompts, so this detector (which checks ``user_message``) is
  unaffected.
- Documentation chatbots that mirror infrastructure jargon back at the
  user — same as above.
"""

from __future__ import annotations

import re

from ..detector import SasterDetector
from ..event import DetectionEvent, TurnData

_RECON_RE = re.compile(
    r"""
    \b(?:
        # ---------- compute / network surface ----------
        (?:which|what)\s+cloud(?:\s+provider)?
      | cloud\s+provider
      | (?:CI\s*/\s*CD|continuous\s+(?:integration|deployment|delivery))
      | deployment\s+pipeline
      | build\s+pipeline
      | k(?:ubernetes|8s)\s+(?:cluster|pod|namespace)
      | container\s+orchestration
      | service\s+mesh
      | what\s+region | which\s+region | which\s+availability\s+zone
      | (?:are\s+you\s+|is\s+(?:this|it)\s+)?
        (?:running|hosted|deployed)
        \s+(?:on|in|at)
      | infrastructure\s+(?:setup|details?|stack|topology)
      | (?:internal\s+)?network\s+topology
      | VPC | security\s+group | subnet
        # ---------- identity surface ----------
      | IAM\s+(?:role|policy|policies|pattern)
      | (?:credential|secret|API\s+key|OAuth\s+token|service[-\s]account)
      | (?:HashiCorp\s+)?vault\b
      | (?:AWS|Azure|GCP)\s+secrets?\s+manager
      | secrets?\s+(?:stored|management)
      | environment\s+variables?(?:\s+on)?
        # ---------- pipeline / supply chain ----------
      | image\s+registry | artifact\s+repo
        # ---------- detection / observability ----------
      | SIEM | observability\s+stack
      | audit\s+logs? | security\s+events?
      | log\s+retention
      | privileged\s+actions?
    )\b
    .{0,300}?\?
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


_SURFACE_TAGS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(cloud|region|VPC|kubernetes|k8s|subnet|service\s+mesh)\b", re.IGNORECASE),
     "compute"),
    (re.compile(r"\b(IAM|credential|secret|API\s+key|OAuth|vault|service.account|env)\b",
                re.IGNORECASE), "identity"),
    (re.compile(r"\b(CI/?CD|pipeline|image\s+registry|artifact\s+repo|build)\b", re.IGNORECASE),
     "pipeline"),
    (re.compile(r"\b(SIEM|audit\s+log|observability|security\s+event|log\s+retention)\b",
                re.IGNORECASE), "observability"),
)


def _classify_surface(text: str) -> str:
    """Return a short tag naming the recon surface a match touches.

    Best-effort: returns the first surface that matches, falling back to
    ``"infrastructure"`` when the matched fragment doesn't fall cleanly
    into one of the four canonical surfaces. Surface tags are evidence,
    not gates — the detector fires on the primary regex regardless of
    whether the surface can be named."""
    for pattern, tag in _SURFACE_TAGS:
        if pattern.search(text):
            return tag
    return "infrastructure"


class ReconGatedInjectionDetector(SasterDetector):
    saster_id = "SASTER-26"
    pattern_name = "Recon-Gated Injection"
    tier = 4
    co_fires_with = ("SASTER-33",)

    def extract_probe_text(self, turn: TurnData) -> str:
        """Which field of the turn to scan for recon vocabulary.

        Default: ``user_message``. Override in subclasses to scan
        ``assistant_response`` for the LLM-as-product deployment shape
        (attack arrives from a real user, not a rogue agent)."""
        return turn.user_message

    def evaluate(self, turn: TurnData) -> DetectionEvent | None:
        probe = self.extract_probe_text(turn)
        if not probe:
            return None
        match = _RECON_RE.search(probe)
        if match is None:
            return None
        surface = _classify_surface(match.group(0))
        return self._build_event(
            turn,
            evidence={
                "signal": "recon_vocabulary_match",
                "detail": (
                    f"User-message text contains {surface} recon vocabulary "
                    f"with no apparent task objective."
                ),
                "match": match.group(0).strip(),
                "surface": surface,
            },
        )


DETECTOR = ReconGatedInjectionDetector()
