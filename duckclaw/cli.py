"""
DuckClaw CLI — Entry point for all commands.
Usage: duckclaw start | chat | setup | status
"""

import sys
import os
import asyncio
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
@click.version_option(version="0.1.0", prog_name="DuckClaw")
def main():
    """🦆🤖 DuckClaw — Secure personal AI assistant."""
    pass


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
    print_banner()

    if not check_config_exists():
        console.print("[red]No config found. Run [bold]duckclaw setup[/bold] first.[/red]")
        sys.exit(1)

    console.print("[bold green]💬 DuckClaw Chat[/bold green] [dim](type 'exit' to quit · 'new' for new conversation · 'clear' to reset screen)[/dim]\n")

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
            if user_input.lower() == "exit":
                console.print("[dim]Goodbye! 👋[/dim]")
                break
            if user_input.lower() == "clear":
                console.clear()
                print_banner()
                continue
            if user_input.lower() == "new":
                session_id = _new_session_id()
                console.print(f"\n[bold green]✦ New conversation started[/bold green] [dim](session {session_id})[/dim]\n")
                continue

            with console.status("[dim]Thinking...[/dim]"):
                response = await orchestrator.chat(
                    message=user_input,
                    session_id=session_id,
                    source="terminal",
                )

            console.print(f"[bold yellow]🦆🤖 DuckClaw:[/bold yellow] {response['reply']}\n")

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
            f"[green]✓[/green] Config loaded\n"
            f"[green]✓[/green] Model: [bold]{config.llm.model}[/bold]\n"
            f"[green]✓[/green] Fallback: [bold]{', '.join(config.llm.fallback_models) or 'none'}[/bold]\n"
            f"[green]✓[/green] Dashboard: [bold]localhost:{config.dashboard.port}[/bold]\n"
            f"[green]✓[/green] Memory: [bold]{config.memory.db_path}[/bold]",
            title="🦆🤖 DuckClaw Status",
            border_style="green",
        ))

    asyncio.run(_show_status())


def _run_setup():
    """Interactive setup wizard implementation."""
    console.print(Panel(
        "[bold]Welcome to DuckClaw Setup![/bold]\n"
        "This wizard will configure your AI assistant in a few steps.\n"
        "[dim]Your config is saved to ~/.duckclaw/duckclaw.yaml[/dim]",
        title="🧙 Setup Wizard",
        border_style="cyan",
    ))

    # Step 1: Choose primary LLM
    console.print("\n[bold cyan]Step 1/3 — Choose your AI model[/bold cyan]")
    model_choice = questionary.select(
        "Which AI model do you want to use?",
        choices=[
            questionary.Choice("Claude (Anthropic) — Recommended, powerful", value="claude"),
            questionary.Choice("Gemini Flash (Google) — Free tier, no cost", value="gemini"),
            questionary.Choice("Custom model (advanced)", value="custom"),
        ]
    ).ask()

    if model_choice is None:
        console.print("[red]Setup cancelled.[/red]")
        return

    model_map = {
        "claude": "claude-haiku-4-5-20251001",
        "gemini": "gemini/gemini-2.0-flash",
    }

    if model_choice == "custom":
        model_name = questionary.text(
            "Enter your LiteLLM model string (e.g. openai/gpt-4o):"
        ).ask()
    else:
        model_name = model_map[model_choice]

    # Step 2: API Key
    console.print("\n[bold cyan]Step 2/3 — API Key[/bold cyan]")

    api_key = ""
    if model_choice == "claude":
        api_key = questionary.password("Enter your Anthropic API key:").ask() or ""
        env_var = "ANTHROPIC_API_KEY"
    elif model_choice == "gemini":
        console.print("[dim]Get a free key at: https://aistudio.google.com/app/apikey[/dim]")
        api_key = questionary.password("Enter your Google AI Studio API key:").ask() or ""
        env_var = "GEMINI_API_KEY"
    else:
        api_key = questionary.password("Enter your API key:").ask() or ""
        env_var = "LLM_API_KEY"

    # Step 3: Preferences
    console.print("\n[bold cyan]Step 3/3 — Preferences[/bold cyan]")
    dashboard_port = questionary.text(
        "Dashboard port:", default="8741"
    ).ask() or "8741"

    enable_audit = questionary.confirm(
        "Enable full audit log? (Recommended — logs every action)", default=True
    ).ask()

    # Write config
    config_dir = os.path.expanduser("~/.duckclaw")
    os.makedirs(config_dir, exist_ok=True)

    config_content = f"""# DuckClaw Configuration
# Generated by setup wizard

llm:
  model: "{model_name}"
  fallback_models:
    - "gemini/gemini-2.0-flash"   # Free fallback — always available
  cost_tracking: true
  max_tokens: 4096
  temperature: 0.7

memory:
  db_path: "~/.duckclaw/duckclaw.db"
  chroma_path: "~/.duckclaw/chroma_db"
  max_facts: 10000
  semantic_search_results: 5

permissions:
  default_tier: "ask"            # Conservative default
  audit_log: {"true" if enable_audit else "false"}
  notify_on_safe: false          # Don't spam notifications for safe actions

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

    # Write .env file for API keys
    env_path = os.path.join(config_dir, ".env")
    env_content = f"{env_var}={api_key}\n"
    if model_choice == "claude":
        env_content += f"GEMINI_API_KEY=  # Optional: add for free fallback\n"

    with open(env_path, "w") as f:
        f.write(env_content)
    os.chmod(env_path, 0o600)  # Secure the env file

    console.print(Panel(
        f"[green]✓[/green] Config saved to [bold]{config_path}[/bold]\n"
        f"[green]✓[/green] API key saved to [bold]{env_path}[/bold] [dim](chmod 600)[/dim]\n\n"
        f"[bold]Run [cyan]duckclaw start[/cyan] to launch your assistant![/bold]",
        title="✅ Setup Complete!",
        border_style="green",
    ))


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
