"""
Scheduler Skill — APScheduler for background/proactive tasks.
Adding a schedule → Tier: ASK (user must approve recurring tasks).
Background tasks default to Tier: NOTIFY (inform, don't act without approval).
"""

import asyncio
import json as _json
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from duckclaw.skills.base import BaseSkill, SkillPermission, SkillResult

logger = logging.getLogger(__name__)

# Global scheduler instance (shared across skills)
_scheduler = None
_notify_callback: Optional[Callable] = None
_memory_store = None        # set via set_memory_store() for job persistence
_orchestrator = None        # set via set_orchestrator() for skill job execution
_active_sessions: dict[str, Callable] = {}  # session_id → ws push callback


def get_scheduler():
    global _scheduler
    if _scheduler is None:
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            _scheduler = AsyncIOScheduler(timezone="UTC")
            _scheduler.start()
            logger.info("APScheduler started")
        except ImportError:
            logger.warning("APScheduler not installed. Scheduler skill disabled.")
    return _scheduler


def set_notification_callback(callback: Callable):
    """Set how scheduled notifications reach the user."""
    global _notify_callback
    _notify_callback = callback


def set_memory_store(store) -> None:
    """Wire up the memory store for job persistence across restarts."""
    global _memory_store
    _memory_store = store


def set_orchestrator(orc) -> None:
    """Wire the orchestrator so skill jobs can execute skills and save results."""
    global _orchestrator
    _orchestrator = orc


def register_session_callback(session_id: str, callback: Callable) -> None:
    """Register a WebSocket push callback for a session (called on WS connect)."""
    _active_sessions[session_id] = callback


def unregister_session_callback(session_id: str) -> None:
    """Remove session callback (called on WS disconnect)."""
    _active_sessions.pop(session_id, None)


def _persist_job(job_id: str, trigger_type: str, trigger_data: dict, message: str) -> None:
    if _memory_store:
        try:
            _memory_store.save_scheduled_job(job_id, trigger_type, trigger_data, message)
        except Exception as e:
            logger.warning(f"Failed to persist job {job_id}: {e}")


def _persist_skill_job(
    job_id: str, trigger_type: str, trigger_data: dict, label: str,
    session_id: str, skill_name: str, skill_action: str, skill_params: str,
) -> None:
    if _memory_store:
        try:
            _memory_store.save_scheduled_job(
                job_id, trigger_type, trigger_data, label,
                session_id=session_id, skill_name=skill_name,
                skill_action=skill_action, skill_params=skill_params,
            )
        except Exception as e:
            logger.warning(f"Failed to persist skill job {job_id}: {e}")


def _unpersist_job(job_id: str) -> None:
    if _memory_store:
        try:
            _memory_store.delete_scheduled_job(job_id)
        except Exception as e:
            logger.warning(f"Failed to remove persisted job {job_id}: {e}")


async def _fire_reminder(message: str, job_id: str):
    """Called when a recurring (cron) job fires — does NOT remove from DB."""
    if _notify_callback:
        try:
            await _notify_callback(f"⏰ Reminder: {message}")
        except Exception as e:
            logger.error(f"Failed to send reminder notification: {e}")
    else:
        logger.info(f"Scheduled reminder fired (no callback): {message}")


async def _fire_once_reminder(message: str, job_id: str):
    """Called when a one-shot (date) job fires — removes itself from DB."""
    _unpersist_job(job_id)
    await _fire_reminder(message, job_id)


async def _fire_skill_job(
    session_id: str, skill_name: str, action: str, params_json: str, job_id: str
):
    """Execute a skill, save the result to the session, and push live if the session is open."""
    if _orchestrator is None:
        logger.warning(f"Skill job {job_id} fired but orchestrator not set — skipping")
        return
    try:
        params = _json.loads(params_json) if params_json else {}
        result = await _orchestrator.run_scheduled_skill(session_id, skill_name, action, params)
        # Push live to the UI if the session is currently open
        callback = _active_sessions.get(session_id)
        if callback:
            try:
                await callback(result)
            except Exception as e:
                logger.warning(f"Live push to session {session_id} failed: {e}")
    except Exception as e:
        logger.error(f"Skill job {job_id} ({skill_name}.{action}) failed: {e}")


