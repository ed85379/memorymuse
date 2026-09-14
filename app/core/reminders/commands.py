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


CRON_VALUE_SCHEMA = {
    "anyOf": [
        {"type": "integer"},
        {"type": "string", "enum": ["*"]},
    ],
}

REMINDER_SCHEDULE_SCHEMA = {
    "type": "object",
    "description": (
        "Cron-like reminder schedule in the user's local timezone. "
        "Each field is either an integer or '*' as a wildcard."
    ),
    "properties": {
        "minute": {"anyOf": [{"type": "integer", "minimum": 0, "maximum": 59}, {"type": "string", "enum": ["*"]}]},
        "hour": {"anyOf": [{"type": "integer", "minimum": 0, "maximum": 23}, {"type": "string", "enum": ["*"]}]},
        "day": {"anyOf": [{"type": "integer", "minimum": 1, "maximum": 31}, {"type": "string", "enum": ["*"]}]},
        "dow": {"anyOf": [{"type": "integer", "minimum": 0, "maximum": 6}, {"type": "string", "enum": ["*"]}]},
        "month": {"anyOf": [{"type": "integer", "minimum": 1, "maximum": 12}, {"type": "string", "enum": ["*"]}]},
        "year": {"anyOf": [{"type": "integer"}, {"type": "string", "enum": ["*"]}]},
    },
    "required": ["minute", "hour", "day", "dow", "month", "year"],
    "additionalProperties": False,
}

REMINDER_MUTABLE_PROPERTIES = {
    "text": {
        "type": "string",
        "description": "Clear description of what the reminder is for.",
    },
    "schedule": REMINDER_SCHEDULE_SCHEMA,
    "ends_on": {
        "type": "string",
        "description": (
            "Optional ISO 8601 cutoff datetime. The reminder will not fire after this time."
        ),
    },
    "notification_offset": {
        "type": "string",
        "description": (
            "Optional early-notification offset, such as '10m' or '2h'."
        ),
    },
    "early_only": {
        "type": "boolean",
        "description": (
            "When notification_offset is set, true means send only the early notification."
        ),
    },
}

