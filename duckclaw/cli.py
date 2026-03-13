"""
DuckClaw CLI — Entry point for all commands.
Usage: duckclaw start | chat | setup | status
"""

import sys
import os
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import click
import questionary
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich import print as rprint

console = Console()

DUCK_BANNER = """
[bold yellow]
    ██████╗ ██╗   ██╗ ██████╗██╗  ██╗ ██████╗██╗      █████╗ ██╗    ██╗
    ██╔══██╗██║   ██║██╔════╝██║ ██╔╝██╔════╝██║     ██╔══██╗██║    ██║
    ██║  ██║██║   ██║██║     █████╔╝ ██║     ██║     ███████║██║ █╗ ██║
    ██║  ██║██║   ██║██║     ██╔═██╗ ██║     ██║     ██╔══██║██║███╗██║
    ██████╔╝╚██████╔╝╚██████╗██║  ██╗╚██████╗███████╗██║  ██║╚███╔███╔╝
    ╚═════╝  ╚═════╝  ╚═════╝╚═╝  ╚═╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝
[/bold yellow]
[dim]    🦆🤖  Powerful AI — built for you, built with you, built securely.[/dim]
"""


def print_banner():
    console.print(DUCK_BANNER)


def check_config_exists() -> bool:
    """Check if duckclaw.yaml exists in current or home directory."""
    home_config = os.path.expanduser("~/.duckclaw/duckclaw.yaml")
    local_config = os.path.join(os.getcwd(), "duckclaw.yaml")
    return os.path.exists(home_config) or os.path.exists(local_config)


@click.group()
@click.version_option(version="0.1.1", prog_name="DuckClaw")
@click.option("--verbose", "-v", is_flag=True, help="Show real-time logs (all modules)")
def main(verbose):
    """🦆🤖 DuckClaw — Secure personal AI assistant."""
    log_dir = os.path.expanduser("~/.duckclaw")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "duckclaw.log")

    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Always write DEBUG+ to file (rotating, max 5 MB × 3 backups)
    fh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console: DEBUG if -v, else WARNING
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.WARNING)
    ch.setFormatter(fmt)
    root.addHandler(ch)


@main.command()
@click.option("--host", default="127.0.0.1", help="Dashboard host (default: 127.0.0.1)")
@click.option("--port", default=8741, help="Dashboard port (default: 8741)")
@click.option("--no-browser", is_flag=True, help="Don't auto-open browser")
@click.option("--debug", is_flag=True, help="Enable debug mode")
def start(host, port, no_browser, debug):
    """Start DuckClaw — launches dashboard at localhost:8741."""
    print_banner()

    if not check_config_exists():
        console.print(
            Panel(
                "[yellow]No config found. Run [bold]duckclaw setup[/bold] first to get started![/yellow]",
                title="⚠️  First Run",
                border_style="yellow",
            )
        )
        if questionary.confirm("Run setup wizard now?", default=True).ask():
            from duckclaw.cli import _run_setup
            _run_setup()
        else:
            console.print("[dim]Exiting. Run [bold]duckclaw setup[/bold] when ready.[/dim]")
            sys.exit(0)

    console.print(f"\n[bold green]🚀 Starting DuckClaw...[/bold green]")
    console.print(f"[dim]Dashboard → [link=http://{host}:{port}]http://{host}:{port}[/link][/dim]")
    console.print(f"[dim]Press Ctrl+C to stop[/dim]\n")

    if not no_browser:
        import threading
        import webbrowser
        def open_browser():
            import time
            time.sleep(1.5)
            webbrowser.open(f"http://{host}:{port}")
        threading.Thread(target=open_browser, daemon=True).start()

    import uvicorn
    from duckclaw.dashboard.app import create_app
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="debug" if debug else "warning")


