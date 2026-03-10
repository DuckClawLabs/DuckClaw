"""
DuckClaw Configuration System.
Loads from ~/.duckclaw/duckclaw.yaml + environment variables.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import yaml
from dotenv import load_dotenv


CONFIG_PATHS = [
    Path.home() / ".duckclaw" / "duckclaw.yaml",
    Path.cwd() / "duckclaw.yaml",
]

ENV_PATHS = [
    Path.home() / ".duckclaw" / ".env",
    Path.cwd() / ".env",
]


@dataclass
class LLMConfig:
    model: str = "claude-haiku-4-5-20251001"
    fallback_models: list[str] = field(default_factory=lambda: ["gemini/gemini-2.0-flash"])
    cost_tracking: bool = True
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: int = 60


@dataclass
class MemoryConfig:
    db_path: str = "~/.duckclaw/duckclaw.db"
    chroma_path: str = "~/.duckclaw/chroma_db"
    max_facts: int = 10000
    semantic_search_results: int = 5

    @property
    def db_path_expanded(self) -> str:
        return os.path.expanduser(self.db_path)

    @property
    def chroma_path_expanded(self) -> str:
        return os.path.expanduser(self.chroma_path)


@dataclass
class PermissionsConfig:
    default_tier: str = "ask"          # Conservative: ask before acting
    audit_log: bool = True
    notify_on_safe: bool = False        # Don't spam for harmless actions


@dataclass
class DashboardConfig:
    host: str = "127.0.0.1"
    port: int = 8741
    auto_open_browser: bool = True


@dataclass
class SecurityConfig:
    prompt_injection_defense: bool = True
    context_isolation: bool = True


@dataclass
class DuckClawConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    permissions: PermissionsConfig = field(default_factory=PermissionsConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)


def _load_env():
    """Load .env file from known locations."""
    for env_path in ENV_PATHS:
        if env_path.exists():
            load_dotenv(env_path)
            return
    # Also try standard .env in cwd
    load_dotenv()


def _find_config() -> Optional[Path]:
    """Find the first existing config file."""
    for path in CONFIG_PATHS:
        if path.exists():
            return path
    return None


def load_config() -> DuckClawConfig:
    """Load and return DuckClaw configuration."""
    _load_env()

    config_path = _find_config()
    if config_path is None:
        # Return defaults if no config found
        return DuckClawConfig()

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    config = DuckClawConfig()

    # LLM config
    if llm_raw := raw.get("llm"):
        config.llm = LLMConfig(
            model=llm_raw.get("model", config.llm.model),
            fallback_models=llm_raw.get("fallback_models", config.llm.fallback_models),
            cost_tracking=llm_raw.get("cost_tracking", config.llm.cost_tracking),
            max_tokens=llm_raw.get("max_tokens", config.llm.max_tokens),
            temperature=llm_raw.get("temperature", config.llm.temperature),
            timeout=llm_raw.get("timeout", config.llm.timeout),
        )

    # Memory config
    if mem_raw := raw.get("memory"):
        config.memory = MemoryConfig(
            db_path=mem_raw.get("db_path", config.memory.db_path),
            chroma_path=mem_raw.get("chroma_path", config.memory.chroma_path),
            max_facts=mem_raw.get("max_facts", config.memory.max_facts),
            semantic_search_results=mem_raw.get("semantic_search_results", config.memory.semantic_search_results),
        )

    # Permissions config
    if perm_raw := raw.get("permissions"):
        config.permissions = PermissionsConfig(
            default_tier=perm_raw.get("default_tier", config.permissions.default_tier),
            audit_log=perm_raw.get("audit_log", config.permissions.audit_log),
            notify_on_safe=perm_raw.get("notify_on_safe", config.permissions.notify_on_safe),
        )

    # Dashboard config
    if dash_raw := raw.get("dashboard"):
        config.dashboard = DashboardConfig(
            host=dash_raw.get("host", config.dashboard.host),
            port=dash_raw.get("port", config.dashboard.port),
            auto_open_browser=dash_raw.get("auto_open_browser", config.dashboard.auto_open_browser),
        )

    # Security config
    if sec_raw := raw.get("security"):
        config.security = SecurityConfig(
            prompt_injection_defense=sec_raw.get("prompt_injection_defense", config.security.prompt_injection_defense),
            context_isolation=sec_raw.get("context_isolation", config.security.context_isolation),
        )

    return config
