"""
Intent Analyzer — classifies every query before execution.

Three intent types:
  - general     : Answer from LLM knowledge alone (no skills needed)
  - skill_single: One skill call is sufficient
  - skill_multi : Multiple skills or a multi-step plan required

Strategy: fast keyword heuristics first, LLM fallback only for ambiguous
          high-complexity queries (avoids an extra round-trip on simple tasks).
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class IntentResult:
    query_type: str                          # "general" | "skill_single" | "skill_multi"
    skills_likely: list[str] = field(default_factory=list)
    complexity: str = "low"                  # "low" | "medium" | "high"
    needs_planning: bool = False
    reasoning: str = ""


# ── Heuristic keyword tables ──────────────────────────────────────────────────

SKILL_KEYWORDS: dict[str, list[str]] = {
    "web_search": [
        "search", "find online", "look up", "google", "web", "internet",
        "latest news", "current news", "news about", "today's", "price of",
        "what is happening", "recent", "trending", "top results",
    ],
    "web_browser": [
        "open website", "go to url", "navigate to", "browse to", "visit",
        "open page", "scrape", "extract from", "read the page",
    ],
    "file_manager": [
        "read file", "write file", "create file", "list files", "open file",
        "save to", "delete file", "show file", "directory", "folder",
        "in my documents", "local file", "read the contents",
    ],
    "shell_runner": [
        "run command", "execute", "terminal", "shell", "git status", "git log",
        "install package", "pip install", "run script", "bash", "cmd",
        "check git", "git diff", "run python",
    ],
    "screen_capture": [
        "screenshot", "screen capture", "take a screenshot",
        "what's on my screen", "capture screen", "look at screen",
    ],
    "camera": [
        "take photo", "webcam", "camera", "take picture", "snap photo",
        "look at me", "see me",
    ],
    "scheduler": [
        "remind me", "schedule", "set reminder", "set alarm",
        "every day", "daily", "weekly", "cron", "at what time",
        "in 10 minutes", "morning briefing",
    ],
}

# Strongly suggests the task is multi-step
MULTI_STEP_INDICATORS = [
    "and then", "after that", "also", "additionally", "followed by",
    "step by step", "create and", "build and", "find and save",
    "search and write", "plan and execute", "set up", "build a project",
    "create a project", "build me a", "multiple", "several", "first",
    "then", "finally", "put it all together",
]

# Strongly suggests a pure knowledge / general question
GENERAL_INDICATORS = [
    "what is", "what are", "explain", "how does", "how do",
    "define", "tell me about", "describe", "why is", "why are",
    "when was", "who is", "history of", "difference between",
    "compare", "give me an example", "write a poem", "write a story",
    "write an essay", "joke", "riddle", "calculate", "solve",
    "help me understand", "what does", "summarize", "pros and cons",
    "advantages", "disadvantages", "hello", "hi ", "thanks", "thank you",
    "good morning", "good evening",
]

_LLM_CLASSIFY_PROMPT = """\
You are an intent classifier for an AI assistant.
The assistant has these skills: web_search, web_browser, file_manager, shell_runner, screen_capture, camera, scheduler.

Classify this query:
"{message}"

Types:
- "general"      → can be answered from knowledge alone, no skills needed
- "skill_single" → needs exactly one skill call
- "skill_multi"  → needs multiple skill calls or a complex multi-step plan

Respond with JSON only (no markdown):
{{"type":"general|skill_single|skill_multi","skills_likely":[],"complexity":"low|medium|high","reasoning":"one line"}}"""


class IntentAnalyzer:
    """
    Classifies query intent to route to the right execution pipeline.

    Fast heuristic path handles ~90% of queries.
    LLM path is only triggered for high-complexity ambiguous cases.
    """

    async def analyze(self, message: str, llm=None) -> IntentResult:
        """Classify intent. Returns IntentResult."""
        msg_lower = message.lower().strip()
        result = self._heuristic_classify(msg_lower)
        logger.info(
            f"IntentAnalyzer (heuristic): type={result.query_type}, "
            f"complexity={result.complexity}, skills={result.skills_likely}"
        )

        # Use LLM to sharpen classification only for high-complexity queries
        if result.complexity == "high" and llm is not None:
            try:
                llm_result = await self._llm_classify(message, llm)
                logger.info(
                    f"IntentAnalyzer (LLM override): type={llm_result.query_type}, "
                    f"reasoning={llm_result.reasoning}"
                )
                return llm_result
            except Exception as e:
                logger.warning(f"LLM intent classification failed, using heuristic: {e}")

        return result

    # ── Heuristic classifier ──────────────────────────────────────────────────

    def _heuristic_classify(self, msg: str) -> IntentResult:
        """Fast rule-based classification — no LLM call."""

        is_multi_step = any(indicator in msg for indicator in MULTI_STEP_INDICATORS)

        skills_found: list[str] = []
        for skill_name, keywords in SKILL_KEYWORDS.items():
            if any(kw in msg for kw in keywords):
                skills_found.append(skill_name)

        is_general = any(indicator in msg for indicator in GENERAL_INDICATORS)

        # Clear general-knowledge question, no skill signals
        if not skills_found and is_general:
            return IntentResult(
                query_type="general",
                complexity="low",
                needs_planning=False,
                reasoning="General knowledge — no skill keywords found",
            )

        # No skill signals, not obviously general → treat short messages as general,
        # longer ones might benefit from web_search
        if not skills_found:
            if len(msg) < 60:
                return IntentResult(
                    query_type="general",
                    complexity="low",
                    needs_planning=False,
                    reasoning="Short ambiguous query — treating as general",
                )
            return IntentResult(
                query_type="skill_single",
                skills_likely=["web_search"],
                complexity="medium",
                needs_planning=False,
                reasoning="Longer query without clear general signal — web search likely",
            )

        # Multi-step task: multiple skills OR explicit multi-step language
        if is_multi_step or len(skills_found) >= 2:
            return IntentResult(
                query_type="skill_multi",
                skills_likely=skills_found,
                complexity="high",
                needs_planning=True,
                reasoning=f"Multi-step task — skills detected: {skills_found}",
            )

        # Single skill task
        return IntentResult(
            query_type="skill_single",
            skills_likely=skills_found,
            complexity="medium",
            needs_planning=False,
            reasoning=f"Single skill task: {skills_found}",
        )

    # ── LLM classifier (fallback for ambiguous high-complexity queries) ────────

    async def _llm_classify(self, message: str, llm) -> IntentResult:
        """Use LLM for precise classification when heuristics are uncertain."""
        prompt = _LLM_CLASSIFY_PROMPT.format(message=message)
        response = await llm.chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.1,
        )

        # Clean up markdown fences if present
        response = response.strip()
        if response.startswith("```"):
            response = re.sub(r"```(?:json)?\s*", "", response).strip("`").strip()

        data = json.loads(response)
        query_type = data.get("type", "general")
        return IntentResult(
            query_type=query_type,
            skills_likely=data.get("skills_likely", []),
            complexity=data.get("complexity", "medium"),
            needs_planning=(query_type == "skill_multi"),
            reasoning=data.get("reasoning", ""),
        )
