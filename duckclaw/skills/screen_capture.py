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
        logger.info("[screen_capture] execute action=%s params=%s", action, {k: v for k, v in params.items() if k != "image_base64"})
        dispatch = {
            "capture":          self._capture,
            "capture_analyze":  self._capture_and_analyze,
            "list_monitors":    self._list_monitors,
        }
        handler = dispatch.get(action)
        if not handler:
            logger.warning("[screen_capture] unknown action: %s", action)
            return SkillResult(success=False, error=f"Unknown action: {action}")
        result = await handler(params)
        logger.info("[screen_capture] action=%s success=%s", action, result.success)
        return result

    async def _capture(self, params: dict) -> SkillResult:
        """Capture a screenshot. Always requires ASK approval."""
        monitor = int(params.get("monitor", 0))
        region = params.get("region", None)  # {"top": y, "left": x, "width": w, "height": h}

        logger.info("[screen_capture] requesting ASK-tier approval — monitor=%d region=%s", monitor, region or "full screen")

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
            logger.info("[screen_capture] capture DENIED by user")
            return SkillResult(success=False, error="Screenshot denied by user.")

        logger.info("[screen_capture] capture APPROVED — proceeding")
        return await self._do_capture(monitor, region)

    async def _capture_and_analyze(self, params: dict) -> SkillResult:
        """Capture screenshot and immediately analyze with LLM vision."""
        monitor = int(params.get("monitor", 0))
        question = params.get("question", "What's on the screen?")

        logger.info("[screen_capture] capture_analyze — monitor=%d question=%r", monitor, question)
        logger.info("[screen_capture] requesting ASK-tier approval for capture_analyze")

        approved = await self._check(
            "screen_capture",
            f"Take screenshot and analyze: '{question}'",
            details={"monitor": monitor, "question": question},
            reversible=True,
            risk_level="low",
        )
        if not approved:
            logger.info("[screen_capture] capture_analyze DENIED by user")
            return SkillResult(success=False, error="Screenshot denied by user.")

        logger.info("[screen_capture] capture_analyze APPROVED — capturing")

        # Capture
        capture_result = await self._do_capture(monitor, None)
        if not capture_result.success:
            logger.warning("[screen_capture] capture step failed: %s", capture_result.error)
            return capture_result

        b64 = capture_result.metadata.get("image_base64")
        if not b64:
            logger.warning("[screen_capture] no image data in capture result — returning without analysis")
            return capture_result
        if not self._llm:
            logger.warning("[screen_capture] no LLM router attached — returning image without analysis")
            return capture_result

        logger.info("[screen_capture] sending image to LLM vision (%dKB) question=%r",
                    len(b64) // 1024, question)

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

            logger.info("[screen_capture] LLM vision response received (%d chars)", len(response or ""))
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
            logger.warning("[screen_capture] vision analysis failed: %s", e, exc_info=True)
            # Return image even if analysis fails
            return SkillResult(
                success=True,
                data=f"Screenshot captured but vision analysis failed: {e}",
                metadata=capture_result.metadata,
            )

    async def _list_monitors(self, params: dict) -> SkillResult:
        """List available monitors. Tier: SAFE — no capture, just info."""
        logger.debug("[screen_capture] listing monitors")
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
            logger.info("[screen_capture] found %d monitor(s): %s",
                        len(monitors), [(m["id"], f"{m['width']}x{m['height']}") for m in monitors])
            return SkillResult(success=True, data=monitors)
        except ImportError:
            logger.error("[screen_capture] mss not installed")
            return SkillResult(success=False, error="mss not installed. Run: pip install mss")
        except Exception as e:
            logger.error("[screen_capture] list_monitors failed: %s", e, exc_info=True)
            return SkillResult(success=False, error=str(e))

    async def _do_capture(self, monitor: int = 0, region=None) -> SkillResult:
        """Internal: perform the actual screenshot capture."""
        logger.debug("[screen_capture] _do_capture monitor=%d region=%s", monitor, region)
        try:
            import mss
            from PIL import Image

            with mss.mss() as sct:
                if region:
                    logger.debug("[screen_capture] grabbing region %s", region)
                    shot = sct.grab(region)
                else:
                    monitors = sct.monitors
                    if monitor >= len(monitors):
                        logger.error("[screen_capture] monitor %d not found (available: 0-%d)", monitor, len(monitors) - 1)
                        return SkillResult(success=False, error=f"Monitor {monitor} not found")
                    logger.debug("[screen_capture] grabbing monitor %d (%dx%d)",
                                 monitor, monitors[monitor]["width"], monitors[monitor]["height"])
                    shot = sct.grab(monitors[monitor])

                # Convert to PIL for compression
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                w, h = img.size
                logger.debug("[screen_capture] raw image size %dx%d", w, h)

                # Compress to JPEG, keep under 5MB for LLM
                buf = io.BytesIO()
                quality = 85
                img.save(buf, format="JPEG", quality=quality)
                raw_size = buf.tell()

                if raw_size > 4_000_000:
                    logger.info("[screen_capture] image too large (%dKB) — resizing to 1920x1080 at quality=75", raw_size // 1024)
                    buf = io.BytesIO()
                    img.thumbnail((1920, 1080))
                    img.save(buf, format="JPEG", quality=75)

                b64 = base64.b64encode(buf.getvalue()).decode()
                final_kb = len(b64) // 1024

            logger.info("[screen_capture] capture SUCCESS — %dx%d px, %dKB (base64)", w, h, final_kb)
            return SkillResult(
                success=True,
                data=f"Screenshot captured ({w}×{h} px, {final_kb}KB)",
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
            logger.error("[screen_capture] missing dependency: %s", missing)
            return SkillResult(
                success=False,
                error=f"{missing} not installed. Run: pip install mss Pillow",
            )
        except Exception as e:
            logger.error("[screen_capture] capture failed: %s", e, exc_info=True)
            return SkillResult(success=False, error=f"Capture failed: {e}")
