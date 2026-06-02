# app/core/scheduler/router.py
# This is an optional router to use for triggering registered tasks via API calls

from fastapi import APIRouter, HTTPException
from app.core.scheduler.registry import get_scheduler_task, list_scheduler_tasks

router = APIRouter(prefix="/api/continuity/scheduler", tags=["continuity-scheduler"])


@router.post("/run/{task_key}")
async def run_scheduler_task(task_key: str):
    handler = get_scheduler_task(task_key)

    if handler is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "Unknown scheduler task",
                "task_key": task_key,
                "available": list_scheduler_tasks(),
            },
        )

    result = await handler()

    return {
        "ok": True,
        "task_key": task_key,
        "result": result,
    }