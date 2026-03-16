"""
ReAct Engine — Reason + Act execution loop.

The model is the intelligence layer. It receives:
  - Full skill catalog from the knowledge base (with use_cases, input/output formats)
  - Session history + user facts from memory
  - The user query

It then decides on its own — no separate classifier needed:
  - General question    → emits final_answer immediately (0 skill calls)
  - Single-skill task   → one skill call, then final_answer
  - Multi-step task     → chains multiple skill calls across iterations

New skills added to knowledge_base.py are automatically picked up — no code changes needed.

Per-iteration cycle:
  THINK  → LLM reasons with full context (history + observations so far)
  ACT    → Calls a skill via SkillRegistry.dispatch()  (OR goes to final_answer)
  OBSERVE→ Skill result appended to running trace
  REPEAT → Until final_answer OR MAX_ITERATIONS hit
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from duckclaw.skills.registry import SkillRegistry
    from duckclaw.llm.router import LLMRouter
    from duckclaw.memory.store import MemoryStore

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5       # hard cap — prevents infinite loops
MAX_OBS_CHARS  = 4000    # truncate long skill results before feeding back to LLM


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class AgentStep:
    """One completed cycle in the ReAct trace."""
    iteration: int
    thought: str
    skill_name: Optional[str] = None
    skill_action: Optional[str] = None
    params: Optional[dict] = None
    observation: Optional[str] = None
    skill_success: bool = True
    is_final: bool = False
    skill_metadata: Optional[dict] = None


@dataclass
class ReActResult:
    """Full result from the ReAct execution loop."""
    final_answer: str
    steps: list[AgentStep] = field(default_factory=list)
    iterations: int = 0
    skills_used: list[str] = field(default_factory=list)
    success: bool = True
    error: Optional[str] = None


# ── System prompt ─────────────────────────────────────────────────────────────
# The model reads this once per session and handles ALL query types natively.
# Skills section is injected dynamically from the knowledge base.

_REACT_SYSTEM_PROMPT = """\
You are DuckClaw 🦆🤖 — an intelligent personal AI agent.
You reason carefully, use skills when needed, and deliver complete answers.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## AVAILABLE SKILLS  (from knowledge base)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{skills_context}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## RESPONSE FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Every response must be a single JSON object — no extra text, no markdown wrapper.

**Option A — Call a skill:**
{{"thought": "<why this skill is needed>", "skill": "<skill_name>", "action": "<action_name>", "params": {{...}}}}

**Option B — Deliver final answer (general question OR task complete):**
{{"thought": "<why this is the complete answer>", "final_answer": "<full, well-formatted answer>"}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## HOW TO HANDLE DIFFERENT QUERY TYPES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**General questions** (history, science, coding concepts, definitions, explanations,
creative writing, math, etc.) — answer from knowledge, NO skill calls needed:
  → Respond IMMEDIATELY with Option B (final_answer)

**Single-skill tasks** (search web, read a file, run a command, take screenshot, etc.):
  → Call the skill (Option A), observe the result, then give final_answer (Option B)

