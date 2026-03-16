"""
Response Synthesizer — final answer composer.

Invoked after Reflection. Two paths:

  Fast path  : Reflection approved (score ≥ 7)  → return ReAct final_answer as-is.
  Polish path: Reflection flagged issues (score < 7) → one final LLM pass that
               takes all observations + the reflection feedback and writes a
               better-grounded, complete answer.

The synthesizer is intentionally lightweight. The ReAct engine does the heavy
lifting — this is just a quality-improvement layer, not another reasoning loop.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from duckclaw.llm.router import LLMRouter
    from duckclaw.agent.react_engine_v3 import ReActV3Result as ReActResult
    from duckclaw.agent.reflection import ReflectionResult

logger = logging.getLogger(__name__)

_SYNTHESIZER_SYSTEM_PROMPT = """\
You are DuckClaw's response synthesizer. Your job is to write a clear, complete, \
well-structured final answer for the user.

You have been given:
- The original question
- All evidence/observations gathered during research
- Feedback from a quality reviewer

Write a comprehensive answer that:
1. Directly addresses the original question
2. Is grounded in the observations (cite sources/findings where relevant)
3. Is well-formatted with markdown (headers, bullets, code blocks where useful)
4. Is concise but complete — no filler, no repetition

Reviewer feedback: {feedback}"""


class ResponseSynthesizer:
    """
    Delivers the final answer to the user.

    Fast-path (most common): reflection approved → return as-is, no extra LLM call.
    Polish-path: reflection flagged issues → one rewrite pass using all evidence.
    """

    async def synthesize(
        self,
        original_query: str,
        react_result: "ReActResult",
        reflection: "ReflectionResult",
        llm: "LLMRouter",
    ) -> str:
        """
        Return the final answer string for delivery to the user.
        """
        # ── Fast path: reflection approved ────────────────────────────────
        if reflection.approved and reflection.quality_score >= 7:
            logger.info(
                f"Synthesizer: fast-path — reflection score={reflection.quality_score}, "
                "returning ReAct answer directly"
            )
            return react_result.final_answer

        # ── Polish path: rewrite with evidence and reviewer hints ─────────
        logger.info(
            f"Synthesizer: polish-path — score={reflection.quality_score}, "
            f"issues={reflection.issues}"
        )

        # Compile all skill observations as evidence
        evidence_parts: list[str] = []
        for step in react_result.step_results:
            if step.skill and step.output:
                evidence_parts.append(
                    f"### Evidence: {step.skill}.{step.action}\n"
                    f"{step.output[:1500]}"
                )

        evidence_text = "\n\n".join(evidence_parts) if evidence_parts else ""

        # Build reviewer feedback summary
        feedback_parts: list[str] = []
        if reflection.issues:
            feedback_parts.append("Issues found: " + "; ".join(reflection.issues))
        if reflection.suggestion:
            feedback_parts.append("Suggestion: " + reflection.suggestion)
        feedback_text = " | ".join(feedback_parts) if feedback_parts else "Minor quality improvements needed."

        # Compose messages for the rewrite call
        messages = []
        if evidence_text:
            messages.append({
                "role": "user",
                "content": f"Research evidence gathered:\n\n{evidence_text}",
            })
            messages.append({
                "role": "user",
                "content": (
                    f"Original question: {original_query}\n\n"
                    f"Previous draft (needs improvement):\n{react_result.final_answer[:1000]}\n\n"
                    "Please write an improved, complete final answer using the evidence above."
                ),
            })
        else:
            messages.append({
                "role": "user",
                "content": (
                    f"Question: {original_query}\n\n"
                    f"Draft answer: {react_result.final_answer}\n\n"
                    f"Please improve this answer. {feedback_text}"
                ),
            })

        try:
            improved = await llm.chat_reasoning(
                messages=messages,
                system_prompt=_SYNTHESIZER_SYSTEM_PROMPT.format(feedback=feedback_text),
                max_tokens=2500,
                temperature=0.4,
            )
            logger.info("Synthesizer: polish-path completed successfully")
            return improved
        except Exception as e:
            logger.error(f"Synthesizer rewrite failed ({e}). Returning original ReAct answer.")
            return react_result.final_answer
