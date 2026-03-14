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
import time
import numpy as np
import logging
from typing import Optional, TYPE_CHECKING

from fastapi import params

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
        logger.info("CameraSkill initialized with permissions: %s", self.permissions)
        self._llm = None  # Injected by Orchestrator for snap_analyze

    def set_llm(self, llm_router):
        """Wire LLM router for vision-enabled snap_analyze."""
        self._llm = llm_router
        logger.info("CameraSkill LLM router set for vision analysis: %s", llm_router.config.model)

    # ── Entry point ────────────────────────────────────────────────────────────

    async def execute(self, action: str, params: dict) -> SkillResult:
        handlers = {
            "snap":         self._snap,
            "list_cameras": self._list_cameras,
            "snap_analyze": self._snap_analyze,
        }
        logger.info(f"CameraSkill execute called with action: {action}, params: {params}")
        return await handlers.get(action, self._snap)(params)

    # ── Actions ────────────────────────────────────────────────────────────────

    async def _snap(self, params: dict) -> SkillResult:
        camera_index = params.get("camera_index", 0)
        quality = min(params.get("quality", 85), 95)
        logger.info(f"CameraSkill snap requested for camera_index={camera_index}, quality={quality}")

        allowed = await self._check(
            action_type="camera.snap",
            description=f"Take a photo from camera {camera_index}",
            details={"camera_index": camera_index},
            reversible=False,
            risk_level="high",
        )
        logger.info(f"CameraSkill snap permission result: {'allowed' if allowed else 'denied'}")
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

        # success=True,
        # data=f"Picture captured successfully and stored at {save_path}",
        # action_taken=f"Captured frame from camera {camera_index} ({w}x{h}) and saved to {save_path}",
        # metadata={
        #     "size_bytes": len(jpeg_bytes),
        #     "quality": quality,
        #     "image_base64": b64,
        #     "saved_path": str(save_path),
        #     "filename": f"{name}.jpeg",
        #     "directory": str(base_dir),
        #     "format": "jpeg",
        #     "width": w,
        #     "height": h,
        #     "camera_index": camera_index,
        # }
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

        b64 = capture_result.metadata["image_base64"]

        # Send to LLM with vision
        ANALYSIS_PROMPT = (
            "You are an AI assistant with vision capabilities. Do details Analysis the provided image and answer the user's prompt is questionary.\n\n"
            "User's prompt: {prompt}\n\n"
        )
        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                        {"type": "text", "text": ANALYSIS_PROMPT},
                    ],
                }
            ]
            analysis = await self._llm.chat(messages=messages)
            return SkillResult(
                success=True,
                data=analysis,
                action_taken=f"Captured and analyzed camera {camera_index}",
                metadata=capture_result.metadata,
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
            import sys
        except ImportError:
            return SkillResult(success=False, error=_OPENCV_MISSING)

        # Cross-platform backend selection
        if sys.platform.startswith("win"):
            backend = cv2.CAP_DSHOW
        elif sys.platform.startswith("darwin"):
            backend = cv2.CAP_AVFOUNDATION
        else:
            backend = cv2.CAP_V4L2

        cap = cv2.VideoCapture(camera_index, backend)

        if not cap.isOpened():
            return SkillResult(
                success=False,
                error=f"Cannot open camera {camera_index}. Use list_cameras to see available cameras."
            )

        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        time.sleep(0.5)

        try:
            # Camera warmup
            frame = None
            start = time.time()

            # warmup camera stream
            while time.time() - start < 2.0:  # 2 seconds warmup
                ret, f = cap.read()
                if not ret or f is None:
                    continue

                # discard black frames
                if np.mean(f) < 5:
                    continue

                frame = f
                break

            if frame is None:
                return SkillResult(
                    success=False,
                    error="Camera returned only empty/black frames."
                )

            # Convert BGR → RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            import os
            from pathlib import Path
            from datetime import datetime

            name = datetime.now().strftime("capture_%Y%m%d_%H%M%S")

            base_dir = Path.home() / ".duckclaw" / "camera"
            base_dir.mkdir(parents=True, exist_ok=True)

            save_path = base_dir / f"{name}.jpeg"

            try:
                from PIL import Image

                pil_img = Image.fromarray(frame_rgb)
                buf = io.BytesIO()
                pil_img.save(buf, format="JPEG", quality=quality)
                jpeg_bytes = buf.getvalue()

                # persist to disk
                with open(save_path, "wb") as f:
                    f.write(jpeg_bytes)

            except ImportError:
                # OpenCV fallback
                _, buffer = cv2.imencode(
                    ".jpg",
                    frame,
                    [cv2.IMWRITE_JPEG_QUALITY, quality]
                )
                jpeg_bytes = buffer.tobytes()

                with open(save_path, "wb") as f:
                    f.write(jpeg_bytes)

            b64 = base64.b64encode(jpeg_bytes).decode()

            h, w = frame.shape[:2]

            return SkillResult(
                success=True,
                data=f"Picture captured successfully and stored at {save_path}",
                action_taken=f"Captured frame from camera {camera_index} ({w}x{h}) and saved to {save_path}",
                metadata={
                    "size_bytes": len(jpeg_bytes),
                    "quality": quality,
                    "image_base64": b64,
                    "saved_path": str(save_path),
                    "filename": f"{name}.jpeg",
                    "directory": str(base_dir),
                    "format": "jpeg",
                    "width": w,
                    "height": h,
                    "camera_index": camera_index,
                }
            )
        finally:
            cap.release()
