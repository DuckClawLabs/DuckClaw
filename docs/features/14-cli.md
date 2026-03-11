# Feature 14 — CLI (One-Command Install)

DuckClaw ships as a standard Python package. One install, one command to start.

---

## Intent

The biggest friction in self-hosted AI tools is setup complexity. DuckClaw is a plain Python package with no Node.js, no WSL2, no Docker required. `pip install duckclaw && duckclaw start` is the entire onboarding path.

---

## Install

```bash
pip install duckclaw
```

Optional extras:
```bash
pip install "duckclaw[camera]"    # adds OpenCV for webcam support
```

Browser automation (downloads Chromium — run once):
```bash
playwright install chromium
```

---

## Commands

| Command | Description |
|---------|-------------|
| `duckclaw setup` | Interactive wizard — configure model, API key, preferences |
| `duckclaw start` | Launch web dashboard at localhost:8741 |
| `duckclaw chat` | Terminal chat session |
| `duckclaw status` | Show config and runtime status |
| `duckclaw telegram` | Start Telegram bridge |
| `duckclaw discord` | Start Discord bridge |
| `duckclaw --version` | Print version |
| `duckclaw --help` | Help for any command |

---

## Entry Point

The `duckclaw` command is registered as a Python entry point in `pyproject.toml`:

```toml
[project.scripts]
duckclaw = "duckclaw.cli:main"
```

It can also be run as a module:

```bash
python -m duckclaw.cli --help
```

---

## First Run Experience

```bash
$ duckclaw start

██████╗ ██╗   ██╗ ██████╗██╗  ██╗ ██████╗██╗      █████╗ ██╗    ██╗
██╔══██╗██║   ██║██╔════╝██║ ██╔╝██╔════╝██║     ██╔══██╗██║    ██║
██║  ██║██║   ██║██║     █████╔╝ ██║     ██║     ███████║██║ █╗ ██║
██║  ██║██║   ██║██║     ██╔═██╗ ██║     ██║     ██╔══██║██║███╗██║
██████╔╝╚██████╔╝╚██████╗██║  ██╗╚██████╗███████╗██║  ██║╚███╔███╔╝
╚═════╝  ╚═════╝  ╚═════╝╚═╝  ╚═╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝
🦆🤖  Powerful AI — built for you, built with you, built securely.[/dim]

⚠️  First Run
No config found. Run duckclaw setup first to get started!

Run setup wizard now? [Y/n]:
```

If no config exists, `duckclaw start` offers to run setup automatically rather than failing with a cryptic error.

---

## Config and Data Locations

| What | Where |
|------|-------|
| Config | `~/.duckclaw/duckclaw.yaml` |
| API keys | `~/.duckclaw/.env` (chmod 600) |
| Database | `~/.duckclaw/duckclaw.db` |
| Vector store | `~/.duckclaw/chroma_db/` |

A local `duckclaw.yaml` in the working directory overrides the home config.

---

## PyPI

```
pip install duckclaw
```

Package homepage: [pypi.org/project/duckclaw](https://pypi.org/project/duckclaw)
