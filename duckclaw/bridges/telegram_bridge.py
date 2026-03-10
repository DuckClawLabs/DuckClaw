"""
DuckClaw Telegram Bridge.
Uses python-telegram-bot v21 (async-native).

Features:
- Receive messages from any Telegram DM or group
- Approval buttons via InlineKeyboardMarkup
- /start command with welcome message
- /memory, /audit quick commands
- Per-chat session isolation
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from duckclaw.bridges.base import BaseBridge, BridgeMessage

if TYPE_CHECKING:
    from duckclaw.core.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

# Per-chat pending approvals (chat_id → {action_id → Future})
_pending: dict[str, dict[str, asyncio.Future]] = {}


class TelegramBridge(BaseBridge):
    platform = "telegram"

    def __init__(self, token: str, orchestrator: "Orchestrator", allowed_users: list[int] | None = None):
        super().__init__(orchestrator)
        self._token = token
        self._allowed_users = allowed_users  # None = allow everyone
        self._app = None

    async def start(self):
        """Start Telegram bot polling."""
        try:
            from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
            from telegram.ext import (
                Application, MessageHandler, CallbackQueryHandler,
                CommandHandler, filters
            )
        except ImportError:
            raise RuntimeError(
                "python-telegram-bot not installed. Run: pip install python-telegram-bot"
            )

        self._app = (
            Application.builder()
            .token(self._token)
            .build()
        )

        # Register handlers
        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(CommandHandler("memory", self._handle_memory_cmd))
        self._app.add_handler(CommandHandler("audit", self._handle_audit_cmd))
        self._app.add_handler(CommandHandler("help", self._handle_help))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))

        self._running = True
        logger.info("Telegram bridge starting...")

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bridge running")

    async def stop(self):
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        self._running = False

    # ── Handlers ────────────────────────────────────────────────────────────

    async def _handle_start(self, update, context):
        chat_id = str(update.effective_chat.id)
        if not self._is_allowed(update):
            await update.message.reply_text("⛔ Access denied.")
            return

        await update.message.reply_text(
            "🦆🦞 *DuckClaw* is ready!\n\n"
            "I'm your secure personal AI assistant.\n"
            "Every sensitive action requires your approval.\n\n"
            "*Commands:*\n"
            "/memory — View stored memories\n"
            "/audit — Recent audit log\n"
            "/help — Show this help\n\n"
            "Just type a message to chat!",
            parse_mode="Markdown",
        )

    async def _handle_help(self, update, context):
        await update.message.reply_text(
            "🦆 *DuckClaw Commands*\n\n"
            "/start — Welcome message\n"
            "/memory — Your stored facts\n"
            "/audit — Recent action log\n\n"
            "Just type anything to chat with your AI assistant.\n"
            "Sensitive actions will show approval buttons.",
            parse_mode="Markdown",
        )

    async def _handle_memory_cmd(self, update, context):
        if not self._is_allowed(update):
            return
        facts = self._orchestrator.memory.list_facts(limit=10)
        if not facts:
            await update.message.reply_text("🧠 No memories stored yet.")
            return
        lines = ["🧠 *Recent Memories:*\n"]
        for f in facts[:10]:
            lines.append(f"• [{f['category']}] {f['fact']}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _handle_audit_cmd(self, update, context):
        if not self._is_allowed(update):
            return
        logs = self._orchestrator.permissions.get_audit_log(limit=5)
        if not logs:
            await update.message.reply_text("📋 No actions logged yet.")
            return
        lines = ["📋 *Recent Actions:*\n"]
        for log in logs:
            status_emoji = {"user_approved": "✅", "user_denied": "❌", "blocked": "🚫", "notified": "ℹ️"}.get(log["status"], "⚪")
            lines.append(f"{status_emoji} {log['action_type']} — {log['description'][:50]}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _handle_message(self, update, context):
        if not self._is_allowed(update):
            await update.message.reply_text("⛔ Access denied.")
            return

        chat_id = str(update.effective_chat.id)
        user_id = str(update.effective_user.id)
        text = update.message.text.strip()

        if not text:
            return

        # Show typing indicator
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        msg = BridgeMessage(
            content=text,
            user_id=user_id,
            chat_id=chat_id,
            platform="telegram",
            username=update.effective_user.username,
        )

        # Override send methods to use this specific update context
        async def send_text_impl(cid: str, text: str):
            await context.bot.send_message(chat_id=cid, text=text, parse_mode="Markdown")

        async def send_approval_impl(cid: str, action_id: str, preview: dict):
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(preview.get("risk_level", "low"), "⚪")
            reversible = "✓ Reversible" if preview.get("reversible") else "✗ Irreversible"

            text = (
                f"⚠️ *Permission Required*\n\n"
                f"*{preview.get('description', 'Action')}*\n"
                f"Type: `{preview.get('action_type', '')}`\n"
                f"Risk: {risk_emoji} {preview.get('risk_level', 'low').upper()} · {reversible}"
            )

            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve:{action_id}"),
                InlineKeyboardButton("❌ Deny",    callback_data=f"deny:{action_id}"),
            ]])

            await context.bot.send_message(chat_id=cid, text=text, parse_mode="Markdown", reply_markup=keyboard)

        # Temporarily override bridge methods for this message
        self.send_text = send_text_impl
        self.send_approval_request = send_approval_impl

        await self.handle_message(msg)

    async def _handle_callback(self, update, context):
        """Handle approve/deny button taps."""
        query = update.callback_query
        await query.answer()

        data = query.data
        if ":" not in data:
            return

        action, action_id = data.split(":", 1)
        chat_id = str(update.effective_chat.id)
        approved = action == "approve"

        # Resolve the pending future
        if chat_id in _pending and action_id in _pending[chat_id]:
            _pending[chat_id][action_id].set_result(approved)

        status = "✅ Approved" if approved else "❌ Denied"
        await query.edit_message_text(
            query.message.text + f"\n\n{status}",
            parse_mode="Markdown",
        )

    def _is_allowed(self, update) -> bool:
        """Check if user is in the allowed list (if configured)."""
        if self._allowed_users is None:
            return True
        user_id = update.effective_user.id
        return user_id in self._allowed_users

    async def send_text(self, chat_id: str, text: str):
        """Send plain text (default impl, overridden per-message)."""
        if self._app:
            await self._app.bot.send_message(chat_id=chat_id, text=text)

    async def send_approval_request(self, chat_id: str, action_id: str, preview: dict):
        """Send approval buttons (default impl, overridden per-message)."""
        pass