def restore_jobs(memory_store) -> None:
    """
    Re-schedule all persisted jobs from SQLite after a server restart.
    Call this once during startup after the memory store is ready.
    """
    set_memory_store(memory_store)
    scheduler = get_scheduler()
    if not scheduler:
        return

    jobs = memory_store.load_scheduled_jobs()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    restored = 0
    for job in jobs:
        job_id       = job["id"]
        trigger_type = job["trigger_type"]
        trigger_data = job["trigger_data"]
        message      = job["message"]
        skill_name   = job.get("skill_name", "")
        skill_action = job.get("skill_action", "")
        skill_params = job.get("skill_params", "")
        session_id   = job.get("session_id", "")
        is_skill_job = bool(skill_name and skill_action and session_id)
        try:
            if is_skill_job:
                # Recurring skill jobs (interval or cron)
                if trigger_type == "interval":
                    from apscheduler.triggers.interval import IntervalTrigger
                    seconds = trigger_data.get("seconds", 60)
                    scheduler.add_job(
                        _fire_skill_job, IntervalTrigger(seconds=seconds),
                        args=[session_id, skill_name, skill_action, skill_params, job_id],
                        id=job_id, replace_existing=True,
                    )
                elif trigger_type == "cron":
                    scheduler.add_job(
                        _fire_skill_job, "cron",
                        minute=trigger_data.get("minute", "*"),
                        hour=trigger_data.get("hour", "*"),
                        day=trigger_data.get("day", "*"),
                        month=trigger_data.get("month", "*"),
                        day_of_week=trigger_data.get("day_of_week", "*"),
                        args=[session_id, skill_name, skill_action, skill_params, job_id],
                        id=job_id, replace_existing=True,
                    )
            else:
                # Plain reminder jobs
                if trigger_type == "date":
                    run_date = datetime.fromisoformat(trigger_data["run_date"])
                    run_date_naive = run_date.replace(tzinfo=None)
                    # Discard stale one-shot jobs older than 1 hour
                    if (now - run_date_naive).total_seconds() > 3600:
                        memory_store.delete_scheduled_job(job_id)
                        logger.info(f"Discarded stale job {job_id} (was due {run_date_naive})")
                        continue
                    scheduler.add_job(
                        _fire_once_reminder, "date",
                        run_date=run_date_naive,
                        args=[message, job_id],
                        id=job_id, replace_existing=True,
                    )
                elif trigger_type == "cron":
                    scheduler.add_job(
                        _fire_reminder, "cron",
                        minute=trigger_data.get("minute", "*"),
                        hour=trigger_data.get("hour", "*"),
                        day=trigger_data.get("day", "*"),
                        month=trigger_data.get("month", "*"),
                        day_of_week=trigger_data.get("day_of_week", "*"),
                        args=[message, job_id],
                        id=job_id, replace_existing=True,
                    )
            restored += 1
            logger.info(f"Restored job {job_id} ({trigger_type}, skill={is_skill_job})")
        except Exception as e:
            logger.warning(f"Failed to restore job {job_id}: {e}")

    logger.info(f"Scheduler restore complete: {restored}/{len(jobs)} jobs active")


