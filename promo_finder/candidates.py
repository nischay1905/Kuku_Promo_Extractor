"""Generate and score candidate promos for one episode.

Two kinds:
  continuous : one stretch [s, e], 20-60 s, starts on a shot cut, ends on a legal cut (never mid-line)
  stitched   : 'teaser + payoff' = a short high-hook clip, then a skip, then a run that ends on the cliffhanger
Cross-episode joins are NOT generated (see README, limitations).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .features import EpisodeIndex, WindowFeatures, clip

MIN_DUR, MAX_DUR = 20.0, 60.0

DEFAULT_WEIGHTS = {"hook": 0.28, "cliff": 0.28, "intensity": 0.14, "pace": 0.10, "standalone": 0.12, "dur": 0.08}
FLAG_PENALTY = {"sexual-content": 0.15, "violence/torture": 0.03}
STITCH_PENALTY = 0.07          # stitched must clearly beat a continuous cut to be chosen
STITCH_GAP_MIN = 8.0


@dataclass
class Candidate:
    ep: int
    segments: list[tuple[float, float]]
    kind: str
    f: WindowFeatures
    score: float
    parts: dict = field(default_factory=dict)
    llm: dict = field(default_factory=dict)      # filled by the optional LLM stage
    candidate_id: str = field(default="")

    def __post_init__(self):
        if not self.candidate_id:
            time_sig = f"{self.ep}_{self.segments[0][0]}_{self.segments[-1][1]}"
            self.candidate_id = hashlib.md5(time_sig.encode()).hexdigest()[:10]

    @property
    def duration(self) -> float:
        return sum(e - s for s, e in self.segments)


def total_score(f: WindowFeatures, w: dict) -> tuple[float, dict]:
    parts = {"hook": f.hook, "cliff": f.cliff, "intensity": f.intensity, "pace": f.pace,
             "standalone": f.standalone, "dur": f.dur_pref}
    s = sum(w[k] * v for k, v in parts.items())
    for fl in f.flags:
        s -= FLAG_PENALTY.get(fl, 0.0)
    return s, parts


def _mk(ix: EpisodeIndex, spans: list[tuple[float, float]], hook_s: float, w: dict, kind: str) -> Candidate | None:
    f = WindowFeatures()
    f.hook = ix.hook(hook_s, f)
    last_s, last_e = spans[-1]
    f.cliff = ix.cliff(last_e, last_s, f)
    ix.body(spans, f)
    if f.n_lines < 3:
        return None
    sc, parts = total_score(f, w)
    return Candidate(ix.ep.number, list(spans), kind, f, sc, parts)


def continuous(ix: EpisodeIndex, w: dict, min_d: float = MIN_DUR, max_d: float = MAX_DUR) -> list[Candidate]:
    out = []
    for s in ix.starts:
        for e in ix.ends:
            d = e - s
            if d < min_d:
                continue
            if d > max_d:
                break
            c = _mk(ix, [(s, e)], s, w, "continuous")
            if c:
                out.append(c)
    return out


def stitched(ix: EpisodeIndex, w: dict, bodies_pool: list[Candidate] | None = None) -> list[Candidate]:
    teasers = []
    for s in ix.starts:
        probe = WindowFeatures()
        h = ix.hook(s, probe)
        if h < 0.6:
            continue
        best = None
        for e in ix.ends:
            if 4.0 <= e - s <= 12.0 and len(ix.lines_in(s, e)) >= 1:
                pf = WindowFeatures()
                c = ix.cliff(e, s, pf)
                if best is None or c > best[0]:
                    best = (c, e)
        if best:
            teasers.append((h, s, best[1]))
    teasers.sort(reverse=True)
    teasers = teasers[:6]
    bodies = [c for c in (bodies_pool if bodies_pool is not None else continuous(ix, w, 14.0, 46.0))
              if c.f.cliff >= 0.45 and 14.0 <= c.duration <= 46.0]
    bodies.sort(key=lambda c: 0.6 * c.f.cliff + 0.2 * c.f.intensity + 0.2 * c.f.standalone, reverse=True)
    bodies = bodies[:12]
    out = []
    for h, ts, te in teasers:
        for b in bodies:
            bs, be = b.segments[0]
            gap = bs - te
            total = (te - ts) + (be - bs)
            if gap < STITCH_GAP_MIN or not (MIN_DUR <= total <= MAX_DUR):
                continue
            c = _mk(ix, [(ts, te), (bs, be)], ts, w, "stitched")
            if not c:
                continue
            t_sp = {l.who for l in ix.lines_in(ts, te)}
            b_sp = {l.who for l in ix.lines_in(bs, be)}
            if not (t_sp & b_sp):
                continue
            c.score -= STITCH_PENALTY + min(0.04, 0.001 * gap)
            out.append(c)
    return out


class CandidateUnion:
    """Advanced Candidate Union architecture for V2 semantic retrieval."""
    def __init__(self, min_sec=MIN_DUR, max_sec=MAX_DUR):
        self.min_sec = min_sec
        self.max_sec = max_sec

    def generate(self, ix: EpisodeIndex, w: dict, strategy: str = "hybrid", use_stitch: bool = True) -> list[Candidate]:
        pool = []
        if strategy in ["baseline", "hybrid"]:
            pool.extend(continuous(ix, w))
            if use_stitch:
                pool.extend(stitched(ix, w))
        if strategy in ["semantic", "hybrid"]:
            pool.extend(self._generate_semantic_anchors(ix, w))
        return self._deduplicate(pool)

    def _generate_semantic_anchors(self, ix: EpisodeIndex, w: dict) -> list[Candidate]:
        anchors = []
        # Leverages high-stakes detection points for semantic event grounding
        for s in ix.starts:
            for e in ix.ends:
                if self.min_sec <= (e - s) <= self.max_sec:
                    c = _mk(ix, [(s, e)], s, w, "semantic_anchor")
                    if c and c.f.hook >= 0.5:
                        anchors.append(c)
        return anchors[:10]

    def _deduplicate(self, candidates: list[Candidate]) -> list[Candidate]:
        seen = set()
        unique = []
        for c in candidates:
            sig = tuple(c.segments)
            if sig not in seen:
                seen.add(sig)
                unique.append(c)
        return unique


def overlap(a: Candidate, b: Candidate) -> float:
    ov = 0.0
    for s1, e1 in a.segments:
        for s2, e2 in b.segments:
            ov += max(0.0, min(e1, e2) - max(s1, s2))
    return ov / max(1e-6, min(a.duration, b.duration))


def nms(cands: list[Candidate], k: int, max_overlap: float = 0.25) -> list[Candidate]:
    cands = sorted(cands, key=lambda c: c.score, reverse=True)
    keep: list[Candidate] = []
    for c in cands:
        if all(overlap(c, k_) <= max_overlap for k_ in keep):
            keep.append(c)
            if len(keep) >= k:
                break
    return keep


def find_for_episode(ix: EpisodeIndex, w: dict | None = None, per_ep: int = 3, use_stitch: bool = True, strategy: str = "baseline") -> list[Candidate]:
    w = w or DEFAULT_WEIGHTS
    if strategy in ["semantic", "hybrid"]:
        union_gen = CandidateUnion()
        pool = union_gen.generate(ix, w, strategy=strategy, use_stitch=use_stitch)
    else:
        cont = continuous(ix, w)
        pool = cont + (stitched(ix, w) if use_stitch else [])
    return nms(pool, per_ep)
