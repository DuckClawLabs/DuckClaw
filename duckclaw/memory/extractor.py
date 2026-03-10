"""
DuckClaw Memory Extractor.
Uses LLM to extract structured facts from conversations.
Runs asynchronously after each turn — doesn't slow down responses.
"""

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from duckclaw.llm.router import LLMRouter
    from duckclaw.memory.store import MemoryStore

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are a memory extraction assistant. Analyze the user's message and extract any factual information about them worth remembering for future conversations.

Extract facts in these categories:
- work: job, company, projects, skills, colleagues
- personal: name, location, hobbies, family, lifestyle
- preferences: likes, dislikes, communication style
- health: allergies, conditions (if voluntarily shared)
- calendar: recurring events, schedules

Rules:
1. Only extract CLEAR, EXPLICIT facts (not guesses)
2. One fact per item — keep them short (under 15 words)
3. Write facts in third person: "User works at..." / "User prefers..."
4. Return ONLY a JSON array. If no facts, return []
5. Maximum 5 facts per message

Example output:
[
  {"fact": "User works at Acme Corp as a backend engineer", "category": "work", "confidence": 0.95},
  {"fact": "User is working on a project called Atlas", "category": "work", "confidence": 0.90}
]

User message to analyze:
"""


async def extract_facts(
    user_message: str,
    llm: "LLMRouter",
    memory: "MemoryStore",
) -> list[dict]:
    """
    Extract facts from a user message and store them.
    Called asynchronously after each turn — non-blocking.
    Returns list of extracted facts.
    """
    if len(user_message.strip()) < 20:
        return []  # Too short to contain useful facts

    try:
        response = await llm.chat(
            messages=[
                {"role": "user", "content": EXTRACTION_PROMPT + user_message}
            ],
            max_tokens=512,
            temperature=0.1,  # Low temperature for consistency
        )

        # Parse JSON response
        response = response.strip()
        if response.startswith("```"):
            # Strip markdown code blocks if present
            lines = response.split("\n")
            response = "\n".join(lines[1:-1])

        facts = json.loads(response)
        if not isinstance(facts, list):
            return []

        # Store valid facts
        stored = []
        for item in facts[:5]:  # Max 5 per message
            if not isinstance(item, dict):
                continue
            fact_text = item.get("fact", "").strip()
            category = item.get("category", "general")
            confidence = float(item.get("confidence", 0.8))

            if fact_text and confidence > 0.7:
                fact_id = memory.save_fact(
                    fact=fact_text,
                    category=category,
                    confidence=confidence,
                    source_msg=user_message[:200],
                )
                stored.append({
                    "id": fact_id,
                    "fact": fact_text,
                    "category": category,
                    "confidence": confidence,
                })

        return stored

    except json.JSONDecodeError:
        logger.debug("Fact extraction returned non-JSON response — skipping")
        return []
    except Exception as e:
        logger.warning(f"Fact extraction failed: {e}")
        return []