class SchedulerSkill(BaseSkill):
    name = "scheduler"
    description = "Schedule reminders, cron jobs, and recurring background tasks."
    version = "1.0.0"
    permissions = [SkillPermission.SCHEDULE]  # Tier: ASK

    async def execute(self, action: str, params: dict) -> SkillResult:
        dispatch = {
            "remind_in":          self._remind_in,
            "remind_at":          self._remind_at,
            "add_cron":           self._add_cron,
            "list_jobs":          self._list_jobs,
            "remove_job":         self._remove_job,
            "morning_brief":      self._morning_brief,
            "schedule_skill_job": self._schedule_skill_job,
        }
        handler = dispatch.get(action, self._remind_in)
        if not handler:
            return SkillResult(success=False, error=f"Unknown scheduler action: {action}")
        logger.info(f"Executing scheduler action: {action} with params: {params}")
        return await handler(params)

    async def _remind_in(self, params: dict) -> SkillResult:
        """Set a reminder N minutes/hours from now."""
        minutes = int(params.get("minutes", 0))
        hours = int(params.get("hours", 0))
        message = params.get("message", "Reminder!")
        total_minutes = hours * 60 + minutes

        if total_minutes <= 0:
            return SkillResult(success=False, error="minutes or hours must be > 0")
        logger.info(f"Setting reminder in {total_minutes} minutes with message: '{message}'")
        approved = await self._check(
            "scheduler.add",
            f"Set reminder in {total_minutes} min: '{message}'",
            details={"minutes": total_minutes, "message": message},
        )
        if not approved:
            return SkillResult(success=False, error="Reminder creation denied.")
        logger.info(f"Permission check passed for reminder in {total_minutes} minutes, proceeding to schedule")
        scheduler = get_scheduler()
        if not scheduler:
            return SkillResult(success=False, error="APScheduler not available. Install: pip install apscheduler")
        
        from datetime import timedelta
        run_at = datetime.now() + timedelta(minutes=total_minutes)
        job_id = f"reminder_{run_at.strftime('%Y%m%d%H%M%S')}"

        scheduler.add_job(
            _fire_once_reminder,
            "date",
            run_date=run_at,
            args=[message, job_id],
            id=job_id,
            replace_existing=True,
        )
        _persist_job(job_id, "date", {"run_date": run_at.isoformat()}, message)

        time_str = f"{hours}h {minutes}m" if hours else f"{minutes}m"
        logger.info(f"Scheduled reminder with job_id {job_id} to fire at {run_at.isoformat()} (in {time_str})")
        remind_sr = SkillResult(
            success=True,
            data=f"⏰ Reminder set for {time_str} from now: '{message}'",
            action_taken=f"Reminder scheduled: {message}",
            metadata={"job_id": job_id, "fires_at": run_at.isoformat()},
        )
        logger.info(f"Reminder action returning SkillResult: {remind_sr}")
        return remind_sr

    async def _remind_at(self, params: dict) -> SkillResult:
        """Set a reminder at a specific time (ISO 8601 or HH:MM)."""
        time_str = params.get("time", "")
        message = params.get("message", "Reminder!")

        if not time_str:
            return SkillResult(success=False, error="time is required (e.g. '14:30' or '2025-03-15T14:30:00')")

        logger.info(f"Setting reminder at {time_str} with message: '{message}'")
        # Parse time
        try:
            if "T" in time_str or "-" in time_str:
                run_at = datetime.fromisoformat(time_str)
            else:
                h, m = map(int, time_str.split(":"))
                run_at = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
                if run_at < datetime.now():
                    from datetime import timedelta
                    run_at += timedelta(days=1)  # Next occurrence
            logger.info(f"Parsed reminder time: {run_at.isoformat()}")
        except ValueError:
            return SkillResult(success=False, error=f"Cannot parse time: '{time_str}'")

        approved = await self._check(
            "scheduler.add",
            f"Set reminder at {run_at.strftime('%H:%M')}: '{message}'",
            details={"time": run_at.isoformat(), "message": message},
        )
        logger.info(f"Permission check for reminder at {run_at.strftime('%H:%M')} returned: {approved}")
        if not approved:
            return SkillResult(success=False, error="Reminder creation denied.")

        scheduler = get_scheduler()
        if not scheduler:
            return SkillResult(success=False, error="APScheduler not available.")

        logger.info(f"Scheduling reminder with message: '{message}' to fire at {run_at.isoformat()}")
        job_id = f"remind_at_{run_at.strftime('%Y%m%d%H%M')}"
        scheduler.add_job(
            _fire_once_reminder, "date",
            run_date=run_at, args=[message, job_id], id=job_id, replace_existing=True,
        )
        _persist_job(job_id, "date", {"run_date": run_at.isoformat()}, message)
        remind_sr = SkillResult(
            success=True,
            data=f"⏰ Reminder set for {run_at.strftime('%H:%M on %b %d')}: '{message}'",
            action_taken=f"Reminder at {run_at.strftime('%H:%M')}",
        )
        logger.info(f"Reminder action returning SkillResult: {remind_sr}")
        return remind_sr

    async def _add_cron(self, params: dict) -> SkillResult:
        """Add a recurring cron job."""
        cron_expr = params.get("cron", "")  # e.g. "0 8 * * *" = daily at 8am
        message = params.get("message", "")
        label = params.get("label", "Scheduled task")
        logger.info(f"Adding cron job with expression: {cron_expr}, message: '{message}', label: '{label}'")
        if not cron_expr:
            logger.warning("Cron expression is required for adding a cron job.")
            return SkillResult(success=False, error="cron expression required (e.g. '0 8 * * *')")

        approved = await self._check(
            "scheduler.add",
            f"Add recurring task: '{label}' ({cron_expr})",
            details={"cron": cron_expr, "label": label},
        )
        logger.info(f"Permission check for adding cron job '{label}' with expression '{cron_expr}' returned: {approved}")
        if not approved:
            logger.warning(f"Cron job creation denied for label: '{label}' with expression: '{cron_expr}'")
            return SkillResult(success=False, error="Cron job creation denied.")

        scheduler = get_scheduler()
        if not scheduler:
            return SkillResult(success=False, error="APScheduler not available.")

        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return SkillResult(success=False, error="Cron must be 5 fields: minute hour day month weekday")

        minute, hour, day, month, dow = parts
        job_id = f"cron_{label.replace(' ', '_').lower()}"
        logger.info(f"Scheduling cron job with ID {job_id} for label '{label}' with cron expression: {cron_expr}")
        scheduler.add_job(
            _fire_reminder, "cron",
            minute=minute, hour=hour, day=day, month=month, day_of_week=dow,
            args=[message or label, job_id], id=job_id, replace_existing=True,
        )
        _persist_job(job_id, "cron", {
            "minute": minute, "hour": hour, "day": day,
            "month": month, "day_of_week": dow,
        }, message or label)

        cron_sr = SkillResult(
            success=True,
            data=f"✅ Recurring task '{label}' added (cron: {cron_expr})",
            action_taken=f"Cron job added: {label}",
        )
        logger.info(f"Cron job action returning SkillResult: {cron_sr}")
        return cron_sr  

    async def _list_jobs(self, params: dict) -> SkillResult:
        """List all scheduled jobs."""
        scheduler = get_scheduler()
        if not scheduler:
            logger.warning("Attempted to list scheduled jobs, but no scheduler is running.")
            return SkillResult(success=True, data="No scheduler running.")

        jobs = scheduler.get_jobs()
        if not jobs:
            logger.info("No scheduled jobs found when listing jobs.")
            return SkillResult(success=True, data="No scheduled tasks.")

        lines = ["Scheduled tasks:\n"]
        for job in jobs:
            logger.info(f"Found scheduled job: id={job.id}, next_run_time={job.next_run_time}, trigger={job.trigger}")
            next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M") if job.next_run_time else "N/A"
            lines.append(f"• {job.id}\n  Next run: {next_run}")

        list_sr = SkillResult(success=True, data="\n".join(lines))
        logger.info(f"List jobs action returning SkillResult: {list_sr}")
        return list_sr

    async def _remove_job(self, params: dict) -> SkillResult:
        """Remove a scheduled job by ID."""
        job_id = params.get("job_id", "")
        if not job_id:
            return SkillResult(success=False, error="job_id required")

        scheduler = get_scheduler()
        if not scheduler:
            return SkillResult(success=False, error="No scheduler running.")

        try:
            scheduler.remove_job(job_id)
            _unpersist_job(job_id)
            remove_sr = SkillResult(success=True, data=f"Removed job: {job_id}")
            logger.info(f"Remove job action returning SkillResult: {remove_sr}")
            return remove_sr
        except Exception as e:
            return SkillResult(success=False, error=str(e))

    async def _morning_brief(self, params: dict) -> SkillResult:
        """Set up a daily morning briefing."""
        time_str = params.get("time", "08:00")
        approved = await self._check(
            "scheduler.add",
            f"Set up daily morning briefing at {time_str}",
            details={"time": time_str},
        )
        if not approved:
            return SkillResult(success=False, error="Morning briefing setup denied.")

        h, m = map(int, time_str.split(":"))
        scheduler = get_scheduler()
        if not scheduler:
            return SkillResult(success=False, error="APScheduler not available.")

        scheduler.add_job(
            _fire_reminder, "cron",
            hour=h, minute=m,
            args=["Good morning! Ready for your daily briefing?", "morning_brief"],
            id="morning_brief", replace_existing=True,
        )
        _persist_job("morning_brief", "cron", {"minute": str(m), "hour": str(h),
                                                "day": "*", "month": "*", "day_of_week": "*"},
                     "Good morning! Ready for your daily briefing?")

        morning_brief_sr = SkillResult(
            success=True,
            data=f"☀️ Daily morning briefing set for {time_str}",
            action_taken="Morning briefing scheduled",
        )
        logger.info(f"Morning briefing action returning SkillResult: {morning_brief_sr}")
        return morning_brief_sr

    async def _schedule_skill_job(self, params: dict) -> SkillResult:
        """
        Schedule a recurring skill execution tied to a session.

        Required params:
          session_id       — the chat session to save results into
          skill_name       — e.g. "camera" or "screen_capture"
          action           — e.g. "snap_analyze" or "capture_and_analyze"
          interval_seconds — run every N seconds  (use this OR cron)
          cron             — 5-field cron expression (use this OR interval_seconds)

        Optional:
          skill_params     — dict passed straight to the skill
          label            — human-readable name shown in list_jobs
        """
        session_id       = params.get("session_id", "")
        skill_name       = params.get("skill_name", "")
        action           = params.get("action", "")
        skill_params     = params.get("skill_params", {})
        interval_seconds = int(params.get("interval_seconds", 0))
        cron_expr        = params.get("cron", "")
        label            = params.get("label", f"{skill_name}.{action}")

        if not session_id or not skill_name or not action:
            return SkillResult(success=False, error="session_id, skill_name, and action are required")
        if not interval_seconds and not cron_expr:
            return SkillResult(success=False, error="interval_seconds or cron required")

        approved = await self._check(
            "scheduler.add",
            f"Run '{label}' every {interval_seconds}s in this session" if interval_seconds
            else f"Run '{label}' on schedule ({cron_expr}) in this session",
            details={"skill": skill_name, "action": action,
                     "interval_seconds": interval_seconds, "cron": cron_expr},
        )
        if not approved:
            return SkillResult(success=False, error="Skill job creation denied.")

        scheduler = get_scheduler()
        if not scheduler:
            return SkillResult(success=False, error="APScheduler not available. Install: pip install apscheduler")

        params_json = _json.dumps(skill_params)
        job_id = f"skill_{skill_name}_{action}_{session_id[:8]}"

        if interval_seconds:
            from apscheduler.triggers.interval import IntervalTrigger
            scheduler.add_job(
                _fire_skill_job, IntervalTrigger(seconds=interval_seconds),
                args=[session_id, skill_name, action, params_json, job_id],
                id=job_id, replace_existing=True,
            )
            _persist_skill_job(
                job_id, "interval", {"seconds": interval_seconds}, label,
                session_id, skill_name, action, params_json,
            )
            return SkillResult(
                success=True,
                data=f"✅ '{label}' scheduled every {interval_seconds}s — results saved to this session",
                action_taken=f"Skill job scheduled: {label}",
                metadata={"job_id": job_id},
            )
        else:
            parts = cron_expr.strip().split()
            if len(parts) != 5:
                return SkillResult(success=False, error="Cron must be 5 fields: minute hour day month weekday")
            minute, hour, day, month, dow = parts
            scheduler.add_job(
                _fire_skill_job, "cron",
                minute=minute, hour=hour, day=day, month=month, day_of_week=dow,
                args=[session_id, skill_name, action, params_json, job_id],
                id=job_id, replace_existing=True,
            )
            _persist_skill_job(
                job_id, "cron",
                {"minute": minute, "hour": hour, "day": day, "month": month, "day_of_week": dow},
                label, session_id, skill_name, action, params_json,
            )
            return SkillResult(
                success=True,
                data=f"✅ '{label}' scheduled (cron: {cron_expr}) — results saved to this session",
                action_taken=f"Skill job scheduled: {label}",
                metadata={"job_id": job_id},
            )
