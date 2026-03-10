"""
DuckClaw Dashboard — FastAPI web interface at localhost:8741.
Routes: / (chat), /memory, /audit, /settings, /api/*
WebSocket: /ws/chat (real-time streaming)
"""

import json
import logging
import asyncio
import collections
from typing import Optional
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from duckclaw.core.config import load_config
from duckclaw.core.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

# Template directory
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

# Global orchestrator (initialized on startup)
_orchestrator: Optional[Orchestrator] = None

# ── In-memory log ring buffer ─────────────────────────────────────────────────
# Keeps the last 500 log records in memory so /api/logs can serve them.
_LOG_BUFFER: collections.deque = collections.deque(maxlen=500)


class _BufferHandler(logging.Handler):
    """Appends formatted log records to _LOG_BUFFER."""

    LEVEL_MAP = {
        logging.DEBUG:    "debug",
        logging.INFO:     "info",
        logging.WARNING:  "warning",
        logging.ERROR:    "error",
        logging.CRITICAL: "critical",
    }

    def emit(self, record: logging.LogRecord):
        try:
            _LOG_BUFFER.append({
                "time":    self.formatTime(record, "%H:%M:%S"),
                "level":   self.LEVEL_MAP.get(record.levelno, "info"),
                "logger":  record.name,
                "message": self.format(record),
            })
        except Exception:
            pass


def _install_log_buffer(min_level: int = logging.DEBUG):
    """Attach the ring-buffer handler to the duckclaw root logger once."""
    root = logging.getLogger("duckclaw")
    for h in root.handlers:
        if isinstance(h, _BufferHandler):
            return  # already installed
    handler = _BufferHandler()
    handler.setLevel(min_level)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    root.setLevel(min_level)


