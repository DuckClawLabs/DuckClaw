# DuckClaw Documentation

> **Powerful AI — built for you, built with you, built securely.**
>
> DuckClaw is a local-first, open-source personal AI assistant. Everything OpenClaw does, minus everything that scares people.

---

## Documentation Index

### Getting Started
- [Quick Start](guides/quickstart.md) — Install and run in 2 minutes
- [Configuration](guides/configuration.md) — `duckclaw.yaml` reference
- [CLI Reference](guides/cli.md) — All commands and flags

### Architecture
- [System Overview](architecture/overview.md) — How everything connects
- [Permission Engine](architecture/permission-engine.md) — The 4-tier safety system
- [LLM Router](architecture/llm-router.md) — Multi-model routing and cost tracking

### Features
| # | Feature | What it does |
|---|---------|-------------|
| 1 | [Screen Capture](features/01-screen-capture.md) | Screenshot + AI vision analysis |
| 2 | [Web Browser](features/02-web-browser.md) | Playwright-based web automation |
| 3 | [Telegram Bridge](features/03-telegram.md) | Chat with DuckClaw from Telegram |
| 4 | [Discord Bridge](features/04-discord.md) | Chat with DuckClaw from Discord |
| 5 | [Persistent Memory](features/05-memory.md) | Facts + conversation history |
| 6 | [Shell Runner](features/06-shell-runner.md) | Safe shell command execution |
| 7 | [File Manager](features/07-file-manager.md) | Scoped file read/write/delete |
| 8 | [Scheduler](features/08-scheduler.md) | Reminders and background tasks |
| 9 | [Prompt Injection Defense](features/09-prompt-injection.md) | Context isolation layer |
| 10 | [Audit Log](features/10-audit-log.md) | Searchable, exportable action history |
| 11 | [Camera](features/11-camera.md) | Webcam capture + vision analysis |
| 12 | [LLM Router](features/12-llm-router.md) | Multi-model, auto-failover, cost tracking |
| 13 | [Web Dashboard](features/13-dashboard.md) | localhost:8741 control panel |
| 14 | [CLI](features/14-cli.md) | One-command install and management |

---

## Design Intent

DuckClaw is built around one idea: **an AI assistant should ask before it acts, not apologize after**.

Every capability in DuckClaw passes through the Permission Engine. There are no silent background actions. No unexpected network calls. No credentials ever touched by the LLM. Every action is logged.

The four principles that guide every decision:

1. **Safe by default** — Conservative out of the box. No configuration required to be safe.
2. **Transparent always** — Every action has a reason, a log entry, and a way to see it.
3. **Local-first** — Your data stays on your machine. Cloud is opt-in, not opt-out.
4. **Permission, not forgiveness** — Ask before acting. Every time.
