# app/core/assets/scheduler_tasks.py

from app.core.assets.assets_core import run_asset_lifecycle_maintenance
from app.core.scheduler.registry import register_scheduler_task


def register_scheduler_tasks() -> None:
    register_scheduler_task(
        key="asset_lifecycle",
        handler=run_asset_lifecycle_maintenance,
        schedule={
            "type": "daily_window",
            "start": "03:00",
            "end": "05:00",
        },
        description=(
            "Soft-deletes expired non-permanent chat uploads and purges "
            "long-deleted asset bytes."
        ),
    )