**Multi-step tasks** (e.g. "search for X and save it to a file", "build a project",
"find info then analyse it") — chain skills across iterations:
  → Iteration 1: call first skill
  → Iteration 2: call next skill using observations from iteration 1
  → ... continue until you have all the information
  → Final iteration: emit final_answer with a complete synthesis

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Think before every action — thought must explain WHY this skill is needed.
2. Never call a skill for information you already have in your observations.
3. If a skill fails, try alternative params or a different skill approach.
4. Final answers must be complete, well-structured markdown. Never truncate.
5. Respond with ONLY the JSON object — absolutely no text outside the JSON.
6. NEVER ask the user for permission or confirmation in your response text. DuckClaw has a built-in permission engine — call the skill directly and it will handle user approval automatically via a UI popup or terminal prompt.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## USER CONTEXT  (from memory)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{memory_context}
"""


# ── Skills context builder ────────────────────────────────────────────────────

def _format_skill_section(s: dict) -> str:
    """Format a single skill dict (from ChromaDB or static list) into prompt text."""
    lines = [f"### {s['name']}", s["description"].strip()]
    if s.get("use_cases"):
        uc = " | ".join(s["use_cases"][:4])
        lines.append(f"When to use: {uc}")
    if s.get("input_format"):
        lines.append(f"Input format:\n{s['input_format'].strip()}")
    if s.get("output_format"):
        lines.append(f"JSON to emit:\n{s['output_format'].strip()}")
    return "\n".join(lines)


def _build_skills_context(
    query: str,
    memory_store: Optional["MemoryStore"],
    skill_registry: "SkillRegistry",
) -> str:
    """
    Return a skills section for the system prompt.

    Primary path: semantic search in ChromaDB for the top 5 skills relevant
    to the user's query — keeps the prompt focused and avoids flooding the
    context window as the skill catalog grows.

    Fallback (in order):
      1. All static skills from knowledge_base.SKILLS (ChromaDB empty / unavailable)
      2. Minimal registry list (knowledge_base unavailable entirely)
    """
    # ── Primary: ChromaDB semantic search ─────────────────────────────────────
    try:
        if memory_store is None:
            raise ValueError("no memory_store")
        matched = memory_store.search_skills(query, n_results=5)
        if matched:
            sections = [_format_skill_section(s) for s in matched]
            logger.debug(
                f"ChromaDB skills: {[s['name'] for s in matched]} "
                f"(similarities: {[s['similarity'] for s in matched]})"
            )
            return "\n\n".join(sections)
    except Exception as e:
        logger.warning(f"ChromaDB skill search failed: {e}. Falling back to static list.")

    # ── Fallback 1: full static list from knowledge_base ──────────────────────
    try:
        from duckclaw.skills.knowledge_base import SKILLS
        if SKILLS:
            return "\n\n".join(_format_skill_section(s) for s in SKILLS)
    except Exception as e:
        logger.warning(f"Could not load static skills: {e}. Falling back to registry.")

    # ── Fallback 2: live registry (minimal descriptions) ──────────────────────
    skills = skill_registry.list_skills()
    return "\n".join(f"- **{s['name']}**: {s['description']}" for s in skills)


# ── JSON parser ───────────────────────────────────────────────────────────────

def _parse_react_response(text: str) -> Optional[dict]:
    """
    Robustly extract a JSON object from LLM output.
    Handles markdown fences, leading/trailing prose, and partial wrapping.
    """
    if isinstance(text, dict):
        return text

    text = text.strip()

    # Strip ```json ... ``` fences
    if "```" in text:
        text = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()

    # Direct full-string parse (happy path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Brace-counting extraction — find the first complete top-level JSON object
    depth, in_string, escape, start = 0, False, False, -1
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if not in_string:
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        return json.loads(text[start: i + 1])
                    except json.JSONDecodeError:
                        pass
                    start = -1  # reset and keep searching

    logger.warning(f"Could not parse ReAct JSON: {text[:300]!r}")
    return None


# ── Trace builder ─────────────────────────────────────────────────────────────

def _steps_to_trace(steps: list[AgentStep]) -> str:
    """Format accumulated steps as a readable trace string for LLM context."""
    parts: list[str] = []
    for step in steps:
        if step.is_final:
            continue
        parts.append(f"THOUGHT: {step.thought}")
        if step.skill_name:
            params_str = json.dumps(step.params or {}, ensure_ascii=False)
            parts.append(f"ACTION: {step.skill_name}.{step.skill_action}({params_str})")
            status = "✅" if step.skill_success else "❌"
            parts.append(f"OBSERVATION {status}: {step.observation or '(no output)'}")
        parts.append("")
    return "\n".join(parts).strip()


# ── Main engine ───────────────────────────────────────────────────────────────

class ReActEngine:
    """
    The core intelligence loop.

    The LLM is given:
      - Full skill catalog from knowledge_base (auto-updates as skills grow)
      - User memory context (facts + past conversations)
      - Session conversation history
      - Running trace of thoughts + observations from prior iterations

    It decides on its own whether to answer directly (general questions),
    call one skill, or chain multiple skills across iterations.
    No separate intent classifier or planner needed.
    """

    async def run(
        self,
        message: str,
        context: dict,
        skill_registry: "SkillRegistry",
        llm: "LLMRouter",
        session_id: str,
        memory_store: Optional["MemoryStore"] = None,
    ) -> ReActResult:
        """
        Execute the ReAct loop for any type of query.

        Args:
            message       : Original user query
            context       : Dict with 'history' (list[dict]) and 'memory_summary' (str)
            skill_registry: Existing SkillRegistry — called directly, no wrapper
            llm           : LLMRouter instance
            session_id    : Session ID passed to SkillRegistry for permission checks
            memory_store  : MemoryStore for ChromaDB skill search (top-5 relevant skills)
        """
        steps: list[AgentStep] = []
        skills_used: list[str] = []
        seen_calls: set[str] = set()  # loop guard

        # Build skills context — top-5 relevant via ChromaDB, or full static list
        skills_ctx = _build_skills_context(message, memory_store, skill_registry)
        logger.debug(f"Skills context built ({len(skills_ctx)} chars)")

        # Build system prompt — skills from knowledge base, memory from context
        system_prompt = _REACT_SYSTEM_PROMPT.format(
            skills_context=skills_ctx,
            memory_context=context.get("memory_summary", "(no prior context)"),
        )

        # Base messages: session history + current user query
        base_messages = list(context.get("history", []))
        base_messages.append({"role": "user", "content": message})

        for iteration in range(1, MAX_ITERATIONS + 1):
            logger.info(
                f"ReAct iter {iteration}/{MAX_ITERATIONS} | session={session_id}"
            )

            # Build messages with accumulated trace as assistant turn
            current_messages = list(base_messages)
            if steps:
                trace = _steps_to_trace(steps)
                if trace:
                    current_messages.append({"role": "assistant", "content": trace})
                    current_messages.append({
                        "role": "user",
                        "content": (
                            "What is your next step? "
                            "Respond with JSON: call another skill, or give your final_answer."
                        ),
                    })

            # ── LLM reasoning call ─────────────────────────────────────────
            try:
                llm_response = await llm.chat(
                    messages=current_messages,
                    system_prompt=system_prompt,
                    max_tokens=1500,
                    temperature=0.3,
                )
            except Exception as e:
                logger.error(f"LLM call failed at ReAct iteration {iteration}: {e}")
                return ReActResult(
                    final_answer=f"Error processing your request: {e}",
                    steps=steps,
                    iterations=iteration,
                    skills_used=skills_used,
                    success=False,
                    error=str(e),
                )

            parsed = _parse_react_response(llm_response)

            # Non-JSON response — treat as direct final answer
            if parsed is None:
                logger.warning(
                    f"ReAct iter {iteration}: non-JSON response — "
                    "treating as direct answer"
                )
                steps.append(AgentStep(
                    iteration=iteration,
                    thought="Direct response",
                    is_final=True,
                ))
                return ReActResult(
                    final_answer=llm_response,
                    steps=steps,
                    iterations=iteration,
                    skills_used=skills_used,
                    success=True,
                )

            thought = parsed.get("thought", "")

            # ── final_answer path ─────────────────────────────────────────
            if "final_answer" in parsed:
                steps.append(AgentStep(
                    iteration=iteration,
                    thought=thought,
                    is_final=True,
                ))
                logger.info(
                    f"ReAct: final_answer at iter {iteration} | "
                    f"skills_used={skills_used}"
                )
                return ReActResult(
                    final_answer=parsed["final_answer"],
                    steps=steps,
                    iterations=iteration,
                    skills_used=skills_used,
                    success=True,
                )

            # ── skill call path ───────────────────────────────────────────
            skill_name   = parsed.get("skill", "").strip()
            skill_action = parsed.get("action", "").strip()
            params       = parsed.get("params") or {}

            if not skill_name or not skill_action:
                logger.warning(
                    f"ReAct iter {iteration}: malformed skill call: {parsed}"
                )
                steps.append(AgentStep(
                    iteration=iteration,
                    thought=thought,
                    observation="ERROR: JSON missing 'skill' or 'action'. Fix and retry.",
                    skill_success=False,
                ))
                continue

            # Loop guard — refuse exact duplicate calls
            call_key = f"{skill_name}.{skill_action}:{json.dumps(params, sort_keys=True)}"
            if call_key in seen_calls:
                logger.warning(f"ReAct: duplicate call detected '{call_key}' — forcing synthesis")
                steps.append(AgentStep(
                    iteration=iteration,
                    thought=thought,
                    observation="Already called this skill with identical params. Use existing observations.",
                    skill_success=False,
                ))
                break
            seen_calls.add(call_key)

            logger.info(
                f"ReAct: dispatching {skill_name}.{skill_action} "
                f"params={json.dumps(params)[:200]}"
            )

            # ── dispatch to SkillRegistry (existing, unchanged) ───────────
            skill_result = await skill_registry.dispatch(
                skill_name, skill_action, params, session_id=session_id
            )

            observation = skill_result.to_text()
            if len(observation) > MAX_OBS_CHARS:
                observation = (
                    observation[:MAX_OBS_CHARS]
                    + "\n[... result truncated for context length]"
                )

            steps.append(AgentStep(
                iteration=iteration,
                thought=thought,
                skill_name=skill_name,
                skill_action=skill_action,
                params=params,
                observation=observation,
                skill_success=skill_result.success,
                skill_metadata=skill_result.metadata or {},
            ))

            if skill_name not in skills_used:
                skills_used.append(skill_name)

            logger.info(
                f"ReAct: observation from {skill_name}.{skill_action} — "
                f"success={skill_result.success}, chars={len(observation)}"
            )

        # ── Max iterations — force final synthesis ────────────────────────
        logger.warning(
            f"ReAct: MAX_ITERATIONS ({MAX_ITERATIONS}) reached. "
            f"Forcing synthesis. session={session_id}"
        )

        trace = _steps_to_trace(steps)
        synth_messages = list(base_messages)
        if trace:
            synth_messages.append({"role": "assistant", "content": trace})
        synth_messages.append({
            "role": "user",
            "content": (
                "You have reached the maximum steps. "
                "Based on ALL observations above, provide your complete final answer now. "
                'Respond with JSON: {"thought": "...", "final_answer": "..."}'
            ),
        })

        try:
            final_resp = await llm.chat(
                messages=synth_messages,
                system_prompt=system_prompt,
                max_tokens=2000,
                temperature=0.3,
            )
            parsed_final = _parse_react_response(final_resp)
            if parsed_final and "final_answer" in parsed_final:
                steps.append(AgentStep(
                    iteration=MAX_ITERATIONS + 1,
                    thought=parsed_final.get("thought", "Forced synthesis"),
                    is_final=True,
                ))
                return ReActResult(
                    final_answer=parsed_final["final_answer"],
                    steps=steps,
                    iterations=MAX_ITERATIONS,
                    skills_used=skills_used,
                    success=True,
                )
            if final_resp:
                return ReActResult(
                    final_answer=final_resp,
                    steps=steps,
                    iterations=MAX_ITERATIONS,
                    skills_used=skills_used,
                    success=True,
                )
        except Exception as e:
            logger.error(f"Forced synthesis failed: {e}")

        fallback = (
            "I gathered the following information:\n\n" + trace
            if trace
            else "I was unable to complete this task."
        )
        return ReActResult(
            final_answer=fallback,
            steps=steps,
            iterations=MAX_ITERATIONS,
            skills_used=skills_used,
            success=False,
            error="Max iterations reached",
        )
