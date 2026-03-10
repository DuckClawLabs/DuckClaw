"""
DuckClaw Camera Skill — OpenCV-based camera capture.

Actions:
- snap         : Capture a frame from a camera (ASK — always requires approval)
- list_cameras : Detect available camera indices (SAFE)
- snap_analyze : Capture + send to LLM for vision analysis (ASK)

Requires: pip install duckclaw[camera]  (opencv-python)

Security:
- Tier: ASK for all capture actions — user must approve every shot
- Images are NOT saved to disk by default (returned as base64)
- Camera is opened and immediately closed after each snap (no persistent stream)
"""

import base64
import io
import logging
from typing import Optional, TYPE_CHECKING

from duckclaw.skills.base import BaseSkill, SkillPermission, SkillResult

if TYPE_CHECKING:
    from duckclaw.permissions.engine import PermissionEngine

logger = logging.getLogger(__name__)

_OPENCV_MISSING = (
    "OpenCV not installed. Run: pip install duckclaw[camera]  "
    "(i.e. pip install opencv-python)"
)


class CameraSkill(BaseSkill):
    """Capture frames from a connected camera with explicit per-shot approval."""

    name = "camera"
    description = (
        "Take a photo from your webcam or connected camera. "
        "Every capture requires your explicit approval."
    )
    version = "1.0.0"
    permissions = [SkillPermission.CAMERA]

    def __init__(self, permission_engine: "PermissionEngine"):
        super().__init__(permission_engine)
        self._llm = None  # Injected by Orchestrator for snap_analyze

    def set_llm(self, llm_router):
        """Wire LLM router for vision-enabled snap_analyze."""
        self._llm = llm_router

    # ── Entry point ────────────────────────────────────────────────────────────

    async def execute(self, action: str, params: dict) -> SkillResult:
        handlers = {
            "snap":         self._snap,
            "list_cameras": self._list_cameras,
            "snap_analyze": self._snap_analyze,
        }
        if action not in handlers:
            return SkillResult(
                success=False,
                error=f"Unknown action '{action}'. Available: {', '.join(handlers)}"
            )
        return await handlers[action](params)

    # ── Actions ────────────────────────────────────────────────────────────────

    async def _snap(self, params: dict) -> SkillResult:
        camera_index = params.get("camera_index", 0)
        quality = min(params.get("quality", 85), 95)

        allowed = await self._check(
            action_type="camera.snap",
            description=f"Take a photo from camera {camera_index}",
            details={"camera_index": camera_index},
            reversible=False,
            risk_level="medium",
        )
        if not allowed:
            return SkillResult(success=False, error="Camera capture denied by user.")

        return await self._capture_frame(camera_index, quality)

    async def _list_cameras(self, params: dict) -> SkillResult:
        """Probe camera indices 0–9 to find available cameras."""
        try:
            import cv2
        except ImportError:
            return SkillResult(success=False, error=_OPENCV_MISSING)

        available = []
        for idx in range(10):
            cap = cv2.VideoCapture(idx)
            if cap.isOpened():
                available.append(idx)
                cap.release()

        return SkillResult(
            success=True,
            data={"available_cameras": available, "count": len(available)},
            action_taken=f"Detected {len(available)} camera(s)",
        )

    async def _snap_analyze(self, params: dict) -> SkillResult:
        """Capture a frame and send to LLM for vision analysis."""
        camera_index = params.get("camera_index", 0)
        prompt = params.get("prompt", "Describe what you see in this image in detail.")
        quality = min(params.get("quality", 85), 95)

        if self._llm is None:
            return SkillResult(
                success=False,
                error="LLM not available for vision analysis."
            )

        allowed = await self._check(
            action_type="camera.snap",
            description=f"Take a photo (camera {camera_index}) and analyze it with AI",
            details={"camera_index": camera_index, "prompt": prompt},
            reversible=False,
            risk_level="medium",
        )
        if not allowed:
            return SkillResult(success=False, error="Camera capture denied by user.")

        capture_result = await self._capture_frame(camera_index, quality)
        if not capture_result.success:
            return capture_result

        b64 = capture_result.data["image_base64"]

        # Send to LLM with vision
        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ]
            analysis = await self._llm.chat(messages=messages)
            return SkillResult(
                success=True,
                data={
                    "analysis": analysis,
                    "image_base64": b64,
                    "camera_index": camera_index,
                },
                action_taken=f"Captured and analyzed camera {camera_index}",
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Vision analysis failed: {e}",
                data={"image_base64": b64},  # Return image even if analysis fails
            )

    # ── Helpers ────────────────────────────────────────────────────────────────

    async def _capture_frame(self, camera_index: int, quality: int) -> SkillResult:
        """Open camera, grab one frame, close immediately, return base64 JPEG."""
        try:
            import cv2
        except ImportError:
            return SkillResult(success=False, error=_OPENCV_MISSING)

        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            return SkillResult(
                success=False,
                error=f"Cannot open camera {camera_index}. Use list_cameras to see available cameras."
            )

        try:
            # Discard first few frames — camera often needs warmup
            for _ in range(3):
                cap.read()

            ret, frame = cap.read()
            if not ret or frame is None:
                return SkillResult(success=False, error="Failed to capture frame from camera.")

            # Convert BGR → RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Encode as JPEG via Pillow (consistent with other skills)
            try:
                from PIL import Image
                pil_img = Image.fromarray(frame_rgb)
                buf = io.BytesIO()
                pil_img.save(buf, format="JPEG", quality=quality)
                jpeg_bytes = buf.getvalue()
            except ImportError:
                # Fallback: OpenCV encode
                _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
                jpeg_bytes = buffer.tobytes()

            b64 = base64.b64encode(jpeg_bytes).decode()
            h, w = frame.shape[:2]

            return SkillResult(
                success=True,
                data={
                    "image_base64": b64,
                    "format": "jpeg",
                    "width": w,
                    "height": h,
                    "camera_index": camera_index,
                },
                action_taken=f"Captured frame from camera {camera_index} ({w}x{h})",
                metadata={"size_bytes": len(jpeg_bytes), "quality": quality},
            )
        finally:
            cap.release()
