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

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File
from typing import List as TypingList
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from duckclaw.core.config import load_config, _find_config
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


def install_log_buffer(min_level: int = logging.DEBUG):
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
    install_log_buffer()
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
        version="0.1.1",
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

    @app.get("/logs", response_class=HTMLResponse)
    async def dashboard_logs(request: Request):
        return templates.TemplateResponse("logs.html", {
            "request": request,
            "page": "logs",
            "title": "Logs — DuckClaw",
        })

    @app.get("/database", response_class=HTMLResponse)
    async def dashboard_database(request: Request):
        orc = get_orchestrator()
        stats = orc.memory.get_stats()
        return templates.TemplateResponse("database.html", {
            "request": request,
            "page": "database",
            "title": "Database — DuckClaw",
            "stats": stats,
        })

    @app.get("/settings", response_class=HTMLResponse)
    async def dashboard_settings(request: Request):
        config = load_config()
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
    async def api_delete_fact(fact_id: str):
        orc = get_orchestrator()
        deleted = orc.memory.delete_fact(fact_id)
        if not deleted:
            raise HTTPException(404, f"Fact {fact_id} not found")
        return JSONResponse({"deleted": fact_id})

    @app.get("/api/db/facts")
    async def api_db_facts(
        category: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ):
        orc = get_orchestrator()
        facts = orc.memory.list_facts(category=category, limit=limit)
        if q:
            q_lower = q.lower()
            facts = [f for f in facts if q_lower in f["fact"].lower()]
        total = len(facts)
        return JSONResponse({"facts": facts[offset:offset + limit], "total": total})

    @app.get("/api/db/conversations")
    async def api_db_conversations(
        session_id: Optional[str] = None,
        role: Optional[str] = None,
        source: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ):
        orc = get_orchestrator()
        rows = orc.memory.list_conversations(
            session_id=session_id,
            role=role,
            source=source,
            q=q,
            limit=limit,
            offset=offset,
        )
        return JSONResponse({"conversations": rows, "total": len(rows)})

    _MAX_FILES = 10
    _MAX_TOTAL_BYTES = 10 * 1024 * 1024  # 10 MB
    _ALLOWED_EXTENSIONS = {
        ".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml",
        ".toml", ".csv", ".html", ".css", ".rst", ".xml", ".sh", ".log", ".sql",
    }

    @app.post("/api/db/ingest")
    async def api_ingest_files(files: TypingList[UploadFile] = File(...)):
        if len(files) > _MAX_FILES:
            raise HTTPException(400, f"Max {_MAX_FILES} files per upload")

        results = []
        total_bytes = 0

        for f in files:
            suffix = Path(f.filename or "").suffix.lower()
            if suffix not in _ALLOWED_EXTENSIONS:
                raise HTTPException(400, f"Unsupported file type: {suffix or '(none)'}. Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}")

            raw = await f.read()
            total_bytes += len(raw)
            if total_bytes > _MAX_TOTAL_BYTES:
                raise HTTPException(400, "Total upload size exceeds 10 MB limit")

            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise HTTPException(400, f"{f.filename}: file is not valid UTF-8 text")

            orc = get_orchestrator()
            chunks = orc.memory.ingest_document(
                filename=f.filename or "unnamed",
                content=content,
                size_bytes=len(raw),
            )
            results.append({"filename": f.filename, "size_bytes": len(raw), "chunks": chunks})

        return JSONResponse({"ingested": results})

    @app.get("/api/db/ingested")
    async def api_list_ingested():
        orc = get_orchestrator()
        files = orc.memory.list_ingested_files()
        return JSONResponse({"files": files})

    @app.delete("/api/db/ingested/{file_id}")
    async def api_delete_ingested(file_id: int):
        orc = get_orchestrator()
        deleted = orc.memory.delete_ingested_file(file_id)
        if not deleted:
            raise HTTPException(404, f"Ingested file {file_id} not found")
        return JSONResponse({"deleted": file_id})

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

    @app.get("/api/permissions/rules")
    async def api_get_permission_rules():
        """Return all action permission rules with their current and default tiers."""
        orc = get_orchestrator()
        return JSONResponse({"rules": orc.permissions.get_all_rules()})

    @app.post("/api/permissions/rules")
    async def api_set_permission_rule(request: Request):
        """Update the tier for a single action type."""
        body = await request.json()
        action_type = body.get("action_type", "").strip()
        tier = body.get("tier", "").strip()
        if not action_type or not tier:
            raise HTTPException(400, "action_type and tier are required")
        orc = get_orchestrator()
        ok = orc.permissions.set_rule(action_type, tier)
        if not ok:
            raise HTTPException(400, f"Cannot update rule for '{action_type}' — it is hardcoded or the tier is invalid")
        return JSONResponse({"updated": action_type, "tier": tier})

    @app.post("/api/permissions/rules/reset")
    async def api_reset_permission_rule(request: Request):
        """Reset a single action type back to its factory default tier."""
        body = await request.json()
        action_type = body.get("action_type", "").strip()
        if not action_type:
            raise HTTPException(400, "action_type is required")
        orc = get_orchestrator()
        orc.permissions.reset_rule(action_type)
        # Return the new (factory default) tier
        factory = next(
            (r for r in orc.permissions.get_all_rules() if r["action_type"] == action_type),
            None,
        )
        return JSONResponse({"reset": action_type, "tier": factory["tier"] if factory else "ask"})

    @app.post("/api/settings")
    async def api_save_settings(request: Request):
        """Save settings to duckclaw.yaml. Restart required to apply."""
        import yaml

        body = await request.json()

        config_path = _find_config()
        if config_path is None:
            raise HTTPException(404, "Config file not found. Run duckclaw setup first.")

        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}

        # Apply changes from body — only known fields
        if "llm" in body:
            raw.setdefault("llm", {})
            llm = body["llm"]
            if "model" in llm:
                raw["llm"]["model"] = str(llm["model"]).strip()
            if "reasoning_model" in llm:
                raw["llm"]["reasoning_model"] = str(llm["reasoning_model"]).strip()
            if "vision_model" in llm:
                raw["llm"]["vision_model"] = str(llm["vision_model"]).strip()
            if "audio_model" in llm:
                raw["llm"]["audio_model"] = str(llm["audio_model"]).strip()
            if "max_tokens" in llm:
                raw["llm"]["max_tokens"] = int(llm["max_tokens"])
            if "temperature" in llm:
                raw["llm"]["temperature"] = float(llm["temperature"])
            if "cost_tracking" in llm:
                raw["llm"]["cost_tracking"] = bool(llm["cost_tracking"])

        if "permissions" in body:
            raw.setdefault("permissions", {})
            perms = body["permissions"]
            if "default_tier" in perms and perms["default_tier"] in ("safe", "notify", "ask", "block"):
                raw["permissions"]["default_tier"] = perms["default_tier"]
            if "audit_log" in perms:
                raw["permissions"]["audit_log"] = bool(perms["audit_log"])
            if "notify_on_safe" in perms:
                raw["permissions"]["notify_on_safe"] = bool(perms["notify_on_safe"])

        if "security" in body:
            raw.setdefault("security", {})
            sec = body["security"]
            if "prompt_injection_defense" in sec:
                raw["security"]["prompt_injection_defense"] = bool(sec["prompt_injection_defense"])
            if "context_isolation" in sec:
                raw["security"]["context_isolation"] = bool(sec["context_isolation"])

        if "dashboard" in body:
            raw.setdefault("dashboard", {})
            dash = body["dashboard"]
            if "port" in dash:
                raw["dashboard"]["port"] = int(dash["port"])

        with open(config_path, "w") as f:
            yaml.dump(raw, f, default_flow_style=False, allow_unicode=True)
        return JSONResponse({"saved": True, "message": "Settings saved. Restart DuckClaw to apply."})

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
    async def api_logs(
        level: Optional[str] = None,
        logger_filter: Optional[str] = None,
        q: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 200,
    ):
        """Return recent log entries from the in-memory ring buffer.

        Query params:
          level         — filter by level: debug | info | warning | error | critical
          logger_filter — substring match on logger name (e.g. "orchestrator")
          q             — full-text search across message + logger
          start_time    — HH:MM:SS lower bound (inclusive)
          end_time      — HH:MM:SS upper bound (inclusive)
          limit         — max entries to return (default 200, max 500)
        """
        entries = list(_LOG_BUFFER)
        if level:
            entries = [e for e in entries if e["level"] == level.lower()]
        if logger_filter:
            entries = [e for e in entries if logger_filter.lower() in e["logger"].lower()]
        if q:
            q_lower = q.lower()
            entries = [e for e in entries if q_lower in e["message"].lower() or q_lower in e["logger"].lower()]
        if start_time:
            entries = [e for e in entries if e["time"] >= start_time]
        if end_time:
            entries = [e for e in entries if e["time"] <= end_time]
        limit = min(limit, 500)
        return JSONResponse({"logs": entries[-limit:], "total": len(entries)})

    @app.get("/api/logs/file")
    async def api_logs_file(
        level: Optional[str] = None,
        logger_filter: Optional[str] = None,
        q: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ):
        """Return log entries parsed from ~/.duckclaw/duckclaw.log.

        Survives restarts — reads the actual log file on disk.
        Same filter params as /api/logs plus offset for pagination.
        """
        import re
        log_path = Path.home() / ".duckclaw" / "duckclaw.log"
        if not log_path.exists():
            return JSONResponse({"logs": [], "total": 0, "source": "file", "file": str(log_path)})

        # Format: HH:MM:SS [LEVEL   ] logger.name — message
        _LINE_RE = re.compile(
            r"^(\d{2}:\d{2}:\d{2}\.\d{3}) \[\s*([A-Z]+)\s*\] ([\w.\-]+) — (.*)$"
        )
        LEVEL_MAP = {
            "DEBUG":    "debug",
            "INFO":     "info",
            "WARNING":  "warning",
            "ERROR":    "error",
            "CRITICAL": "critical",
        }

        entries = []
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                for raw_line in f:
                    line = raw_line.rstrip()
                    m = _LINE_RE.match(line)
                    if not m:
                        # continuation line — append to last entry's message
                        if entries:
                            entries[-1]["message"] += " " + line.strip()
                        continue
                    time_str, lvl_raw, log_name, msg = m.groups()
                    entries.append({
                        "time":    time_str,
                        "level":   LEVEL_MAP.get(lvl_raw.strip(), lvl_raw.strip().lower()),
                        "logger":  log_name,
                        "message": msg,
                    })
        except OSError as exc:
            raise HTTPException(500, f"Cannot read log file: {exc}")

        # Apply filters
        if level:
            entries = [e for e in entries if e["level"] == level.lower()]
        if logger_filter:
            entries = [e for e in entries if logger_filter.lower() in e["logger"].lower()]
        if q:
            q_lower = q.lower()
            entries = [e for e in entries if q_lower in e["message"].lower() or q_lower in e["logger"].lower()]
        if start_time:
            entries = [e for e in entries if e["time"] >= start_time]
        if end_time:
            entries = [e for e in entries if e["time"] <= end_time]

        total = len(entries)
        limit = min(limit, 2000)
        # Return most-recent entries (last N after offset from end)
        sliced = entries[-(limit + offset):][:limit] if offset == 0 else entries[-(limit + offset):-offset]
        return JSONResponse({"logs": sliced, "total": total, "source": "file", "file": str(log_path)})

    # ── WebSocket Chat (Real-time) ─────────────────────────────────────────────

    @app.websocket("/ws/chat")
    async def websocket_chat(websocket: WebSocket):
        """
        Streaming chat via WebSocket.
        Messages: {"type": "message", "content": "...", "session_id": "..."}
        Responses: {"type": "chunk", "content": "..."} and {"type": "done"}
        """
        logger.info("WebSocket connection established")
        await websocket.accept()
        logger.info("WebSocket connection accepted")
        orc = get_orchestrator()

        # Set approval callback to send approval requests over WebSocket
        pending_approvals: dict[str, asyncio.Future] = {}


        async def ws_approval_callback(preview) -> bool:
            logger.info(f"Permission check requires user approval: {preview.description} (type={preview.action_type}, risk={preview.risk_level})")
            import uuid
            action_id = str(uuid.uuid4())
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            pending_approvals[action_id] = future

            await websocket.send_json({
                "type": "approval_request",
                "action_id": action_id,
                "preview": preview.to_dict(),
            })
            logger.info(f"Sent approval request to client: {preview.description} (action_id={action_id})")

            try:
                result = await asyncio.wait_for(future, timeout=120.0)
                logger.info(f"Received user response for action_id={action_id}: {'approved' if result else 'denied'}")
                return result
            except asyncio.TimeoutError:
                pending_approvals.pop(action_id, None)
                logger.warning(f"Approval request timed out for action_id={action_id}")
                return False

        async def ws_notify_callback(message: str):
            logger.info(f"Sending notification to client: {message}")
            await websocket.send_json({
                "type": "notification",
                "message": message,
            })

        logger.info("Setting WebSocket approval and notify callbacks")
        orc.permissions.set_approval_callback(ws_approval_callback)
        logger.info("Approval callback set. Setting notify callback.")
        orc.permissions.set_notify_callback(ws_notify_callback)

        try:
            while True:
                raw = await websocket.receive_json()
                msg_type = raw.get("type", "message")
                logger.info(f"Received WebSocket message of type '{msg_type}' with content: {raw}")

                if msg_type == "message":
                    user_msg = raw.get("content", "").strip()
                    session_id = raw.get("session_id", "dashboard-ws")
                    logger.info(f"Processing chat message for session_id={session_id}: {user_msg}")
                    if not user_msg:
                        continue

                    await websocket.send_json({"type": "thinking"})

                    # Run chat as a background task so the receive loop stays alive
                    # to handle incoming approval messages while orc.chat() is waiting.
                    async def _run_chat(msg: str, sid: str):
                        try:
                            result = await orc.chat(message=msg, session_id=sid, source="dashboard")
                            ws_msg = {
                                "type": "response",
                                "content": result["reply"],
                                "session_id": result["session_id"],
                            }
                            if result.get("image_base64"):
                                ws_msg["image_base64"] = result["image_base64"]
                            try:
                                await websocket.send_json(ws_msg)
                            except (RuntimeError, WebSocketDisconnect):
                                pass
                        except Exception as e:
                            logger.error(f"Chat task error: {e}")
                            try:
                                await websocket.send_json({"type": "error", "message": str(e)})
                            except (RuntimeError, WebSocketDisconnect):
                                pass

                    asyncio.create_task(_run_chat(user_msg, session_id))

                elif msg_type == "approval":
                    # User approved or denied a pending action
                    action_id = raw.get("action_id")
                    approved = raw.get("approved", False)
                    logger.info(f"Received approval response from client for action_id={action_id}: {'approved' if approved else 'denied'}")
                    if action_id in pending_approvals:
                        pending_approvals[action_id].set_result(approved)
                        pending_approvals.pop(action_id)
                        logger.info(f"Set result for pending approval action_id={action_id}")

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            try:
                await websocket.send_json({"type": "error", "message": str(e)})
            except Exception:
                pass

    return app
