# continuity/scheduler/registry.py

from dataclasses import dataclass
from typing import Callable, Awaitable, Any, Literal, TypedDict


SchedulerHandler = Callable[[], Awaitable[Any]]


class IntervalSchedule(TypedDict):
    type: Literal["interval"]
    seconds: int


class DailyWindowSchedule(TypedDict):
    type: Literal["daily_window"]
    start: str  # "02:00"
    end: str    # "05:00"


SchedulerSchedule = IntervalSchedule | DailyWindowSchedule


@dataclass(frozen=True)
class SchedulerTask:
    key: str
    handler: SchedulerHandler
    schedule: SchedulerSchedule
    description: str | None = None


_scheduler_tasks: dict[str, SchedulerTask] = {}


def register_scheduler_task(
    key: str,
    handler: SchedulerHandler,
    schedule: SchedulerSchedule,
    description: str | None = None,
) -> None:
    print(f"Registering scheduler task: {key}")

    if key in _scheduler_tasks:
        raise ValueError(f"Scheduler task already registered: {key}")

    _scheduler_tasks[key] = SchedulerTask(
        key=key,
        handler=handler,
        schedule=schedule,
        description=description,
    )


def get_scheduler_task(key: str) -> SchedulerHandler | None:
    """
    Backward-compatible helper.

    Existing endpoints/manual triggers only care about the runnable handler,
    so keep this returning the handler directly.
    """
    task = _scheduler_tasks.get(key)
    return task.handler if task else None


def get_scheduler_task_definition(key: str) -> SchedulerTask | None:
    """
    New helper for the actual scheduler loop, UI metadata, logging, etc.
    """
    return _scheduler_tasks.get(key)


def list_scheduler_tasks() -> list[str]:
    """
    Backward-compatible list of registered keys.
    """
    return sorted(_scheduler_tasks.keys())


def list_scheduler_task_definitions() -> list[SchedulerTask]:
    """
    New metadata-aware listing.
    """
    return [
        _scheduler_tasks[key]
        for key in sorted(_scheduler_tasks.keys())
    ]