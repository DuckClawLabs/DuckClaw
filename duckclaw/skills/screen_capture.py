"""
Screen Capture Skill.
Uses `mss` library — cross-platform (macOS, Windows, Linux), zero system deps.

Every capture → Tier: ASK (explicit user approval required, every time).
Option to analyze with LLM vision immediately after capture.
"""

import base64
import io
import logging
import os
import uuid
from datetime import datetime
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
        logger.info(f"ScreenCaptureSkill called with action: {action}, params: {params}")
        dispatch = {
            "list_monitors":    self._list_monitors,
        }
        handler = self._capture_and_analyze if "capture" in action else dispatch.get(action)
        logger.info(f"Dispatching to handler: {handler.__name__ if handler else 'None'} for action: {action}")
        if not handler:
            logger.warning(f"Unknown action requested: {action}")
            return SkillResult(success=False, error=f"Unknown action: {action}")
        return await handler(params)

    async def _capture(self, params: dict) -> SkillResult:
        """Capture a screenshot. Always requires ASK approval."""
        logger.info(f"Initiating screen capture with params: {params}") 
        monitor = int(params.get("monitor", 0))
        region = params.get("region", None)  # {"top": y, "left": x, "width": w, "height": h}
        logger.info(f"Requested capture for monitor {monitor} with region: {region}")

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
        logger.info(f"User approval for screen capture: {'approved' if approved else 'denied'}")
        if not approved:
            logger.info("Screen capture denied by user.")
            return SkillResult(success=False, error="Screenshot denied by user.")

        return await self._do_capture(monitor, region)

    async def _capture_and_analyze(self, params: dict) -> SkillResult:
        """Capture screenshot and immediately analyze with LLM vision."""
        logger.info(f"Initiating screen capture and analysis with params: {params}")
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

        # Send to LLM vision — must use a vision-capable model (Groq doesn't support multimodal)
        try:
            vision_model = self._llm.get_vision_model()
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
                model=vision_model,
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
                    {"id": i, "left": m["left"], "top": m["top"],
                     "width": m["width"], "height": m["height"]}
                    for i, m in enumerate(sct.monitors)
                ]
            return SkillResult(success=True, data=monitors)
        except ImportError:
            return SkillResult(success=False, error="mss not installed. Run: pip install mss")
        except Exception as e:
            return SkillResult(success=False, error=str(e))

    @staticmethod
    def _grab_with_subprocess(cmd: list, region=None):
        """Run a CLI screenshot tool, save to temp file, return PIL Image."""
        import subprocess, tempfile
        from PIL import Image
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            result = subprocess.run(cmd + [tmp_path], capture_output=True)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.decode().strip())
            img = Image.open(tmp_path).convert("RGB")
            if region:
                img = img.crop((
                    region["left"], region["top"],
                    region["left"] + region["width"],
                    region["top"] + region["height"],
                ))
            return img
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def _do_capture(self, monitor: int = 0, region=None) -> SkillResult:
        """Internal: perform the actual screenshot capture.

        Backend priority (tried in order, first success wins):
          1. mss          — Windows / macOS / Linux X11  (pip install mss)
          2. grim         — Linux Wayland/wlroots        (apt/dnf/pacman install grim)
          3. gnome-screenshot — Linux GNOME Wayland      (usually pre-installed)
          4. spectacle    — Linux KDE Wayland            (apt install kde-spectacle)
          5. scrot        — Linux X11 fallback           (apt install scrot)
        """
        logger.info(f"Performing screen capture on monitor {monitor} with region: {region}")
        try:
            import shutil
            from PIL import Image

            img = None
            errors = []

            # ── 1. mss (Windows / macOS / Linux X11) ─────────────────────────
            try:
                import mss
                with mss.mss() as sct:
                    if region:
                        grab_region = {k: region[k] for k in ("left", "top", "width", "height")}
                    else:
                        mon_index = (
                            max(1, min(monitor + 1, len(sct.monitors) - 1))
                            if len(sct.monitors) > 1 else 0
                        )
                        grab_region = sct.monitors[mon_index]
                    raw = sct.grab(grab_region)
                    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
                    logger.info(f"Captured via mss: {grab_region}")
            except Exception as e:
                errors.append(f"mss: {e}")
                logger.debug(f"mss failed, trying next backend: {e}")

            # ── 2. grim (Wayland / wlroots: Sway, Hyprland, etc.) ────────────
            if img is None and shutil.which("grim"):
                try:
                    cmd = ["grim"]
                    if region:
                        cmd += ["-g", f"{region['left']},{region['top']} {region['width']}x{region['height']}"]
                    img = self._grab_with_subprocess(cmd)
                    logger.info("Captured via grim")
                except Exception as e:
                    errors.append(f"grim: {e}")

            # ── 3. gnome-screenshot (GNOME Wayland) ───────────────────────────
            if img is None and shutil.which("gnome-screenshot"):
                try:
                    img = self._grab_with_subprocess(["gnome-screenshot", "-f"], region)
                    logger.info("Captured via gnome-screenshot")
                except Exception as e:
                    errors.append(f"gnome-screenshot: {e}")

            # ── 4. spectacle (KDE Wayland) ────────────────────────────────────
            if img is None and shutil.which("spectacle"):
                try:
                    img = self._grab_with_subprocess(["spectacle", "-b", "-n", "-o"], region)
                    logger.info("Captured via spectacle")
                except Exception as e:
                    errors.append(f"spectacle: {e}")

            # ── 5. scrot (X11 fallback) ───────────────────────────────────────
            if img is None and shutil.which("scrot"):
                try:
                    img = self._grab_with_subprocess(["scrot"], region)
                    logger.info("Captured via scrot")
                except Exception as e:
                    errors.append(f"scrot: {e}")

            if img is None:
                platform_hint = (
                    "Install a screenshot tool:\n"
                    "  Linux - Wayland (wlroots): sudo apt install grim\n"
                    "  Linux - Wayland (GNOME):   gnome-screenshot is usually pre-installed\n"
                    "  Linux - Wayland (KDE):     sudo apt install kde-spectacle\n"
                    "  Linux - X11:               sudo apt install scrot\n"
                    "  Windows/macOS:     pip install mss"
                )
                raise RuntimeError(
                    f"All backends failed:\n" +
                    "\n".join(f"  • {e}" for e in errors) +
                    f"\n\n{platform_hint}"
                )

            w, h = img.size
            logger.info(f"Captured image size: {w}x{h}px")

            # Compress to JPEG, keep under 5MB for LLM
            buf = io.BytesIO()
            quality = 85
            img.save(buf, format="JPEG", quality=quality)
            if buf.tell() > 4_000_000:
                buf = io.BytesIO()
                img.thumbnail((1920, 1080))
                img.save(buf, format="JPEG", quality=75)
            logger.info(f"Compressed image size: {buf.tell()//1024}KB with quality={quality}")
            b64 = base64.b64encode(buf.getvalue()).decode()

            # Save to ~/.duckclaw/screen_capture/<YYYY-MM-DD>/<uuid>.jpg
            date_str = datetime.now().strftime("%Y-%m-%d")
            save_dir = os.path.expanduser(f"~/.duckclaw/screen_capture/{date_str}")
            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, f"{uuid.uuid4()}.jpg")
            with open(save_path, "wb") as f:
                f.write(buf.getvalue())
            logger.info(f"Screenshot saved: {save_path}")

            return SkillResult(
                success=True,
                data=f"Screenshot captured ({w}×{h} px, {buf.tell()//1024}KB) → {save_path}",
                action_taken="Screenshot taken",
                metadata={
                    "image_base64": b64,
                    "width": w,
                    "height": h,
                    "format": "jpeg",
                    "saved_path": save_path,
                },
            )

        except ImportError as e:
            return SkillResult(success=False, error=f"Missing dependency: {e}. Run: pip install mss Pillow")
        except Exception as e:
            logger.error(f"Screenshot capture failed: {e}")
            return SkillResult(success=False, error=f"Capture failed: {e}")
