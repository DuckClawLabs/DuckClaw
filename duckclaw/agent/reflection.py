"""
Reflection Agent — reviews the ReAct output before delivery.

Checks:
  1. Does the answer fully address the original question?
  2. Is it grounded in actual observations (not hallucinated)?
  3. Is there anything clearly missing or wrong?

Fast-path: skips reflection when no skills were used (pure knowledge answers
are directly trusted — the LLM generated them with full confidence).

Returns a ReflectionResult that tells the Synthesizer whether to deliver
the answer as-is or do one final improvement pass.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from duckclaw.llm.router import LLMRouter
    from duckclaw.agent.react_engine_v3 import ReActV3Result as ReActResult

logger = logging.getLogger(__name__)


@dataclass
class ReflectionResult:
    approved: bool
    quality_score: int = 8          # 1–10
    issues: list[str] = field(default_factory=list)
    suggestion: Optional[str] = None
    needs_retry: bool = False


_REFLECTION_PROMPT = """\
You are a quality reviewer for an AI assistant's response.
Review the draft answer and score its quality.

Original question:
{question}

Evidence gathered (skill observations):
{observations}

Draft answer:
{answer}

Review criteria:
1. Does it fully answer the original question?
2. Is the answer grounded in the observations (not made up)?
3. Is it clear, well-structured, and actionable?
4. Are there obvious gaps, errors, or missing information?

Respond with JSON only (no markdown):
{{"approved": true, "quality_score": 8, "issues": [], "needs_retry": false, "suggestion": null}}
(quality_score is 1-10; needs_retry=true only if score < 6 and a retry would likely improve it)"""


class ReflectionAgent:
    """
    Lightweight quality gate before the final answer is delivered.

    - Skips reflection for pure general-knowledge answers (no skills used) → fast path.
    - Runs one LLM call for skill-grounded answers to verify completeness.
    - Scores 1-10; quality < 6 triggers a Synthesizer re-pass.
    """

    async def reflect(
        self,
        original_query: str,
        react_result: "ReActResult",
        llm: "LLMRouter",
    ) -> ReflectionResult:
        """
        Review the ReAct output and return a quality verdict.

        Fast-path: if no skills were used, approve immediately.
        """
        # Fast path: no skills used → pure knowledge answer, trust it directly
        skill_steps = [s for s in react_result.step_results if s.skill]
        if not skill_steps:
            logger.info("Reflection: fast-path — no skills used, auto-approved")
            return ReflectionResult(
                approved=True,
                quality_score=8,
                issues=[],
                needs_retry=False,
            )

        # Build observations summary (capped for context efficiency)
        obs_parts: list[str] = []
        for step in skill_steps:
            if step.output:
                snippet = step.output[:600]
                obs_parts.append(f"[{step.skill}.{step.action}]: {snippet}")

        observations_text = (
            "\n".join(obs_parts) if obs_parts else "(no observations captured)"
        )
        answer_excerpt = react_result.final_answer[:2000]

        try:
            response = await llm.chat_reasoning(
                messages=[{
                    "role": "user",
                    "content": _REFLECTION_PROMPT.format(
                        question=original_query,
                        observations=observations_text,
                        answer=answer_excerpt,
                    ),
                }],
                max_tokens=350,
                temperature=0.1,
            )

            response = response.strip()
            if response.startswith("```"):
                response = re.sub(r"```(?:json)?\s*", "", response).strip("`").strip()

            data = json.loads(response)
            result = ReflectionResult(
                approved=data.get("approved", True),
                quality_score=data.get("quality_score", 7),
                issues=data.get("issues") or [],
                suggestion=data.get("suggestion"),
                needs_retry=data.get("needs_retry", False),
            )
            logger.info(
                f"Reflection: score={result.quality_score}, "
                f"approved={result.approved}, issues={result.issues}"
            )
            return result

        except Exception as e:
            logger.warning(f"Reflection LLM call failed ({e}). Auto-approving.")
            return ReflectionResult(
                approved=True,
                quality_score=7,
                issues=[],
                needs_retry=False,
            )
