"""
ReAct Engine V3 — Parallel DAG Execution.

Core difference from V1 and V2:
  V1: sequential iterations, one LLM call per skill (adaptive, slow)
  V2: sequential plan, one planning call (faster, not adaptive)
  V3: dependency graph, independent skills run in PARALLEL (fastest, still one planning call)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why parallel matters:

  Task: "morning briefing — weather, news, calendar"
    V1: 4 sequential LLM calls, 3 sequential skill calls
    V2: 2 LLM calls, 3 sequential skill calls
    V3: 2 LLM calls, 3 PARALLEL skill calls  ← wall-clock ~3x faster

  Task: "search X then write to file"  (dependent — can't parallelize)
    V3 gracefully falls back to sequential for dependent steps.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
How it works:

  1. PLAN   — Single LLM call generates a DAG plan JSON.
              Each step lists its `depends_on` (empty = independent).

  2. EXECUTE — Topological wave executor:
                 Wave 1: all steps with depends_on=[] → asyncio.gather (parallel)
                 Wave 2: steps whose deps are now complete → asyncio.gather
                 Wave N: repeat until all steps done

  3. PARAM RESOLUTION (per step, before dispatch):
       - No deps / llm_required=false   → static params, run immediately
       - Has deps / llm_required=false  → {{step_id_output}} template substitution
       - Has deps / llm_required=true   → mini focused LLM call fills params
                                          (uses ALL dependency outputs as context)

  4. SYNTHESIZE — Final LLM call with all observations → final_answer

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Plan JSON the LLM emits:

  No skills needed:
    {"thought": "...", "final_answer": "..."}

  Single skill (depends_on=[]):
    {
      "thought": "...",
      "plan": [
        {"id": "step_0", "skill": "web_search", "action": "search",
         "params": {"query": "X"}, "depends_on": [], "llm_required": false}
      ]
    }

  Parallel independent skills (all depends_on=[]):
    {
      "thought": "...",
      "plan": [
        {"id": "step_0", "skill": "weather",    "action": "get",    "params": {"city": "NYC"},    "depends_on": [], "llm_required": false},
        {"id": "step_1", "skill": "web_search", "action": "search", "params": {"query": "news"},  "depends_on": [], "llm_required": false},
        {"id": "step_2", "skill": "calendar",   "action": "today",  "params": {},                 "depends_on": [], "llm_required": false}
      ]
    }
    → step_0, step_1, step_2 all run simultaneously.

  Parallel then merge (fan-in):
    {
      "thought": "...",
      "plan": [
        {"id": "step_0", "skill": "web_search", "action": "search",  "params": {"query": "A"}, "depends_on": [],                     "llm_required": false},
        {"id": "step_1", "skill": "web_search", "action": "search",  "params": {"query": "B"}, "depends_on": [],                     "llm_required": false},
        {"id": "step_2", "skill": "file",        "action": "write",   "params": {"path": "out.txt", "content": "{{step_0_output}}\n\n{{step_1_output}}"}, "depends_on": ["step_0", "step_1"], "llm_required": false}
      ]
    }
    → step_0 and step_1 run in parallel, step_2 waits for both.

  Sequential dependent (LLM needed to resolve params):
    {
      "thought": "...",
      "plan": [
        {"id": "step_0", "skill": "web_search", "action": "search", "params": {"query": "X"},  "depends_on": [],         "llm_required": false},
        {"id": "step_1", "skill": "http_fetch", "action": "fetch",  "params": {},               "depends_on": ["step_0"], "llm_required": true}
      ]
    }
    → step_0 runs, then mini LLM call fills step_1 params from step_0 output.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LLM call budget:
  1 planning call       (always)
  0..K param-resolve    (one per llm_required=true step, focused mini calls)
  1 synthesis call      (always)
  ─────────────────────────────────────────────
  Minimum: 1 call (general question, final_answer from planning)
  Typical: 2 calls (plan + synthesis, all static or template params)
  Max:     2 + K  (K = number of llm_required=true steps)
"""

