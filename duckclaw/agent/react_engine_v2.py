"""
ReAct Engine V2 — Plan-then-Execute with minimal LLM calls.

Key improvement over V1 (react_engine.py):
  V1: N skills = N+1 LLM calls (one reasoning call per iteration)
  V2: N skills = 2 LLM calls minimum (1 plan + 1 synthesis)
      + 1 lightweight LLM call per step where llm_required=true

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Flow:
  1. PLAN      → Single LLM call generates complete execution plan JSON
  2. EXECUTE   → Run each skill sequentially, no LLM unless llm_required=true
                   - dependable_skill_output: pulls a previous step's raw output
                   - {{step_id_output}} templates: direct param injection (no LLM)
                   - llm_required=true: mini LLM call to resolve params from prev output
  3. SYNTHESIZE → Final LLM call with all observations → final_answer

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Plan JSON formats the LLM must emit:

  No skills needed (general question):
    {"thought": "...", "final_answer": "..."}

  Single skill:
    {
      "thought": "...",
      "plan": [
        {
          "id": "step_0",
          "skill": "web_search",
          "action": "search",
          "params": {"query": "X"},
          "llm_required": false
        }
      ]
    }

  Multi-skill — static params (no inter-skill LLM needed):
    {
      "thought": "...",
      "plan": [
        {
          "id": "step_0",
          "skill": "web_search",
          "action": "search",
          "params": {"query": "X"},
          "llm_required": false
        },
        {
          "id": "step_1",
          "skill": "file",
          "action": "write",
          "params": {"path": "out.txt", "content": "{{step_0_output}}"},
          "dependable_skill_output": "step_0",
          "llm_required": false
        }
      ]
    }

  Multi-skill — LLM needed to resolve params from previous output:
    {
      "thought": "...",
      "plan": [
        {
          "id": "step_0",
          "skill": "web_search",
          "action": "search",
          "params": {"query": "X"},
          "llm_required": false
        },
        {
          "id": "step_1",
          "skill": "http_fetch",
          "action": "fetch",
          "params": {},
          "dependable_skill_output": "step_0",
          "llm_required": true
        }
      ]
    }

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Template substitution (llm_required=false dependency):
  Use {{step_id_output}} anywhere in a param value string.
  The executor replaces it with the raw text output of that step.
  Example: "content": "Summary of: {{step_0_output}}"

LLM param resolution (llm_required=true):
  Executor makes a focused mini LLM call:
    - Input: previous step's output (from dependable_skill_output)
    - Task: fill in the params for the current skill/action
    - Output: just the params JSON
  No system prompt, no skill catalog, no memory — cheap and fast.
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

MAX_OBS_CHARS = 4000   # truncate long skill outputs before feeding back to LLM


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class PlanStep:
    """One step in the LLM-generated execution plan."""
    id: str
    skill: str
    action: str
    params: dict
    llm_required: bool = False
    # ID of a previous step whose output this step depends on.
    # If llm_required=False: supports {{step_id_output}} template substitution.
    # If llm_required=True:  mini LLM call fills params using that step's output.
    dependable_skill_output: Optional[str] = None


@dataclass
class StepResult:
    """Result of executing one plan step."""
    step_id: str
    skill: str
    action: str
    params_used: dict
    output: str               # raw text from skill (possibly truncated)
    llm_output: Optional[str] # LLM-processed output (set when llm_required=True)
    success: bool
    metadata: Optional[dict] = None

    def effective_output(self) -> str:
        """Return LLM-processed output if available, otherwise raw output."""
        return self.llm_output if self.llm_output else self.output


@dataclass
class ReActV2Result:
    """Full result from the V2 plan-then-execute engine."""
    final_answer: str
    plan: list[PlanStep] = field(default_factory=list)
    step_results: list[StepResult] = field(default_factory=list)
    skills_used: list[str] = field(default_factory=list)
    llm_calls: int = 0        # total LLM calls made (useful for cost tracking)
    success: bool = True
    error: Optional[str] = None


# ── System prompt ─────────────────────────────────────────────────────────────

_PLAN_SYSTEM_PROMPT = """\
You are DuckClaw 🦆🤖 — an intelligent personal AI agent.
Your job is to produce a complete execution plan in ONE response.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## AVAILABLE SKILLS  (from knowledge base)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{skills_context}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## RESPONSE FORMAT  — emit exactly ONE JSON object, no extra text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**Option A — No skills needed (general question, definition, explanation, math, etc.):**
{{"thought": "<reasoning>", "final_answer": "<full answer in markdown>"}}