@main.command()
@click.option("--model", default=None, help="Override model for this session")
def chat(model):
    """Start a terminal chat session with DuckClaw."""
    # Silence all console output during interactive chat — logs go to file only.
    # Third-party libs (litellm, httpx, chromadb) add their own stream handlers;
    # suppress them so they don't bleed into the chat UI.
    _root = logging.getLogger()
    for _h in list(_root.handlers):
        if isinstance(_h, logging.StreamHandler) and not isinstance(_h, RotatingFileHandler):
            _root.removeHandler(_h)
    for _noisy in ("httpx", "httpcore", "litellm", "LiteLLM", "chromadb", "urllib3", "asyncio"):
        logging.getLogger(_noisy).setLevel(logging.CRITICAL)

    print_banner()

    if not check_config_exists():
        console.print("[red]No config found. Run [bold]duckclaw setup[/bold] first.[/red]")
        sys.exit(1)

    # Install log buffer BEFORE the chat loop starts so no early messages are missed.
    # lifespan() also calls this but runs asynchronously after uvicorn starts — too late.
    from duckclaw.dashboard.app import install_log_buffer
    install_log_buffer()

    # Start dashboard server in background so the web UI is available while chatting
    import threading
    def _start_dashboard():
        import uvicorn
        from duckclaw.dashboard.app import create_app
        uvicorn.run(create_app(), host="127.0.0.1", port=8741, log_level="warning")

    _dash_thread = threading.Thread(target=_start_dashboard, daemon=True, name="duckclaw-dashboard")
    _dash_thread.start()
    console.print("[dim]Dashboard → http://127.0.0.1:8741[/dim]\n")

    console.print("[bold green]💬 DuckClaw Chat[/bold green] [dim](type '/exit' to quit · '/new' for new conversation · '/clear' to reset screen)[/dim]\n")

    async def _chat_loop():
        from duckclaw.core.config import load_config
        from duckclaw.core.orchestrator import Orchestrator

        config = load_config()
        if model:
            config.llm.model = model

        orchestrator = Orchestrator(config)
        await orchestrator.initialize()

        def _new_session_id():
            import uuid
            return f"terminal-{uuid.uuid4().hex[:8]}"

        session_id = _new_session_id()

        while True:
            try:
                user_input = console.input("[bold cyan]You:[/bold cyan] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye! 👋[/dim]")
                break

            if not user_input:
                continue
            if user_input.lower() == "/exit":
                console.print("[dim]Goodbye! 👋[/dim]")
                break
            if user_input.lower() == "/clear":
                console.clear()
                print_banner()
                continue
            if user_input.lower() == "/new":
                session_id = _new_session_id()
                print_banner()
                console.print(f"\n[bold green]✦ New conversation started[/bold green] [dim](session {session_id})[/dim]\n")
                continue

            with console.status("[dim]Thinking...[/dim]"):
                response = await orchestrator.chat(
                    message=user_input,
                    session_id=session_id,
                    source="terminal",
                )

            console.print(f"[bold yellow]DuckClaw:[/bold yellow] {response['reply']}\n")
            if response.get("image_path"):
                console.print(f"[dim]  📸 Screenshot saved: {response['image_path']}[/dim]\n")

            # Show permission notifications if any
            for note in response.get("notifications", []):
                console.print(f"[dim]  ℹ️  {note}[/dim]")

    asyncio.run(_chat_loop())


@main.command()
def setup():
    """Interactive setup wizard — configure DuckClaw in minutes."""
    print_banner()
    _run_setup()


