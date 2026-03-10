# Configuration Reference

DuckClaw is configured via `~/.duckclaw/duckclaw.yaml`. A local `duckclaw.yaml` in the working directory overrides it.

API keys are loaded from `~/.duckclaw/.env` (never stored in the YAML).

---

## Full Example

```yaml
llm:
  model: "claude-haiku-4-5-20251001"
  fallback_models:
    - "gemini/gemini-2.0-flash"
  cost_tracking: true
  max_tokens: 4096
  temperature: 0.7

memory:
  db_path: "~/.duckclaw/duckclaw.db"
  chroma_path: "~/.duckclaw/chroma_db"
  max_facts: 10000
  semantic_search_results: 5

permissions:
  default_tier: "ask"
  audit_log: true
  notify_on_safe: false

dashboard:
  host: "127.0.0.1"
  port: 8741
  auto_open_browser: true

security:
  prompt_injection_defense: true
  context_isolation: true
```

---

## `llm` — Language Model

| Key | Default | Description |
|-----|---------|-------------|
| `model` | `claude-haiku-4-5-20251001` | Primary LiteLLM model string |
| `fallback_models` | `["gemini/gemini-2.0-flash"]` | Tried in order when primary fails |
| `cost_tracking` | `true` | Track token usage and USD cost |
| `max_tokens` | `4096` | Max tokens per completion |
| `temperature` | `0.7` | Sampling temperature (0 = deterministic) |

**Supported model strings** (via LiteLLM):
- `claude-sonnet-4-6` — Claude Sonnet (most capable)
- `claude-haiku-4-5-20251001` — Claude Haiku (fast, cheap)
- `gemini/gemini-2.0-flash` — Google Gemini Flash (free tier)
- `openai/gpt-4o` — OpenAI GPT-4o

**API keys** go in `~/.duckclaw/.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
```

---

## `memory` — Persistent Memory

| Key | Default | Description |
|-----|---------|-------------|
| `db_path` | `~/.duckclaw/duckclaw.db` | SQLite database path |
| `chroma_path` | `~/.duckclaw/chroma_db` | ChromaDB vector store path |
| `max_facts` | `10000` | Maximum facts stored |
| `semantic_search_results` | `5` | Results returned per semantic search |

Both paths support `~` expansion.

---

## `permissions` — Permission Engine

| Key | Default | Description |
|-----|---------|-------------|
| `default_tier` | `ask` | Tier for unknown action types |
| `audit_log` | `true` | Log every permission check to SQLite |
| `notify_on_safe` | `false` | Suppress notifications for SAFE-tier actions |

Setting `default_tier: "ask"` is the safest option — any action type not in the built-in rules requires explicit approval.

**Note:** BLOCK-tier actions (credential access, `rm -rf /`, `sudo`, etc.) are hardcoded and cannot be overridden here.

---

## `dashboard` — Web UI

| Key | Default | Description |
|-----|---------|-------------|
| `host` | `127.0.0.1` | Bind address (keep as localhost unless you need LAN access) |
| `port` | `8741` | Dashboard port |
| `auto_open_browser` | `true` | Open browser on `duckclaw start` |

---

## `security` — Defenses

| Key | Default | Description |
|-----|---------|-------------|
| `prompt_injection_defense` | `true` | Wrap external data in isolation markers |
| `context_isolation` | `true` | Label trusted vs untrusted content in prompts |

See [Prompt Injection Defense](../features/09-prompt-injection.md) for details.
