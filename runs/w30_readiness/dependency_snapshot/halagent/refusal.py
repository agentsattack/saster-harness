"""Standalone refusal classifier.

Minimum-viable: weighted pattern matching with a confidence score. Emits one of
four refusal_type values plus the triggering text span. Deliberately dependency-
free and self-contained so it can be lifted into other projects unchanged.

Taxonomy:
  hard_refusal       explicit decline to act ("I can't help with that")
  hedge              declines but offers a caveated/limited alternative
  partial_compliance refusal markers co-occurring with substantive content
  deflection         redirects elsewhere instead of acting ("consult a pro")
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Each pattern carries a weight. Patterns are scanned case-insensitively.
_PATTERNS: dict[str, list[tuple[str, float]]] = {
    "hard_refusal": [
        (r"\bI (?:can(?:'|no)t|cannot|won'?t|will not)\b[^.]{0,40}\b(?:help|assist|do|provide|comply|continue)\b", 0.9),
        (r"\bI'?m (?:not able|unable) to (?:help|assist|provide|do)\b", 0.85),
        (r"\bI (?:must|have to) (?:decline|refuse)\b", 0.9),
        (r"\b(?:that|this) (?:request|is|would be) (?:against|not something I can)\b", 0.6),
        (r"\bI'?m sorry,? but I (?:can'?t|cannot|won'?t)\b", 0.9),
    ],
    "hedge": [
        (r"\bI can'?t .{0,60}?, but I can\b", 0.8),
        (r"\bwhile I (?:can'?t|cannot) .{0,60}?, (?:I|here)\b", 0.7),
        (r"\bI'?m not comfortable\b", 0.6),
        (r"\bwithout more (?:context|information)[, ].{0,30}\bI (?:can'?t|won'?t)\b", 0.55),
    ],
    "deflection": [
        (r"\b(?:you should|I'?d recommend|please) (?:consult|contact|speak|reach out|talk) (?:to|with)\b", 0.75),
        (r"\bconsult (?:a|an|your) (?:professional|lawyer|doctor|expert|administrator)\b", 0.8),
        (r"\brefer (?:to|you to) (?:the )?(?:official|proper|appropriate)\b", 0.6),
    ],
}

# Markers that, when present alongside real content, indicate partial compliance.
_PARTIAL_MARKERS = re.compile(
    r"\b(?:I can'?t provide the full|only part|I'?ll (?:share|give) (?:a|some)|"
    r"limited|redacted|for safety I'?ve|I'?ve omitted)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RefusalResult:
    is_refusal: bool
    refusal_type: Optional[str] = None
    confidence: float = 0.0
    span: Optional[str] = None
    matched_pattern: Optional[str] = None

    def as_record(self) -> Optional[dict]:
        """Shape for the telemetry `refusal` field, or None if not a refusal."""
        if not self.is_refusal:
            return None
        return {
            "refusal_type": self.refusal_type,
            "confidence": round(self.confidence, 4),
            "span": self.span or "",
        }


class RefusalClassifier:
    def __init__(self) -> None:
        self._compiled: dict[str, list[tuple[re.Pattern, float]]] = {
            rtype: [(re.compile(p, re.IGNORECASE), w) for p, w in pats]
            for rtype, pats in _PATTERNS.items()
        }

    def classify(self, text: Optional[str]) -> RefusalResult:
        if not text:
            return RefusalResult(is_refusal=False)

        best: Optional[tuple[str, float, re.Match, str]] = None  # type, weight, match, pattern
        for rtype, pats in self._compiled.items():
            for pat, weight in pats:
                m = pat.search(text)
                if m and (best is None or weight > best[1]):
                    best = (rtype, weight, m, pat.pattern)

        if best is None:
            return RefusalResult(is_refusal=False)

        rtype, weight, match, pattern = best

        # Upgrade to partial_compliance if a decline marker coexists with a
        # substantial amount of other content (the model gave *something*).
        has_partial_marker = bool(_PARTIAL_MARKERS.search(text))
        substantive = len(text) > 400 or text.count("\n") > 6
        if has_partial_marker and substantive:
            rtype = "partial_compliance"
            weight = max(weight, 0.7)

        return RefusalResult(
            is_refusal=True,
            refusal_type=rtype,
            confidence=min(weight, 1.0),
            span=match.group(0),
            matched_pattern=pattern,
        )
