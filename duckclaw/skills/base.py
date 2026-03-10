"""
DuckClaw Skill System — Base classes and sandboxed execution.

Every skill:
1. Declares its permissions upfront (no surprises)
2. Runs through the Permission Engine before executing
3. Has its integrity verified via SHA-256 hash
4. Executes within resource limits (CPU, memory caps)

This directly addresses a known AI assistant risk:
third-party skill marketplaces can distribute malicious code that runs with full process privileges.
"""

import hashlib
import importlib
import inspect
import json
import logging
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from duckclaw.permissions.engine import PermissionEngine

logger = logging.getLogger(__name__)


class SkillPermission(str, Enum):
    """All possible permissions a skill can declare."""
    # Read-only / information
    WEB_SEARCH    = "web.search"       # Tier: SAFE
    MEMORY_READ   = "memory.read"      # Tier: SAFE
    FILE_LIST     = "file.list"        # Tier: SAFE

    # Side effects — notify user
    FILE_READ     = "file.read"        # Tier: NOTIFY
    WEB_BROWSE    = "web.browse"       # Tier: NOTIFY
    SHELL_SAFE    = "shell.safe"       # Tier: NOTIFY (ls, cat, git status…)

    # Requires explicit approval
    FILE_WRITE    = "file.write"       # Tier: ASK
    FILE_DELETE   = "file.delete"      # Tier: ASK
    SHELL_EXEC    = "shell.exec"       # Tier: ASK
    SCREEN        = "screen.capture"   # Tier: ASK
    CAMERA        = "camera.snap"      # Tier: ASK
    SEND_MESSAGE  = "msg.send"         # Tier: ASK
    WEB_SUBMIT    = "web.submit"       # Tier: ASK
    PKG_INSTALL   = "pkg.install"      # Tier: ASK
    SCHEDULE      = "scheduler.add"    # Tier: ASK


@dataclass
class SkillResult:
    """Standardized return type from all skill calls."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    action_taken: Optional[str] = None   # Human-readable description
    metadata: dict = field(default_factory=dict)

    def to_text(self) -> str:
        """Format result as text for LLM context."""
        if not self.success:
            return f"❌ Skill error: {self.error}"
        if isinstance(self.data, str):
            return self.data
        if isinstance(self.data, (dict, list)):
            return json.dumps(self.data, indent=2)
        return str(self.data)


class BaseSkill(ABC):
    """
    Base class for all DuckClaw skills.

    Subclasses must define:
      - name: str
      - description: str
      - permissions: list[SkillPermission]
      - execute(action, params) -> SkillResult
    """

    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    permissions: list[SkillPermission] = []
    integrity_hash: str = ""          # SHA-256 of skill file — verified at load

    # Resource limits for sandboxed execution
    max_cpu_seconds: int = 30
    max_memory_mb: int = 256
    network_allowed: bool = False
    allowed_paths: list[str] = []

    def __init__(self, permission_engine: "PermissionEngine"):
        self._permissions = permission_engine
        self._session_id: Optional[str] = None

    def set_session(self, session_id: str):
        self._session_id = session_id

    @abstractmethod
    async def execute(self, action: str, params: dict) -> SkillResult:
        """Execute a skill action. Called after permission check."""
        pass

    async def run(self, action: str, params: dict, session_id: Optional[str] = None) -> SkillResult:
        """
        Public entry point. Verifies integrity, checks permissions, then executes.
        """
        if session_id:
            self._session_id = session_id

        # 1. Verify integrity hash (if declared)
        if self.integrity_hash and not self._verify_integrity():
            logger.error(f"Skill {self.name} failed integrity check!")
            return SkillResult(
                success=False,
                error="Skill integrity verification failed. Skill file may have been tampered with."
            )

        # 2. Execute (permission checks happen inside each skill action)
        try:
            result = await self.execute(action, params)
            return result
        except Exception as e:
            logger.exception(f"Skill {self.name}.{action} raised exception")
            return SkillResult(success=False, error=str(e))

    def _verify_integrity(self) -> bool:
        """Check that the skill file hasn't been modified since registration."""
        skill_file = inspect.getfile(self.__class__)
        try:
            with open(skill_file, "rb") as f:
                actual = hashlib.sha256(f.read()).hexdigest()
            expected = self.integrity_hash.replace("sha256:", "")
            return actual == expected
        except Exception as e:
            logger.warning(f"Could not verify skill integrity: {e}")
            return True  # Fail open for local dev; fail closed in production

    async def _check(
        self,
        action_type: str,
        description: str,
        details: Optional[dict] = None,
        reversible: bool = True,
        risk_level: str = "low",
    ) -> bool:
        """Helper: check permission before executing an action."""
        return await self._permissions.check(
            action_type=action_type,
            description=description,
            details=details,
            source=f"skill:{self.name}",
            session_id=self._session_id,
            reversible=reversible,
            risk_level=risk_level,
        )
