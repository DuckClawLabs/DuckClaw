"""
DuckClaw Orchestrator — Intelligent Agent Pipeline.

Architecture:
  User Query
      ↓
  [1] Injection Scan          (security — input)
      ↓
  [2] Build Memory Context    (facts + memories + session history from ChromaDB/SQLite)
      ↓
  [3] ReAct Engine            (model decides: general / skill / multi-skill)
         Reads full skill catalog from knowledge_base.py → auto-expands as skills grow
         Thinks → Calls skill via SkillRegistry → Observes → Repeats → final_answer
      ↓
  [4] Reflection Agent        (quality check — skipped for pure knowledge answers)
      ↓
  [5] Response Synthesizer    (fast-path if approved, rewrite if quality < 7)
      ↓
  [6] Injection Scan          (security — output)
      ↓
  [7] Memory + Audit          (save turns, extract facts, log actions)
      ↓
  Rich, grounded, multi-step answer

The model is the intelligence layer — no separate intent classifier or planner.
It reads the knowledge base and handles general questions, single-skill tasks,
and multi-step workflows natively through the ReAct loop.

All permission checks, audit logging, and prompt-injection defence are
preserved exactly as before.
"""

import asyncio
import logging
import uuid
from typing import Optional

from duckclaw.core.config import DuckClawConfig
from duckclaw.llm.router import LLMRouter
from duckclaw.memory.store import MemoryStore
from duckclaw.memory.extractor import extract_facts
from duckclaw.permissions.engine import PermissionEngine
from duckclaw.skills.registry import SkillRegistry
from duckclaw.security.context_isolation import scan_output

