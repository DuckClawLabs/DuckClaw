"""
DuckClaw Agent System.

The model is the intelligence layer — it reads the skill knowledge base and
handles all query types natively through the ReAct loop:

  User Query
      → ReActEngine      (Thought → Skill call → Observation → … → final_answer)
      → ReflectionAgent  (quality check)
      → ResponseSynthesizer (polish if needed, pass-through if approved)

No separate intent classifier or planner — the model does that reasoning itself.
New skills added to knowledge_base.py are automatically available to the model.
"""

from duckclaw.agent.react_engine import ReActEngine, ReActResult, AgentStep
from duckclaw.agent.reflection import ReflectionAgent, ReflectionResult
from duckclaw.agent.synthesizer import ResponseSynthesizer

__all__ = [
    "ReActEngine",
    "ReActResult",
    "AgentStep",
    "ReflectionAgent",
    "ReflectionResult",
    "ResponseSynthesizer",
]