**Option B — One or more skills needed:**
{{
  "thought": "<reasoning about the full plan>",
  "plan": [
    {{
      "id": "step_0",
      "skill": "<skill_name>",
      "action": "<action_name>",
      "params": {{...}},
      "llm_required": false
    }},
    {{
      "id": "step_1",
      "skill": "<skill_name>",
      "action": "<action_name>",
      "params": {{...or empty {{}} if llm_required=true}},
      "dependable_skill_output": "step_0",
      "llm_required": true
    }}
  ]
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## PLAN RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. **Step IDs** must be sequential: "step_0", "step_1", "step_2", ...

2. **llm_required** — set to true ONLY when the previous step's output must be
   interpreted by an LLM to determine this step's params.
   Examples:
     - web_search results → pick best URL for http_fetch         → llm_required=true
     - vision/screenshot output → extract text for next action   → llm_required=true
     - file path returned by step_0 → pass directly to step_1    → llm_required=false

3. **dependable_skill_output** — set to the step ID whose output this step needs.
   - If llm_required=false: use {{{{step_id_output}}}} template in param values.
     Example: {{"content": "{{{{step_0_output}}}}"}}
   - If llm_required=true: leave params as {{}} — executor will fill via mini LLM call.

4. **llm_required=false with no dependable_skill_output** — params are fully static,
   no inter-step dependency. Executor runs the skill directly.

5. Think about the FULL plan upfront. Order steps logically.
   Never emit a step that needs output you haven't planned to produce yet.

6. Keep params precise. Do not add fields you are not sure about.

7. NEVER ask the user for permission — DuckClaw's permission engine handles approvals.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## USER CONTEXT  (from memory)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{memory_context}
"""

_PARAM_RESOLVE_PROMPT = """\
You are a parameter resolver for DuckClaw agent.

The previous skill returned this output:
───────────────────────────────────────
{prev_output}
───────────────────────────────────────

Based on that output, fill in the params JSON for the next skill call:
  Skill:  {skill}
  Action: {action}

Current partial params (may be empty):
{current_params}

Return ONLY a valid JSON object containing the completed params.
No explanation, no markdown, just the JSON object.
"""

_SYNTHESIS_PROMPT = """\
You are DuckClaw 🦆🤖. You have finished executing all planned skills.

Here is a summary of each step's output:
{observations}

Now deliver the final answer to the user's original request.
Be complete and well-structured. Use markdown formatting.

Respond with JSON: {{"thought": "...", "final_answer": "..."}}
"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _format_skill_section(s: dict) -> str:
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
    """Top-5 relevant skills via ChromaDB, falling back to static list."""
    try:
        if memory_store is None:
            raise ValueError("no memory_store")
        matched = memory_store.search_skills(query, n_results=5)
        if matched:
            logger.debug(f"ChromaDB skills: {[s['name'] for s in matched]}")
            return "\n\n".join(_format_skill_section(s) for s in matched)
    except Exception as e:
        logger.warning(f"ChromaDB skill search failed: {e}. Falling back to static list.")

    try:
        from duckclaw.skills.knowledge_base import SKILLS
        if SKILLS:
            return "\n\n".join(_format_skill_section(s) for s in SKILLS)
    except Exception as e:
        logger.warning(f"Could not load static skills: {e}. Falling back to registry.")

    skills = skill_registry.list_skills()
    return "\n".join(f"- **{s['name']}**: {s['description']}" for s in skills)


def _parse_json(text: str) -> Optional[dict]:
    """Robustly extract a JSON object from LLM output (handles fences, prose wrapping)."""
    if isinstance(text, dict):
        return text

    text = text.strip()

    if "```" in text:
        text = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

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
                    start = -1

    logger.warning(f"Could not parse JSON from LLM output: {text[:300]!r}")
    return None


def _parse_plan(raw: dict) -> list[PlanStep]:
    """Convert the raw plan list from LLM JSON into PlanStep objects."""
    steps = []
    for item in raw.get("plan", []):
        steps.append(PlanStep(
            id=item.get("id", f"step_{len(steps)}"),
            skill=item.get("skill", "").strip(),
            action=item.get("action", "").strip(),
            params=item.get("params") or {},
            llm_required=bool(item.get("llm_required", False)),
            dependable_skill_output=item.get("dependable_skill_output"),
        ))
    return steps


def _substitute_templates(params: dict, step_outputs: dict[str, str]) -> dict:
    """
    Replace {{step_id_output}} placeholders in param string values.

    Works recursively on nested dicts/lists.
    Only applies when llm_required=False — no LLM call needed.
    """
    def _replace(value):
        if isinstance(value, str):
            for step_id, output in step_outputs.items():
                value = value.replace(f"{{{{{step_id}_output}}}}", output)
            return value
        if isinstance(value, dict):
            return {k: _replace(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_replace(v) for v in value]
        return value

    return {k: _replace(v) for k, v in params.items()}


def _truncate(text: str) -> str:
    if len(text) > MAX_OBS_CHARS:
        return text[:MAX_OBS_CHARS] + "\n[... truncated]"
    return text


def _build_observations_summary(step_results: list[StepResult]) -> str:
    """Format all step results for the synthesis LLM call."""
    parts = []
    for r in step_results:
        status = "SUCCESS" if r.success else "FAILED"
        parts.append(
            f"[{r.step_id}] {r.skill}.{r.action} — {status}\n"
            f"{r.effective_output()}"
        )
    return "\n\n".join(parts)


# ── Core param resolution ──────────────────────────────────────────────────────

async def _resolve_params(
    step: PlanStep,
    step_outputs: dict[str, str],   # step_id → effective output text
    llm: "LLMRouter",
    llm_calls: list[int],           # single-element mutable counter
) -> dict:
    """
    Resolve the final params for a step before execution.

    Cases:
      1. No dependable_skill_output → params are static, return as-is.
      2. dependable_skill_output + llm_required=False → template substitution.
      3. dependable_skill_output + llm_required=True  → mini LLM call fills params.
      4. llm_required=True but no dependable_skill_output → params returned as-is
         (the skill itself handles LLM internally, e.g. vision).
    """
    prev_output = None
    if step.dependable_skill_output:
        prev_output = step_outputs.get(step.dependable_skill_output)

    # Case 1 & 4 — no dependency or self-contained LLM skill
    if prev_output is None:
        return step.params

    # Case 2 — template substitution, no LLM needed
    if not step.llm_required:
        return _substitute_templates(step.params, step_outputs)

    # Case 3 — mini LLM call to fill params from prev output
    logger.info(
        f"  [param-resolve] mini LLM call for {step.skill}.{step.action} "
        f"using output of '{step.dependable_skill_output}'"
    )
    prompt = _PARAM_RESOLVE_PROMPT.format(
        prev_output=_truncate(prev_output),
        skill=step.skill,
        action=step.action,
        current_params=json.dumps(step.params, indent=2),
    )
    try:
        raw = await llm.chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=None,
            max_tokens=500,
            temperature=0.1,
        )
        llm_calls[0] += 1
        resolved = _parse_json(raw)
        if resolved and isinstance(resolved, dict):
            logger.debug(f"  [param-resolve] resolved params: {resolved}")
            return resolved
        logger.warning(f"  [param-resolve] LLM returned non-dict — using empty params")
    except Exception as e:
        logger.error(f"  [param-resolve] mini LLM call failed: {e} — using empty params")

    return {}


# ── Main engine ────────────────────────────────────────────────────────────────

class ReActEngineV2:
    """
    Plan-then-Execute engine.

    Single planning LLM call generates the full skill execution sequence.
    Skills run without LLM involvement unless a step marks llm_required=true,
    which triggers a focused mini LLM call only for param resolution.

    LLM call budget:
      - 1 planning call  (always)
      - 0..N param-resolve calls  (only for llm_required=true steps)
      - 1 synthesis call  (always, skipped if plan was final_answer directly)
      ─────────────────────────────────────────────────────
      Minimum: 2 calls   (general question: 1 plan + 0 execution + 0 synthesis
                          because final_answer comes directly from planning call)
      Typical: 2 calls   (1 plan + 1 synthesis, static params)
      Max:     2 + N     (N = number of llm_required=true steps)
    """

    async def run(
        self,
        message: str,
        context: dict,
        skill_registry: "SkillRegistry",
        llm: "LLMRouter",
        session_id: str,
        memory_store: Optional["MemoryStore"] = None,
    ) -> ReActV2Result:
        """
        Execute the plan-then-execute loop for any type of query.

        Args:
            message       : Original user query
            context       : Dict with 'history' (list[dict]) and 'memory_summary' (str)
            skill_registry: SkillRegistry instance — dispatches skills
            llm           : LLMRouter instance
            session_id    : Session ID for permission checks
            memory_store  : MemoryStore for ChromaDB skill search
        """
        llm_calls = [0]   # mutable counter passed into helpers

        # ── Build planning prompt ──────────────────────────────────────────────
        skills_ctx = _build_skills_context(message, memory_store, skill_registry)
        system_prompt = _PLAN_SYSTEM_PROMPT.format(
            skills_context=skills_ctx,
            memory_context=context.get("memory_summary", "(no prior context)"),
        )

        messages = list(context.get("history", []))
        messages.append({"role": "user", "content": message})

        # ── Planning call — one LLM call for the full plan ─────────────────────
        logger.info(f"[V2] Planning call | session={session_id}")
        try:
            plan_raw = await llm.chat(
                messages=messages,
                system_prompt=system_prompt,
                max_tokens=2000,
                temperature=0.3,
            )
            llm_calls[0] += 1
        except Exception as e:
            logger.error(f"[V2] Planning LLM call failed: {e}")
            return ReActV2Result(
                final_answer=f"Error processing your request: {e}",
                llm_calls=llm_calls[0],
                success=False,
                error=str(e),
            )

        parsed_plan = _parse_json(plan_raw)

        # Non-JSON response — treat as direct answer
        if parsed_plan is None:
            logger.warning("[V2] Planning returned non-JSON — treating as direct answer")
            return ReActV2Result(
                final_answer=plan_raw,
                llm_calls=llm_calls[0],
                success=True,
            )

        # ── General question path — LLM answered directly ──────────────────────
        if "final_answer" in parsed_plan:
            logger.info("[V2] Direct final_answer from planning call (no skills needed)")
            return ReActV2Result(
                final_answer=parsed_plan["final_answer"],
                llm_calls=llm_calls[0],
                success=True,
            )

        # ── Validate plan ──────────────────────────────────────────────────────
        if "plan" not in parsed_plan or not parsed_plan["plan"]:
            logger.warning("[V2] Plan missing or empty — treating thought as answer")
            fallback = parsed_plan.get("thought", plan_raw)
            return ReActV2Result(
                final_answer=fallback,
                llm_calls=llm_calls[0],
                success=False,
                error="LLM returned no plan and no final_answer",
            )

        plan_steps = _parse_plan(parsed_plan)
        logger.info(
            f"[V2] Plan received: {len(plan_steps)} step(s) — "
            f"{[f'{s.id}:{s.skill}.{s.action}' for s in plan_steps]}"
        )

        # ── Execution loop — no LLM unless llm_required=true ──────────────────
        step_results: list[StepResult] = []
        step_outputs: dict[str, str] = {}   # step_id → effective output text
        skills_used: list[str] = []
        seen_calls: set[str] = set()        # loop guard

        for step in plan_steps:
            if not step.skill or not step.action:
                logger.warning(f"[V2] Step '{step.id}' missing skill or action — skipping")
                step_outputs[step.id] = "ERROR: step skipped (missing skill/action)"
                continue

            # Duplicate call guard
            call_key = f"{step.skill}.{step.action}:{json.dumps(step.params, sort_keys=True)}"
            if call_key in seen_calls:
                logger.warning(f"[V2] Duplicate call detected for '{call_key}' — skipping")
                step_outputs[step.id] = "SKIPPED: duplicate call"
                continue
            seen_calls.add(call_key)

            # Resolve params (templates or mini LLM call)
            final_params = await _resolve_params(step, step_outputs, llm, llm_calls)

            logger.info(
                f"[V2] Executing {step.id}: {step.skill}.{step.action} "
                f"| params={json.dumps(final_params)[:200]}"
                f"{' [llm_required]' if step.llm_required and step.dependable_skill_output else ''}"
            )

            # ── Dispatch skill ─────────────────────────────────────────────────
            skill_result = await skill_registry.dispatch(
                step.skill, step.action, final_params, session_id=session_id
            )

            raw_output = _truncate(skill_result.to_text())

            # Determine effective output: for llm_required steps WITHOUT dependable_skill_output
            # (e.g. vision/screenshot), the skill itself already ran LLM internally.
            # We store the raw output as both raw and effective.
            result = StepResult(
                step_id=step.id,
                skill=step.skill,
                action=step.action,
                params_used=final_params,
                output=raw_output,
                llm_output=None,   # only set if we add post-processing in future
                success=skill_result.success,
                metadata=skill_result.metadata or {},
            )
            step_results.append(result)
            step_outputs[step.id] = result.effective_output()

            if step.skill not in skills_used:
                skills_used.append(step.skill)

            logger.info(
                f"[V2] {step.id} done — success={skill_result.success}, "
                f"chars={len(raw_output)}"
            )

        # ── Synthesis call — one LLM call to produce final answer ─────────────
        logger.info(
            f"[V2] Synthesis call | {len(step_results)} observations | "
            f"total LLM calls so far: {llm_calls[0]}"
        )

        observations = _build_observations_summary(step_results)
        synth_messages = list(context.get("history", []))
        synth_messages.append({"role": "user", "content": message})
        synth_prompt = _SYNTHESIS_PROMPT.format(observations=observations)

        try:
            synth_raw = await llm.chat(
                messages=synth_messages,
                system_prompt=synth_prompt,
                max_tokens=2000,
                temperature=0.3,
            )
            llm_calls[0] += 1
        except Exception as e:
            logger.error(f"[V2] Synthesis LLM call failed: {e}")
            fallback = "I gathered the following:\n\n" + observations
            return ReActV2Result(
                final_answer=fallback,
                plan=plan_steps,
                step_results=step_results,
                skills_used=skills_used,
                llm_calls=llm_calls[0],
                success=False,
                error=str(e),
            )

        parsed_synth = _parse_json(synth_raw)
        if parsed_synth and "final_answer" in parsed_synth:
            final_answer = parsed_synth["final_answer"]
        elif synth_raw:
            final_answer = synth_raw
        else:
            final_answer = "I gathered the following:\n\n" + observations

        logger.info(
            f"[V2] Complete | skills_used={skills_used} | "
            f"total LLM calls={llm_calls[0]}"
        )

        return ReActV2Result(
            final_answer=final_answer,
            plan=plan_steps,
            step_results=step_results,
            skills_used=skills_used,
            llm_calls=llm_calls[0],
            success=True,
        )