# Agent pipeline
from duckclaw.agent.react_engine import ReActEngine
from duckclaw.agent.reflection import ReflectionAgent, ReflectionResult
from duckclaw.agent.synthesizer import ResponseSynthesizer

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Central coordinator for DuckClaw.
    One instance per server — shared across all active sessions.
    """

    def __init__(self, config: DuckClawConfig):
        self.config = config

        # Core subsystems
        self.llm         = LLMRouter(config.llm)
        self.memory:      Optional[MemoryStore]      = None
        self.permissions: Optional[PermissionEngine] = None
        self.skills:      Optional[SkillRegistry]    = None

        # Agent pipeline (no intent classifier, no planner — model handles it)
        self.react_engine        = ReActEngine()
        self.reflection_agent    = ReflectionAgent()
        self.synthesizer         = ResponseSynthesizer()

        self._initialized = False

    # ── Startup ───────────────────────────────────────────────────────────────

    async def initialize(self):
        """Initialize all subsystems. Call once at startup."""
        if self._initialized:
            return

        self.memory = MemoryStore(self.config.memory)
        await self.memory.initialize()

        self.permissions = PermissionEngine(
            config=self.config.permissions,
            db_path=self.config.memory.db_path_expanded,
        )

        self.skills = SkillRegistry(self.permissions)

        try:
            self.skills.wire_llm(self.llm)
        except Exception:
            pass

        # Seed skill knowledge base into ChromaDB if empty
        try:
            from duckclaw.skills.knowledge_base import SKILLS
            if (
                self.memory._skills_collection is not None
                and self.memory._skills_collection.count() == 0
            ):
                self.memory.seed_skills(SKILLS)
        except Exception as e:
            logger.warning(f"Could not auto-seed skills KB: {e}")

        self._initialized = True
        logger.info(
            f"DuckClaw Orchestrator initialized — "
            f"primary={self.config.llm.model} | "
            f"reasoning={self.llm.get_reasoning_model()} | "
            f"vision={self.llm.get_vision_model()} | "
            f"audio={self.llm.get_audio_model()}"
        )

    # ── Main entry point ──────────────────────────────────────────────────────

    async def chat(
        self,
        message: str,
        session_id: Optional[str] = None,
        source: str = "terminal",
        user_id: Optional[str] = None,
    ) -> dict:
        """
        Process a user message through the intelligent agent pipeline.

        Compatible with all existing callers: dashboard WebSocket, CLI, bridges.
        """
        if not self._initialized:
            await self.initialize()

        session_id         = session_id or str(uuid.uuid4())
        injection_warnings: list[str]  = []
        skills_used:        list[str]  = []
        image_b64:          Optional[str] = None
        image_path:         Optional[str] = None

        # ── [1] Injection scan — input ────────────────────────────────────
        if self.config.security.prompt_injection_defense:
            input_warnings = scan_output(message, context="user_input")
            if input_warnings:
                logger.warning(f"Input injection signals: {input_warnings}")
                injection_warnings.extend(input_warnings)
                await self._log_injection_warnings(input_warnings, session_id, source)

        # ── [2] Build memory context ──────────────────────────────────────
        agent_context = self._build_agent_context(message, session_id)

        # ── [3] ReAct Engine — model handles everything ───────────────────
        # The model reads the full skill knowledge base and decides on its own:
        #   - General question  → final_answer immediately (no skill calls)
        #   - Single-skill task → one skill call then final_answer
        #   - Multi-step task   → chains skill calls, then final_answer
        try:
            react_result = await self.react_engine.run(
                message=message,
                context=agent_context,
                skill_registry=self.skills,
                llm=self.llm,
                session_id=session_id,
                memory_store=self.memory,
            )
            skills_used = react_result.skills_used
            logger.info(
                f"ReAct complete: iters={react_result.iterations}, "
                f"skills={skills_used}, success={react_result.success}"
            )
        except Exception as e:
            logger.error(f"ReAct engine error: {e}")
            reply = f"⚠️ Agent error: {e}. Please check your API key and try again."
            self.memory.save_message(session_id, "user", message, source)
            self.memory.save_message(session_id, "assistant", reply, source)
            return self._build_response(
                reply=reply,
                session_id=session_id,
                skills_used=[],
                injection_warnings=injection_warnings,
            )

        # ── [4] Reflection ────────────────────────────────────────────────
        try:
            reflection = await self.reflection_agent.reflect(
                original_query=message,
                react_result=react_result,
                llm=self.llm,
            )
        except Exception as e:
            logger.warning(f"Reflection failed ({e}). Auto-approving.")
            reflection = ReflectionResult(approved=True, quality_score=7)

        # ── [5] Synthesize final answer ───────────────────────────────────
        try:
            reply = await self.synthesizer.synthesize(
                original_query=message,
                react_result=react_result,
                reflection=reflection,
                llm=self.llm,
            )
        except Exception as e:
            logger.warning(f"Synthesizer failed ({e}). Using ReAct answer directly.")
            reply = react_result.final_answer

        # ── [6] Injection scan — output ───────────────────────────────────
        if self.config.security.prompt_injection_defense:
            out_warnings = scan_output(reply, context=message[:100])
            if out_warnings:
                logger.warning(f"Output injection signals: {out_warnings}")
                injection_warnings.extend(out_warnings)
                await self._log_injection_warnings(out_warnings, session_id, source)

        # ── [7] Save to memory ────────────────────────────────────────────
        self.memory.save_message(session_id, "user", message, source)
        self.memory.save_message(session_id, "assistant", reply, source)

        # Background fact extraction (non-blocking)
        asyncio.create_task(self._extract_facts_background(message, session_id))

        # Extract image metadata (screen_capture / camera skills)
        for step in react_result.steps:
            if step.skill_name in ("screen_capture", "camera") and step.skill_success:
                # Image data is returned in SkillResult.metadata; mark for UI
                image_b64  = None   # populated by dashboard if needed
                image_path = None

        return self._build_response(
            reply=reply,
            session_id=session_id,
            skills_used=skills_used,
            injection_warnings=injection_warnings,
            image_b64=image_b64,
            image_path=image_path,
            react_steps=len(react_result.steps),
            iterations=react_result.iterations,
        )

    # ── Context builder ───────────────────────────────────────────────────────

    def _build_agent_context(self, message: str, session_id: str) -> dict:
        """
        Load memory, facts, and session history for the ReAct engine.

        memory_summary  → injected into the ReAct system prompt
        history         → prepended to the messages list
        """
        facts    = self.memory.search_facts(message, n_results=10)  if self.memory else []
        memories = self.memory.search_memory(message, n_results=3)  if self.memory else []
        history  = self.memory.get_session_history(session_id, limit=20) if self.memory else []

        # Build readable memory summary for the system prompt
        parts: list[str] = []
        if facts:
            parts.append("Known user facts:")
            for f in facts:
                parts.append(f"  - [{f['category']}] {f['fact']}")
        if memories:
            parts.append("Relevant past conversations:")
            for m in memories:
                parts.append(f"  - {m[:200]}")

        return {
            "history":        history,
            "facts":          facts,
            "memories":       memories,
            "memory_summary": "\n".join(parts) if parts else "(no prior context)",
        }

    # ── Response builder ──────────────────────────────────────────────────────

    @staticmethod
    def _build_response(
        reply: str,
        session_id: str,
        skills_used: list[str],
        injection_warnings: list[str],
        image_b64: Optional[str] = None,
        image_path: Optional[str] = None,
        react_steps: int = 0,
        iterations: int = 0,
    ) -> dict:
        """Build the standard response dict consumed by dashboard, CLI, and bridges."""
        return {
            "reply":              reply,
            "session_id":         session_id,
            "notifications":      [],
            "skill_used":         skills_used[0] if skills_used else None,
            "skills_used":        skills_used,
            "injection_warnings": injection_warnings,
            "image_base64":       image_b64,
            "image_path":         image_path,
            "react_steps":        react_steps,
            "iterations":         iterations,
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _log_injection_warnings(
        self, warnings: list[str], session_id: str, source: str
    ):
        if not self.permissions:
            return
        for warning in warnings:
            try:
                await self.permissions.check(
                    action_type="security.injection_signal",
                    description=warning,
                    details={"session_id": session_id, "source": source},
                    source="security:scan_output",
                    session_id=session_id,
                    reversible=True,
                    risk_level="high",
                )
            except Exception as e:
                logger.warning(f"Could not log injection warning: {e}")

    async def _extract_facts_background(self, message: str, session_id: str):
        try:
            facts = await extract_facts(message, self.llm, self.memory)
            if facts:
                logger.debug(f"Extracted {len(facts)} facts — session={session_id}")
        except Exception as e:
            logger.warning(f"Background fact extraction failed: {e}")

    # ── Stats & lifecycle ─────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        return {
            "llm":         self.llm.get_stats(),
            "memory":      self.memory.get_stats()          if self.memory      else {},
            "permissions": self.permissions.get_audit_stats() if self.permissions else {},
            "skills":      self.skills.list_skills()         if self.skills      else [],
        }

    async def start_bridge(self, bridge_type: str, **kwargs):
        if not self._initialized:
            await self.initialize()
        if bridge_type == "telegram":
            from duckclaw.bridges.telegram_bridge import TelegramBridge
            bridge = TelegramBridge(
                token=kwargs["token"],
                orchestrator=self,
                allowed_users=kwargs.get("allowed_users"),
            )
        elif bridge_type == "discord":
            from duckclaw.bridges.discord_bridge import DiscordBridge
            bridge = DiscordBridge(
                token=kwargs["token"],
                orchestrator=self,
                guild_ids=kwargs.get("guild_ids"),
            )
        else:
            raise ValueError(f"Unknown bridge type: {bridge_type}")
        await bridge.start()
        return bridge

    async def shutdown(self):
        if self.memory:
            self.memory.close()
        if self.permissions:
            self.permissions.close()
        logger.info("DuckClaw Orchestrator shut down")
