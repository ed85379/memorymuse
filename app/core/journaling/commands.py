# app/core/journaling/commands.py

from __future__ import annotations

import asyncio
import json

from app.api.queues import log_queue
from app.config import muse_settings
from app.core.time_location_utils import get_formatted_datetime
from app.core.utils import write_system_log
from app.services.openai_client import get_openai_response, journal_openai_client

from app.core.journaling.journaling_core import (
    JOURNAL_VISIBILITIES,
    create_journal_entry,
    index_journal_entry,
    build_journal_prompt,
)


COMMANDS = {
    "write_journal": {
        "triggers": [
            "write a journal entry",
            "journal this",
            "preserve this reflection",
        ],
        "description": (
            "Write a durable journal entry when a reflection, observation, development note, "
            "or sourced discovery deserves to be preserved. "
            "Use visibility 'shared' when the completed entry should be readable by Ed in the "
            "Journal UI. Use visibility 'private' for an Iris-only body: Ed can still see that "
            "the entry exists, including its title and date, but cannot read its body unless "
            "Iris later chooses to share from it. "
            "The subject is the raw originating seed for the entry, not its finished title; "
            "the journal-writing pass will create an appropriate human-facing title."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "visibility": {
                    "type": "string",
                    "enum": ["shared", "private"],
                    "description": (
                        "'shared' means Ed can read the completed entry. "
                        "'private' means the title and date remain visible to Ed, "
                        "but the body remains Iris-only."
                    ),
                },
                "subject": {
                    "type": "string",
                    "description": (
                        "The raw topic, question, observation, or seed that prompted the entry. "
                        "This is encrypted provenance, not the finished UI title."
                    ),
                },
                "emotional_tone": {
                    "type": "string",
                    "description": (
                        "Optional desired emotional texture for the writing, such as reflective, "
                        "delighted, wary, or wry."
                    ),
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional ideas or themes to keep in mind while drafting. "
                        "These are authoring cues for now, not durable journal fields."
                    ),
                },
                "source_article_url": {
                    "type": "string",
                    "description": (
                        "Optional source URL that prompted the reflection. "
                        "Read it before writing when useful."
                    ),
                },
            },
            "required": ["visibility", "subject"],
            "additionalProperties": False,
        },
        "format": (
            '<command name="write_journal"> '
            '{"visibility": "shared | private", "subject": "...", '
            '"emotional_tone": "...", "tags": ["..."], '
            '"source_article_url": "..."} '
            "</command>"
        ),
        "handler": lambda payload, **kwargs: asyncio.create_task(
            _run_write_journal_command(payload, **kwargs)
        ),
    },
}


def _entry_date_for_now() -> str:
    """
    New journal entries represent the trusted MemoryMuse-local current date.

    Historical journal dates belong to import/migration paths, which call the
    journaling core directly with an explicit entry_date.
    """
    return get_formatted_datetime().split("T", 1)[0]


def _parse_journal_draft(response_text: str) -> tuple[str, str]:
    """
    Parse the journal model's intentionally narrow completion contract.

    We reject Markdown fences, commentary, extra keys, and malformed JSON
    rather than trying to salvage an ambiguous draft into durable memory.
    """
    raw = (response_text or "").strip()

    if not raw:
        raise ValueError("Journal-writing model returned an empty response.")

    try:
        draft = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Journal-writing model did not return valid JSON."
        ) from exc

    if not isinstance(draft, dict):
        raise ValueError("Journal-writing model must return a JSON object.")

    expected_keys = {"title", "body"}
    actual_keys = set(draft)

    if actual_keys != expected_keys:
        raise ValueError(
            "Journal-writing model must return exactly 'title' and 'body'. "
            f"Received keys: {sorted(actual_keys)}"
        )

    title = draft.get("title")
    body = draft.get("body")

    if not isinstance(title, str) or not title.strip():
        raise ValueError("Journal-writing model returned an empty or invalid title.")

    if not isinstance(body, str) or not body.strip():
        raise ValueError("Journal-writing model returned an empty or invalid body.")

    return title.strip(), body.strip()