import asyncio
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

MAX_OBS_CHARS = 4000


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class DAGStep:
    """One node in the execution DAG."""
    id: str
    skill: str
    action: str
    params: dict
    depends_on: list[str]           # IDs of steps that must complete first
    llm_required: bool = False      # True → mini LLM call to resolve params from dep outputs


@dataclass
class StepResult:
    """Result of one executed DAG step."""
    step_id: str
    skill: str
    action: str
    params_used: dict
    output: str
    success: bool
    wave: int                       # which parallel wave this ran in (0-indexed)
    metadata: Optional[dict] = None


@dataclass
class ReActV3Result:
    """Full result from the V3 DAG engine."""
    final_answer: str
    plan: list[DAGStep] = field(default_factory=list)
    step_results: list[StepResult] = field(default_factory=list)
    skills_used: list[str] = field(default_factory=list)
    waves: int = 0                  # number of parallel execution waves
    llm_calls: int = 0
    success: bool = True
    error: Optional[str] = None


# ── System prompt ──────────────────────────────────────────────────────────────

_PLAN_SYSTEM_PROMPT = """\
You are DuckClaw 🦆🤖 — an intelligent personal AI agent.
Produce a complete execution plan as a dependency graph in ONE response.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## AVAILABLE SKILLS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{skills_context}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## RESPONSE FORMAT — single JSON object, no extra text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**Option A — No skills needed:**
{{"thought": "...", "final_answer": "<full markdown answer>"}}

**Option B — One or more skills:**
{{
  "thought": "<full reasoning about the plan>",
  "plan": [
    {{
      "id": "step_0",
      "skill": "<skill_name>",
      "action": "<action_name>",
      "params": {{...}},
      "depends_on": [],
      "llm_required": false
    }}
  ]
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## DAG RULES — read carefully
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**depends_on** — list the step IDs this step must wait for.
  - Empty list []  → runs in parallel with all other independent steps (PREFERRED when possible)
  - ["step_0"]     → waits for step_0 to complete first
  - ["step_0","step_1"] → waits for BOTH to complete (fan-in)

**ALWAYS use depends_on=[] when steps are independent.**
  The executor runs all independent steps simultaneously.
  Example: weather + news + calendar — all three should have depends_on=[]

**llm_required** — set true ONLY when you cannot determine this step's params
  without seeing the previous step's actual output.
  Example: web_search returns URLs → you need LLM to pick the right one for http_fetch
  Example: screenshot output → you need LLM to extract text for the next step
  When llm_required=true, leave params as {{}} — the executor fills them via a mini LLM call.

**Template substitution** (llm_required=false with dependencies):
  Use {{{{step_id_output}}}} in param string values. The executor replaces it with
  the raw output of that step. Works for any number of dependencies.
  Example: "content": "Weather: {{{{step_0_output}}}}\\n\\nNews: {{{{step_1_output}}}}"

**Step IDs** must be "step_0", "step_1", "step_2", ... in order.
**No cycles** — depends_on must only reference steps with lower IDs.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## USER CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{memory_context}
"""

_PARAM_RESOLVE_PROMPT = """\
You are a parameter resolver for DuckClaw agent.

The following steps have completed. Here are their outputs:
{dep_outputs}

Based on these outputs, fill in the params JSON for the next skill call:
  Skill:  {skill}
  Action: {action}

Current partial params (may be empty):
{current_params}

Return ONLY a valid JSON object of the completed params. No explanation, no markdown.
"""