@main.command()
def status():
    """Show DuckClaw status — config, models, memory stats."""
    print_banner()

    if not check_config_exists():
        console.print("[red]No config found. Run [bold]duckclaw setup[/bold] first.[/red]")
        sys.exit(1)

    async def _show_status():
        from duckclaw.core.config import load_config
        config = load_config()

        console.print(Panel(
            f"[bold cyan]LLM[/bold cyan]\n"
            f"  Model:               [bold]{config.llm.model}[/bold]\n"
            f"  Max tokens:          {config.llm.max_tokens}\n"
            f"  Temperature:         {config.llm.temperature}\n"
            f"  Cost tracking:       {'on' if config.llm.cost_tracking else 'off'}\n"
            f"\n[bold cyan]Permissions[/bold cyan]\n"
            f"  Default tier:        {config.permissions.default_tier}\n"
            f"  Audit log:           {'on' if config.permissions.audit_log else 'off'}\n"
            f"  Notify on safe:      {'on' if config.permissions.notify_on_safe else 'off'}\n"
            f"\n[bold cyan]Security[/bold cyan]\n"
            f"  Injection defense:   {'on' if config.security.prompt_injection_defense else 'off'}\n"
            f"  Context isolation:   {'on' if config.security.context_isolation else 'off'}\n"
            f"\n[bold cyan]Dashboard[/bold cyan]\n"
            f"  URL:                 http://{config.dashboard.host}:{config.dashboard.port}\n"
            f"\n[bold cyan]Memory[/bold cyan]\n"
            f"  Database:            {config.memory.db_path}\n"
            f"  Vector index:        {config.memory.chroma_path}\n"
            f"  Max facts:           {config.memory.max_facts}",
            title="🦆🤖 DuckClaw Status",
            border_style="green",
        ))

    asyncio.run(_show_status())


def _validate_config(path: str) -> tuple[bool, str]:
    """Validate a user-provided config file. Returns (is_valid, error_message)."""
    import yaml
    import re

    if not os.path.exists(path):
        return False, f"File not found: {path}"
    if not path.lower().endswith((".yaml", ".yml")):
        return False, "File must have a .yaml or .yml extension"
    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
    except Exception as e:
        return False, f"Invalid YAML: {e}"
    if not isinstance(raw, dict):
        return False, "Config must be a YAML mapping"
    known_keys = {"llm", "memory", "permissions", "dashboard", "security"}
    unknown = set(raw.keys()) - known_keys
    if unknown:
        return False, f"Unknown top-level keys: {', '.join(sorted(unknown))}"
    if "llm" not in raw or not isinstance(raw.get("llm"), dict) or "model" not in raw["llm"]:
        return False, "Missing required field: llm.model"

    def _scan(val, keypath):
        if isinstance(val, str) and re.search(r'[;&|`]|\$\(', val):
            return f"Suspicious characters in '{keypath}'"
        if isinstance(val, dict):
            for k, v in val.items():
                err = _scan(v, f"{keypath}.{k}")
                if err:
                    return err
        return None

    for k, v in raw.items():
        err = _scan(v, k)
        if err:
            return False, err
    return True, ""


def _write_config(config_dir: str, model_name: str, dashboard_port: str, enable_audit: bool) -> str:
    """Write duckclaw.yaml to config_dir. Returns the config file path."""
    config_content = f"""# DuckClaw Configuration
# Generated by setup wizard

llm:
  model: "{model_name}"
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
  audit_log: {"true" if enable_audit else "false"}
  notify_on_safe: false

dashboard:
  host: "127.0.0.1"
  port: {dashboard_port}
  auto_open_browser: true

security:
  prompt_injection_defense: true
  context_isolation: true
"""
    config_path = os.path.join(config_dir, "duckclaw.yaml")
    with open(config_path, "w") as f:
        f.write(config_content)
    return config_path


def _setup_import():
    """Import and validate an existing config file."""
    console.print("\n[bold cyan]Import Config File[/bold cyan]")

    config_path = questionary.text("Path to your config file:").ask()
    if not config_path:
        console.print("[red]Cancelled.[/red]")
        return

    config_path = os.path.expanduser(config_path.strip())
    valid, error = _validate_config(config_path)

    if not valid:
        console.print(f"\n[red]✗ Config rejected:[/red] {error}")
        console.print("[dim]Fix the file and run [bold]duckclaw setup[/bold] again.[/dim]")
        return

    default_dest = os.path.expanduser("~/.duckclaw/duckclaw.yaml")
    save_to = questionary.text("Save to:", default=default_dest).ask() or default_dest
    save_to = os.path.expanduser(save_to)

    if os.path.abspath(config_path) == os.path.abspath(save_to):
        console.print("[red]✗ Source and destination are the same file. Choose a different path.[/red]")
        return

    os.makedirs(os.path.dirname(save_to), exist_ok=True)
    import shutil
    shutil.copy2(config_path, save_to)

    console.print(Panel(
        f"[green]✓[/green] Config imported to [bold]{save_to}[/bold]\n\n"
        f"[bold]Run [cyan]duckclaw start[/cyan] to launch![/bold]",
        title="✅ Import Complete!",
        border_style="green",
    ))


