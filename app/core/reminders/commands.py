# app/core/reminders/commands.py
# This file contains the commands that are specific to the reminders subsystem

import asyncio
from app.core.reminders.reminders_core import (
    handle_set,
    handle_edit,
    handle_skip,
    handle_snooze,
    handle_toggle,
    handle_search_reminders,
    format_visible_reminders,
    handle_send_reminders,
)

# Commands + intent triggers
COMMANDS = {
    "set_reminder": {
        "triggers": ["remind me to", "set a reminder", "remind me that", "set an alarm", "set a schedule"],
        "format": (
            "[COMMAND: set_reminder] {\"text\": \"<meaningful description of the reminder>\", \"schedule\": {\"minute\":0-59, \"hour\":0-23, \"day\":1-31, \"dow\":0-6, \"month\":1-12, \"year\":YYYY}, \"ends_on\": \"<ISO 8601 datetime, optional>\", \"notification_offset\": \"<duration before trigger, e.g. '10m' or '2h', optional>\", \"early_only\": <Boolean - optional>} [/COMMAND]\n\n"
            "Notes:\n"
            "  - `text`: Clear description of what the reminder is for (e.g. 'take vitamins').\n"
            "  - `schedule`: Parsed cron-like structure, with each field as an integer or wildcard '*'.\n"
            "  - `ends_on`: Optional cutoff date/time in ISO 8601 format. The reminder will not fire after this.\n"
            "  - `notification_offset`: Optional early warning, expressed as a relative duration before the scheduled time.\n"
            "  - `early_only`: If a notification_offset is set, and the user only wants the early notification, set this to true.\n"
            "  - For one‑time reminders, set an `ends_on` timestamp set to after the reminder would fire, so the reminder expires after firing once.\n"
        ),
        "handler": lambda payload, **kwargs: handle_set(
            {
                "text": payload.get("text"),
                "schedule": payload.get("schedule"),
                "ends_on": payload.get("ends_on"),
                "notification_offset": payload.get("notification_offset"),
                "early_only": payload.get("early_only")
            }
        ),
        "filter": lambda entry: {
            "visible": f"Reminder set: {format_visible_reminders(entry)}",
            "hidden": entry
        },
        "note_schema": {
            "exclude": ["created_on", "updated_on", "cron", "early_notification"],
            "child_commands": ["edit_reminder", "snooze_reminder", "skip_reminder", "toggle_reminder"]
        }
    },
    "edit_reminder": {
        "triggers": ["update reminder", "change reminder", "fix schedule"],
        "format": (
            "[COMMAND: edit_reminder] {\"id\": <entry_id>, \"text\": \"<meaningful description of the reminder>\", \"schedule\": {\"minute\":0-59, \"hour\":0-23, \"day\":1-31, \"dow\":0-6, \"month\":1-12, \"year\":YYYY}, \"ends_on\": \"<ISO 8601 datetime, optional>\", \"notification_offset\": \"<duration before trigger, e.g. '10m' or '2h', optional>\", \"early_only\": <Boolean - optional>} [/COMMAND]\n\n"
            "  Notes:\n"
            "  - `id`: To edit an existing reminder, use the entry_id from the reminder shown above.\n"
            "  The following are all optional for edits. You only need to enter what needs to be changed:\n"
            "  - `text`: Clear description of what the reminder is for (e.g. 'take vitamins').\n"
            "  - `schedule`: Parsed cron-like structure, with each field as an integer or wildcard '*'.\n"
            "  - `ends_on`: Optional cutoff date/time in ISO 8601 format. The reminder will not fire after this.\n"
            "  - `notification_offset`: Optional early warning, expressed as a relative duration before the scheduled time.\n"
            "  - `early_only`: If a notification_offset is set, and the user only wants the early notification, set this to true.\n"
        ),
        "handler": lambda payload, **kwargs: handle_edit(
            {
                "id": payload.get("id"),
                "text": payload.get("text"),
                "schedule": payload.get("schedule"),
                "ends_on": payload.get("ends_on"),
                "notification_offset": payload.get("notification_offset"),
                "early_only": payload.get("early_only")
            }
        ),
        "filter": lambda entry: {
            "visible": f"Reminder edited: {format_visible_reminders(entry)}",
            "hidden": entry
        },
        "note_schema": {
            "exclude": ["created_on", "updated_on", "cron", "early_notification"],
            "child_commands": ["edit_reminder", "snooze_reminder", "skip_reminder", "toggle_reminder"]
        }
    },
    "snooze_reminder": {
        "triggers": ["snooze reminder", "remind me again in", "let me know again in"],
        "format": (
            "[COMMAND: snooze_reminder] {\"id\": <entry_id>, \"snooze_until\": \"<ISO 8601 datetime>\"} [/COMMAND]\n\n"
            "  Notes:\n"
            "  - `id`: To edit an existing reminder, use the entry_id from the reminder shown above.\n"
            "  - `snooze_until`: Date/time in ISO 8601 format in user's timezone. The reminder will fire again at this time.\n"
        ),
        "handler": lambda payload, **kwargs: handle_snooze(
            {
                "id": payload.get("id"),
                "snooze_until": payload.get("snooze_until"),
            }
        ),
        "filter": lambda entry: {
            "visible": f"Reminder snoozed until: {entry.get('snooze_until')}",
            "hidden": entry
        },
        "note_schema": {
            "exclude": ["created_on", "updated_on", "cron", "early_notification"],
            "child_commands": ["edit_reminder", "snooze_reminder", "skip_reminder", "toggle_reminder"]
        }
    },
    "skip_reminder": {
        "triggers": ["skip reminder", "disable reminder until", "pause reminder"],
        "format": (
            "[COMMAND: skip_reminder] {\"id\": <entry_id>, \"skip_until\": \"<ISO 8601 datetime>\"} [/COMMAND]\n\n"
            "  Notes:\n"
            "  - `id`: To edit an existing reminder, use the entry_id from the reminder shown above.\n"
            "  - `skip_until`: Date/time in ISO 8601 format in user's timezone. The reminder won't fire again until after this time.\n"
        ),
        "handler": lambda payload, **kwargs: handle_skip(
            {
                "id": payload.get("id"),
                "skip_until": payload.get("skip_until"),
            }
        ),
        "filter": lambda entry: {
            "visible": f"Reminder paused until: {entry.get('skip_until')}",
            "hidden": entry
        },
        "note_schema": {
            "exclude": ["created_on", "updated_on", "cron", "early_notification"],
            "child_commands": ["edit_reminder", "snooze_reminder", "skip_reminder", "toggle_reminder"]
        }
    },
    "toggle_reminder": {
        "triggers": ["cancel reminder", "disable reminder", "don't notify again"],
        "format": (
            "[COMMAND: toggle_reminder] {\"id\": <entry_id>, \"status\": \"enabled/disabled\"} [/COMMAND]\n\n"
            "  Notes:\n"
            "  - `id`: To edit an existing reminder, use the entry_id from the reminder shown above.\n"
            "  - `status`: Set to either 'enabled' or 'disabled'. Disabling the reminder will prevent all future notifications.\n"
        ),
        "handler": lambda payload, **kwargs: handle_toggle(
            {
                "id": payload.get("id"),
                "status": payload.get("status"),
            }
        ),
        "filter": lambda entry: {
            "visible": f"Reminder {entry.get('status')}",
            "hidden": entry
        },
        "note_schema": {
            "exclude": ["created_on", "updated_on", "cron", "early_notification"],
            "child_commands": ["edit_reminder", "snooze_reminder", "skip_reminder", "toggle_reminder"]
        }
    },
    "send_reminders": {
        "triggers": [],
        "format": "[COMMAND: send_reminders] {\"text\": \"message to send\", \"to\": \"webui\"} [/COMMAND]",
        "handler": lambda payload, **kwargs: asyncio.create_task(handle_send_reminders(payload, **kwargs))
    },
    "search_reminders": {
        "triggers": [],
        "format": (
            "# Purpose:\n"
            "# Use this command when you need to locate one or more reminders matching a phrase or schedule.\n"
            "# It is used both when the user explicitly asks to list reminders, and implicitly when they\n"
            "# request another reminder-related action (skip, snooze, disable, etc.) without specifying which.\n"
            "# In that case, you run this command first to find candidates, present the list to the user,\n"
            "# and then prompt for which reminder to act on.\n\n"
            "# Instruction:\n"
            "# When you run the command, the user will see a list clearly formatted with IDs and text.\n"
            "# You should then ask the user which one they meant before proceeding with the next command.\n\n"
            "[COMMAND: search_reminders] {"
            "\"query\": {"
            "\"text\": \"<string or partial match on reminder text — You may also include semantically similar or related words to improve matching>\", "
            "\"schedule\": {\"minute\": \"*\", \"hour\": \"*\", \"day\": \"*\", \"dow\": \"*\", \"month\": \"*\", \"year\": \"*\"}, "
            "\"status\": \"<enabled|disabled>\", "
            "\"skip_until_active\": <boolean>, "
            "\"expired\": <boolean>"
            "}, "
            "\"limit\": <integer, optional>"
            "} [/COMMAND]"
        ),
        "handler": lambda payload, **kwargs: handle_search_reminders(payload),
        "filter": lambda data: {
            "visible": (
                f"[Search query] {data['query']}\n"
                + "\n".join([
                    f"[Reminder found: (id - {r['id']}) {format_visible_reminders(r)}]"
                    for r in data["results"]
                ])
                if data["results"]
                else f"[Search query] {data['query']}\n[No matching reminders found.]"
            ),
            "hidden": data["results"]
        },
        "note_schema": {
            "exclude": ["created_on", "updated_on", "cron", "early_notification"],
            "child_commands": ["edit_reminder", "snooze_reminder", "skip_reminder", "toggle_reminder"]
        }
    },
}

def register_reminder_commands(registry):
    for name, handler in COMMANDS.items():
        print(f"Registering Reminders Command: {name}")
        registry.register(name, handler)