_SYNTHESIS_PROMPT = """\
You are DuckClaw 🦆🤖. All planned skills have finished executing.

Execution summary ({wave_count} parallel wave(s), {step_count} step(s) total):
{observations}

Deliver the final answer to the user's original request.
Be complete and well-structured. Use markdown.

Respond with JSON: {{"thought": "...", "final_answer": "..."}}
"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _format_skill_section(s: dict) -> str:
    lines = [f"### {s['name']}", s["description"].strip()]
    if s.get("use_cases"):
        lines.append(f"When to use: {' | '.join(s['use_cases'][:4])}")
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
    logger.warning(f"Could not parse JSON: {text[:300]!r}")
    return None


def _parse_dag(raw: dict) -> list[DAGStep]:
    steps = []
    for item in raw.get("plan", []):
        steps.append(DAGStep(
            id=item.get("id", f"step_{len(steps)}"),
            skill=item.get("skill", "").strip(),
            action=item.get("action", "").strip(),
            params=item.get("params") or {},
            depends_on=item.get("depends_on") or [],
            llm_required=bool(item.get("llm_required", False)),
        ))
    return steps


def _substitute_templates(params: dict, completed: dict[str, StepResult]) -> dict:
    """Replace {{step_id_output}} placeholders with actual step outputs."""
    def _replace(value):
        if isinstance(value, str):
            for step_id, result in completed.items():
                value = value.replace(f"{{{{{step_id}_output}}}}", result.output)
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


def _validate_dag(steps: list[DAGStep]) -> Optional[str]:
    """
    Basic DAG validation — catches cycles and missing dep IDs before execution.
    Returns an error string if invalid, None if valid.
    """
    ids = {s.id for s in steps}
    for step in steps:
        for dep in step.depends_on:
            if dep not in ids:
                return f"Step '{step.id}' depends on unknown step '{dep}'"
            # No forward references — dep must appear before step in list
            dep_index = next((i for i, s in enumerate(steps) if s.id == dep), -1)
            step_index = next((i for i, s in enumerate(steps) if s.id == step.id), -1)
            if dep_index >= step_index:
                return f"Step '{step.id}' has forward/circular dependency on '{dep}'"
    return None


def _build_observations_summary(step_results: list[StepResult]) -> str:
    parts = []
    for r in step_results:
        status = "SUCCESS" if r.success else "FAILED"
        parts.append(
            f"[{r.step_id}] {r.skill}.{r.action} (wave {r.wave}) — {status}\n"
            f"{r.output}"
        )
    return "\n\n".join(parts)


# ── Param resolution ───────────────────────────────────────────────────────────

async def _resolve_params(
    step: DAGStep,
    completed: dict[str, StepResult],
    llm: "LLMRouter",
    llm_calls: list[int],
) -> dict:
    """
    Resolve final params for a step given its completed dependencies.

    Cases:
      1. No deps                             → static params, return as-is
      2. Has deps, llm_required=False        → {{step_id_output}} template substitution
      3. Has deps, llm_required=True         → mini LLM call using all dep outputs
      4. llm_required=True, no deps          → params as-is (skill handles LLM itself)
    """
    if not step.depends_on:
        return step.params

    dep_results = {dep_id: completed[dep_id] for dep_id in step.depends_on if dep_id in completed}

    if not step.llm_required:
        return _substitute_templates(step.params, dep_results)

    # Mini LLM call: provide all dependency outputs, ask to fill params
    dep_outputs_text = "\n\n".join(
        f"[{dep_id}] {result.skill}.{result.action} output:\n{_truncate(result.output)}"
        for dep_id, result in dep_results.items()
    )

    prompt = _PARAM_RESOLVE_PROMPT.format(
        dep_outputs=dep_outputs_text,
        skill=step.skill,
        action=step.action,
        current_params=json.dumps(step.params, indent=2),
    )

    logger.info(
        f"  [param-resolve] mini LLM call for {step.skill}.{step.action} "
        f"from deps {list(dep_results.keys())}"
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
            return resolved
        logger.warning(f"  [param-resolve] LLM returned non-dict — using empty params")
    except Exception as e:
        logger.error(f"  [param-resolve] mini LLM call failed: {e} — using empty params")

    return {}


# ── DAG executor ───────────────────────────────────────────────────────────────

async def _execute_dag(
    plan: list[DAGStep],
    skill_registry: "SkillRegistry",
    llm: "LLMRouter",
    session_id: str,
    llm_calls: list[int],
) -> tuple[list[StepResult], int]:
    """
    Execute the DAG using topological wave scheduling.

    Each wave: find all steps whose dependencies are complete → run in parallel.
    Repeat until all steps are done or a deadlock is detected.

    Returns: (step_results ordered by completion, total waves)
    """
    step_by_id: dict[str, DAGStep] = {s.id: s for s in plan}
    completed: dict[str, StepResult] = {}      # step_id → result
    all_results: list[StepResult] = []
    wave_index = 0

    async def execute_one(step: DAGStep, wave: int) -> StepResult:
        """Resolve params, dispatch skill, return StepResult."""
        final_params = await _resolve_params(step, completed, llm, llm_calls)

        logger.info(
            f"  [wave {wave}] {step.id}: {step.skill}.{step.action} "
            f"params={json.dumps(final_params)[:150]}"
        )

        skill_result = await skill_registry.dispatch(
            step.skill, step.action, final_params, session_id=session_id
        )

        output = _truncate(skill_result.to_text())
        logger.info(
            f"  [wave {wave}] {step.id} done — "
            f"success={skill_result.success}, chars={len(output)}"
        )

        return StepResult(
            step_id=step.id,
            skill=step.skill,
            action=step.action,
            params_used=final_params,
            output=output,
            success=skill_result.success,
            wave=wave,
            metadata=skill_result.metadata or {},
        )

    while len(completed) < len(plan):
        # Find all steps ready to run: deps all complete, not yet started
        ready = [
            s for s in plan
            if s.id not in completed
            and all(dep in completed for dep in s.depends_on)
        ]

        if not ready:
            # Deadlock — some steps can never run (shouldn't happen after validation)
            logger.error(
                f"[V3] DAG deadlock at wave {wave_index}. "
                f"Completed: {list(completed.keys())}. "
                f"Remaining: {[s.id for s in plan if s.id not in completed]}"
            )
            break

        logger.info(
            f"[V3] Wave {wave_index}: running {len(ready)} step(s) in parallel — "
            f"{[s.id for s in ready]}"
        )

        # Run all ready steps simultaneously
        wave_results = await asyncio.gather(
            *[execute_one(s, wave_index) for s in ready],
            return_exceptions=True,
        )

        for step, result in zip(ready, wave_results):
            if isinstance(result, Exception):
                logger.error(f"  [wave {wave_index}] {step.id} raised exception: {result}")
                error_result = StepResult(
                    step_id=step.id,
                    skill=step.skill,
                    action=step.action,
                    params_used={},
                    output=f"ERROR: {result}",
                    success=False,
                    wave=wave_index,
                )
                completed[step.id] = error_result
                all_results.append(error_result)
            else:
                completed[step.id] = result
                all_results.append(result)

        wave_index += 1

    return all_results, wave_index


# ── Main engine ────────────────────────────────────────────────────────────────

class ReActEngineV3:
    """
    DAG-based parallel execution engine.

    The key insight: most multi-skill tasks have at least some independent
    steps. V1 and V2 both execute sequentially even when skills don't depend
    on each other. V3 runs all independent skills simultaneously.

    For fully sequential tasks (all steps depend on previous), V3 behaves
    identically to V2 with the same LLM call count.
    For tasks with independent steps, V3 is significantly faster in wall-clock time.

    Example: "morning briefing" (weather + news + calendar)
      V2: ~3 sequential API calls  (~3x latency)
      V3: 1 parallel wave          (~1x latency)
    """

    async def run(
        self,
        message: str,
        context: dict,
        skill_registry: "SkillRegistry",
        llm: "LLMRouter",
        session_id: str,
        memory_store: Optional["MemoryStore"] = None,
    ) -> ReActV3Result:
        llm_calls = [0]

        # ── Build planning prompt ──────────────────────────────────────────────
        skills_ctx = _build_skills_context(message, memory_store, skill_registry)
        system_prompt = _PLAN_SYSTEM_PROMPT.format(
            skills_context=skills_ctx,
            memory_context=context.get("memory_summary", "(no prior context)"),
        )

        messages = list(context.get("history", []))
        messages.append({"role": "user", "content": message})

        # ── Planning call ──────────────────────────────────────────────────────
        logger.info(f"[V3] Planning call | session={session_id}")
        try:
            plan_raw = await llm.chat(
                messages=messages,
                system_prompt=system_prompt,
                max_tokens=2000,
                temperature=0.3,
            )
            llm_calls[0] += 1
        except Exception as e:
            logger.error(f"[V3] Planning call failed: {e}")
            return ReActV3Result(
                final_answer=f"Error processing your request: {e}",
                llm_calls=llm_calls[0],
                success=False,
                error=str(e),
            )

        parsed_plan = _parse_json(plan_raw)

        if parsed_plan is None:
            logger.warning("[V3] Non-JSON planning response — treating as direct answer")
            return ReActV3Result(
                final_answer=plan_raw,
                llm_calls=llm_calls[0],
                success=True,
            )

        # ── Direct answer (general question) ──────────────────────────────────
        if "final_answer" in parsed_plan:
            logger.info("[V3] Direct final_answer from planning call")
            return ReActV3Result(
                final_answer=parsed_plan["final_answer"],
                llm_calls=llm_calls[0],
                success=True,
            )

        # ── Parse and validate DAG ─────────────────────────────────────────────
        if "plan" not in parsed_plan or not parsed_plan["plan"]:
            fallback = parsed_plan.get("thought", plan_raw)
            return ReActV3Result(
                final_answer=fallback,
                llm_calls=llm_calls[0],
                success=False,
                error="LLM returned no plan and no final_answer",
            )

        plan = _parse_dag(parsed_plan)

        dag_error = _validate_dag(plan)
        if dag_error:
            logger.error(f"[V3] Invalid DAG from LLM: {dag_error}")
            return ReActV3Result(
                final_answer=f"Planning produced an invalid execution graph: {dag_error}",
                plan=plan,
                llm_calls=llm_calls[0],
                success=False,
                error=dag_error,
            )

        # Log the plan structure so it's easy to see what's parallel vs sequential
        independent = [s.id for s in plan if not s.depends_on]
        dependent   = [s.id for s in plan if s.depends_on]
        logger.info(
            f"[V3] Plan: {len(plan)} step(s) | "
            f"independent (parallel): {independent} | "
            f"dependent (sequential): {dependent}"
        )

        # ── Execute DAG ────────────────────────────────────────────────────────
        step_results, wave_count = await _execute_dag(
            plan, skill_registry, llm, session_id, llm_calls
        )

        skills_used = list(dict.fromkeys(r.skill for r in step_results))  # order-preserving dedup

        # ── Synthesis call ─────────────────────────────────────────────────────
        logger.info(
            f"[V3] Synthesis call | {len(step_results)} step(s) across "
            f"{wave_count} wave(s) | LLM calls so far: {llm_calls[0]}"
        )

        observations = _build_observations_summary(step_results)
        synth_messages = list(context.get("history", []))
        synth_messages.append({"role": "user", "content": message})
        synth_prompt = _SYNTHESIS_PROMPT.format(
            wave_count=wave_count,
            step_count=len(step_results),
            observations=observations,
        )

        try:
            synth_raw = await llm.chat(
                messages=synth_messages,
                system_prompt=synth_prompt,
                max_tokens=2000,
                temperature=0.3,
            )
            llm_calls[0] += 1
        except Exception as e:
            logger.error(f"[V3] Synthesis call failed: {e}")
            return ReActV3Result(
                final_answer="I gathered the following:\n\n" + observations,
                plan=plan,
                step_results=step_results,
                skills_used=skills_used,
                waves=wave_count,
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
            f"[V3] Complete | skills_used={skills_used} | "
            f"waves={wave_count} | total LLM calls={llm_calls[0]}"
        )

        return ReActV3Result(
            final_answer=final_answer,
            plan=plan,
            step_results=step_results,
            skills_used=skills_used,
            waves=wave_count,
            llm_calls=llm_calls[0],
            success=True,
        )
