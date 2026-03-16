# 🦆🤖 DuckClaw

**Powerful AI — built for you, built with you, built securely in Python**
> *Local-first personal AI assistant with a 4-tier permission engine.*

> *AI assistance you can actually trust — because it works with you, not around you.*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![Status: Alpha](https://img.shields.io/badge/Status-Alpha-orange.svg)]()

---

## The Problem

Local AI assistants are powerful — but most of them are built to be capable first and safe second.

- 🔓 **Broad permissions by default** — agents act before asking
- 🦠 **No skill verification** — third-party extensions run with full process privileges
- 💸 **$30–150/month** in API costs with no controls
- 🧩 **Complex setup** — Node.js, build tools, platform-specific dependencies
- 🕵️ **No audit trail** — you can't see what it did or why
- 💉 **Prompt injection** — web pages and emails can manipulate your assistant

## The Solution

```bash
pip install duckclaw
duckclaw setup   # 2-minute guided wizard
duckclaw start   # opens localhost:8741
```

That's it. No Node.js. No WSL2. No build tools.

---

## What's Different

| Common Problem | DuckClaw Solution |
|---|---|
| Agents act without asking | **4-tier Permission Engine** (SAFE / NOTIFY / ASK / BLOCK) |
| No preview before actions | **Action Preview Mode** — see exactly what happens before it happens |
| No audit trail | **Full audit log** — every action logged, searchable, exportable |
| Unverified third-party skills | **Sandboxed skill execution** + SHA-256 integrity verification |
| Prompt injection vulnerable | **Context isolation** — trusted instructions vs untrusted data |
| Complex multi-tool setup | **Pure Python** — `pip install` and done |
| No cost controls | **Cost tracking** per conversation, budget alerts |

---

## Quick Start

```bash
# Create Virtual Environment
python3 -m venv <virtual-environment-name>

# Activate Environment
# ubuntu and macOD
source <virtual-environment-name>/bin/activate
# or
# Windows
sh ./<virtual-environment-name>/bin/Activate.sh 

# Install
pip install duckclaw

# Configure (guided wizard)
duckclaw setup

# Start
duckclaw start

# Or just chat in terminal
duckclaw chat
```

## **Requirements:** 
Python 3.11+. That's it.
> create virtual environment for better keeping all python module in one environment that will not effect other packages

---

## Permission System

Every action DuckClaw takes is classified into one of four tiers:

| Tier | Color | Examples | Behavior |
|---|---|---|---|
| **SAFE** | 🟢 | Answer questions, read memory | Auto-approved, silent |
| **NOTIFY** | 🔵 | Browse web, read files | Auto-approved, user informed |
| **ASK** | 🟡 | Screenshots, send messages, run commands | Requires explicit approval |
| **BLOCK** | 🔴 | Delete system files, access credentials | Never allowed |

```
You: "Take a screenshot and analyze it"

DuckClaw: ⚠️ Permission Required
  Action: Take a screenshot of your screen
  Risk: 🟢 Low  |  ✓ Reversible
  [✗ Deny]  [✓ Approve]
```

---

## Architecture

### Core

```
┌─────────────────────────────────────────────────────────────────┐
│                         DUCKCLAW CORE                           │
│                                                                 │
│   ┌─────────────┐   ┌──────────────────┐   ┌─────────────────┐  │
│   │  llm/       │   │  memory/         │   │  permissions/   │  │
│   │  LiteLLM    │   │  SQLite (facts)  │   │  Engine 4-Tier  │  │
│   │  Router     │   │  ChromaDB        │   │  + Audit Log    │  │
│   │  100+ mdls  │   │  (vectors)       │   │  + Action       │  │
│   │  cost track │   │  Extractor       │   │  Preview        │  │
│   └──────┬──────┘   └────────┬─────────┘   └────────┬────────┘  │
│          │                   │                      │           │
│   ┌──────┴───────────────────┴──────────────────────┴───────┐   │
│   │                  core/Orchestrator (FastAPI)            │   │
│   └───┬──────────┬──────────────┬────────────┬──────────────┘   │
│       │          │              │            │                  │
│  ┌────┴───┐ ┌────┴────┐  ┌──────┴──────┐ ┌───┴────────────┐     │
│  │bridges/│ │skills/  │  │  agent/     │ │ security/      │     │
│  │Telegram│ │File Mgr │  │  Web Agent  │ │ Context        │     │
│  │Discord │ │Web Srch │  │  (Playwright│ │ Isolation      │     │  
│  │        │ │Shell Run│  │  + Screen / │ │ Prompt         │     │
│  │        │ │Scheduler│  │    Camera)  │ │ Injection Def. │     │
│  └────────┘ └─────────┘  └─────────────┘ └────────────────┘     │
│                                                                 │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │          dashboard/ (FastAPI + Jinja2) @ :8741           │  │
│   │       Chat · Memory · Logs · Database · Settings         │  │
│   └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Dashboard** at `localhost:8741` — Chat, Memory, Audit Log, Settings.

### DuckClaw Labs Ecosystem

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            DuckClawLabs                                 │
│                                                                         │
│  ┌───────────────────────────┐       ┌──────────────────────────────┐   │
│  │   Outside Skills          │       │   DuckClawSkills             │   │
│  │   (from GitHub)           │       │   Built by DuckClaw Team     │   │
│  │                           │       │                              │   │
│  │  Any developer builds a   │       │  Official, verified skills   │   │
│  │  skill in their own repo  │       │  maintained by DuckClaw Labs │   │
│  └────────────┬──────────────┘       └──────────────┬───────────────┘   │
│               │                                     │                   │
│               └──────────────────┬──────────────────┘                   │
│                                  ▼                                      │
│              ┌───────────────────────────────────────┐                  │
│              │             DuckClawHub               │                  │
│              │  Central registry — manifests only    │                  │
│              │  Browse / search / install skills     │                  │
│              │  SHA-256 verification on publish      │                  │
│              └───────────────────┬───────────────────┘                  │
│                                  │                                      │
│                   duckclaw skill install <name>                         │
│                                  ▼                                      │
│              ┌───────────────────────────────────────┐                  │
│              │              DuckClaw(Core)           │                  │
│              │  Core agent — installs skill,         │                  │
│              │  registers actions into ChromaDB,     │                  │
│              │  permission engine gates execution    │                  │
│              └───────────────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────────────────┘
```
## STATUS 
```
DuckClawLabs
  Outside Skills (From Github) - TODO
  DuckClawSkills               - InProgress 
  DuckClawHub                  - TODO
  DuckClaw (Core)              - In Progress
```
### Vision
![DuckClawLabsVision](DuckClawLabsVision.png)

#### Per-Action Knowledge Base

Skills register **one ChromaDB row per action** (not per skill). This gives precise semantic retrieval:

```
User: "copy report.pdf to /backup/"
  → ChromaDB returns: file_manager.copy   ← direct hit
  → Permission engine: ASK tier → user approves
  → Action executes + audit log entry written
```

Install official or community skills:

```bash
duckclaw skill install file_manager          # official
duckclaw skill install github:user/my-skill  # community
```

### DuckClawHub — Not just another skill registry

> ClawHub (OpenClaw) already exists. DuckClawHub is built for a different user.

**ClawHub** = npm for agent tools. Developers sharing dev tools. No permission model. No audit. Requires Node.js.

**DuckClawHub** = App Store for trusted AI actions. You see exactly what a skill can do before it does anything.

#### Trust Score per skill
```
file_manager v1.2  ★ Trust: 94/100
  ✅ file_manager.read    → SAFE    (auto-allowed)
  ⚠️  file_manager.write  → NOTIFY  (you'll be told)
  🔐 shell_runner.run    → ASK     (always asks first)
```

#### Permission Preview before install
```bash
duckclaw skill preview file_manager

  Before installing, this skill will need:
  → Read files from your disk      [SAFE   — auto allowed]
  → Write files to your disk       [NOTIFY — you'll be told]
  → Run shell commands             [ASK    — always asks first]

  Install anyway? (y/n)
```

#### Skill Recipes — outcomes, not just tools
```bash
duckclaw recipe install research-and-save
# Uses: web_search.search → file_manager.write
# Trust: 87/100  |  Permissions: SAFE + NOTIFY
```

---

## Config

DuckClaw uses `~/.duckclaw/duckclaw.yaml`. See [duckclaw.yaml.example](duckclaw.yaml.example) for all options.

---

## Core Principles

1. **Safe by default** — trustworthy out of the box, not after hours of config
2. **Transparent always** — audit log shows everything the agent did and why
3. **Local first** — your data stays on your machine; cloud is opt-in
4. **Python simple** — one language, one install command, no build tools
5. **Permission, not forgiveness** — ask before acting, not apologize after
6. **Quality over quantity** — 5 secure skills beat 13,700 unvetted ones

---

## Feature Coverage

**14 fully implemented · 6 partial · 6 post-MVP**

### 👁️ Vision & Screen

| Feature | Status | Notes | File |
|---|---|---|---|
| Screenshot Capture | ✅ | ASK-tier approval + LLM vision analysis | `skills/screen_capture.py` |
| Camera Capture | ⚠️ | Photo only — video capture not yet supported | `skills/camera.py` |
| Media Understanding (Vision) | ⚠️ | Images sent to cloud LLM — no local PII scan or LLaVA yet | `skills/screen_capture.py` |

### 🌐 Browser & Web

| Feature | Status | Notes | File |
|---|---|---|---|
| Browser Automation | ✅ | Playwright: navigate, click, fill forms, extract text, screenshot | `skills/web_browser.py` |
| Web Search | ⚠️ | DuckDuckGo (free) — Brave Search / SearXNG not yet added | `skills/web_search.py` |

### 💬 Messaging

| Feature | Status | Notes | File |
|---|---|---|---|
| Telegram | ✅ | Full + inline approve/deny buttons | `bridges/telegram_bridge.py` |
| Discord | ✅ | Slash commands + button components for approvals | `bridges/discord_bridge.py` |
| WhatsApp | ❌ | Post-MVP (Month 2) | — |
| Slack / Signal / iMessage / Teams | ❌ | Post-MVP | — |

### 🧠 Intelligence & Memory

| Feature | Status | Notes | File |
|---|---|---|---|
| Persistent Memory | ✅ | SQLite facts + ChromaDB semantic search, viewable/deletable in dashboard | `memory/store.py` |
| Multi-Model Support | ⚠️ | 100+ models via LiteLLM, cost tracking — smart routing by task complexity not yet added | `llm/router.py` |
| Context Engine (Plugin Interface) | ❌ | Lifecycle hooks (bootstrap, ingest, compact) — Post-MVP (Month 2) | — |

### ⚙️ Automation & Skills

| Feature | Status | Notes | File |
|---|---|---|---|
| Shell Execution | ✅ | Blocklist for dangerous commands + NOTIFY/ASK tiers | `skills/shell_runner.py` |
| File System Access | ✅ | Scoped allowlist + hardcoded credential blocklist | `skills/file_manager.py` |
| Proactive Background Tasks | ✅ | APScheduler: cron, reminders, morning briefs — defaults to NOTIFY | `skills/scheduler.py` |
| Skill & Plugin System | ⚠️ | SHA-256 verify + permission declarations — no external marketplace yet | `skills/registry.py` |
| Code Sandbox (Python/JS exec) | ❌ | Sprint 4 candidate | — |
| Self-Improving / Skill Creation | ❌ | Post-MVP (Month 2) — draft-state review flow planned | — |

### 🎙️ Voice

| Feature | Status | Notes | File |
|---|---|---|---|
| Voice Mode | ❌ | Post-MVP (Month 3) — Whisper STT + Piper TTS planned | — |

### 🛡️ Security & Trust

| Feature | Status | Notes | File |
|---|---|---|---|
| Permission Engine (4-tier) | ✅ | SAFE/NOTIFY/ASK/BLOCK — per-skill, configurable, conservative defaults | `permissions/engine.py` |
| Audit Preview Mode | ✅ | ActionPreview before every ASK action — approve/deny on all platforms | `permissions/engine.py` |
| Full Audit Log | ✅ | Every action logged, searchable, filterable, exportable JSON/CSV | `permissions/engine.py` |
| Prompt Injection Defense | ✅ | Context isolation + dual-pass output scanning + audit logging of signals | `security/context_isolation.py` |
| Sandboxed Skill Execution | ⚠️ | SHA-256 + permissions declared — OS-level subprocess isolation not yet enforced | `skills/base.py` |
| Web Dashboard | ✅ | Chat, memory, audit log, settings @ localhost:8741 | `dashboard/` |
| One Command Install | ✅ | `pip install duckclaw && duckclaw start` — pure Python, no Node.js | `pyproject.toml` |

---

## Contributing

DuckClaw is Apache licensed and built in public.
Issues, PRs, and ideas welcome.

---

**⭐ Star this repo if you believe AI assistants should work as per user permissions**
