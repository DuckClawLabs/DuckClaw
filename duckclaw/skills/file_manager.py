"""
File Manager Skill.
Scoped by default: only allowed paths, hardcoded blocklist.
The blocklist CANNOT be overridden by LLM output or user config — it's code.

Tier mapping:
  list_files, read_file → NOTIFY
  write_file, create_dir → ASK
  delete_file → ASK (risk: medium)
"""

import logging
import os
import re
from pathlib import Path
from duckclaw.skills.base import BaseSkill, SkillPermission, SkillResult

logger = logging.getLogger(__name__)

# Hardcoded blocklist — these paths NEVER get read or written
# regardless of what the LLM or user says in chat.
BLOCKED_PATH_PATTERNS = [
    r"\.ssh",
    r"\.gnupg",
    r"\.pgp",
    r"\.env",
    r"credentials",
    r"\.netrc",
    r"\.git/config",
    r"id_rsa",
    r"id_ed25519",
    r"\.pem$",
    r"\.key$",
    r"\.p12$",
    r"keychain",
    r"wallet",
    r"password",
    r"secret",
    r"token",
    r"api_key",
]

# Safe home-relative paths — DuckClaw only touches these by default
DEFAULT_ALLOWED_DIRS = [
    "~/Documents",
    "~/Downloads",
    "~/Desktop",
    "~/Projects",
    "~/duckclaw-workspace",
]

MAX_READ_SIZE_BYTES = 1_000_000  # 1 MB max read


