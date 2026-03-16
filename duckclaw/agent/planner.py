"""
Planner — generates a structured multi-step execution plan for complex queries.

The plan is a lightweight blueprint passed to the ReAct engine as guiding context.
It tells the agent what steps to take, which skills to use, and which steps can
run in parallel — without taking away the agent's freedom to reason at each step.

Only invoked when IntentAnalyzer returns needs_planning=True (skill_multi queries).
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from duckclaw.llm.router import LLMRouter

logger = logging.getLogger(__name__)


@dataclass
class PlanStep:
    id: int
    description: str
    skill: Optional[str] = None          # skill name hint (can be None for reasoning steps)
    action: Optional[str] = None         # skill action hint
    params_hint: dict = field(default_factory=dict)
    depends_on: list[int] = field(default_factory=list)
    parallel_group: Optional[int] = None  # steps with same group can run concurrently


@dataclass
class Plan:
    goal: str
    steps: list[PlanStep]
    complexity: str = "medium"

    def to_context_string(self) -> str:
        """Format plan as readable context for the ReAct engine system prompt."""
        lines = [f"## Execution Blueprint\nGoal: {self.goal}\n\nPlanned steps:"]
        for step in self.steps:
            parts = [f"  Step {step.id}: {step.description}"]
            if step.skill:
                parts.append(f"    → Suggested skill: {step.skill}" +
                              (f".{step.action}" if step.action else ""))
            if step.depends_on:
                parts.append(f"    → Requires: step(s) {step.depends_on} to complete first")
            if step.parallel_group is not None:
                parts.append(f"    → Can run in parallel (group {step.parallel_group})")
            lines.append("\n".join(parts))
        lines.append(
            "\nFollow this plan, but adapt based on what you observe at each step. "
            "If a step's result makes a later step unnecessary, skip it and explain why."
        )
        return "\n".join(lines)


_PLANNER_SYSTEM_PROMPT = """\
You are a task planner for DuckClaw, a personal AI assistant.
Your job is to break complex user requests into 2–6 clear, ordered steps.

Available skills and their key actions:
- web_search    : search (query, max_results), news (query, max_results)
- web_browser   : navigate (url), extract_text, screenshot, search (query)
- file_manager  : read (path), write (path, content), list (path), search (path, pattern), delete (path), create_dir (path)
- shell_runner  : run (command), check_safe (command)
- screen_capture: capture (question), list_monitors
- camera        : snap, snap_analyze (prompt), list_cameras
- scheduler     : remind_in (minutes, message), remind_at (time, message), add_cron (cron, label), list_jobs, remove_job (job_id)

Guidelines:
- Keep steps focused — one clear action per step.
- Mark steps that can run independently (no shared data) with the same parallel_group integer.
- Steps that need data from a previous step must list that step in depends_on.
- Set skill/action to null for pure reasoning or synthesis steps.
- Use params_hint for rough parameter guidance (not required to be exact).

Respond with JSON only (no markdown fences):
{
  "goal": "one-line overall goal",
  "complexity": "medium|high",
  "steps": [
    {
      "id": 1,
      "description": "what this step does",
      "skill": "skill_name or null",
      "action": "skill_action or null",
      "params_hint": {},
      "depends_on": [],
      "parallel_group": null
    }
  ]
}"""


class Planner:
    """
    Generates a step-by-step execution blueprint for complex multi-skill queries.
    Falls back gracefully to a single-step plan if LLM call fails.
    """

    async def plan(self, message: str, llm: "LLMRouter") -> Plan:
        """Generate an execution plan for the given user message."""
        try:
            response = await llm.chat(
                messages=[{"role": "user", "content": f"Create an execution plan for this task:\n\n{message}"}],
                system_prompt=_PLANNER_SYSTEM_PROMPT,
                max_tokens=900,
                temperature=0.2,
            )

            response = response.strip()
            if response.startswith("```"):
                response = re.sub(r"```(?:json)?\s*", "", response).strip("`").strip()

            data = json.loads(response)

            steps = [
                PlanStep(
                    id=s["id"],
                    description=s["description"],
                    skill=s.get("skill"),
                    action=s.get("action"),
                    params_hint=s.get("params_hint") or {},
                    depends_on=s.get("depends_on") or [],
                    parallel_group=s.get("parallel_group"),
                )
                for s in data.get("steps", [])
            ]

            if not steps:
                raise ValueError("Planner returned empty steps list")

            plan = Plan(
                goal=data.get("goal", message),
                steps=steps,
                complexity=data.get("complexity", "medium"),
            )
            logger.info(
                f"Planner generated plan: goal='{plan.goal}', "
                f"{len(steps)} steps, complexity={plan.complexity}"
            )
            return plan

        except Exception as e:
            logger.warning(f"Plan generation failed ({e}). Using trivial fallback plan.")
            return Plan(
                goal=message,
                steps=[
                    PlanStep(
                        id=1,
                        description="Execute the user request using available skills",
                    )
                ],
                complexity="medium",
            )