def _setup_browser():
    """Minimal setup, then launch dashboard and open browser settings."""
    console.print("\n[bold cyan]Browser Setup[/bold cyan]")
    console.print("[dim]Answer two quick questions, then we'll open the settings page in your browser.[/dim]\n")

    model_choice = questionary.select(
        "Choose your AI model:",
        choices=[
            questionary.Choice("Claude (Anthropic) — Recommended", value="claude"),
            questionary.Choice("Groq — Ultra-fast inference, free tier", value="groq"),
            questionary.Choice("Gemini Flash (Google) — Free", value="gemini"),
            questionary.Choice("Ollama — Local inference, no API key", value="ollama")        ]
    ).ask()

    if model_choice is None:
        console.print("[red]Cancelled.[/red]")
        return

    env_entries: dict = {}

    if model_choice == "ollama":
        model_name = questionary.text(
            "Ollama model string:", default="ollama/gemma3:1b"
        ).ask() or "ollama/gemma3:1b"
        console.print("[dim]Make sure Ollama is running: ollama serve[/dim]")
    elif model_choice == "claude":
        model_name = questionary.text(
            "Claude model string:", default="claude-haiku-4-5-20251001"
        ).ask() or "claude-haiku-4-5-20251001"
        api_key = questionary.password("Anthropic API key:").ask() or ""
        if api_key:
            env_entries["ANTHROPIC_API_KEY"] = api_key
    elif model_choice == "groq":
        model_name = questionary.text(
            "Groq model string:", default="groq/llama-3.3-70b-versatile"
        ).ask() or "groq/llama-3.3-70b-versatile"
        console.print("[dim]Get a free key at: https://console.groq.com/keys[/dim]")
        api_key = questionary.password("Groq API key:").ask() or ""
        if api_key:
            env_entries["GROQ_API_KEY"] = api_key
    elif model_choice == "gemini":
        model_name = questionary.text(
            "Gemini model string:", default="gemini/gemini-2.0-flash"
        ).ask() or "gemini/gemini-2.0-flash"
        api_key = questionary.password("Google AI Studio API key:").ask() or ""
        if api_key:
            env_entries["GEMINI_API_KEY"] = api_key

    config_dir = os.path.expanduser("~/.duckclaw")
    os.makedirs(config_dir, exist_ok=True)
    config_path = _write_config(config_dir, model_name, "8741", True)

    if env_entries:
        env_path = os.path.join(config_dir, ".env")
        with open(env_path, "w") as f:
            for k, v in env_entries.items():
                f.write(f"{k}={v}\n")
        os.chmod(env_path, 0o600)

    console.print(f"\n[green]✓[/green] Config saved to [bold]{config_path}[/bold]")
    console.print("[dim]Opening browser settings... Press Ctrl+C to stop when done.[/dim]\n")

    import threading
    import webbrowser
    def _open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open("http://127.0.0.1:8741/settings")
    threading.Thread(target=_open_browser, daemon=True).start()

    import uvicorn
    from duckclaw.dashboard.app import create_app
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=8741, log_level="warning")


