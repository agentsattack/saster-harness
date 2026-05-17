"""SASTER-27 — Detection Layer Injection / DLI (Tier 4, Infrastructure & Recon).

Canonical definition (from SASTER.md):

    Attack:
        Probe crafted to exploit the classification/quarantine agent rather
        than the downstream model. Exploits the defender's dilemma: the
        scanner must ingest content to classify it, making the scanner
        itself an attack surface.

    Detection:
        Payloads that appear benign to the primary model but contain
        instructions targeting scanner/classifier behavior.

    Subtypes:
        Scanner simulation (fake thinking tags / system commands), delayed
        activation (benign on first pass, malicious on re-read), context
        splitting (harmless fragments that assemble into malicious whole),
        encoding obfuscation (hide payload from scanner regex), EchoGram
        classifier evasion (flip tokens, fake classifier-output strings,
        token flooding, Unicode zero-width insertion), constitutional bypass
        (simultaneous model-judge compromise).

Operational shape at the wire level
-----------------------------------
At the wire level DLI shows up as input artifacts targeting *the
classifier* rather than the model:

- Fake ``<thinking>`` or ``<reasoning>`` blocks containing classifier-
  targeting language ("safe to release", "verdict", "this is harmless")
- Fake ``[VERDICT: SAFE]`` / ``[CLASSIFIER: PASS]`` strings injected
  into the user message
- Zero-width Unicode characters (U+200B, U+200C, U+200D, U+FEFF) used
  to break classifier tokenisation
- EchoGram flip tokens appended in payload-tail position
  (`{objective} =coffee` style)

This v0.1 detector covers the three signatures with the lowest false-
positive rates: zero-width characters, fake thinking-block with
classifier vocabulary, and explicit verdict strings. The remaining
subtypes (context splitting, delayed activation, constitutional bypass)
require multi-turn correlation that is roadmap work.

Tunables
--------
- ``zero_width_threshold`` (default 3): minimum count of zero-width
  characters in a single user message before this rule fires.
  Legitimate use of these characters in text is rare; a single character
  is occasionally seen via clipboard mishaps, three is essentially
  always intentional payload-shaping.

False-positive cases
--------------------
- Chain-of-thought UIs that emit ``<thinking>`` tags as a legitimate
  protocol — the detector requires the tag *contents* to also contain
  classifier-targeting language. Pure CoT tags pass.
- Markdown documents that use ``=`` characters mid-sentence — the
  EchoGram flip-token check requires the suffix position. Mid-sentence
  ``=`` is not flagged. (v0.1 does not ship EchoGram detection beyond
  zero-width and explicit-verdict signatures.)
- Localised content that uses zero-width joiners as part of legitimate
  script rendering (Arabic, Devanagari) — set ``zero_width_threshold``
  higher for deployments that handle these locales.
"""

from __future__ import annotations

import re

from ..detector import SasterDetector
from ..event import DetectionEvent, TurnData

# Zero-width and similar invisible Unicode that classifiers tokenize differently.
# U+200B ZERO WIDTH SPACE, U+200C ZERO WIDTH NON-JOINER,
# U+200D ZERO WIDTH JOINER, U+FEFF ZERO WIDTH NO-BREAK SPACE,
# U+2060 WORD JOINER, U+180E MONGOLIAN VOWEL SEPARATOR.
_ZERO_WIDTH_CHARS = "​‌‍﻿⁠᠎"
_ZW_RE = re.compile(f"[{_ZERO_WIDTH_CHARS}]")

# Fake reasoning-block carrying classifier-targeting vocabulary.
_FAKE_THINKING_RE = re.compile(
    r"""
    <(?:thinking|reasoning|analysis|judgement|judgment|verdict)
        [^>]*>
        [^<]{0,2000}?
        \b(?:classifier|verdict|harmless|safe\s+to\s+release|allow|allowed|approved|cleared|benign|pass)\b
        [^<]{0,2000}?
    </(?:thinking|reasoning|analysis|judgement|judgment|verdict)>
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)

# Explicit verdict / classifier-output strings injected into user content.
_FAKE_VERDICT_RE = re.compile(
    r"""
    \[
        (?:VERDICT|CLASSIFIER|JUDGE|SAFETY)
        \s*[:=]\s*
        (?:SAFE|PASS|ALLOWED|APPROVED|CLEAR(?:ED)?|HARMLESS|BENIGN|OK)
    \]
    """,
    re.IGNORECASE | re.VERBOSE,
)


class DetectionLayerInjectionDetector(SasterDetector):
    saster_id = "SASTER-27"
    pattern_name = "Detection Layer Injection"
    tier = 4

    def __init__(self, zero_width_threshold: int = 3) -> None:
        super().__init__()
        self._zw_threshold = zero_width_threshold

    def evaluate(self, turn: TurnData) -> DetectionEvent | None:
        probe = turn.user_message
        if not probe:
            return None

        zw_count = len(_ZW_RE.findall(probe))
        if zw_count >= self._zw_threshold:
            return self._build_event(
                turn,
                evidence={
                    "signal": "zero_width_unicode",
                    "detail": (
                        f"User message contains {zw_count} zero-width Unicode "
                        f"characters (threshold {self._zw_threshold}). Common "
                        f"shape for breaking classifier tokenisation."
                    ),
                    "count": zw_count,
                },
            )

        verdict_match = _FAKE_VERDICT_RE.search(probe)
        if verdict_match is not None:
            return self._build_event(
                turn,
                evidence={
                    "signal": "fake_verdict_string",
                    "detail": (
                        "User message contains a fake classifier verdict string "
                        "(e.g. [VERDICT: SAFE]). The model interprets this as "
                        "user content but a downstream classifier may interpret "
                        "it as authoritative output."
                    ),
                    "match": verdict_match.group(0),
                },
            )

        thinking_match = _FAKE_THINKING_RE.search(probe)
        if thinking_match is not None:
            return self._build_event(
                turn,
                evidence={
                    "signal": "fake_reasoning_block",
                    "detail": (
                        "User message contains a reasoning/thinking block whose "
                        "contents carry classifier-targeting vocabulary "
                        "(verdict, classifier, safe to release, etc.). Common "
                        "shape for scanner-simulation injection."
                    ),
                    "match": thinking_match.group(0)[:200],
                },
            )

        return None


DETECTOR = DetectionLayerInjectionDetector()
