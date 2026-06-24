# app/core/scheduler_core.py

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from app.config import muse_settings
from app.core.utils import write_system_log
from app.core.scheduler.registry import (
    SchedulerTask,
    list_scheduler_task_definitions,
)

ENABLE_SCHEDULER = muse_settings.get_section('muse_features').get('ENABLE_SCHEDULER', False)
LOCAL_TIMEZONE = muse_settings.get_section('user_config').get('USER_TIMEZONE', "UTC")

@dataclass(frozen=True)
class SchedulerJob:
    task: SchedulerTask
    source: str
    enqueued_at: datetime
    scheduled_for: datetime | None = None
    metadata: dict | None = None


_scheduler_enabled: bool = ENABLE_SCHEDULER
_scheduler_started: bool = False

_scheduler_ticker_tasks: list[asyncio.Task] = []
_scheduler_worker_task: asyncio.Task | None = None

_scheduler_queue: asyncio.Queue[SchedulerJob] = asyncio.Queue()


def is_scheduler_enabled() -> bool:
    return _scheduler_enabled


def set_scheduler_enabled(enabled: bool) -> None:
    global _scheduler_enabled
    _scheduler_enabled = enabled
    print(f"[Scheduler] Enabled set to: {_scheduler_enabled}")


def scheduler_jitter(interval: int) -> int:
    return (
        random.randint(1, max(90, interval // 4))
        if interval >= 300
        else 0
        #else random.randint(1, 15)
    )


async def enqueue_scheduler_job(
    task: SchedulerTask,
    *,
    source: str,
    scheduled_for: datetime | None = None,
    metadata: dict | None = None,
) -> bool:
    if not is_scheduler_enabled():
        print(f"[Scheduler] Not enqueueing disabled scheduler task: {task.key}")
        return False

    job = SchedulerJob(
        task=task,
        source=source,
        scheduled_for=scheduled_for,
        enqueued_at=datetime.now(scheduled_for.tzinfo) if scheduled_for else datetime.now(),
        metadata=metadata,
    )

    await _scheduler_queue.put(job)

    print(
        f"[Scheduler] Enqueued task: {task.key} "
        f"source={source} queue_size={_scheduler_queue.qsize()}"
    )

    return True


async def run_scheduler_queue(queue: asyncio.Queue[SchedulerJob]) -> None:
    while True:
        job = await queue.get()
        task = job.task

        try:
            print(
                f"[Scheduler] Running queued task: {task.key} "
                f"source={job.source}"
            )

            await task.handler()

            write_system_log(
                level="info",
                module="api",
                component="scheduler",
                function="run_scheduler_queue",
                action="scheduler_task_completed",
                task_key=task.key,
                source=job.source,
                scheduled_for=job.scheduled_for.isoformat() if job.scheduled_for else None,
                enqueued_at=job.enqueued_at.isoformat(),
            )

        except Exception as e:
            print(f"[Scheduler] Error in queued task '{task.key}': {e}")

            write_system_log(
                level="error",
                module="api",
                component="scheduler",
                function="run_scheduler_queue",
                action="scheduler_task_failed",
                error=str(e),
                task_key=task.key,
                source=job.source,
                scheduled_for=job.scheduled_for.isoformat() if job.scheduled_for else None,
                enqueued_at=job.enqueued_at.isoformat(),
            )

        finally:
            queue.task_done()


def parse_hhmm(value: str) -> time:
    hour_str, minute_str = value.split(":", 1)
    return time(hour=int(hour_str), minute=int(minute_str))


def random_datetime_in_window(
    target_date: date,
    start: str,
    end: str,
    tz: ZoneInfo,
) -> datetime:
    start_time = parse_hhmm(start)
    end_time = parse_hhmm(end)

    start_dt = datetime.combine(target_date, start_time, tzinfo=tz)
    end_dt = datetime.combine(target_date, end_time, tzinfo=tz)

    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    window_seconds = int((end_dt - start_dt).total_seconds())
    offset = random.randint(0, window_seconds)

    return start_dt + timedelta(seconds=offset)


def compute_next_daily_window_run(
    start: str,
    end: str,
    tz: ZoneInfo,
) -> datetime:
    now = datetime.now(tz)

    candidate = random_datetime_in_window(
        target_date=now.date(),
        start=start,
        end=end,
        tz=tz,
    )

    if candidate <= now:
        candidate = random_datetime_in_window(
            target_date=now.date() + timedelta(days=1),
            start=start,
            end=end,
            tz=tz,
        )

    return candidate


async def sleep_until(run_at: datetime) -> None:
    now = datetime.now(run_at.tzinfo)
    delay = max(0, (run_at - now).total_seconds())
    await asyncio.sleep(delay)


async def interval_task_runner(task: SchedulerTask) -> None:
    interval = int(task.schedule["seconds"])

    initial_delay = scheduler_jitter(interval)
    print(f"[Scheduler] Initial delay for {task.key}: {initial_delay} seconds")
    await asyncio.sleep(initial_delay)

    while True:
        await enqueue_scheduler_job(
            task,
            source="scheduler",
            metadata={
                "schedule_type": "interval",
                "interval": interval,
            },
        )

        jitter = scheduler_jitter(interval)
        sleep_for = interval + jitter

        print(
            f"[Scheduler] Next enqueue for {task.key} in "
            f"{sleep_for} seconds ({interval}s + {jitter}s jitter)"
        )

        await asyncio.sleep(sleep_for)


async def daily_window_task_runner(task: SchedulerTask) -> None:
    start = task.schedule["start"]
    end = task.schedule["end"]

    tz = ZoneInfo(LOCAL_TIMEZONE)

    while True:
        next_run_at = compute_next_daily_window_run(
            start=start,
            end=end,
            tz=tz,
        )

        print(
            f"[Scheduler] {task.key} scheduled for "
            f"{next_run_at.isoformat()} in daily window {start}-{end}"
        )

        await sleep_until(next_run_at)

        await enqueue_scheduler_job(
            task,
            source="scheduler",
            scheduled_for=next_run_at,
            metadata={
                "schedule_type": "daily_window",
                "window_start": start,
                "window_end": end,
            },
        )


async def task_runner(task: SchedulerTask) -> None:
    schedule_type = task.schedule.get("type")

    if schedule_type == "interval":
        await interval_task_runner(task)

    elif schedule_type == "daily_window":
        await daily_window_task_runner(task)

    else:
        print(
            f"[Scheduler] Unknown schedule type for task "
            f"{task.key}: {schedule_type}"
        )

        write_system_log(
            level="error",
            module="api",
            component="scheduler",
            function="task_runner",
            action="unknown_schedule_type",
            task_key=task.key,
            schedule_type=str(schedule_type),
        )


async def start_scheduler() -> None:
    global _scheduler_started
    global _scheduler_ticker_tasks
    global _scheduler_worker_task

    if _scheduler_started:
        print("[Scheduler] Already started.")
        return

    task_definitions = list_scheduler_task_definitions()

    print(
        "[Scheduler] Starting with tasks: "
        f"{[task.key for task in task_definitions]}"
    )

    _scheduler_worker_task = asyncio.create_task(
        run_scheduler_queue(_scheduler_queue),
        name="scheduler:queue_worker",
    )

    _scheduler_ticker_tasks = [
        asyncio.create_task(
            task_runner(task),
            name=f"scheduler:ticker:{task.key}",
        )
        for task in task_definitions
    ]

    _scheduler_started = True


async def stop_scheduler() -> None:
    global _scheduler_started
    global _scheduler_ticker_tasks
    global _scheduler_worker_task

    if not _scheduler_started:
        return

    print("[Scheduler] Stopping scheduler.")

    tasks_to_cancel = list(_scheduler_ticker_tasks)

    if _scheduler_worker_task:
        tasks_to_cancel.append(_scheduler_worker_task)

    for task in tasks_to_cancel:
        task.cancel()

    await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

    _scheduler_ticker_tasks = []
    _scheduler_worker_task = None
    _scheduler_started = False