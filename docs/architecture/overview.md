# System Overview

DuckClaw is a single Python process. One `Orchestrator` instance coordinates all subsystems.

---

## Message Flow

Every user message — from any interface — follows the same path:

```
User message
     │
     ▼
┌─────────────────────────────────────────────┐
│              Orchestrator                    │
│                                             │
│  1. Load context                            │
│     ├─ Session history (SQLite)             │
│     ├─ Relevant memories (ChromaDB)         │
│     └─ Stored facts                         │
│                                             │
│  2. Build safe prompt                       │
│     ├─ Conversational (no tools) OR         │
│     └─ Skills-enabled (with tool grammar)   │
│                                             │
│  3. Call LLM Router                         │
│     ├─ Primary model (Claude)               │
│     └─ Auto-failover (Gemini Flash)         │
│                                             │
│  4. Parse response                          │
│     ├─ Plain text → return to user          │
│     └─ Skill call JSON → dispatch           │
│                                             │
│  5. Skill dispatch                          │
│     ├─ Permission Engine check              │
│     │   ├─ SAFE/NOTIFY → auto              │
│     │   ├─ ASK → wait for user             │
│     │   └─ BLOCK → reject                  │
│     └─ Execute skill                        │
│                                             │
│  6. Second LLM call (with skill result)     │
│                                             │
│  7. Log to memory + audit trail             │
│  8. Extract facts (async, non-blocking)     │
└─────────────────────────────────────────────┘
     │
     ▼
  Response
```

---

## Components

```
duckclaw/
├── core/
│   ├── orchestrator.py     # Central coordinator
│   └── config.py           # Configuration loader
│
├── llm/
│   └── router.py           # LiteLLM wrapper, failover, cost tracking
│
├── memory/
│   ├── store.py            # SQLite + ChromaDB
│   └── extractor.py        # Async fact extraction from conversations
│
├── permissions/
│   └── engine.py           # 4-tier permission gate + audit log
│
├── skills/
│   ├── base.py             # BaseSkill, SkillResult, SkillPermission
│   ├── registry.py         # Skill registration and dispatch
│   ├── web_browser.py      # Playwright browser automation
│   ├── web_search.py       # DuckDuckGo search
│   ├── file_manager.py     # File read/write with path scoping
│   ├── shell_runner.py     # Shell execution with blocklist
│   ├── screen_capture.py   # Screenshot + vision
│   ├── camera.py           # Webcam capture + vision
│   └── scheduler.py        # APScheduler reminders
│
├── bridges/
│   ├── base.py             # BaseBridge interface
│   ├── telegram_bridge.py  # Telegram bot
│   └── discord_bridge.py   # Discord bot
│
├── dashboard/
│   └── app.py              # FastAPI web UI + WebSocket chat
│
├── security/
│   └── context_isolation.py # Prompt injection defense
│
└── cli.py                  # Click CLI entry point
```

---

## Interfaces

DuckClaw can be reached from four interfaces. All share the same `Orchestrator` and `PermissionEngine`:

| Interface | How it connects | Approval delivery |
|-----------|----------------|-------------------|
| Terminal (`duckclaw chat`) | Direct function call | Printed to stdout, `input()` |
| Web Dashboard | HTTP REST + WebSocket | Real-time popup in browser |
| Telegram | Bot polling | Inline keyboard buttons |
| Discord | Bot events | Button components (`ApprovalView`) |

Each interface registers its own `approval_callback` and `notify_callback` with the Permission Engine at connection time.

---

## Dual System Prompts

DuckClaw uses a lightweight classifier to avoid tool-calling overhead on simple questions:

```
User message
     │
     ├─ Contains skill keywords? ("search", "run", "screenshot", ...)
     │       │
     │       ├─ YES → SYSTEM_PROMPT_SKILLS (full JSON skill grammar)
     │       └─ NO  → SYSTEM_PROMPT_CONVERSATIONAL (plain text only)
```

This means typing "hi" or "explain Python generators" never triggers a tool call — the LLM is given a prompt that contains no skill grammar and therefore cannot emit one.

---

## Data Storage

| What | Where | Format |
|------|-------|--------|
| Facts | `~/.duckclaw/duckclaw.db` | SQLite `facts` table |
| Conversation history | `~/.duckclaw/duckclaw.db` | SQLite `conversations` table |
| Semantic vectors | `~/.duckclaw/chroma_db/` | ChromaDB (local, file-backed) |
| Audit log | `~/.duckclaw/duckclaw.db` | SQLite `audit_log` table |
| Config | `~/.duckclaw/duckclaw.yaml` | YAML |
| API keys | `~/.duckclaw/.env` | dotenv (chmod 600) |
