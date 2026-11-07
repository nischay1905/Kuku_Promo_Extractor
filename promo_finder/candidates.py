import hashlib

class Candidate:
    def __init__(self, episode, segments, generator_source, start_time, end_time):
        self.episode = episode
        self.segments = segments
        self.generator_source = generator_source
        self.start_time = start_time
        self.end_time = end_time
        self.duration = sum(s.duration for s in segments)
        
        # Deterministic ID for deduplication
        id_string = f"{episode}_{start_time}_{end_time}_{generator_source}"
        self.candidate_id = hashlib.md5(id_string.encode()).hexdigest()[:10]

class CandidateUnion:
    def __init__(self, min_sec=20, max_sec=60):
        self.min_sec = min_sec
        self.max_sec = max_sec

    def generate(self, events, strategy="hybrid"):
        pool = []
        
        if strategy in ["baseline", "hybrid"]:
            pool.extend(self._generate_continuous_windows(events))
            pool.extend(self._generate_stitched_teasers(events))
            
        if strategy in ["semantic", "hybrid"]:
            pool.extend(self._generate_heuristic_hook_anchors(events))
            pool.extend(self._generate_cliffhanger_anchors(events))
            pool.extend(self._generate_confrontation_anchors(events))
            
        return self._deduplicate(pool)

    def _generate_continuous_windows(self, events):
        # Existing logic: sliding window checking features.py legal cuts
        pass

    def _generate_heuristic_hook_anchors(self, events):
        # Scan events for stakes words/delivery tags. Build 20-60s window around it.
        anchors = []
        for i, event in enumerate(events):
            if event.is_high_stakes:
                # Expand forward to valid cut
                anchors.append(self._build_legal_window(events, start_idx=i))
        return [a for a in anchors if a is not None]

    def _generate_confrontation_anchors(self, events):
        # Scan for rapid speaker alternation (power shifts)
        pass

    def _deduplicate(self, candidates):
        seen = set()
        unique = []
        for c in candidates:
            # Deduplicate by exact start/end time. Maintain primary generator source.
            time_signature = (c.start_time, c.end_time)
            if time_signature not in seen:
                seen.add(time_signature)
                unique.append(c)
        return unique