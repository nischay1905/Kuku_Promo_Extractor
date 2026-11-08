"""Generate and score continuous, stitched, and semantic promo candidates."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .features import EpisodeIndex, WindowFeatures
from .semantics import extract_semantic_anchors

MIN_DUR, MAX_DUR = 20.0, 60.0
DEFAULT_WEIGHTS = {"hook": 0.28, "cliff": 0.28, "intensity": 0.14, "pace": 0.10, "standalone": 0.12, "dur": 0.08}
FLAG_PENALTY = {"sexual-content": 0.15, "violence/torture": 0.03}
STITCH_PENALTY = 0.07
STITCH_GAP_MIN = 8.0


@dataclass
class Candidate:
    ep: int
    segments: list[tuple[float, float]]
    kind: str
    f: WindowFeatures
    score: float
    parts: dict = field(default_factory=dict)
    llm: dict = field(default_factory=dict)
    candidate_id: str = field(default="")

    def __post_init__(self):
        if not self.candidate_id:
            signature = f"{self.ep}_{self.segments[0][0]}_{self.segments[-1][1]}"
            self.candidate_id = hashlib.md5(signature.encode()).hexdigest()[:10]

    @property
    def duration(self) -> float:
        return sum(end - start for start, end in self.segments)


def total_score(features: WindowFeatures, weights: dict) -> tuple[float, dict]:
    parts = {
        "hook": features.hook, "cliff": features.cliff,
        "intensity": features.intensity, "pace": features.pace,
        "standalone": features.standalone, "dur": features.dur_pref,
    }
    score = sum(weights[key] * value for key, value in parts.items())
    for flag in features.flags:
        score -= FLAG_PENALTY.get(flag, 0.0)
    return score, parts


def _make_candidate(ix, spans, hook_start, weights, kind):
    features = WindowFeatures()
    features.hook = ix.hook(hook_start, features)
    last_start, last_end = spans[-1]
    features.cliff = ix.cliff(last_end, last_start, features)
    ix.body(spans, features)
    if features.n_lines < 3:
        return None
    score, parts = total_score(features, weights)
    return Candidate(ix.ep.number, list(spans), kind, features, score, parts)


def continuous(ix, weights, min_d=MIN_DUR, max_d=MAX_DUR):
    candidates = []
    for start in ix.starts:
        for end in ix.ends:
            duration = end - start
            if duration < min_d:
                continue
            if duration > max_d:
                break
            candidate = _make_candidate(ix, [(start, end)], start, weights, "continuous")
            if candidate:
                candidates.append(candidate)
    return candidates


def stitched(ix, weights, bodies_pool=None):
    teasers = []
    for start in ix.starts:
        probe = WindowFeatures()
        hook_score = ix.hook(start, probe)
        if hook_score < 0.6:
            continue
        best = None
        for end in ix.ends:
            if 4.0 <= end - start <= 12.0 and len(ix.lines_in(start, end)) >= 1:
                probe_features = WindowFeatures()
                cliff_score = ix.cliff(end, start, probe_features)
                if best is None or cliff_score > best[0]:
                    best = (cliff_score, end)
        if best:
            teasers.append((hook_score, start, best[1]))

    teasers.sort(reverse=True)
    teasers = teasers[:6]
    bodies = [
        candidate for candidate in (
            bodies_pool if bodies_pool is not None else continuous(ix, weights, 14.0, 46.0)
        )
        if candidate.f.cliff >= 0.45 and 14.0 <= candidate.duration <= 46.0
    ]
    bodies.sort(
        key=lambda candidate: 0.6 * candidate.f.cliff
        + 0.2 * candidate.f.intensity + 0.2 * candidate.f.standalone,
        reverse=True,
    )
    bodies = bodies[:12]

    output = []
    for _, teaser_start, teaser_end in teasers:
        for body in bodies:
            body_start, body_end = body.segments[0]
            gap = body_start - teaser_end
            duration = (teaser_end - teaser_start) + (body_end - body_start)
            if gap < STITCH_GAP_MIN or not (MIN_DUR <= duration <= MAX_DUR):
                continue
            candidate = _make_candidate(
                ix, [(teaser_start, teaser_end), (body_start, body_end)],
                teaser_start, weights, "stitched",
            )
            if not candidate:
                continue
            teaser_speakers = {line.who for line in ix.lines_in(teaser_start, teaser_end)}
            body_speakers = {line.who for line in ix.lines_in(body_start, body_end)}
            if not (teaser_speakers & body_speakers):
                continue
            candidate.score -= STITCH_PENALTY + min(0.04, 0.001 * gap)
            output.append(candidate)
    return output


class CandidateUnion:
    """Combine baseline candidates with legal windows grounded around story beats."""

    def __init__(self, min_sec=MIN_DUR, max_sec=MAX_DUR, max_anchors=12, windows_per_anchor=3):
        self.min_sec = float(min_sec)
        self.max_sec = float(max_sec)
        self.max_anchors = int(max_anchors)
        self.windows_per_anchor = int(windows_per_anchor)

    def generate(self, ix, weights, strategy="hybrid", use_stitch=True):
        if strategy not in {"baseline", "semantic", "hybrid"}:
            raise ValueError("strategy must be 'baseline', 'semantic', or 'hybrid'")

        pool = []
        if strategy in {"baseline", "hybrid"}:
            pool.extend(continuous(ix, weights))
            if use_stitch:
                pool.extend(stitched(ix, weights))
        if strategy in {"semantic", "hybrid"}:
            pool.extend(self._generate_semantic_anchors(ix, weights))
        return self._deduplicate(pool)

    def _generate_semantic_anchors(self, ix, weights):
        """Generate legal 20-60s windows containing detected narrative events."""
        anchors = extract_semantic_anchors(ix.ep.events)
        output = []

        for anchor in sorted(anchors, key=lambda item: item.confidence, reverse=True)[:self.max_anchors]:
            eligible_starts = [
                start for start in ix.starts
                if start <= anchor.start and anchor.start - start <= self.max_sec - self.min_sec
            ]
            eligible_ends = [end for end in ix.ends if end >= anchor.end]
            proposals = []

            for start in eligible_starts:
                min_end = max(anchor.end, start + self.min_sec)
                max_end = min(start + self.max_sec, ix.duration)
                possible_ends = [end for end in eligible_ends if min_end <= end <= max_end]
                if not possible_ends:
                    continue

                target_end = min(max(start + 40.0, min_end), max_end)
                end = min(possible_ends, key=lambda value: abs(value - target_end))
                proposals.append((abs((end - start) - 40.0), start, end))

            proposals.sort()
            for _, start, end in proposals[:self.windows_per_anchor]:
                candidate = _make_candidate(
                    ix, [(start, end)], start, weights, "semantic_anchor"
                )
                if candidate is None:
                    continue

                bonus = 0.06 * anchor.confidence
                candidate.score = min(1.0, candidate.score + bonus)
                candidate.parts.update({
                    "semantic_anchor": anchor.confidence,
                    "semantic_bonus": round(bonus, 4),
                    "semantic_categories": [category.value for category in anchor.categories],
                    "semantic_explanation": anchor.explanation,
                    "semantic_event_idx": anchor.event_idx,
                })
                output.append(candidate)

        output.sort(key=lambda candidate: candidate.score, reverse=True)
        return output

    def _deduplicate(self, candidates):
        seen = set()
        unique = []
        for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
            signature = tuple(
                (round(start, 2), round(end, 2))
                for start, end in candidate.segments
            )
            if signature not in seen:
                seen.add(signature)
                unique.append(candidate)
        return unique


def overlap(a, b):
    overlap_seconds = 0.0
    for start_a, end_a in a.segments:
        for start_b, end_b in b.segments:
            overlap_seconds += max(
                0.0, min(end_a, end_b) - max(start_a, start_b)
            )
    return overlap_seconds / max(1e-6, min(a.duration, b.duration))


def nms(candidates, k, max_overlap=0.25):
    ranked = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    selected = []
    for candidate in ranked:
        if all(overlap(candidate, kept) <= max_overlap for kept in selected):
            selected.append(candidate)
            if len(selected) >= k:
                break
    return selected


def find_for_episode(ix, weights=None, per_ep=3, use_stitch=True, strategy="baseline"):
    weights = weights or DEFAULT_WEIGHTS
    if strategy in {"semantic", "hybrid"}:
        pool = CandidateUnion().generate(
            ix, weights, strategy=strategy, use_stitch=use_stitch
        )
    else:
        pool = continuous(ix, weights)
        if use_stitch:
            pool += stitched(ix, weights)
    return nms(pool, per_ep)