def get_orchestrator() -> Orchestrator:
    if _orchestrator is None:
        raise RuntimeError("Orchestrator not initialized")
    return _orchestrator


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    global _orchestrator
    _install_log_buffer()
    config = load_config()
    _orchestrator = Orchestrator(config)
    await _orchestrator.initialize()
    logger.info("DuckClaw Dashboard ready")
    yield
    if _orchestrator:
        await _orchestrator.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title="DuckClaw",
        description="Secure personal AI assistant",
        version="0.1.0",
        lifespan=lifespan,
    )

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Mount static files
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ── Page Routes ───────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def dashboard_home(request: Request):
        return templates.TemplateResponse("chat.html", {
            "request": request,
            "page": "chat",
            "title": "Chat — DuckClaw",
        })

    @app.get("/memory", response_class=HTMLResponse)
    async def dashboard_memory(request: Request):
        orc = get_orchestrator()
        facts = orc.memory.list_facts(limit=200)
        stats = orc.memory.get_stats()
        return templates.TemplateResponse("memory.html", {
            "request": request,
            "page": "memory",
            "title": "Memory — DuckClaw",
            "facts": facts,
            "stats": stats,
        })

    @app.get("/audit", response_class=HTMLResponse)
    async def dashboard_audit(request: Request):
        orc = get_orchestrator()
        logs = orc.permissions.get_audit_log(limit=100)
        stats = orc.permissions.get_audit_stats()
        return templates.TemplateResponse("audit.html", {
            "request": request,
            "page": "audit",
            "title": "Audit Log — DuckClaw",
            "logs": logs,
            "stats": stats,
        })

    @app.get("/settings", response_class=HTMLResponse)
    async def dashboard_settings(request: Request):
        orc = get_orchestrator()
        config = orc.config
        return templates.TemplateResponse("settings.html", {
            "request": request,
            "page": "settings",
            "title": "Settings — DuckClaw",
            "config": config,
        })

    # ── API Routes ────────────────────────────────────────────────────────────

    @app.post("/api/chat")
    async def api_chat(request: Request):
        """REST chat endpoint (non-streaming)."""
        body = await request.json()
        message = body.get("message", "").strip()
        session_id = body.get("session_id", "dashboard-default")

        if not message:
            raise HTTPException(400, "Message cannot be empty")

        orc = get_orchestrator()
        result = await orc.chat(
            message=message,
            session_id=session_id,
            source="dashboard",
        )
        return JSONResponse(result)

    @app.get("/api/stats")
    async def api_stats():
        """Aggregate stats for the dashboard."""
        orc = get_orchestrator()
        return JSONResponse(orc.get_stats())

    @app.get("/api/memory/facts")
    async def api_list_facts(category: Optional[str] = None):
        orc = get_orchestrator()
        facts = orc.memory.list_facts(category=category)
        return JSONResponse({"facts": facts})

    @app.delete("/api/memory/facts/{fact_id}")
    async def api_delete_fact(fact_id: int):
        orc = get_orchestrator()
        deleted = orc.memory.delete_fact(fact_id)
        if not deleted:
            raise HTTPException(404, f"Fact {fact_id} not found")
        return JSONResponse({"deleted": fact_id})

    @app.get("/api/audit")
    async def api_audit_log(
        limit: int = 100,
        offset: int = 0,
        action_type: Optional[str] = None,
        status: Optional[str] = None,
        tier: Optional[str] = None,
        q: Optional[str] = None,
    ):
        orc = get_orchestrator()
        logs = orc.permissions.get_audit_log(
            limit=limit,
            offset=offset,
            action_type=action_type,
            status=status,
        )
        # Apply tier filter
        if tier:
            logs = [l for l in logs if l.get("tier", "").lower() == tier.lower()]
        # Apply full-text search across description and action_type
        if q:
            q_lower = q.lower()
            logs = [
                l for l in logs
                if q_lower in l.get("description", "").lower()
                or q_lower in l.get("action_type", "").lower()
                or q_lower in (l.get("source") or "").lower()
            ]
        return JSONResponse({"logs": logs, "total": len(logs)})

    @app.get("/api/audit/export")
    async def api_audit_export(fmt: str = "json"):
        orc = get_orchestrator()
        content = orc.permissions.export_audit_log(fmt=fmt)
        media_type = "application/json" if fmt == "json" else "text/csv"
        filename = f"duckclaw-audit.{fmt}"
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    @app.get("/api/llm/stats")
    async def api_llm_stats():
        orc = get_orchestrator()
        return JSONResponse({
            "stats": orc.llm.get_stats(),
            "recent_calls": orc.llm.get_recent_calls(limit=20),
        })

    @app.get("/api/skills")
    async def api_skills():
        orc = get_orchestrator()
        skills = orc.skills.list_skills() if orc.skills else []
        return JSONResponse({"skills": skills})

    @app.get("/api/logs")
    async def api_logs(level: Optional[str] = None, logger_filter: Optional[str] = None, limit: int = 200):
        """Return recent log entries from the in-memory ring buffer.

        Query params:
          level         — filter by level: debug | info | warning | error | critical
          logger_filter — substring match on logger name (e.g. "screen_capture")
          limit         — max entries to return (default 200, max 500)
        """
        entries = list(_LOG_BUFFER)
        if level:
            entries = [e for e in entries if e["level"] == level.lower()]
        if logger_filter:
            entries = [e for e in entries if logger_filter.lower() in e["logger"].lower()]
        limit = min(limit, 500)
        return JSONResponse({"logs": entries[-limit:], "total": len(entries)})

    # ── WebSocket Chat (Real-time) ─────────────────────────────────────────────

    @app.websocket("/ws/chat")
    async def websocket_chat(websocket: WebSocket):
        """
        Streaming chat via WebSocket.
        Messages: {"type": "message", "content": "...", "session_id": "..."}
        Responses: {"type": "chunk", "content": "..."} and {"type": "done"}
        """
        await websocket.accept()
        orc = get_orchestrator()

        # Set approval callback to send approval requests over WebSocket
        pending_approvals: dict[str, asyncio.Future] = {}

        async def ws_approval_callback(preview) -> bool:
            import uuid
            action_id = str(uuid.uuid4())
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            pending_approvals[action_id] = future

            await websocket.send_json({
                "type": "approval_request",
                "action_id": action_id,
                "preview": preview.to_dict(),
            })

            try:
                result = await asyncio.wait_for(future, timeout=120.0)
                return result
            except asyncio.TimeoutError:
                pending_approvals.pop(action_id, None)
                return False

        async def ws_notify_callback(message: str):
            await websocket.send_json({
                "type": "notification",
                "message": message,
            })

        orc.permissions.set_approval_callback(ws_approval_callback)
        orc.permissions.set_notify_callback(ws_notify_callback)

        try:
            while True:
                raw = await websocket.receive_json()
                msg_type = raw.get("type", "message")

                if msg_type == "message":
                    user_msg = raw.get("content", "").strip()
                    session_id = raw.get("session_id", "dashboard-ws")

                    if not user_msg:
                        continue

                    # Stream response
                    await websocket.send_json({"type": "thinking"})

                    result = await orc.chat(
                        message=user_msg,
                        session_id=session_id,
                        source="dashboard",
                    )

                    await websocket.send_json({
                        "type": "response",
                        "content": result["reply"],
                        "session_id": result["session_id"],
                    })

                elif msg_type == "approval":
                    # User approved or denied a pending action
                    action_id = raw.get("action_id")
                    approved = raw.get("approved", False)
                    if action_id in pending_approvals:
                        pending_approvals[action_id].set_result(approved)
                        pending_approvals.pop(action_id)

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            try:
                await websocket.send_json({"type": "error", "message": str(e)})
            except Exception:
                pass

    return app
