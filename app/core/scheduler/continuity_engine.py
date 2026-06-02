import asyncio
import random
import httpx
#from app.core.muse_initiator import run_initiative, run_discoveryfeeds_lookup
#from addons.memorymuse.memorymuse.continuity.reminders.reminders_core import run_check_reminders
from app.core.time_location_utils import seconds_until
from app.config import API_URL


async def run_reminders():
    response = httpx.post(
        f"{API_URL}/api/continuity/scheduler/run/reminders",
        timeout=5
    )

async def run_initiative():
    response = httpx.post(
        f"{API_URL}/api/continuity/scheduler/run/initiative",
        timeout=5
    )

async def run_discoveryfeeds():
    response = httpx.post(
        f"{API_URL}/api/continuity/scheduler/run/discoveryfeeds",
        timeout=5
    )

# --- Scheduled Tasks ---
scheduled_tasks = [
    {"name": "initiative", "interval": 3600, "function": run_initiative},
#    {"name": "check_dropped_threads", "interval": 3600, "function": muse_initiator.run_dropped_threads_check},
    {"name": "discovery_feed", "interval": 3600, "function": run_discoveryfeeds},
    {"name": "reminder_checker", "interval": 60, "function": run_reminders},
#    {"name": "inactivity_checker", "interval": 1800, "function": muse_initiator.run_inactivity_check},
#    {"name": "dreamtime", "interval": 86400, "function": muse_initiator.run_dream_gate},
#    {"name": "introspection_engine", "interval": 86400, "function": muse_initiator.run_introspection_engine},
]



# --- Individual Loop for Each Task ---
async def task_runner(task):
    name = task["name"]
    fn = task["function"]

    if name in ("dreamtime", "introspection_engine"):
        hour = 3 if name == "dreamtime" else 4
        delay = seconds_until(hour)
        print(f"[ContinuityEngine] {name} will run in {delay} seconds (scheduled for {hour}:00)")
        await asyncio.sleep(delay)
        while True:
            try:
                print(f"[ContinuityEngine] Running task: {name}")
                await fn()
            except Exception as e:
                print(f"[ContinuityEngine] Error in task '{name}': {e}")
            await asyncio.sleep(86400)  # Every 24 hours after
    else:
        interval = task["interval"]
        # Apply jitter
        jitter = random.randint(1, max(90, interval // 4)) if interval >= 300 else random.randint(1, 15)
        print(f"[ContinuityEngine] Initial delay for {name}: {jitter} seconds")
        await asyncio.sleep(jitter)
        while True:
            try:
                print(f"[ContinuityEngine] Running task: {name}")
                await fn()
            except Exception as e:
                print(f"[ContinuityEngine] Error in task '{name}': {e}")
            await asyncio.sleep(interval)



# --- Main Event Loop ---
async def main():
    # launch your scheduled tasks
    await asyncio.gather(
        *(task_runner(task) for task in scheduled_tasks),
    )

# --- Entrypoint ---
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[ContinuityEngine] Stopped.")