def _setup_cli_wizard():
    """Step-by-step CLI configuration wizard."""
    # Step 1: Choose primary LLM
    console.print("\n[bold cyan]Step 1/3 — Choose your AI model[/bold cyan]")
    model_choice = questionary.select(
        "Which AI model do you want to use?",
        choices=[
            questionary.Choice("Claude (Anthropic) — Recommended, powerful", value="claude"),
            questionary.Choice("Groq — Ultra-fast inference, free tier", value="groq"),
            questionary.Choice("Gemini Flash (Google) — Free tier, no cost", value="gemini"),
            questionary.Choice("Ollama — Local inference, no API key", value="ollama"),
        ]
    ).ask()

    if model_choice is None:
        console.print("[red]Setup cancelled.[/red]")
        return

    # Step 2: Credentials
    console.print("\n[bold cyan]Step 2/3 — Credentials[/bold cyan]")
    env_entries: dict = {}

    if model_choice == "ollama":
        model_name = questionary.text(
            "Ollama model string:", default="ollama/gemma3:1b"
        ).ask() or "ollama/gemma3:1b"
        console.print("[dim]Make sure Ollama is running: ollama serve[/dim]")
    elif model_choice == "claude":
        model_name = questionary.text(
            "Claude model string:", default="claude-haiku-4-5-20251001"
        ).ask() or "claude-haiku-4-5-20251001"
        api_key = questionary.password("Enter your Anthropic API key:").ask() or ""
        if api_key:
            env_entries["ANTHROPIC_API_KEY"] = api_key
    elif model_choice == "groq":
        model_name = questionary.text(
            "Groq model string:", default="groq/llama-3.3-70b-versatile"
        ).ask() or "groq/llama-3.3-70b-versatile"
        console.print("[dim]Get a free key at: https://console.groq.com/keys[/dim]")
        api_key = questionary.password("Enter your Groq API key:").ask() or ""
        if api_key:
            env_entries["GROQ_API_KEY"] = api_key
    elif model_choice == "gemini":
        model_name = questionary.text(
            "Gemini model string:", default="gemini/gemini-2.0-flash"
        ).ask() or "gemini/gemini-2.0-flash"
        console.print("[dim]Get a free key at: https://aistudio.google.com/app/apikey[/dim]")
        api_key = questionary.password("Enter your Google AI Studio API key:").ask() or ""
        if api_key:
            env_entries["GEMINI_API_KEY"] = api_key

    # Step 3: Preferences
    console.print("\n[bold cyan]Step 3/3 — Preferences[/bold cyan]")
    dashboard_port = questionary.text("Dashboard port:", default="8741").ask() or "8741"
    enable_audit = questionary.confirm(
        "Enable full audit log? (Recommended — logs every action)", default=True
    ).ask()

    config_dir = os.path.expanduser("~/.duckclaw")
    os.makedirs(config_dir, exist_ok=True)
    config_path = _write_config(config_dir, model_name, dashboard_port, enable_audit)

    completion_lines = f"[green]✓[/green] Config saved to [bold]{config_path}[/bold]\n"
    if env_entries:
        env_path = os.path.join(config_dir, ".env")
        with open(env_path, "w") as f:
            for k, v in env_entries.items():
                f.write(f"{k}={v}\n")
        os.chmod(env_path, 0o600)
        completion_lines += f"[green]✓[/green] Credentials saved to [bold]{env_path}[/bold] [dim](chmod 600)[/dim]\n"

    console.print(Panel(
        completion_lines + f"\n[bold]Run [cyan]duckclaw start[/cyan] to launch your assistant![/bold]",
        title="✅ Setup Complete!",
        border_style="green",
    ))


def _run_setup():
    """Interactive setup wizard implementation."""
    console.print(Panel(
        "[bold]Welcome to DuckClaw Setup![/bold]\n"
        "Configure your AI assistant in a few steps.\n"
        "[dim]Config saved to ~/.duckclaw/duckclaw.yaml[/dim]",
        title="🧙 Setup Wizard",
        border_style="cyan",
    ))

    setup_mode = questionary.select(
        "How do you want to configure DuckClaw?",
        choices=[
            questionary.Choice("CLI wizard   — step-by-step in terminal", value="cli"),
            questionary.Choice("Browser      — visual settings page", value="browser"),
            questionary.Choice("Import file  — load an existing config file", value="import"),
        ]
    ).ask()

    if setup_mode is None:
        console.print("[red]Setup cancelled.[/red]")
        return

    if setup_mode == "import":
        _setup_import()
    elif setup_mode == "browser":
        _setup_browser()
    else:
        _setup_cli_wizard()


