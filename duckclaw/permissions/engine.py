"""
DuckClaw Permission Engine — THE core differentiator.
4-Tier action approval system:
  SAFE   → auto-approved, no notification
  NOTIFY → auto-approved, user informed
  ASK    → must get explicit user approval before executing
  BLOCK  → never allowed, always rejected

Every action is logged to the audit trail.
"""

import json
import logging
import sqlite3
import asyncio
from enum import Enum
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Any
from dataclasses import dataclass

from duckclaw.core.config import PermissionsConfig, MemoryConfig

logger = logging.getLogger(__name__)


AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
    action_type     TEXT NOT NULL,
    tier            TEXT NOT NULL,
    description     TEXT NOT NULL,
    details         TEXT,
    status          TEXT NOT NULL,
    source          TEXT DEFAULT 'system',
    session_id      TEXT,
    reversible      INTEGER DEFAULT 1,
    risk_level      TEXT DEFAULT 'low'
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_log(action_type);
CREATE INDEX IF NOT EXISTS idx_audit_status ON audit_log(status);
"""


class Tier(str, Enum):
    SAFE = "safe"        # No approval needed — answer questions, read memory
    NOTIFY = "notify"    # User informed after — file reads, web search, browse
    ASK = "ask"          # Must approve before — send email, screenshot, shell exec
    BLOCK = "block"      # Never allowed — delete system files, access credentials


# ── Default action classification ─────────────────────────────────────────────
# Conservative defaults: unknown actions default to ASK
DEFAULT_RULES: dict[str, Tier] = {
    # SAFE — pure information, no side effects
    "chat_response":        Tier.SAFE,
    "memory_read":          Tier.SAFE,
    "memory_search":        Tier.SAFE,
    "web_search":           Tier.SAFE,
    "list_files":           Tier.SAFE,
    "list_cameras":         Tier.SAFE,

    # NOTIFY — read-only access, informs user
    "file_read":            Tier.NOTIFY,
    "web_browse":           Tier.NOTIFY,
    "shell_safe":           Tier.NOTIFY,
    "browser_screenshot":   Tier.NOTIFY,
    "extract_text":         Tier.NOTIFY,

    # ASK — has real-world side effects
    "screen_capture":       Tier.ASK,
    "camera_capture":       Tier.ASK,
    "file_write":           Tier.ASK,
    "file_delete":          Tier.ASK,
    "send_email":           Tier.ASK,
    "send_message":         Tier.ASK,
    "shell_exec":           Tier.ASK,
    "web_form_submit":      Tier.ASK,
    "web_fill_form":        Tier.ASK,
    "install_package":      Tier.ASK,
    "create_calendar_event": Tier.ASK,
    "browser_navigate":     Tier.ASK,

    # BLOCK — hardcoded, can NEVER be overridden via chat or config
    "access_credentials":   Tier.BLOCK,
    "sudo_command":         Tier.BLOCK,
    "rm_recursive_root":    Tier.BLOCK,
    "curl_pipe_bash":       Tier.BLOCK,
    "format_disk":          Tier.BLOCK,
    "write_raw_disk":       Tier.BLOCK,
    "fork_bomb":            Tier.BLOCK,
}

# These are HARDCODED and cannot be changed by user config or LLM
HARDCODED_BLOCKS = {
    "access_credentials",
    "sudo_command",
    "rm_recursive_root",
    "curl_pipe_bash",
    "format_disk",
    "write_raw_disk",
    "fork_bomb",
}


@dataclass
class ActionPreview:
    """Preview shown to user before any ASK-tier action executes."""
    action_type: str
    description: str
    details: dict
    reversible: bool
    risk_level: str  # "low" | "medium" | "high"
    tier: Tier

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type,
            "description": self.description,
            "details": self.details,
            "reversible": self.reversible,
            "risk_level": self.risk_level,
            "tier": self.tier.value,
        }

    def format_for_terminal(self) -> str:
        """Format the preview for terminal display."""
        risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(self.risk_level, "⚪")
        reversible_str = "✓ Reversible" if self.reversible else "✗ Irreversible"

        lines = [
            f"\n{'='*50}",
            f"⚠️  Permission Required",
            f"Action: {self.description}",
            f"Risk: {risk_emoji} {self.risk_level.upper()}  |  {reversible_str}",
        ]

        if self.details:
            lines.append("Details:")
            for k, v in self.details.items():
                lines.append(f"  {k}: {v}")

        lines.append(f"{'='*50}")
        return "\n".join(lines)


class PermissionEngine:
    """
    Central permission gatekeeper for DuckClaw.

    Every action passes through here before execution.
    Every action is logged to the audit trail.

    Approval callbacks are set by the active interface (dashboard WebSocket,
    Telegram bot, Discord bot, or terminal prompt).
    """

    def __init__(
        self,
        config: PermissionsConfig,
        db_path: str,
    ):
        self.config = config
        self.db_path = db_path

        # Build effective rules (user overrides, but HARDCODED_BLOCKS are immutable)
        self.rules = dict(DEFAULT_RULES)

        # Apply user config overrides — but NEVER allow overriding hardcoded blocks
        # (Even if user sets "access_credentials: safe" in config, we ignore it)

        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(AUDIT_SCHEMA)
        self._db.commit()

        # Approval callback — set by active interface
        # Signature: async (preview: ActionPreview) -> bool
        self._approval_callback: Optional[Callable] = None

        # Notification callback — set by active interface
        # Signature: async (message: str) -> None
        self._notify_callback: Optional[Callable] = None

    def set_approval_callback(self, callback: Callable):
        """Register the function that asks user for approval."""
        self._approval_callback = callback

    def set_notify_callback(self, callback: Callable):
        """Register the function that notifies user."""
        self._notify_callback = callback

    def get_tier(self, action_type: str) -> Tier:
        """Get the permission tier for an action type."""
        # HARDCODED blocks cannot be overridden
        if action_type in HARDCODED_BLOCKS:
            return Tier.BLOCK
        return self.rules.get(action_type, Tier.ASK)  # Unknown = ASK (safe default)

    async def check(
        self,
        action_type: str,
        description: str,
        details: Optional[dict] = None,
        source: str = "system",
        session_id: Optional[str] = None,
        reversible: bool = True,
        risk_level: str = "low",
    ) -> bool:
        """
        Check permission for an action. Returns True if approved, False if denied/blocked.

        This is the main entry point. Call this before EVERY sensitive action.

        Example:
            approved = await permissions.check(
                action_type="screen_capture",
                description="Take a screenshot of your screen",
                details={"monitor": 0},
                reversible=True,
                risk_level="low",
            )
            if approved:
                do_screenshot()
        """
        tier = self.get_tier(action_type)

        if tier == Tier.SAFE:
            status = "auto_approved"
            approved = True

        elif tier == Tier.NOTIFY:
            approved = True
            status = "notified"
            if self._notify_callback:
                try:
                    await self._notify_callback(f"ℹ️ {description}")
                except Exception as e:
                    logger.warning(f"Notify callback failed: {e}")

        elif tier == Tier.ASK:
            preview = ActionPreview(
                action_type=action_type,
                description=description,
                details=details or {},
                reversible=reversible,
                risk_level=risk_level,
                tier=tier,
            )

            approved = False
            if self._approval_callback:
                try:
                    approved = await self._approval_callback(preview)
                except Exception as e:
                    logger.error(f"Approval callback failed: {e}")
                    approved = False
            else:
                # No callback set — fall back to terminal prompt
                approved = await self._terminal_prompt(preview)

            status = "user_approved" if approved else "user_denied"

        else:  # BLOCK
            approved = False
            status = "blocked"
            if self._notify_callback:
                try:
                    await self._notify_callback(f"🚫 BLOCKED: {description}")
                except Exception:
                    pass
            logger.warning(f"BLOCKED action attempted: {action_type} — {description}")

        # Log EVERYTHING to audit trail
        self._log(
            action_type=action_type,
            tier=tier,
            description=description,
            details=details,
            status=status,
            source=source,
            session_id=session_id,
            reversible=reversible,
            risk_level=risk_level,
        )

        return approved

    async def _terminal_prompt(self, preview: ActionPreview) -> bool:
        """Fallback: ask for approval in the terminal."""
        import sys
        print(preview.format_for_terminal())

        loop = asyncio.get_event_loop()
        try:
            answer = await loop.run_in_executor(
                None,
                lambda: input("Approve? [y/N]: ").strip().lower()
            )
            return answer in ("y", "yes", 1, "1", "true", "t")
        except (EOFError, KeyboardInterrupt):
            return False

    def _log(
        self,
        action_type: str,
        tier: Tier,
        description: str,
        status: str,
        details: Optional[dict],
        source: str,
        session_id: Optional[str],
        reversible: bool,
        risk_level: str,
    ):
        """Write to audit log. Every action, no exceptions."""
        try:
            self._db.execute(
                "INSERT INTO audit_log "
                "(action_type, tier, description, details, status, source, session_id, reversible, risk_level) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    action_type,
                    tier.value,
                    description,
                    json.dumps(details) if details else None,
                    status,
                    source,
                    session_id,
                    int(reversible),
                    risk_level,
                ),
            )
            self._db.commit()
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

    # ── Audit Log Queries ──────────────────────────────────────────────────────

    def get_audit_log(
        self,
        limit: int = 50,
        offset: int = 0,
        action_type: Optional[str] = None,
        status: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> list[dict]:
        """Fetch audit log entries for the dashboard."""
        conditions = []
        params = []

        if action_type:
            conditions.append("action_type = ?")
            params.append(action_type)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if tier:
            conditions.append("tier = ?")
            params.append(tier)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])

        rows = self._db.execute(
            f"SELECT * FROM audit_log {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()

        return [dict(r) for r in rows]

    def get_audit_stats(self) -> dict:
        """Summary stats for the dashboard."""
        total = self._db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        approved = self._db.execute(
            "SELECT COUNT(*) FROM audit_log WHERE status IN ('auto_approved', 'notified', 'user_approved')"
        ).fetchone()[0]
        denied = self._db.execute(
            "SELECT COUNT(*) FROM audit_log WHERE status = 'user_denied'"
        ).fetchone()[0]
        blocked = self._db.execute(
            "SELECT COUNT(*) FROM audit_log WHERE status = 'blocked'"
        ).fetchone()[0]

        return {
            "total_actions": total,
            "approved": approved,
            "denied": denied,
            "blocked": blocked,
        }

    def export_audit_log(self, fmt: str = "json") -> str:
        """Export full audit log as JSON or CSV."""
        rows = self.get_audit_log(limit=100000)
        if fmt == "json":
            return json.dumps(rows, indent=2)
        elif fmt == "csv":
            if not rows:
                return "id,timestamp,action_type,tier,description,status,source\n"
            headers = list(rows[0].keys())
            lines = [",".join(headers)]
            for row in rows:
                values = [str(row.get(h, "")).replace(",", ";") for h in headers]
                lines.append(",".join(values))
            return "\n".join(lines)
        raise ValueError(f"Unknown format: {fmt}")

    def close(self):
        if self._db:
            self._db.close()
