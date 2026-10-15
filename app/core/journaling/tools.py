
from app.core.journaling.journaling_core import read_journal_entry

from app.config import muse_settings
muse_name = muse_settings.get_section('muse_config').get('MUSE_NAME', "Muse")
user_name = muse_settings.get_section("user_config").get("USER_NAME", "User")


def handle_read_journal_entry(
    journal_entry_id: str,
    **kwargs,
) -> dict:
    journal_entry_id = str(journal_entry_id or "").strip()

    if not journal_entry_id:
        raise ValueError("journal_entry_id is required.")

    entry = read_journal_entry(journal_entry_id)

    if entry is None:
        return {
            "found": False,
            "journal_entry_id": journal_entry_id,
            "message": "No available journal entry was found for that Journal ID.",
        }

    visibility = entry["visibility"]

    sharing_note = (
        "This is Iris's complete shared personal journal entry. "
        "It may be discussed normally with Ed."
        if visibility == "shared"
        else
        "This is Iris's complete private personal journal entry. "
        "Retrieving it for context does not automatically mean its full "
        "contents should be disclosed to Ed; Iris may withhold, summarize, "
        "quote selectively, or choose to share it."
    )

    return {
        "found": True,
        "journal_entry": entry,
        "sharing_note": sharing_note,
    }


TOOL_REGISTRY = {
    "read_journal_entry": {
        "schema": {
            "type": "function",
            "name": "read_journal_entry",
            "description": (
                "Retrieve one complete Iris journal entry by its Journal ID. "
                "Use when a recalled excerpt needs its complete surrounding entry."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "journal_entry_id": {
                        "type": "string",
                        "description": "The Journal ID of the entry to retrieve."
                    }
                },
                "required": ["journal_entry_id"],
                "additionalProperties": False,
            },
        },
        "ui": {
            "start": f"{muse_name} is reading a journal entry…",
            "error": "Journal entry not found."
        },
        "handler": handle_read_journal_entry,
    }
}

def register_tools(registry):
    for name, handler in TOOL_REGISTRY.items():
        print(f"Registering Journaling Tools: {name}")
        registry.register(name, handler)