@main.command()
def doctor():
    """Security health check — config integrity, file permissions, audit anomalies."""
    print_banner()
    console.print("[bold cyan]Running DuckClaw Doctor...[/bold cyan]\n")
    console.print("[dim]Note: This is a static health check. Real-time intrusion detection requires a running security agent.[/dim]\n")

    import re
    import stat
    import yaml

    issues = []
    checks = []

    duckclaw_dir = os.path.expanduser("~/.duckclaw")
    config_path = os.path.join(duckclaw_dir, "duckclaw.yaml")
    env_path = os.path.join(duckclaw_dir, ".env")
    db_path = os.path.join(duckclaw_dir, "duckclaw.db")
    chroma_path = os.path.join(duckclaw_dir, "chroma_db")

    def ok(msg):
        checks.append(f"[green]✓[/green] {msg}")

    def warn(msg):
        checks.append(f"[yellow]⚠[/yellow]  {msg}")
        issues.append(msg)

    def fail(msg):
        checks.append(f"[red]✗[/red] {msg}")
        issues.append(msg)

    # 1. Config file
    if not os.path.exists(config_path):
        fail("Config file not found — run duckclaw setup")
    else:
        mode = oct(stat.S_IMODE(os.stat(config_path).st_mode))
        if os.stat(config_path).st_mode & 0o004:
            warn(f"Config file is world-readable ({mode}) — consider chmod 600 -- run: chmod 600 ~/.duckclaw/duckclaw.yaml")
        else:
            ok(f"Config file permissions OK ({mode})")

        try:
            with open(config_path) as f:
                raw = yaml.safe_load(f) or {}

            def _scan(val, keypath):
                if isinstance(val, str) and re.search(r'[;&|`]|\$\(', val):
                    return keypath
                if isinstance(val, dict):
                    for k, v in val.items():
                        r = _scan(v, f"{keypath}.{k}")
                        if r:
                            return r
                return None

            hit = _scan(raw, "config")
            if hit:
                fail(f"Suspicious characters in config at '{hit}' — possible injection")
            else:
                ok("Config values clean — no injection characters found")

        except Exception as e:
            fail(f"Config file unreadable or invalid YAML: {e}")

    # 2. .env file permissions
    if not os.path.exists(env_path):
        warn(".env file not found — API keys may not be set")
    else:
        env_mode = stat.S_IMODE(os.stat(env_path).st_mode)
        if env_mode & 0o077:
            fail(f".env file is readable by group/others (mode {oct(env_mode)}) — run: chmod 600 ~/.duckclaw/.env")
        else:
            ok(f".env file permissions OK ({oct(env_mode)})")

        # Check for obviously leaked keys in wrong place
        try:
            with open(env_path) as f:
                content = f.read()
            if content:
                ok(".env contains API key entries")
            else:
                warn(".env exists but no recognizable API keys found")
        except Exception:
            warn("Could not read .env file")

    # 3. DB files
    if os.path.exists(db_path):
        size_kb = os.path.getsize(db_path) // 1024
        ok(f"SQLite database exists ({size_kb} KB)")
    else:
        warn("SQLite database not found — will be created on first run")

    if os.path.exists(chroma_path):
        ok("ChromaDB vector index exists")
    else:
        warn("ChromaDB vector index not found — will be created on first run")

    # 4. Audit log anomalies (requires DB)
    if os.path.exists(db_path):
        try:
            import sqlite3
            con = sqlite3.connect(db_path)
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'")
            if cur.fetchone():
                cur.execute("SELECT COUNT(*) FROM audit_log WHERE status='blocked'")
                blocked = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM audit_log")
                total = cur.fetchone()[0]
                if total > 0:
                    ratio = blocked / total
                    if ratio > 0.3:
                        warn(f"High BLOCK rate in audit log: {blocked}/{total} ({ratio:.0%}) — possible repeated attack attempts")
                    else:
                        ok(f"Audit log BLOCK rate normal: {blocked}/{total} ({ratio:.0%})")
                else:
                    ok("Audit log empty — no actions recorded yet")
            else:
                ok("Audit log table not yet created")
            con.close()
        except Exception as e:
            warn(f"Could not read audit log: {e}")

    # 5. Port check
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            result = s.connect_ex(("127.0.0.1", 8741))
        if result == 0:
            ok("Dashboard port 8741 is open (DuckClaw is running)")
        else:
            ok("Dashboard port 8741 is closed (DuckClaw not running)")
    except Exception:
        ok("Port check skipped")

    # Print results
    for line in checks:
        console.print(f"  {line}")

    console.print()
    if issues:
        console.print(Panel(
            "\n".join(f"• {i}" for i in issues),
            title=f"[yellow]⚠  {len(issues)} issue(s) found[/yellow]",
            border_style="yellow",
        ))
    else:
        console.print(Panel(
            "[green]All checks passed. DuckClaw looks healthy![/green]",
            title="✅ Doctor Report",
            border_style="green",
        ))


