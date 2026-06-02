# app/core/reminders/scheduler_tasks.py

from app.core.scheduler.registry import register_scheduler_task
from app.core.reminders.reminders_core import run_check_reminders


def register_scheduler_tasks() -> None:
    register_scheduler_task(
        key="reminders",
        handler=run_check_reminders,
        schedule={
            "type": "interval",
            "seconds": 60,
        },
        description="Checks for due reminders.",
    )
