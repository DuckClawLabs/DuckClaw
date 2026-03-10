"""
DuckClaw Discord Bridge.
Uses discord.py v2 (async, slash commands, button components).

Features:
- Receive messages in DMs and servers
- Approval via interactive Button components
- /duckclaw chat slash command
- /duckclaw memory and /duckclaw audit slash commands
- Per-channel session isolation
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from duckclaw.bridges.base import BaseBridge, BridgeMessage

if TYPE_CHECKING:
    from duckclaw.core.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

# Pending approvals: channel_id → {action_id → Future}
_pending: dict[str, dict[str, asyncio.Future]] = {}


class DuckClawDiscordBot:
    """Discord bot with DuckClaw integration."""

    def __init__(self, token: str, orchestrator: "Orchestrator", guild_ids: list[int] | None = None):
        self._token = token
        self._orchestrator = orchestrator
        self._guild_ids = guild_ids
        self._client = None
        self._tree = None

    async def start(self):
        try:
            import discord
            from discord import app_commands
            from discord.ext import commands
        except ImportError:
            raise RuntimeError("discord.py not installed. Run: pip install discord.py")

        import discord
        from discord import app_commands

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)
        self._tree = app_commands.CommandTree(self._client)

        client = self._client
        tree = self._tree
        orchestrator = self._orchestrator

        @client.event
        async def on_ready():
            await tree.sync()
            logger.info(f"Discord bot ready: {client.user}")

        @client.event
        async def on_message(message: discord.Message):
            if message.author.bot:
                return
            # Only respond to DMs or @mentions
            if isinstance(message.channel, discord.DMChannel) or client.user in message.mentions:
                content = message.content.replace(f"<@{client.user.id}>", "").strip()
                if content:
                    await _process_message(message, content, orchestrator)

        @tree.command(name="duckclaw", description="Chat with DuckClaw AI assistant")
        @app_commands.describe(message="Your message")
        async def duckclaw_chat(interaction: discord.Interaction, message: str):
            await interaction.response.defer(thinking=True)
            await _process_interaction(interaction, message, orchestrator)

        @tree.command(name="memory", description="View DuckClaw's stored memories")
        async def duckclaw_memory(interaction: discord.Interaction):
            facts = orchestrator.memory.list_facts(limit=10)
            if not facts:
                await interaction.response.send_message("🧠 No memories stored yet.", ephemeral=True)
                return
            lines = ["🧠 **Recent Memories:**\n"]
            for f in facts[:10]:
                lines.append(f"• `[{f['category']}]` {f['fact']}")
            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        @tree.command(name="audit", description="View recent DuckClaw audit log")
        async def duckclaw_audit(interaction: discord.Interaction):
            logs = orchestrator.permissions.get_audit_log(limit=5)
            if not logs:
                await interaction.response.send_message("📋 No actions logged.", ephemeral=True)
                return
            lines = ["📋 **Recent Actions:**\n"]
            for log in logs:
                emoji = {"user_approved": "✅", "user_denied": "❌", "blocked": "🚫", "notified": "ℹ️"}.get(log["status"], "⚪")
                lines.append(f"{emoji} `{log['action_type']}` — {log['description'][:60]}")
            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        logger.info("Starting Discord bot...")
        await client.start(self._token)

    async def stop(self):
        if self._client:
            await self._client.close()


async def _process_message(message, content: str, orchestrator: "Orchestrator"):
    """Process a Discord message."""
    import discord
    channel_id = str(message.channel.id)
    user_id = str(message.author.id)

    _pending.setdefault(channel_id, {})

    async def approval_callback(preview) -> bool:
        import uuid
        action_id = str(uuid.uuid4())
        future = asyncio.get_event_loop().create_future()
        _pending[channel_id][action_id] = future

        await _send_approval_embed(message.channel, action_id, preview.to_dict())

        try:
            return await asyncio.wait_for(future, timeout=120.0)
        except asyncio.TimeoutError:
            _pending[channel_id].pop(action_id, None)
            await message.channel.send("⏱️ Approval timed out. Action cancelled.")
            return False

    async def notify_callback(text: str):
        await message.channel.send(text)

    orchestrator.permissions.set_approval_callback(approval_callback)
    orchestrator.permissions.set_notify_callback(notify_callback)

    async with message.channel.typing():
        result = await orchestrator.chat(
            message=content,
            session_id=f"discord-{channel_id}",
            source="discord",
            user_id=user_id,
        )

    # Discord has 2000 char limit — split if needed
    reply = result["reply"]
    chunks = [reply[i:i+1900] for i in range(0, len(reply), 1900)]
    for chunk in chunks:
        await message.channel.send(chunk)


async def _process_interaction(interaction, content: str, orchestrator: "Orchestrator"):
    """Process a Discord slash command interaction."""
    import discord
    channel_id = str(interaction.channel_id)
    user_id = str(interaction.user.id)

    _pending.setdefault(channel_id, {})

    async def approval_callback(preview) -> bool:
        import uuid
        action_id = str(uuid.uuid4())
        future = asyncio.get_event_loop().create_future()
        _pending[channel_id][action_id] = future

        await _send_approval_embed(interaction.channel, action_id, preview.to_dict())

        try:
            return await asyncio.wait_for(future, timeout=120.0)
        except asyncio.TimeoutError:
            _pending[channel_id].pop(action_id, None)
            return False

    async def notify_callback(text: str):
        await interaction.followup.send(text, ephemeral=True)

    orchestrator.permissions.set_approval_callback(approval_callback)
    orchestrator.permissions.set_notify_callback(notify_callback)

    result = await orchestrator.chat(
        message=content,
        session_id=f"discord-{channel_id}",
        source="discord",
        user_id=user_id,
    )

    reply = result["reply"][:1900]
    await interaction.followup.send(reply)


async def _send_approval_embed(channel, action_id: str, preview: dict):
    """Send an embed with approve/deny buttons."""
    import discord

    risk_colors = {"low": 0x22c55e, "medium": 0xf59e0b, "high": 0xef4444}
    color = risk_colors.get(preview.get("risk_level", "low"), 0x94a3b8)

    embed = discord.Embed(
        title=f"⚠️ Permission Required",
        description=preview.get("description", ""),
        color=color,
    )
    embed.add_field(name="Action", value=f"`{preview.get('action_type', '')}`", inline=True)
    embed.add_field(name="Risk", value=preview.get("risk_level", "low").upper(), inline=True)
    embed.add_field(name="Reversible", value="Yes" if preview.get("reversible") else "No", inline=True)

    if details := preview.get("details"):
        detail_str = "\n".join(f"`{k}`: {v}" for k, v in list(details.items())[:5])
        embed.add_field(name="Details", value=detail_str, inline=False)

    view = ApprovalView(action_id)
    await channel.send(embed=embed, view=view)


class ApprovalView:
    """Discord UI View with approve/deny buttons."""

    def __init__(self, action_id: str):
        self._action_id = action_id

    def __new__(cls, action_id: str):
        try:
            import discord

            class _View(discord.ui.View):
                def __init__(self, aid):
                    super().__init__(timeout=120)
                    self.aid = aid

                @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.green)
                async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
                    channel_id = str(interaction.channel_id)
                    if channel_id in _pending and self.aid in _pending[channel_id]:
                        _pending[channel_id][self.aid].set_result(True)
                    button.disabled = True
                    for child in self.children:
                        child.disabled = True
                    await interaction.response.edit_message(content="✅ Approved", view=self)

                @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.red)
                async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
                    channel_id = str(interaction.channel_id)
                    if channel_id in _pending and self.aid in _pending[channel_id]:
                        _pending[channel_id][self.aid].set_result(False)
                    for child in self.children:
                        child.disabled = True
                    await interaction.response.edit_message(content="❌ Denied", view=self)

            return _View(action_id)
        except ImportError:
            return object.__new__(cls)


class DiscordBridge(BaseBridge):
    """Thin wrapper around DuckClawDiscordBot to match BaseBridge interface."""
    platform = "discord"

    def __init__(self, token: str, orchestrator: "Orchestrator", guild_ids: list[int] | None = None):
        super().__init__(orchestrator)
        self._bot = DuckClawDiscordBot(token, orchestrator, guild_ids)

    async def start(self):
        self._running = True
        await self._bot.start()

    async def stop(self):
        await self._bot.stop()
        self._running = False

    async def send_text(self, chat_id: str, text: str):
        pass  # Discord bot handles responses inline

    async def send_approval_request(self, chat_id: str, action_id: str, preview: dict):
        pass  # Handled per-message in the bot