@main.command()
@click.option("--db", is_flag=True, help="Delete SQLite database (facts, conversations, audit log)")
@click.option("--vector-db", is_flag=True, help="Delete ChromaDB vector index")
@click.option("--api-keys", is_flag=True, help="Delete .env file (API keys)")
@click.option("--config", "config_file", is_flag=True, help="Delete duckclaw.yaml config file")
@click.option("--all", "all_data", is_flag=True, help="Delete everything (db + vector-db + api-keys + config)")
@click.option("--yes", is_flag=True, help="Skip confirmation prompts")
def smash(db, vector_db, api_keys, config_file, all_data, yes):
    """Permanently delete DuckClaw data — db, vector-db, api-keys, config."""
    import shutil
    print_banner()

    if all_data:
        db = vector_db = api_keys = config_file = True

    if not any([db, vector_db, api_keys, config_file]):
        console.print(
            "[yellow]Nothing selected. Use flags to choose what to delete:[/yellow]\n"
            "  --db          SQLite database (facts, conversations, audit log)\n"
            "  --vector-db   ChromaDB vector index\n"
            "  --api-keys    .env file (API keys)\n"
            "  --config      duckclaw.yaml config file\n"
            "  --all         Everything above\n"
            "  --yes         Skip confirmation prompts"
        )
        return

    duckclaw_dir = os.path.expanduser("~/.duckclaw")
    targets = []
    if db:
        targets.append(("SQLite database", os.path.join(duckclaw_dir, "duckclaw.db")))
    if vector_db:
        targets.append(("ChromaDB vector index", os.path.join(duckclaw_dir, "chroma_db")))
    if api_keys:
        targets.append(("API keys (.env)", os.path.join(duckclaw_dir, ".env")))
    if config_file:
        targets.append(("Config file (duckclaw.yaml)", os.path.join(duckclaw_dir, "duckclaw.yaml")))

    console.print("[bold red]The following will be permanently deleted:[/bold red]")
    for label, path in targets:
        exists = os.path.exists(path)
        status = "" if exists else " [dim](not found)[/dim]"
        console.print(f"  [red]•[/red] {label} — [dim]{path}[/dim]{status}")

    console.print()

    if not yes:
        confirmed = questionary.confirm(
            "This cannot be undone. Are you sure?", default=False
        ).ask()
        if not confirmed:
            console.print("[dim]Aborted.[/dim]")
            return

    deleted = []
    skipped = []
    for label, path in targets:
        if not os.path.exists(path):
            skipped.append(label)
            continue
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            deleted.append(label)
        except Exception as e:
            console.print(f"[red]✗[/red] Failed to delete {label}: {e}")

    if deleted:
        console.print(Panel(
            "\n".join(f"[green]✓[/green] Deleted: {l}" for l in deleted) +
            ("\n" + "\n".join(f"[dim]— Skipped (not found): {l}[/dim]" for l in skipped) if skipped else ""),
            title="💥 Smash Complete",
            border_style="red",
        ))
    else:
        console.print("[dim]Nothing was deleted (files not found).[/dim]")


