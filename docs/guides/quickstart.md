# Quick Start

Get DuckClaw running in under 2 minutes.

---

## Requirements

- Python 3.11 or higher
- An API key for Claude (Anthropic) or Gemini (Google — free tier available)

---

## Install

```bash
pip install duckclaw
```

For camera support (optional):
```bash
pip install "duckclaw[camera]"
```

For browser automation (optional — downloads Chromium):
```bash
playwright install chromium
```

---

## First Run

```bash
duckclaw setup
```

The setup wizard walks through three steps:

1. **Choose a model** — Claude (recommended) or Gemini Flash (free)
2. **Enter API key** — Saved to `~/.duckclaw/.env` with `chmod 600`
3. **Set preferences** — Dashboard port, audit log on/off

Config is written to `~/.duckclaw/duckclaw.yaml`.

---

## Start the Dashboard

```bash
duckclaw start
```

Opens the web dashboard at [http://localhost:8741](http://localhost:8741) and launches a browser window automatically.

The dashboard includes:
- **Chat** — Talk to DuckClaw in your browser
- **Memory** — Browse and delete stored facts
- **Audit Log** — See every action DuckClaw has taken
- **Settings** — View current configuration

---

## Terminal Chat

If you prefer the terminal:

```bash
duckclaw chat
```

Type `exit` to quit, `clear` to reset the screen.

---

## Check Status

```bash
duckclaw status
```

Shows the active model, config path, memory database, and dashboard port.

---

## Next Steps

- [Configuration reference](configuration.md) — Tune every setting
- [CLI reference](cli.md) — All commands and flags
- [Permission Engine](../architecture/permission-engine.md) — Understand how DuckClaw decides what to allow
