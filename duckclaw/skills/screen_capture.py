"""
Screen Capture Skill.
Uses `mss` library — cross-platform (macOS, Windows, Linux), zero system deps.

Every capture → Tier: ASK (explicit user approval required, every time).
Option to analyze with LLM vision immediately after capture.
"""

import base64
import io
import logging
from typing import Optional, TYPE_CHECKING

from duckclaw.skills.base import BaseSkill, SkillPermission, SkillResult

if TYPE_CHECKING:
    from duckclaw.llm.router import LLMRouter

logger = logging.getLogger(__name__)

VISION_PROMPT = """Analyze this screenshot and describe what you see.
Be specific about:
- Applications open and what they show
- Any text visible
- Any errors or important information
- The general state of the desktop/screen"""


class ScreenCaptureSkill(BaseSkill):
    name = "screen_capture"
    description = "Capture screenshots and optionally analyze with AI vision. Requires approval every time."
    version = "1.0.0"
    permissions = [SkillPermission.SCREEN]  # Tier: ASK — requires approval

    def __init__(self, permission_engine, llm_router: Optional["LLMRouter"] = None):
        super().__init__(permission_engine)
        self._llm = llm_router

    def set_llm(self, llm_router: "LLMRouter"):
        self._llm = llm_router

    async def execute(self, action: str, params: dict) -> SkillResult:
        dispatch = {
            "capture":          self._capture,
            "capture_analyze":  self._capture_and_analyze,
            "list_monitors":    self._list_monitors,
        }
        handler = dispatch.get(action)
        if not handler:
            return SkillResult(success=False, error=f"Unknown action: {action}")
        return await handler(params)

    async def _capture(self, params: dict) -> SkillResult:
        """Capture a screenshot. Always requires ASK approval."""
        monitor = int(params.get("monitor", 0))
        region = params.get("region", None)  # {"top": y, "left": x, "width": w, "height": h}

        # ASK tier — user must approve every capture
        approved = await self._check(
            "screen_capture",
            "Take a screenshot of your screen",
            details={
                "monitor": monitor,
                "region": region or "full screen",
            },
            reversible=True,
            risk_level="low",
        )
        if not approved:
            return SkillResult(success=False, error="Screenshot denied by user.")

        return await self._do_capture(monitor, region)

    async def _capture_and_analyze(self, params: dict) -> SkillResult:
        """Capture screenshot and immediately analyze with LLM vision."""
        monitor = int(params.get("monitor", 0))
        question = params.get("question", "What's on the screen?")

        approved = await self._check(
            "screen_capture",
            f"Take screenshot and analyze: '{question}'",
            details={"monitor": monitor, "question": question},
            reversible=True,
            risk_level="low",
        )
        if not approved:
            return SkillResult(success=False, error="Screenshot denied by user.")

        # Capture
        capture_result = await self._do_capture(monitor, None)
        if not capture_result.success:
            return capture_result

        b64 = capture_result.metadata.get("image_base64")
        if not b64 or not self._llm:
            return capture_result

        # Send to LLM vision
        try:
            response = await self._llm.chat(
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{b64}"
                                },
                            },
                            {"type": "text", "text": question},
                        ],
                    }
                ],
            )

            return SkillResult(
                success=True,
                data=response,
                action_taken="Screenshot captured and analyzed",
                metadata={
                    "question": question,
                    "image_base64": b64,
                    "width": capture_result.metadata.get("width"),
                    "height": capture_result.metadata.get("height"),
                },
            )

        except Exception as e:
            logger.warning(f"Vision analysis failed: {e}")
            # Return image even if analysis fails
            return SkillResult(
                success=True,
                data=f"Screenshot captured but vision analysis failed: {e}",
                metadata=capture_result.metadata,
            )

    async def _list_monitors(self, params: dict) -> SkillResult:
        """List available monitors. Tier: SAFE — no capture, just info."""
        try:
            import mss
            with mss.mss() as sct:
                monitors = [
                    {
                        "id": i,
                        "width": m["width"],
                        "height": m["height"],
                        "top": m["top"],
                        "left": m["left"],
                    }
                    for i, m in enumerate(sct.monitors)
                ]
            return SkillResult(success=True, data=monitors)
        except ImportError:
            return SkillResult(success=False, error="mss not installed. Run: pip install mss")
        except Exception as e:
            return SkillResult(success=False, error=str(e))

    async def _do_capture(self, monitor: int = 0, region=None) -> SkillResult:
        """Internal: perform the actual screenshot capture."""
        try:
            import mss
            from PIL import Image

            with mss.mss() as sct:
                if region:
                    shot = sct.grab(region)
                else:
                    monitors = sct.monitors
                    if monitor >= len(monitors):
                        return SkillResult(success=False, error=f"Monitor {monitor} not found")
                    shot = sct.grab(monitors[monitor])

                # Convert to PIL for compression
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                w, h = img.size

                # Compress to JPEG, keep under 5MB for LLM
                buf = io.BytesIO()
                quality = 85
                img.save(buf, format="JPEG", quality=quality)
                if buf.tell() > 4_000_000:
                    buf = io.BytesIO()
                    img.thumbnail((1920, 1080))
                    img.save(buf, format="JPEG", quality=75)

                b64 = base64.b64encode(buf.getvalue()).decode()

            return SkillResult(
                success=True,
                data=f"Screenshot captured ({w}×{h} px, {len(b64)//1024}KB)",
                action_taken="Screenshot taken",
                metadata={
                    "image_base64": b64,
                    "width": w,
                    "height": h,
                    "format": "jpeg",
                },
            )

        except ImportError as e:
            missing = "mss" if "mss" in str(e) else "Pillow"
            return SkillResult(
                success=False,
                error=f"{missing} not installed. Run: pip install mss Pillow",
            )
        except Exception as e:
            logger.error(f"Screenshot capture failed: {e}")
            return SkillResult(success=False, error=f"Capture failed: {e}")
