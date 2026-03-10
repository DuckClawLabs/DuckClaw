"""
Shell Runner Skill.
Executes shell commands with safety classification.

Hardcoded BLOCKED patterns — these can NEVER be executed, regardless
of what the LLM or user says (prompt injection defense at the skill level).

Safe commands → NOTIFY tier (just inform user).
Unknown commands → ASK tier (explicit approval required).
Blocked patterns → immediate rejection, no approval possible.
"""

import logging
import re
import subprocess
from duckclaw.skills.base import BaseSkill, SkillPermission, SkillResult

logger = logging.getLogger(__name__)

# ── Hardcoded block list — IMMUTABLE ──────────────────────────────────────────
# These patterns are NEVER executed, no approval can override.
BLOCKED_PATTERNS = [
    (r"rm\s+-rf\s+[/~]",          "Recursive delete from root/home"),
    (r"rm\s+--no-preserve-root",  "rm --no-preserve-root"),
    (r"sudo\s+",                   "sudo command"),
    (r"su\s+-",                    "switch user"),
    (r"curl[^|]*\|\s*(ba)?sh",    "curl pipe to shell"),
    (r"wget[^|]*\|\s*(ba)?sh",    "wget pipe to shell"),
    (r":\(\)\s*\{\s*:\|:",        "fork bomb"),
    (r"dd\s+if=",                  "disk read/write with dd"),
    (r"mkfs\.",                    "format filesystem"),
    (r">\s*/dev/sd",               "write to raw disk device"),
    (r"chmod\s+777\s+/",          "chmod 777 on root"),
    (r"chown\s+-R.*:.*\s+/",      "recursive chown on root"),
    (r"mv\s+.*\s+/dev/null",      "move to /dev/null"),
    (r"iptables\s+-F",             "flush firewall rules"),
    (r"systemctl\s+disable",       "disable system service"),
]

# ── Safe commands — always NOTIFY tier ────────────────────────────────────────
SAFE_COMMAND_PREFIXES = [
    "ls", "ll", "la", "l ",
    "cat ", "head ", "tail ", "wc ", "nl ",
    "echo ", "printf ",
    "grep ", "awk ", "sed ",
    "find ", "locate ",
    "pwd", "whoami", "id", "uptime", "date", "cal",
    "df ", "du ", "free", "top -bn1",
    "ps ", "pgrep ",
    "git status", "git log", "git diff", "git branch", "git stash list",
    "git show ", "git blame ", "git tag",
    "python --version", "python3 --version",
    "pip list", "pip show ", "pip freeze",
    "node --version", "npm list",
    "which ", "type ", "man ",
    "sort ", "uniq ", "cut ", "tr ",
    "env", "printenv ",
    "uname ", "lsb_release",
    "curl -s ", "curl --silent ",  # Read-only curl (no pipe to shell)
    "ping -c ",
    "nslookup ", "dig ",
    "netstat -", "ss -",
]

COMMAND_TIMEOUT = 30  # seconds


class ShellRunnerSkill(BaseSkill):
    name = "shell_runner"
    description = "Execute shell commands with safety classification. Dangerous patterns are always blocked."
    version = "1.0.0"
    permissions = [SkillPermission.SHELL_SAFE, SkillPermission.SHELL_EXEC]

    async def execute(self, action: str, params: dict) -> SkillResult:
        if action == "run":
            return await self._run(params)
        elif action == "check_safe":
            return self._check_safe(params)
        return SkillResult(success=False, error=f"Unknown action: {action}")

    async def _run(self, params: dict) -> SkillResult:
        command = params.get("command", "").strip()
        if not command:
            return SkillResult(success=False, error="command is required")

        # 1. Check hardcoded blocklist first
        for pattern, reason in BLOCKED_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                logger.warning(f"BLOCKED shell command: {command!r} — {reason}")
                # Log to audit trail via permission engine (tier=BLOCK)
                await self._permissions.check(
                    action_type="sudo_command",
                    description=f"BLOCKED: {reason}",
                    details={"command": command, "blocked_reason": reason},
                    source=f"skill:{self.name}",
                    session_id=self._session_id,
                )
                return SkillResult(
                    success=False,
                    error=f"🚫 Command blocked: {reason}\nThis pattern is permanently blocked for security.",
                )

        # 2. Classify tier
        is_safe = any(command.strip().startswith(prefix) for prefix in SAFE_COMMAND_PREFIXES)
        action_type = "shell_safe" if is_safe else "shell_exec"
        risk = "low" if is_safe else "medium"
        description = f"{'Run' if is_safe else 'Execute'} command: `{command}`"

        # 3. Permission check
        approved = await self._check(
            action_type,
            description,
            details={"command": command, "safe": is_safe},
            reversible=True,
            risk_level=risk,
        )
        if not approved:
            return SkillResult(success=False, error="Command execution denied.")

        # 4. Execute with timeout
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT,
                cwd=None,
            )

            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}" if result.stdout else result.stderr

            if not output.strip():
                output = f"(Command completed with exit code {result.returncode})"

            # Truncate very long output
            if len(output) > 8000:
                output = output[:8000] + f"\n\n[... truncated — {len(output):,} total chars]"

            return SkillResult(
                success=result.returncode == 0,
                data=output,
                action_taken=f"Ran: {command}",
                metadata={"exit_code": result.returncode},
                error=f"Exit code {result.returncode}" if result.returncode != 0 else None,
            )

        except subprocess.TimeoutExpired:
            return SkillResult(success=False, error=f"Command timed out after {COMMAND_TIMEOUT}s: {command}")
        except Exception as e:
            return SkillResult(success=False, error=f"Execution error: {e}")

    def _check_safe(self, params: dict) -> SkillResult:
        """Check if a command would be blocked without running it."""
        command = params.get("command", "")
        for pattern, reason in BLOCKED_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return SkillResult(success=True, data={"safe": False, "reason": reason})
        is_safe = any(command.strip().startswith(p) for p in SAFE_COMMAND_PREFIXES)
        return SkillResult(success=True, data={"safe": True, "tier": "notify" if is_safe else "ask"})
