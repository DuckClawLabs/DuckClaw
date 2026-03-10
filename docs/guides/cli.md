# CLI Reference

DuckClaw is controlled entirely from the command line.

```
duckclaw <command> [options]
```

---

## `duckclaw setup`

Interactive setup wizard. Run this first.

```bash
duckclaw setup
```

Guides through model selection, API key entry, and preferences. Writes:
- `~/.duckclaw/duckclaw.yaml` — configuration
- `~/.duckclaw/.env` — API keys (chmod 600)

---

## `duckclaw start`

Start the web dashboard.

```bash
duckclaw start [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `8741` | Port number |
| `--no-browser` | off | Don't auto-open the browser |
| `--debug` | off | Enable debug logging |

**Example:**
```bash
duckclaw start --port 9000 --no-browser
```

Opens dashboard at `http://localhost:8741`. Press `Ctrl+C` to stop.

---

## `duckclaw chat`

Start an interactive terminal chat session.

```bash
duckclaw chat [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--model TEXT` | Override the configured model for this session |

**In-session commands:**
- `exit` — quit the session
- `clear` — clear the screen and reset the banner

**Example:**
```bash
duckclaw chat --model claude-sonnet-4-6
```

---

## `duckclaw status`

Show the current configuration and runtime status.

```bash
duckclaw status
```

Prints: active model, fallback models, dashboard port, memory database path.

Exits with code `1` if no config is found.

---

## `duckclaw telegram`

Start the Telegram bridge.

```bash
duckclaw telegram --token <BOT_TOKEN> [--allowed-users 123,456]
```

| Option | Env var | Description |
|--------|---------|-------------|
| `--token` | `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `--allowed-users` | — | Comma-separated Telegram user IDs (empty = everyone) |

Get a bot token: message [@BotFather](https://t.me/BotFather) on Telegram and run `/newbot`.

---

## `duckclaw discord`

Start the Discord bridge.

```bash
duckclaw discord --token <BOT_TOKEN> [--guild-ids 123456,789012]
```

| Option | Env var | Description |
|--------|---------|-------------|
| `--token` | `DISCORD_BOT_TOKEN` | Bot token from Discord Developer Portal |
| `--guild-ids` | — | Comma-separated server IDs for slash command registration |

---

## `duckclaw --version`

Print the installed version and exit.

```bash
duckclaw --version
# DuckClaw, version 0.1.0
```

---

## `duckclaw --help`

Print help for any command.

```bash
duckclaw --help
duckclaw start --help
duckclaw chat --help
```