@main.command()
@click.option("--purge", is_flag=True, help="Also delete all data and config in ~/.duckclaw/")
@click.option("--yes", is_flag=True, help="Skip confirmation prompts")
def uninstall(purge, yes):
    """Uninstall DuckClaw — removes the package (and optionally all data)."""
    import shutil
    import subprocess
    print_banner()

    console.print("[bold red]DuckClaw Uninstall[/bold red]\n")

    lines = ["• Uninstall the [bold]duckclaw[/bold] Python package"]
    if purge:
        lines.append("• Delete all data in [bold]~/.duckclaw/[/bold] (config, db, keys, vector index)")

    for l in lines:
        console.print(f"  {l}")
    console.print()

    if not yes:
        confirmed = questionary.confirm(
            "This cannot be undone. Continue?", default=False
        ).ask()
        if not confirmed:
            console.print("[dim]Aborted.[/dim]")
            return

    if purge:
        duckclaw_dir = os.path.expanduser("~/.duckclaw")
        if os.path.exists(duckclaw_dir):
            try:
                shutil.rmtree(duckclaw_dir)
                console.print(f"[green]✓[/green] Deleted {duckclaw_dir}")
            except Exception as e:
                console.print(f"[red]✗[/red] Could not delete {duckclaw_dir}: {e}")
        else:
            console.print(f"[dim]~/.duckclaw/ not found — nothing to purge[/dim]")

    console.print("[dim]Uninstalling duckclaw package...[/dim]")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", "duckclaw", "-y"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            console.print("[green]✓[/green] duckclaw uninstalled successfully.")
            console.print("[dim]Goodbye! 👋[/dim]")
        else:
            console.print(f"[red]✗[/red] pip uninstall failed:\n{result.stderr.strip()}")
    except Exception as e:
        console.print(f"[red]✗[/red] Could not run pip: {e}")


@main.command()
@click.option("--token", required=True, envvar="TELEGRAM_BOT_TOKEN", help="Telegram bot token")
@click.option("--allowed-users", default=None, help="Comma-separated Telegram user IDs (leave empty for all)")
def telegram(token, allowed_users):
    """Start the Telegram bridge — chat with DuckClaw from Telegram."""
    print_banner()
    console.print("[bold green]📱 Starting Telegram bridge...[/bold green]")
    console.print("[dim]Get a bot token from @BotFather on Telegram[/dim]\n")

    allowed = [int(u.strip()) for u in allowed_users.split(",")] if allowed_users else None

    async def _run():
        from duckclaw.core.config import load_config
        from duckclaw.core.orchestrator import Orchestrator
        config = load_config()
        orchestrator = Orchestrator(config)
        await orchestrator.initialize()
        bridge = await orchestrator.start_bridge("telegram", token=token, allowed_users=allowed)
        console.print("[bold green]✅ Telegram bridge running. Send a message to your bot![/bold green]")
        try:
            await asyncio.Event().wait()  # Run forever
        except KeyboardInterrupt:
            await bridge.stop()
            await orchestrator.shutdown()

    asyncio.run(_run())


@main.command()
@click.option("--token", required=True, envvar="DISCORD_BOT_TOKEN", help="Discord bot token")
@click.option("--guild-ids", default=None, help="Comma-separated guild IDs for slash commands")
def discord(token, guild_ids):
    """Start the Discord bridge — chat with DuckClaw from Discord."""
    print_banner()
    console.print("[bold green]🎮 Starting Discord bridge...[/bold green]")

    guilds = [int(g.strip()) for g in guild_ids.split(",")] if guild_ids else None

    async def _run():
        from duckclaw.core.config import load_config
        from duckclaw.core.orchestrator import Orchestrator
        config = load_config()
        orchestrator = Orchestrator(config)
        await orchestrator.initialize()
        await orchestrator.start_bridge("discord", token=token, guild_ids=guilds)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
