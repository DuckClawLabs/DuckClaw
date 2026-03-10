# 🦆🦞 DuckClaw — 30-Day MVP Roadmap

### The Secure, Simple, Open-Source Personal AI Assistant
**"Powerful AI — built for you, built with you, built securely."**

> **Solo Developer · 30 Days · Python-First · MIT License**

---

## Vision

Developers want a local-first, always-on AI assistant. But most existing tools are built to be capable first and safe second — with unpredictable autonomy, no audit trail, and a security posture that assumes trust rather than earning it.

**DuckClaw is built differently — security and transparency are first-class, not afterthoughts.**

| The Problem | DuckClaw Solution |
|---|---|
| Broad, uncontrolled permissions | Granular 4-tier permission system |
| Prompt injection vulnerabilities | Isolated context layers |
| Unverified third-party skills | Sandboxed execution + SHA-256 verify |
| Complex setup (Node + build tools) | `pip install duckclaw && duckclaw start` |
| Unpredictable autonomous behavior | Action Preview Mode |
| $30–150/month API costs | Free Gemini fallback, cost tracking |
| No audit trail | Full audit log — every action logged |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   DUCKCLAW CORE                     │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ LiteLLM  │  │ Memory   │  │ Permission       │  │
│  │ Router   │  │ SQLite + │  │ Engine (4-Tier   │  │
│  │ 100+ mdl │  │ ChromaDB │  │ + Audit Log)     │  │
│  └────┬─────┘  └────┬─────┘  └────────┬─────────┘  │
│       │              │                  │             │
│  ┌────┴──────────────┴──────────────────┴─────────┐  │
│  │           Orchestrator (FastAPI)               │  │
│  └──┬──────────┬──────────┬──────────┬────────────┘  │
│     │          │          │          │               │
│  ┌──┴───┐ ┌───┴────┐ ┌───┴───┐ ┌────┴─────────────┐│
│  │Bridg.│ │Skills  │ │ Web   │ │ Screen / Camera  ││
│  │TG/DC │ │Sandbox │ │ Agent │ │ Capture          ││
│  └──────┘ └────────┘ └───────┘ └──────────────────┘│
│                                                     │
│  ┌─────────────────────────────────────────────┐    │
│  │   Dashboard (FastAPI + Jinja2) @ :8741      │    │
│  │   Chat · Memory · Audit · Skills · Settings │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

---

## Sprint Breakdown

### 🔵 Sprint 1 — Foundation & Core Brain (Days 1–7) ✅ IN PROGRESS

**Goal:** A working AI assistant with memory, permissions, and a web dashboard.

| Task | Status | File |
|---|---|---|
| Project scaffold, pyproject.toml, CLI | ✅ Done | `duckclaw/cli.py` |
| LLM Router (LiteLLM + cost tracking) | ✅ Done | `duckclaw/llm/router.py` |
| Memory System (SQLite + ChromaDB) | ✅ Done | `duckclaw/memory/store.py` |
| Permission Engine (4-tier + audit log) | ✅ Done | `duckclaw/permissions/engine.py` |
| Orchestrator (central brain) | ✅ Done | `duckclaw/core/orchestrator.py` |
| Dashboard v1 (FastAPI + Jinja2) | ✅ Done | `duckclaw/dashboard/` |

**Sprint 1 Deliverable:**
- `pip install duckclaw && duckclaw start`
- Chat via terminal or browser at localhost:8741
- Works with Claude (private) or Gemini (free)
- Remembers conversations across restarts
- Every action classified by permission tier
- Full audit log from Day 1

---

### 🟢 Sprint 2 — Messaging, Skills & Vision (Days 8–16)

| Task | Effort |
|---|---|
| Telegram bridge (python-telegram-bot + approval buttons) | 1.5 days |
| Discord bridge (discord.py + button components) | 1 day |
| Sandboxed skill system (subprocess + hash verification) | 2 days |
| Core skills: File Manager, Web Search, Shell Runner, Task Manager, Scheduler | 3 days |
| Screen capture (mss library + ASK-tier approval) | 1 day |
| Action Preview Mode | 1.5 days |

**Sprint 2 Deliverable:**
- Chat via Telegram/Discord from your phone
- "What's on my screen?" with explicit permission approval
- 5 sandboxed built-in skills
- Approval buttons on mobile

---

### 🟡 Sprint 3 — Web Agent, Proactive & Security (Days 17–23)

| Task | Effort |
|---|---|
| Web browsing agent (Playwright — navigate, click, fill, screenshot) | 2.5 days |
| Prompt injection defense (context isolation + output scanning) | 2 days |
| Background scheduler (APScheduler — cron jobs, reminders, briefings) | 1.5 days |
| Camera capture (OpenCV + ASK-tier approval) | 1 day |
| Audit log dashboard (searchable, filters, export) | 1 day |

**Sprint 3 Deliverable:**
- Browse web with approval before form submissions
- Prompt injection defenses on all external data
- Daily morning briefings, reminders, background tasks
- Full searchable audit log in dashboard

---

### 🔴 Sprint 4 — Polish, Docs & Launch (Days 24–30)

