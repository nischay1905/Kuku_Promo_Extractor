import random
import math

class PairwiseRanker:
    def __init__(self, judge_client, max_comparisons_per_ep=10):
        self.judge = judge_client
        self.max_comps = max_comparisons_per_ep
        
    def rank_candidates(self, candidates: List[dict]) -> List[dict]:
        """Ranks shortlisted candidates using Elo-style pairwise comparisons."""
        
        # 1. Preselect the top N candidates based on absolute judge scores to save API costs
        shortlist = sorted(candidates, key=lambda x: x['hybrid_quality_score'], reverse=True)[:5]
        
        # Initialize Elo ratings
        ratings = {c['candidate_id']: 1200 for c in shortlist}
        
        # 2. Adaptive Tournament
        comparisons_made = 0
        for i in range(len(shortlist)):
            for j in range(i + 1, len(shortlist)):
                if comparisons_made >= self.max_comps:
                    break
                    
                c1, c2 = shortlist[i], shortlist[j]
                
                # Randomize order to prevent LLM position bias (A-bias)
                is_reversed = random.choice([True, False])
                if is_reversed:
                    winner_id = self._llm_compare(c2, c1)
                else:
                    winner_id = self._llm_compare(c1, c2)
                
                # Update Elo ratings based on match result
                self._update_elo(ratings, c1['candidate_id'], c2['candidate_id'], winner_id)
                comparisons_made += 1
                
        # 3. Return candidates sorted by their final Elo rating
        return sorted(shortlist, key=lambda x: ratings[x['candidate_id']], reverse=True)

    def _llm_compare(self, cand_a, cand_b) -> str:
        """
        Prompts the LLM: 'Which candidate would be more compelling on TikTok?'
        Returns the winning candidate_id, or None if tied.
        """
        pass