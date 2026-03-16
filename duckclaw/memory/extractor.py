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

EXTRACTION_PROMPT = """You are a personality and memory extraction assistant. Analyze the user's message and extract facts worth remembering — prioritizing who they ARE as a person, not just what they do.

Extract facts in these categories (in order of priority):
- personality: character traits, values, temperament, emotional style, sense of humor, how they think or make decisions
- communication: how they prefer to receive information (blunt/detailed/casual/formal), tone preferences
- personal: name, age, location, hobbies, family, lifestyle, life philosophy
- work: job, company, projects, skills, colleagues, career goals
- preferences: strong likes/dislikes, opinions, pet peeves, favorite things
- health: allergies, conditions (only if voluntarily shared)
- calendar: recurring events, schedules, deadlines

Rules:
1. PRIORITIZE personality and character over mundane facts
2. Only extract CLEAR, EXPLICIT facts (not guesses)
3. One fact per item — keep them short (under 15 words)
4. Write in third person: "User is direct and prefers..." / "User values honesty..."
5. Return ONLY a JSON array. If no facts, return []
6. Maximum 5 facts per message

Example output:
[
  {"fact": "User is direct and dislikes vague or sugarcoated answers", "category": "personality", "confidence": 0.92},
  {"fact": "User prefers concise explanations over lengthy ones", "category": "communication", "confidence": 0.90},
  {"fact": "User is a solo developer building DuckClaw", "category": "work", "confidence": 0.95}
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
