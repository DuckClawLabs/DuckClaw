"""
Scheduler Skill — APScheduler for background/proactive tasks.
Adding a schedule → Tier: ASK (user must approve recurring tasks).
Background tasks default to Tier: NOTIFY (inform, don't act without approval).
"""

import asyncio
import logging
from datetime import datetime
from typing import Callable, Optional

from duckclaw.skills.base import BaseSkill, SkillPermission, SkillResult

logger = logging.getLogger(__name__)

# Global scheduler instance (shared across skills)
_scheduler = None
_notify_callback: Optional[Callable] = None


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


async def _fire_reminder(message: str, job_id: str):
    """Called when a scheduled job fires."""
    if _notify_callback:
        try:
            await _notify_callback(f"⏰ Reminder: {message}")
        except Exception as e:
            logger.error(f"Failed to send reminder notification: {e}")
    else:
        logger.info(f"Scheduled reminder fired (no callback): {message}")


class SchedulerSkill(BaseSkill):
    name = "scheduler"
    description = "Schedule reminders, cron jobs, and recurring background tasks."
    version = "1.0.0"
    permissions = [SkillPermission.SCHEDULE]  # Tier: ASK

    async def execute(self, action: str, params: dict) -> SkillResult:
        dispatch = {
            "remind_in":     self._remind_in,
            "remind_at":     self._remind_at,
            "add_cron":      self._add_cron,
            "list_jobs":     self._list_jobs,
            "remove_job":    self._remove_job,
            "morning_brief": self._morning_brief,
        }
        handler = dispatch.get(action)
        if not handler:
            return SkillResult(success=False, error=f"Unknown scheduler action: {action}")
        return await handler(params)

    async def _remind_in(self, params: dict) -> SkillResult:
        """Set a reminder N minutes/hours from now."""
        minutes = int(params.get("minutes", 0))
        hours = int(params.get("hours", 0))
        message = params.get("message", "Reminder!")
        total_minutes = hours * 60 + minutes

        if total_minutes <= 0:
            return SkillResult(success=False, error="minutes or hours must be > 0")

        approved = await self._check(
            "scheduler.add",
            f"Set reminder in {total_minutes} min: '{message}'",
            details={"minutes": total_minutes, "message": message},
        )
        if not approved:
            return SkillResult(success=False, error="Reminder creation denied.")

        scheduler = get_scheduler()
        if not scheduler:
            return SkillResult(success=False, error="APScheduler not available. Install: pip install apscheduler")

        from datetime import timedelta
        run_at = datetime.now() + timedelta(minutes=total_minutes)
        job_id = f"reminder_{run_at.strftime('%Y%m%d%H%M%S')}"

        scheduler.add_job(
            _fire_reminder,
            "date",
            run_date=run_at,
            args=[message, job_id],
            id=job_id,
            replace_existing=True,
        )

        time_str = f"{hours}h {minutes}m" if hours else f"{minutes}m"
        return SkillResult(
            success=True,
            data=f"⏰ Reminder set for {time_str} from now: '{message}'",
            action_taken=f"Reminder scheduled: {message}",
            metadata={"job_id": job_id, "fires_at": run_at.isoformat()},
        )

    async def _remind_at(self, params: dict) -> SkillResult:
        """Set a reminder at a specific time (ISO 8601 or HH:MM)."""
        time_str = params.get("time", "")
        message = params.get("message", "Reminder!")

        if not time_str:
            return SkillResult(success=False, error="time is required (e.g. '14:30' or '2025-03-15T14:30:00')")

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
        except ValueError:
            return SkillResult(success=False, error=f"Cannot parse time: '{time_str}'")

        approved = await self._check(
            "scheduler.add",
            f"Set reminder at {run_at.strftime('%H:%M')}: '{message}'",
            details={"time": run_at.isoformat(), "message": message},
        )
        if not approved:
            return SkillResult(success=False, error="Reminder creation denied.")

        scheduler = get_scheduler()
        if not scheduler:
            return SkillResult(success=False, error="APScheduler not available.")

        job_id = f"remind_at_{run_at.strftime('%Y%m%d%H%M')}"
        scheduler.add_job(
            _fire_reminder, "date",
            run_date=run_at, args=[message, job_id], id=job_id, replace_existing=True,
        )

        return SkillResult(
            success=True,
            data=f"⏰ Reminder set for {run_at.strftime('%H:%M on %b %d')}: '{message}'",
            action_taken=f"Reminder at {run_at.strftime('%H:%M')}",
        )

    async def _add_cron(self, params: dict) -> SkillResult:
        """Add a recurring cron job."""
        cron_expr = params.get("cron", "")  # e.g. "0 8 * * *" = daily at 8am
        message = params.get("message", "")
        label = params.get("label", "Scheduled task")

        if not cron_expr:
            return SkillResult(success=False, error="cron expression required (e.g. '0 8 * * *')")

        approved = await self._check(
            "scheduler.add",
            f"Add recurring task: '{label}' ({cron_expr})",
            details={"cron": cron_expr, "label": label},
        )
        if not approved:
            return SkillResult(success=False, error="Cron job creation denied.")

        scheduler = get_scheduler()
        if not scheduler:
            return SkillResult(success=False, error="APScheduler not available.")

        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return SkillResult(success=False, error="Cron must be 5 fields: minute hour day month weekday")

        minute, hour, day, month, dow = parts
        job_id = f"cron_{label.replace(' ', '_').lower()}"

        scheduler.add_job(
            _fire_reminder, "cron",
            minute=minute, hour=hour, day=day, month=month, day_of_week=dow,
            args=[message or label, job_id], id=job_id, replace_existing=True,
        )

        return SkillResult(
            success=True,
            data=f"✅ Recurring task '{label}' added (cron: {cron_expr})",
            action_taken=f"Cron job added: {label}",
        )

    async def _list_jobs(self, params: dict) -> SkillResult:
        """List all scheduled jobs."""
        scheduler = get_scheduler()
        if not scheduler:
            return SkillResult(success=True, data="No scheduler running.")

        jobs = scheduler.get_jobs()
        if not jobs:
            return SkillResult(success=True, data="No scheduled tasks.")

        lines = ["Scheduled tasks:\n"]
        for job in jobs:
            next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M") if job.next_run_time else "N/A"
            lines.append(f"• {job.id}\n  Next run: {next_run}")

        return SkillResult(success=True, data="\n".join(lines))

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
            return SkillResult(success=True, data=f"Removed job: {job_id}")
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

        return SkillResult(
            success=True,
            data=f"☀️ Daily morning briefing set for {time_str}",
            action_taken="Morning briefing scheduled",
        )
