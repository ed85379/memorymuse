# continuity/discoveryfeeds/scheduler_tasks.py

from app.core.scheduler.registry import register_scheduler_task
from .discovery_core import run_discoveryfeeds


def register_scheduler_tasks() -> None:
    register_scheduler_task(
        key="discoveryfeeds",
        handler=run_discoveryfeeds,
        schedule={
            "type": "interval",
            "seconds": 3600,
        },
        description="Grants a window for curiousity-focused self-prompting.",
    )