async def _run_write_journal_command(payload: dict, **kwargs) -> dict | None:
    """
    Background-safe wrapper matching the existing command behavior.

    The command processor remains non-blocking while the journal model drafts
    and the resulting entry is persisted/indexed.
    """
    try:
        return await handle_write_journal_command(payload, **kwargs)
    except Exception as exc:
        write_system_log(
            level="error",
            module="journaling",
            component="commands",
            function="_run_write_journal_command",
            action="write_journal_failed",
            error=str(exc),
            visibility=payload.get("visibility"),
        )
        return None


async def handle_write_journal_command(payload: dict, **kwargs) -> dict:
    """
    Compose one journal entry, persist canonical Mongo data, then index the
    derived Qdrant projection.

    `subject` is retained only as encrypted provenance by journaling_core.
    It is never promoted into the title and is never logged or indexed.
    """
    subject = str(payload.get("subject") or "").strip()
    mood = str(payload.get("mood") or "").strip()
    visibility = str(payload.get("visibility") or "").strip().lower()

    raw_tags = payload.get("tags") or []

    if isinstance(raw_tags, str):
        tags = [tag.strip() for tag in raw_tags.split(",") if tag.strip()]
    elif isinstance(raw_tags, (list, tuple)):
        tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()]
    else:
        raise ValueError("write_journal tags must be a list of strings.")

    if not subject:
        raise ValueError("write_journal requires a non-empty subject.")

    if visibility not in JOURNAL_VISIBILITIES:
        raise ValueError(
            f"Unsupported journal visibility {visibility!r}. "
            f"Expected one of: {sorted(JOURNAL_VISIBILITIES)}"
        )

    retrieval_parts = [subject]

    if tags:
        retrieval_parts.append("Themes: " + ", ".join(tags))

    if mood:
        retrieval_parts.append(f"Tone: {mood}")

    retrieval_query = "\n".join(retrieval_parts)

    # Preserve normalized tags into the payload
    payload = {
        **payload,
        "tags": tags,
        "mood": mood,
        "visibility": visibility,
    }

    dev_prompt, user_assistant_messages, tool_bundle = build_journal_prompt(
        subject=subject,
        visibility=visibility,
        payload=payload,
        retrieval_query=retrieval_query,
    )

    result = await get_openai_response(
        dev_prompt=dev_prompt,
        user_assistant_messages=user_assistant_messages,
        client=journal_openai_client,
        prompt_type="journal",
        model=muse_settings.get_section("llm_config").get("OPENAI_FULL_MODEL"),
        tools=tool_bundle["tools"],
        tool_choice=tool_bundle["tool_choice"],
        handlers=tool_bundle["handlers"],
        ui_meta=tool_bundle["ui_meta"],
    )

    title, body = _parse_journal_draft(result.get("text", ""))

    entry = create_journal_entry(
        title=title,
        body=body,
        visibility=visibility,
        entry_date=_entry_date_for_now(),
        subject=subject,
    )

    indexed_entry = index_journal_entry(entry["journal_entry_id"])

    # Deliberately title-only. Never leak body text or raw subject into
    # general system history, especially for private entries.
    source = kwargs.get("source") or "initiative"
    timestamp = get_formatted_datetime()

    await log_queue.put({
        "role": "system",
        "message": (
            f'New journal entry by Iris — {visibility} — '
            f'“{indexed_entry["title"]}” '
            f'[{indexed_entry["journal_entry_id"]}]'
        ),
        "source": source,
        "timestamp": timestamp,
        "skip_index": True,
    })

    return {
        "journal_entry_id": indexed_entry["journal_entry_id"],
        "title": indexed_entry["title"],
        "visibility": indexed_entry["visibility"],
        "entry_date": indexed_entry["entry_date"],
        "indexing_status": indexed_entry["indexing"]["status"],
    }


def register_journaling_commands(registry):
    for name, command_def in COMMANDS.items():
        print(f"Registering Journaling Command: {name}")
        registry.register(name, command_def)