| Task | Effort |
|---|---|
| Interactive setup wizard (terminal + web) | 1.5 days |
| Full documentation (README, architecture, security, skills) | 2 days |
| Demo video (install → setup → chat → Telegram → screenshot → audit) | 1 day |
| Test suite (pytest — permissions, sandbox, memory) | 1.5 days |
| PyPI publish + GitHub release | 1 day |

**Sprint 4 Deliverable:**
- Published on PyPI (`pip install duckclaw`)
- GitHub-ready with documentation and demo
- First public release

---

## Feature Matrix

### ✅ Sprint 1 (Done)

| Feature | Typical AI Assistants | DuckClaw | Status |
|---|---|---|---|
| Persistent Memory | Opaque, no user control | SQLite + ChromaDB, user can view/delete | ⬆️ Improved |
| Multi-Model Support | Locked to 1–5 models | 100+ via LiteLLM + cost tracking | ⬆️ Improved |
| Permission Engine | None | 4-tier SAFE/NOTIFY/ASK/BLOCK | 🆕 Exclusive |
| Audit Log | None | Full structured log, searchable, exportable | 🆕 Exclusive |
| Web Dashboard | CLI-only or Electron | Full dashboard @ localhost:8741 | 🆕 Exclusive |
| One-Command Install | Multi-tool setup required | `pip install duckclaw` | 🆕 Exclusive |
| Cost Tracking | None | Per-call tracking + dashboard | 🆕 Exclusive |

### 📱 Sprint 2 (Days 8–16)

| Feature | Typical AI Assistants | DuckClaw | Status |
|---|---|---|---|
| Telegram | Basic integration | Full + approval buttons | ⬆️ Improved |
| Discord | Basic integration | Full + button components | ⬆️ Improved |
| Screen Capture | Auto-approved or missing | `mss` + ASK approval every time | ⬆️ Improved |
| Skill System | Open, unverified marketplace | Sandboxed + SHA-256 + curated | ⬆️ Improved |
| Shell Execution | Broad access, optional policies | Dangerous patterns blocked, safe cmds notify | ⬆️ Improved |
| Action Preview | None | See exactly what happens before execution | 🆕 Exclusive |

### 🌐 Sprint 3 (Days 17–23)

| Feature | Typical AI Assistants | DuckClaw | Status |
|---|---|---|---|
| Browser Automation | Unguarded form submission | Playwright + URL blocklist + form approval | ⬆️ Improved |
| Prompt Injection Defense | Vulnerable | Context isolation + output scanning | 🆕 Exclusive |
| Proactive Tasks | Cron + heartbeat | APScheduler, defaults to NOTIFY tier | ✅ Matched |
| Camera Capture | Auto-approved or missing | OpenCV + ASK approval | ⬆️ Improved |
| Vision (LLM) | Cloud models only | Cloud + local LLaVA option | ⬆️ Improved |

### 📅 Post-MVP (Month 2–3)

| Feature | Priority | Timeline |
|---|---|---|
| WhatsApp (Baileys bridge) | P0 | Week 5–6 |
| Email (IMAP/SMTP) | P1 | Week 6–7 |
| Slack integration | P1 | Week 6 |
| Calendar (Google Cal, CalDAV) | P1 | Week 7–8 |
| Voice mode (Whisper STT + Piper TTS, local) | P2 | Week 9–10 |
| Signal / iMessage bridges | P2 | Week 10–12 |
| Self-improving skills (draft → review flow) | P1 | Week 8 |
| Skill marketplace with code review | P0 | Week 5–7 |
| MCP server support | P2 | Week 8–9 |
| Mobile companion app | P2 | Week 11–12 |

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Language | Python 3.11+ | Solo dev speed, AI ecosystem, no Node complexity |
| API Server | FastAPI | Async, auto-docs, WebSocket |
| LLM | LiteLLM | 100+ models, one interface |
| Database | SQLite | Zero config, single file |
| Vector Memory | ChromaDB | Embedded, no external server |
| Messaging | python-telegram-bot, discord.py | Mature, async |
| Browser | Playwright | Best Python headless browser |
| Screenshots | mss | Cross-platform, zero deps |
| Camera | OpenCV | Industry standard |
| Scheduling | APScheduler | In-process, cron-syntax |
| CLI | Click + Questionary | Beautiful terminal UX |
| Dashboard | FastAPI + Jinja2 | No frontend build step |
| Testing | Pytest | Async support |
| Packaging | PyPI | `pip install` everywhere |

---

## Core Principles

1. **Safe by default** — trustworthy out of the box, not after hours of config
2. **Transparent always** — audit log shows everything the agent did and why
3. **Local first** — your data stays on your machine; cloud is opt-in
4. **Python simple** — one language, one install command, no build tools
5. **Permission, not forgiveness** — ask before acting, not apologize after
6. **Quality over quantity** — 5 secure skills beat 13,700 unvetted ones

---

## GitHub Launch (Day 30)

- **Hacker News:** "Show HN: DuckClaw — personal AI assistant that asks before it acts, pure Python"
- **Reddit:** r/LocalLLaMA, r/selfhosted, r/artificial, r/Python
- **Tagline:** *"Powerful AI — built for you, built with you, built securely."*

> ⭐ Star if you believe AI assistants should ask before they act.
