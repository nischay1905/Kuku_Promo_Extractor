import os
import asyncio
from pydantic import BaseModel, Field
from typing import List, Optional

# --- 1. Structured Output Schemas ---

class HookEvaluation(BaseModel):
    attention_grab_explanation: str = Field(description="Why the first 3 seconds attract or fail to attract attention.")
    evidence_event_ids: List[str] = Field(description="Exact event IDs from the text supporting the hook.")
    is_generic: bool = Field(description="True if the opening is a generic conversation, False if genuinely intriguing.")
    score: int = Field(ge=1, le=5, description="Hook strength from 1 to 5. 1=Boring, 5=Scroll-stopping.")

class CliffhangerEvaluation(BaseModel):
    unresolved_state: str = Field(description="What exact outcome remains unknown at the end?")
    viewer_question: str = Field(description="The primary question a viewer has when the clip cuts to black.")
    reveals_too_much: bool = Field(description="True if the ending gives away the twist instead of teasing it.")
    score: int = Field(ge=1, le=5, description="Cliffhanger tension from 1 to 5.")

class StandaloneContextEvaluation(BaseModel):
    missing_info: str = Field(description="What information is missing for a first-time viewer?")
    unintroduced_entities: List[str] = Field(description="Characters or concepts referenced but not explained.")
    score: int = Field(ge=1, le=5, description="5=Completely understandable standalone, 1=Confusing without watching prior episodes.")

# --- 2. Independent Async Evaluators ---

class SpecializedJudges:
    def __init__(self, provider_client):
        self.client = provider_client # Supports OpenAI/Anthropic SDKs
    
    async def evaluate_candidate(self, candidate_text: str):
        """Runs specialized judges concurrently to avoid prompt-dilution."""
        
        # Parallel execution of LLM calls
        hook_task = self._run_judge("hook_prompt_v1", HookEvaluation, candidate_text)
        cliff_task = self._run_judge("cliff_prompt_v1", CliffhangerEvaluation, candidate_text)
        context_task = self._run_judge("context_prompt_v1", StandaloneContextEvaluation, candidate_text)
        
        hook_res, cliff_res, context_res = await asyncio.gather(hook_task, cliff_task, context_task)
        
        return {
            "hook": hook_res.model_dump(),
            "cliffhanger": cliff_res.model_dump(),
            "standalone": context_res.model_dump(),
            # Convert 1-5 scales to deterministic 0-100 metric internally
            "hybrid_quality_score": self._compute_weighted_score(hook_res.score, cliff_res.score, context_res.score)
        }

    async def _run_judge(self, system_prompt, schema, text):
        # Implementation using provider's structured output API (e.g. OpenAI's response_format)
        pass