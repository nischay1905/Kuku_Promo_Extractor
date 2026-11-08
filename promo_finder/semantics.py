"""Lightweight semantic event detection for screenplay events.

Uses transparent, editable lexical rules. Each anchor points to an original
parsed event and retains its timestamps; no timestamps are invented.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class EventCategory(str, Enum):
    REVELATION = "revelation"
    BETRAYAL = "betrayal"
    POWER_SHIFT = "power_shift"
    ROMANTIC_TENSION = "romantic_tension"
    THREAT = "threat"


@dataclass(frozen=True)
class SemanticEvent:
    event_idx: int
    start: float
    end: float
    categories: tuple[EventCategory, ...]
    confidence: float
    explanation: str
    text: str = ""


_CATEGORY_PATTERNS = {
    EventCategory.REVELATION: re.compile(
        r"\b(reveal\w*|confess\w*|secret|truth|identity|impost(?:er|or)|unmask\w*|"
        r"it was you|i am your|i'm your|you are the)\b", re.I
    ),
    EventCategory.BETRAYAL: re.compile(
        r"\b(betray\w*|deceiv\w*|double.cross\w*|lied to|sold out|backstab\w*|"
        r"abandon\w*|disown\w*|set me up)\b", re.I
    ),
    EventCategory.POWER_SHIFT: re.compile(
        r"\b(inherit\w*|heir|take command|take control|you are dismissed|kneel|"
        r"your title|crown|throne|promot\w*|demot\w*|now i am|from now on|"
        r"you answer to me)\b", re.I
    ),
    EventCategory.ROMANTIC_TENSION: re.compile(
        r"\b(love you|marry|wedding|bride|groom|kiss\w*|jealous\w*|engaged|"
        r"fianc\w*|heart belongs|choose me|can't live without)\b", re.I
    ),
    EventCategory.THREAT: re.compile(
        r"\b(kill\w*|murder\w*|dead|death|poison\w*|execute\w*|hang\w*|gallows|"
        r"destroy\w*|you will pay|make you suffer|i will find you|threat\w*|"
        r"arrest\w*|imprison\w*|dungeon)\b", re.I
    ),
}


def extract_semantic_anchors(episode_events: Iterable) -> list[SemanticEvent]:
    """Detect narrative beats and retain their original event indices/timestamps."""
    anchors: list[SemanticEvent] = []
    for idx, event in enumerate(episode_events):
        text = (getattr(event, "text", "") or "").strip()
        if not text:
            continue

        categories = tuple(
            category for category, pattern in _CATEGORY_PATTERNS.items()
            if pattern.search(text)
        )
        if not categories:
            continue

        confidence = min(0.92, 0.48 + 0.12 * (len(categories) - 1))
        if getattr(event, "kind", "") == "DIALOGUE":
            confidence = min(0.95, confidence + 0.03)

        explanation = "Detected " + ", ".join(
            category.value.replace("_", " ") for category in categories
        )
        anchors.append(SemanticEvent(
            event_idx=idx,
            start=float(getattr(event, "start", 0.0)),
            end=float(getattr(event, "end", getattr(event, "start", 0.0))),
            categories=categories,
            confidence=round(confidence, 3),
            explanation=explanation,
            text=text[:240],
        ))

    return sorted(anchors, key=lambda item: (item.start, -item.confidence))
