"""
DuckClaw Bridge Base Class.
All messaging platform bridges (Telegram, Discord, etc.) inherit from this.

Every bridge:
- Receives messages from the platform
- Forwards to the Orchestrator
- Returns responses back (text or approval buttons)
- Translates platform-specific approval interactions to the Permission Engine
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from duckclaw.core.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


class BridgeMessage:
    """Normalized message from any platform."""
    def __init__(
        self,
        content: str,
        user_id: str,
        chat_id: str,
        platform: str,
        username: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        self.content = content
        self.user_id = user_id
        self.chat_id = chat_id
        self.platform = platform
        self.username = username
        self.session_id = session_id or f"{platform}-{chat_id}"


class BaseBridge(ABC):
    """Base class for all DuckClaw messaging bridges."""

    platform: str = "unknown"

    def __init__(self, orchestrator: "Orchestrator"):
        self._orchestrator = orchestrator
        self._running = False

    @abstractmethod
    async def start(self):
        """Start listening for messages on this platform."""
        pass

    @abstractmethod
    async def stop(self):
        """Stop the bridge."""
        pass

    @abstractmethod
    async def send_text(self, chat_id: str, text: str):
        """Send a plain text message."""
        pass

    @abstractmethod
    async def send_approval_request(self, chat_id: str, action_id: str, preview: dict):
        """Send an approval request with approve/deny buttons."""
        pass

    async def handle_message(self, msg: BridgeMessage) -> None:
        """
        Process an incoming message.
        Wires up approval callbacks for this specific chat.
        """
        # Pending approvals for this chat
        pending: dict[str, asyncio.Future] = {}

        async def approval_callback(preview) -> bool:
            import uuid
            action_id = str(uuid.uuid4())
            loop = asyncio.get_event_loop()
            future: asyncio.Future = loop.create_future()
            pending[action_id] = future

            await self.send_approval_request(msg.chat_id, action_id, preview.to_dict())

            try:
                return await asyncio.wait_for(future, timeout=120.0)
            except asyncio.TimeoutError:
                pending.pop(action_id, None)
                await self.send_text(msg.chat_id, "⏱️ Approval timed out. Action cancelled.")
                return False

        async def notify_callback(message: str) -> None:
            await self.send_text(msg.chat_id, message)

        # Register callbacks for this session
        self._orchestrator.permissions.set_approval_callback(approval_callback)
        self._orchestrator.permissions.set_notify_callback(notify_callback)

        # Process message
        try:
            result = await self._orchestrator.chat(
                message=msg.content,
                session_id=msg.session_id,
                source=self.platform,
                user_id=msg.user_id,
            )
            await self.send_text(msg.chat_id, result["reply"])
        except Exception as e:
            logger.exception(f"Error processing message on {self.platform}")
            await self.send_text(msg.chat_id, f"❌ Error: {e}")

    def resolve_approval(self, pending: dict, action_id: str, approved: bool):
        """Called when a user taps approve/deny on a platform button."""
        if action_id in pending:
            pending[action_id].set_result(approved)
            pending.pop(action_id)
