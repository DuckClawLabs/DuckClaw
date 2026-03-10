"""
DuckClaw Skill Registry.
Central registry of all available skills.
Skills are loaded lazily on first use.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from duckclaw.permissions.engine import PermissionEngine
    from duckclaw.skills.base import BaseSkill

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    Registry of all available DuckClaw skills.
    Resolves natural language intent → skill + action.
    """

    def __init__(self, permission_engine: "PermissionEngine"):
        self._permissions = permission_engine
        self._skills: dict[str, "BaseSkill"] = {}
        self._loaded = False

    def _load_skills(self):
        """Lazy-load all built-in skills."""
        if self._loaded:
            return

        from duckclaw.skills.web_search import WebSearchSkill
        from duckclaw.skills.file_manager import FileManagerSkill
        from duckclaw.skills.shell_runner import ShellRunnerSkill
        from duckclaw.skills.screen_capture import ScreenCaptureSkill
        from duckclaw.skills.scheduler import SchedulerSkill
        from duckclaw.skills.web_browser import WebBrowserSkill
        from duckclaw.skills.camera import CameraSkill

        skill_classes = [
            WebSearchSkill,
            FileManagerSkill,
            ShellRunnerSkill,
            ScreenCaptureSkill,
            SchedulerSkill,
            WebBrowserSkill,
            CameraSkill,
        ]

        for cls in skill_classes:
            try:
                skill = cls(self._permissions)
                self._skills[skill.name] = skill
                logger.info(f"Loaded skill: {skill.name}")
            except Exception as e:
                logger.warning(f"Failed to load skill {cls.__name__}: {e}")

        self._loaded = True

    def wire_llm(self, llm_router):
        """Inject LLM router into skills that support vision (camera, screen)."""
        self._load_skills()
        for skill in self._skills.values():
            if hasattr(skill, "set_llm"):
                skill.set_llm(llm_router)

    def get(self, skill_name: str) -> "BaseSkill | None":
        self._load_skills()
        return self._skills.get(skill_name)

    def list_skills(self) -> list[dict]:
        self._load_skills()
        return [
            {
                "name": s.name,
                "description": s.description,
                "version": s.version,
                "permissions": [p.value for p in s.permissions],
            }
            for s in self._skills.values()
        ]

    def get_skills_context(self) -> str:
        """Build a skills summary for injection into the system prompt."""
        self._load_skills()
        if not self._skills:
            return ""

        lines = ["\n## Available Skills (tools you can use):"]
        for skill in self._skills.values():
            lines.append(f"- **{skill.name}**: {skill.description}")
        lines.append(
            "\nTo use a skill, respond with JSON in this format:\n"
            '```json\n{"skill": "skill_name", "action": "action_name", "params": {...}}\n```'
        )
        return "\n".join(lines)

    async def dispatch(
        self,
        skill_name: str,
        action: str,
        params: dict,
        session_id: str | None = None,
    ):
        """Dispatch a skill call. Returns SkillResult."""
        self._load_skills()
        skill = self._skills.get(skill_name)
        if skill is None:
            from duckclaw.skills.base import SkillResult
            return SkillResult(success=False, error=f"Unknown skill: {skill_name}")
        return await skill.run(action, params, session_id=session_id)
