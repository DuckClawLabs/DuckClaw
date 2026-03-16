"""
DuckClaw LLM Router.
Unified interface for 100+ models via LiteLLM.
Features: cost tracking, smart routing.
"""

import time
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, Any
from datetime import datetime

import litellm
from litellm import acompletion

from duckclaw.core.config import LLMConfig

logger = logging.getLogger(__name__)

# Suppress LiteLLM verbose logging
litellm.suppress_debug_info = True
litellm.set_verbose = False
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("LiteLLM Router").setLevel(logging.WARNING)
logging.getLogger("LiteLLM Proxy").setLevel(logging.WARNING)


@dataclass
class LLMCallRecord:
    """Record of a single LLM call for cost tracking."""
    timestamp: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: float
    success: bool
    error: Optional[str] = None


@dataclass
class RouterStats:
    """Aggregated stats for the dashboard."""
    total_calls: int = 0
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    call_log: list[LLMCallRecord] = field(default_factory=list)

    @property
    def avg_cost_per_call(self) -> float:
        if self.successful_calls == 0:
            return 0.0
        return self.total_cost_usd / self.successful_calls

    def to_dict(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "total_tokens": self.total_tokens,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "avg_cost_per_call": round(self.avg_cost_per_call, 6),
        }


class LLMRouter:
    """
    Routes LLM calls to the configured model.

    Usage:
        router = LLMRouter(config.llm)
        response = await router.chat([{"role": "user", "content": "Hello"}])
    """

    def __init__(self, config: LLMConfig):
        self.config = config
        self.stats = RouterStats()

    async def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> str:
        """Send messages to LLM and return text response."""
        target_model = model or self.config.model
        max_tok = max_tokens or self.config.max_tokens
        temp = temperature if temperature is not None else self.config.temperature

        # Prepend system prompt if provided
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        return await self._call(target_model, full_messages, max_tok, temp, api_key=api_key)

    async def _call(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        api_key: Optional[str] = None,
    ) -> str:
        """Make a single LLM API call and record stats."""
        start = time.monotonic()
        self.stats.total_calls += 1

        try:
            import os
            resolved_key = api_key or os.environ.get("PRIMARY_MODEL_KEY") or None
            call_kwargs: dict[str, Any] = dict(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=self.config.timeout,
            )
            if resolved_key:
                call_kwargs["api_key"] = resolved_key
            response = await acompletion(**call_kwargs)

            latency_ms = (time.monotonic() - start) * 1000
            usage = response.usage

            # Extract cost (LiteLLM calculates this)
            cost = 0.0
            try:
                cost = litellm.completion_cost(completion_response=response)
            except Exception:
                pass

            record = LLMCallRecord(
                timestamp=datetime.now().isoformat(),
                model=model,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
                cost_usd=cost,
                latency_ms=round(latency_ms, 1),
                success=True,
            )

            if self.config.cost_tracking:
                self.stats.total_cost_usd += cost
                self.stats.total_tokens += record.total_tokens
                self.stats.successful_calls += 1
                self.stats.call_log.append(record)
                # Keep only last 1000 records in memory
                if len(self.stats.call_log) > 1000:
                    self.stats.call_log = self.stats.call_log[-1000:]

            return response.choices[0].message.content

        except Exception as e:
            self.stats.failed_calls += 1
            record = LLMCallRecord(
                timestamp=datetime.now().isoformat(),
                model=model,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                cost_usd=0.0,
                latency_ms=(time.monotonic() - start) * 1000,
                success=False,
                error=str(e),
            )
            if self.config.cost_tracking:
                self.stats.call_log.append(record)
            raise

    async def chat_stream(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ):
        """
        Streaming chat — yields text chunks as they arrive.
        Used by the dashboard WebSocket endpoint.
        """
        target_model = model or self.config.model

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        response = await acompletion(
            model=target_model,
            messages=full_messages,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            stream=True,
        )

        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def get_reasoning_model(self) -> str:
        """Return the reasoning model, or primary model if not configured."""
        return self.config.reasoning_model or self.config.model

    def get_vision_model(self) -> str:
        """Return the vision model, or primary model if not configured."""
        return self.config.vision_model or self.config.model

    def get_tts_model(self) -> str:
        """Return the text-to-speech model, or primary model if not configured."""
        return self.config.tts_model or self.config.model

    async def chat_reasoning(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Send messages using the configured reasoning model."""
        import os
        return await self.chat(
            messages=messages,
            model=self.get_reasoning_model(),
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            api_key=os.environ.get("REASONING_API_KEY") or None,
        )

    async def chat_vision(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Send messages using the configured vision model.

        Raises ValueError if the resolved model does not support image input,
        so the caller gets a clear message instead of a cryptic API error.
        """
        vision_model = self.get_vision_model()

        # Groq and several other providers reject multimodal content arrays.
        # Guard here so the error is actionable.
        has_image = any(
            isinstance(m.get("content"), list) and
            any(p.get("type") == "image_url" for p in m["content"])
            for m in messages
        )
        if has_image and not litellm.supports_vision(model=vision_model):
            raise ValueError(
                f"Model '{vision_model}' does not support image input. "
                "Set a vision-capable model (e.g. gemini/gemini-2.0-flash or "
                "claude-haiku-4-5-20251001) under Settings → Vision model."
            )

        import os
        return await self.chat(
            messages=messages,
            model=vision_model,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            api_key=os.environ.get("VISION_API_KEY") or None,
        )

    async def chat_tts(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Send messages using the configured text-to-speech model."""
        import os
        return await self.chat(
            messages=messages,
            model=self.get_tts_model(),
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            api_key=os.environ.get("AUDIO_API_KEY") or None,
        )

    def get_stats(self) -> dict:
        """Return cost and usage stats for dashboard."""
        return self.stats.to_dict()

    def get_recent_calls(self, limit: int = 20) -> list[dict]:
        """Return recent call records for dashboard."""
        recent = self.stats.call_log[-limit:]
        return [
            {
                "timestamp": r.timestamp,
                "model": r.model,
                "tokens": r.total_tokens,
                "cost_usd": round(r.cost_usd, 6),
                "latency_ms": r.latency_ms,
                "success": r.success,
                "error": r.error,
            }
            for r in reversed(recent)
        ]