# Commands + intent triggers
COMMANDS = {
    "set_reminder": {
        "triggers": ["remind me to", "set a reminder", "remind me that", "set an alarm", "set a schedule"],
        "description": (
            "Create a reminder. For one-time reminders, use a schedule for the intended local "
            "time and set ends_on shortly after it so the reminder expires after firing. "
            "Use notification_offset only when an earlier warning is useful."
        ),
        "parameters": {
            "type": "object",
            "properties": REMINDER_MUTABLE_PROPERTIES,
            "required": ["text", "schedule"],
            "additionalProperties": False,
        },
        "example_payload": {
            "text": "<MEANINGFUL DESCRIPTION>",
            "schedule": {
                "minute": 0,
                "hour": 9,
                "day": "*",
                "dow": "*",
                "month": "*",
                "year": "*",
            },
            "ends_on": "<ISO 8601 DATETIME, OPTIONAL>",
            "notification_offset": "<e.g. 10m OR 2h, OPTIONAL>",
            "early_only": False,
        },
        "format": (
            "<command name=\"set_reminder\"> {\"text\": \"<meaningful description of the reminder>\", \"schedule\": {\"minute\":0-59, \"hour\":0-23, \"day\":1-31, \"dow\":0-6, \"month\":1-12, \"year\":YYYY}, \"ends_on\": \"<ISO 8601 datetime, optional>\", \"notification_offset\": \"<duration before trigger, e.g. '10m' or '2h', optional>\", \"early_only\": <Boolean - optional>} </command>\n\n"
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
        "description": (
            "Edit an existing reminder using its entry ID. Include only the fields that need to "
            "change; all reminder fields besides id are optional."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "The entry ID of the existing reminder to edit.",
                },
                **REMINDER_MUTABLE_PROPERTIES,
            },
            "required": ["id"],
            "additionalProperties": False,
        },
        "example_payload": {
            "id": "<entry_id>",
            "text": "<MEANINGFUL DESCRIPTION>",
            "schedule": {
                "minute": 0,
                "hour": 9,
                "day": "*",
                "dow": "*",
                "month": "*",
                "year": "*",
            },
            "ends_on": "<ISO 8601 DATETIME, OPTIONAL>",
            "notification_offset": "<e.g. 10m OR 2h, OPTIONAL>",
            "early_only": False,
        },
        "format": (
            "<command name=\"edit_reminder\"> {\"id\": <entry_id>, \"text\": \"<meaningful description of the reminder>\", \"schedule\": {\"minute\":0-59, \"hour\":0-23, \"day\":1-31, \"dow\":0-6, \"month\":1-12, \"year\":YYYY}, \"ends_on\": \"<ISO 8601 datetime, optional>\", \"notification_offset\": \"<duration before trigger, e.g. '10m' or '2h', optional>\", \"early_only\": <Boolean - optional>} </command>\n\n"
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
        "description": (
            "Temporarily defer an existing reminder until a specific ISO 8601 datetime in the "
            "user's local timezone. Use the reminder ID supplied in reminder context or search "
            "for the reminder first if its identity is unclear."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "The entry ID of the reminder to snooze.",
                },
                "snooze_until": {
                    "type": "string",
                    "description": (
                        "The new local fire time as an ISO 8601 datetime with appropriate timezone."
                    ),
                },
            },
            "required": ["id", "snooze_until"],
            "additionalProperties": False,
        },
        "format": (
            "<command name=\"snooze_reminder\"> {\"id\": <entry_id>, \"snooze_until\": \"<ISO 8601 datetime>\"} </command>\n\n"
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
        "description": (
            "Temporarily pause an existing reminder until a specific ISO 8601 datetime in the "
            "user's local timezone. The reminder remains enabled and resumes normally afterward."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "The entry ID of the reminder to pause.",
                },
                "skip_until": {
                    "type": "string",
                    "description": (
                        "The local ISO 8601 datetime after which the reminder may fire again."
                    ),
                },
            },
            "required": ["id", "skip_until"],
            "additionalProperties": False,
        },
        "format": (
            "<command name=\"skip_reminder\"> {\"id\": <entry_id>, \"skip_until\": \"<ISO 8601 datetime>\"} </command>\n\n"
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
        "description": (
            "Enable or disable an existing reminder. Disabling prevents future notifications but "
            "retains the reminder so it can be enabled again later."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "The entry ID of the reminder to enable or disable.",
                },
                "status": {
                    "type": "string",
                    "enum": ["enabled", "disabled"],
                    "description": "Whether the reminder should be enabled or disabled.",
                },
            },
            "required": ["id", "status"],
            "additionalProperties": False,
        },
        "format": (
            "<command name=\"toggle_reminder\"> {\"id\": <entry_id>, \"status\": \"enabled/disabled\"} </command>\n\n"
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
        "description": (
            "Send an already-composed reminder notification through the specified delivery "
            "channel. This is a subsystem delivery action, not the command used to create or "
            "edit reminder schedules."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The exact reminder message to deliver.",
                },
                "to": {
                    "type": "string",
                    "enum": ["webui"],
                    "description": "The delivery channel for this reminder notification.",
                },
            },
            "required": ["text", "to"],
            "additionalProperties": False,
        },
        "format": "<command name=\"send_reminders\"> {\"text\": \"message to send\", \"to\": \"webui\"} </command>",
        "handler": lambda payload, **kwargs: asyncio.create_task(handle_send_reminders(payload, **kwargs))
    },
    "search_reminders": {
        "triggers": [],
        "description": (
            "Locate reminders by text, schedule, status, or state. Use this when asked to list "
            "reminders, or before snoozing, pausing, editing, or disabling a reminder whose ID is "
            "not already known. The result is shown with reminder IDs; if more than one candidate "
            "matches and intent remains ambiguous, ask which reminder is meant before acting."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "object",
                    "description": (
                        "Optional matching criteria. Omit individual fields that should not "
                        "constrain the search."
                    ),
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": (
                                "Full or partial reminder text; may include semantically related words."
                            ),
                        },
                        "schedule": {
                            "type": "object",
                            "description": (
                                "Optional cron-like schedule fields to match; use '*' for any "
                                "explicit wildcard fields."
                            ),
                            "properties": REMINDER_SCHEDULE_SCHEMA["properties"],
                            "additionalProperties": False,
                        },
                        "status": {
                            "type": "string",
                            "enum": ["enabled", "disabled"],
                            "description": "Optionally limit results by enabled/disabled status.",
                        },
                        "skip_until_active": {
                            "type": "boolean",
                            "description": (
                                "Optionally limit results by whether a temporary skip is currently active."
                            ),
                        },
                        "expired": {
                            "type": "boolean",
                            "description": (
                                "Optionally limit results by whether their expiration cutoff has passed."
                            ),
                        },
                    },
                    "additionalProperties": False,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional maximum number of reminders to return.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
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
            "<command name=\"search_reminders\"> {"
            "\"query\": {"
            "\"text\": \"<string or partial match on reminder text — You may also include semantically similar or related words to improve matching>\", "
            "\"schedule\": {\"minute\": \"*\", \"hour\": \"*\", \"day\": \"*\", \"dow\": \"*\", \"month\": \"*\", \"year\": \"*\"}, "
            "\"status\": \"<enabled|disabled>\", "
            "\"skip_until_active\": <boolean>, "
            "\"expired\": <boolean>"
            "}, "
            "\"limit\": <integer, optional>"
            "} </command>"
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