class FileManagerSkill(BaseSkill):
    name = "file_manager"
    description = "Read, write, list, and search files in allowed directories."
    version = "1.0.0"
    permissions = [SkillPermission.FILE_READ, SkillPermission.FILE_WRITE, SkillPermission.FILE_LIST]

    allowed_paths: list[str] = DEFAULT_ALLOWED_DIRS

    async def execute(self, action: str, params: dict) -> SkillResult:
        dispatch = {
            "read":       self._read,
            "write":      self._write,
            "list":       self._list,
            "search":     self._search,
            "delete":     self._delete,
            "create_dir": self._create_dir,
        }
        handler = dispatch.get(action, self._read)
        logger.info(f"FileManagerSkill.execute called with action: '{action}' and params: {params}. Handler found: {bool(handler)}")
        if not handler:
            return SkillResult(success=False, error=f"Unknown file action: {action}")
        return await handler(params)

    # ── Security Helpers ───────────────────────────────────────────────────────

    def _validate_path(self, path_str: str) -> Path:
        """
        Validate a path is allowed and not in the blocklist.
        Raises ValueError if the path is not permitted.
        """
        path = Path(os.path.expanduser(path_str)).resolve()

        # Check blocklist (hardcoded, immutable)
        path_lower = str(path).lower()
        for pattern in BLOCKED_PATH_PATTERNS:
            if re.search(pattern, path_lower, re.IGNORECASE):
                raise ValueError(f"Access denied: path matches security blocklist ({pattern})")

        # Check allowlist
        expanded_allowed = [Path(os.path.expanduser(p)).resolve() for p in self.allowed_paths]
        if not any(str(path).startswith(str(allowed)) for allowed in expanded_allowed):
            allowed_str = ", ".join(str(p) for p in expanded_allowed)
            raise ValueError(
                f"Path not in allowed directories.\n"
                f"Allowed: {allowed_str}\n"
                f"Requested: {path}"
            )
        logger.info(f"Validated path: {path} is allowed for file operations.")
        return path

    # ── Actions ────────────────────────────────────────────────────────────────

    async def _read(self, params: dict) -> SkillResult:
        path_str = params.get("path", "")
        try:
            path = self._validate_path(path_str)
        except ValueError as e:
            return SkillResult(success=False, error=str(e))

        approved = await self._check(
            "file_read",
            f"Read file: {path}",
            details={"path": str(path)},
        )
        if not approved:
            logger.warning(f"File read permission denied for path: {path}")
            return SkillResult(success=False, error="File read denied.")

        if not path.exists():
            logger.warning(f"File not found: {path}")
            return SkillResult(success=False, error=f"File not found: {path}")
        if not path.is_file():
            logger.warning(f"Not a file: {path}")
            return SkillResult(success=False, error=f"Not a file: {path}")

        size = path.stat().st_size
        if size > MAX_READ_SIZE_BYTES:
            logger.warning(f"File too large to read: {path} ({size:,} bytes)")
            return SkillResult(success=False, error=f"File too large ({size:,} bytes). Max: {MAX_READ_SIZE_BYTES:,}")

        content = path.read_text(encoding="utf-8", errors="replace")
        logger.info(f"Read file: {path} ({size:,} bytes). Content preview: {content[:200]!r}")
        read_sr = SkillResult(
            success=True,
            data=content,
            action_taken=f"Read {path.name} ({len(content):,} chars)",
        )
        logger.info(f"Read file action returning SkillResult: {read_sr}")
        return read_sr

    async def _write(self, params: dict) -> SkillResult:
        path_str = params.get("path", "")
        content = params.get("content", "")
        try:
            path = self._validate_path(path_str)
        except ValueError as e:
            return SkillResult(success=False, error=str(e))
        logger.info(f"Attempting to write to file: {path} with content length: {len(content):,} chars")
        exists = path.exists()
        approved = await self._check(
            "file_write",
            f"{'Overwrite' if exists else 'Create'} file: {path}",
            details={"path": str(path), "size": f"{len(content):,} chars", "overwrite": exists},
            reversible=False,
            risk_level="medium" if exists else "low",
        )
        logger.info(f"File write permission check for path: {path} returned: {approved}")
        if not approved:
            return SkillResult(success=False, error="File write denied.")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info(f"Wrote to file: {path} ({len(content):,} chars)")
        write_sr = SkillResult(
            success=True,
            data=f"Written {len(content):,} chars to {path}",
            action_taken=f"Wrote {path.name}",
        )
        logger.info(f"Write file action returning SkillResult: {write_sr}")
        return write_sr

    async def _list(self, params: dict) -> SkillResult:
        logger.info(f"FileManagerSkill._list called with params: {params}")
        path_str = params.get("path", "~")
        try:
            path = self._validate_path(path_str)
        except ValueError as e:
            return SkillResult(success=False, error=str(e))
        logger.info(f"Listing directory: {path}")
        await self._check("file_read", f"List directory: {path}", details={"path": str(path)})

        if not path.exists():
            return SkillResult(success=False, error=f"Directory not found: {path}")
        if not path.is_dir():
            return SkillResult(success=False, error=f"Not a directory: {path}")
        logger.info(f"Directory exists and is valid: {path}. Listing contents.")
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        lines = []
        for entry in entries[:200]:  # Cap at 200 entries
            icon = "📄" if entry.is_file() else "📁"
            size = f" ({entry.stat().st_size:,}b)" if entry.is_file() else ""
            lines.append(f"{icon} {entry.name}{size}")
        logger.info(f"Listed directory: {path}. Total entries: {len(entries)}. Returning {len(lines)} entries.")
        list_sr = SkillResult(success=True, data="\n".join(lines) or "(empty directory)")
        logger.info(f"List directory action returning SkillResult: {list_sr}")
        return list_sr

    async def _search(self, params: dict) -> SkillResult:
        logger.info(f"FileManagerSkill._search called with params: {params}")
        root_str = params.get("path", "~")
        pattern = params.get("pattern", "")
        content_query = params.get("content", "")

        try:
            root = self._validate_path(root_str)
        except ValueError as e:
            return SkillResult(success=False, error=str(e))
        logger.info(f"Searching files in: {root} with pattern: '{pattern}' and content query: '{content_query}'")
        await self._check("file_read", f"Search files in {root}", details={"pattern": pattern})

        matches = []
        for p in root.rglob(pattern or "*"):
            if len(matches) >= 50:
                break
            if p.is_file():
                if content_query:
                    try:
                        text = p.read_text(errors="ignore")
                        if content_query.lower() in text.lower():
                            matches.append(str(p))
                    except Exception:
                        pass
                else:
                    matches.append(str(p))
        logger.info(f"Search completed in {root}. Found {len(matches)} matches for pattern '{pattern}' with content query '{content_query}'.")
        if not matches:
            return SkillResult(success=True, data="No files found matching the criteria.")

        search_sr = SkillResult(success=True, data="\n".join(matches), action_taken=f"Found {len(matches)} files")
        logger.info(f"Search action returning SkillResult: {search_sr}")
        return search_sr

    async def _delete(self, params: dict) -> SkillResult:
        logger.info(f"FileManagerSkill._delete called with params: {params}")
        path_str = params.get("path", "")
        try:
            path = self._validate_path(path_str)
        except ValueError as e:
            return SkillResult(success=False, error=str(e))

        logger.info(f"Attempting to delete file: {path}")
        approved = await self._check(
            "file_delete",
            f"Delete file: {path}",
            details={"path": str(path)},
            reversible=False,
            risk_level="high",
        )
        if not approved:
            logger.warning(f"File delete permission denied for path: {path}")
            return SkillResult(success=False, error="Delete denied.")

        if not path.exists():
            logger.warning(f"File not found for deletion: {path}")
            return SkillResult(success=False, error=f"File not found: {path}")

        path.unlink()
        delete_sr = SkillResult(success=True, data=f"Deleted: {path}", action_taken=f"Deleted {path.name}")
        logger.info(f"Delete action returning SkillResult: {delete_sr}")
        return delete_sr

    async def _create_dir(self, params: dict) -> SkillResult:
        logger.info(f"FileManagerSkill._create_dir called with params: {params}")
        path_str = params.get("path", "")
        try:
            path = self._validate_path(path_str)
        except ValueError as e:
            return SkillResult(success=False, error=str(e))
        logger.info(f"Attempting to create directory: {path}")
        approved = await self._check("file_write", f"Create directory: {path}", details={"path": str(path)})
        if not approved:
            return SkillResult(success=False, error="Directory creation denied.")

        path.mkdir(parents=True, exist_ok=True)
        create_dir_sr = SkillResult(success=True, data=f"Created directory: {path}")
        logger.info(f"Create directory action returning SkillResult: {create_dir_sr}")
        return create_dir_sr
