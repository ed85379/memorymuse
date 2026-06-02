# app/core/initiative/scheduler_tasks.py

from app.core.scheduler.registry import register_scheduler_task
from app.core.initiative.initative_core import run_initiative


def register_scheduler_tasks() -> None:
    register_scheduler_task(
        key="initiative",
        handler=run_initiative,
        schedule={
            "type": "interval",
            "seconds": 3600,
        },
        description="Grants a window for open-ended self-prompting.",
    )