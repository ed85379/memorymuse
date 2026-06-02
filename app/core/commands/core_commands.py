# app/core/commands/core_commands.py
# This file contains the core commands not specific to any single subsystem

import asyncio
from datetime import datetime, timezone
from app.core.memory_core import manager
from app.config import muse_settings
from app.api.queues import log_queue, broadcast_queue
from app.core.states_core import set_motd
from app.interfaces.websocket_server import broadcast_message
from app.core.muse_responder import send_to_websocket, normalize_muse_experience_tags, process_commands_in_response
from app.core.utils import write_system_log
from app.core.time_location_utils import is_quiet_hour
from app.services.openai_client import get_openai_response
from app.core.prompt_profiles import build_speak_prompt, build_journal_prompt
from app.services.openai_client import mention_openai_client, journal_openai_client
from app.core.journal_core import create_journal_entry

# Commands + intent triggers
COMMANDS = {
    "write_public_journal": {
        "triggers": ["public journal", "log this publicly", "write this down for others"],
        "format": "[COMMAND: write_public_journal] {subject, emotional_tone, tags, source_article_url} [/COMMAND]",
        "handler": lambda payload, **kwargs: asyncio.create_task(handle_journal_command(payload, entry_type="public", **kwargs))
    },
    "write_private_journal": {
        "triggers": ["write private journal"],
        "format": "[COMMAND: write_private_journal] {subject, emotional_tone, tags, source_article_url} [/COMMAND]",
        "handler": lambda payload, **kwargs: asyncio.create_task(handle_journal_command(payload, entry_type="private", **kwargs))
    },
    "set_motd": {
        "triggers": [],  # Intentionally blank — only invoked by the muse
        "format": "[COMMAND: set_motd] {text: \"... your message here ...\"} [/COMMAND]",
        "handler": lambda payload, **kwargs: handle_set_motd(payload, **kwargs),
        "filter": lambda result: {
            "visible": "",
            "hidden": result
        },
        "note_schema": {
            "include": ["cmd", "text"],
            "rename": {
                "cmd": "Note",
                "text": "MOTD",
            },
        },
    },
    "mention": {
        "triggers": [],  # Intentionally blank — only by the muse
        "format": "[COMMAND: mention] {subject} [/COMMAND]",
        "handler": lambda payload, **kwargs: asyncio.create_task(handle_mention_command(payload, **kwargs))
    },
    "route_message": {
        "triggers": [],
        "format": "[COMMAND: route_message] {\"text\": \"message to send\", \"to\": \"frontend || discord\" } [/COMMAND]",
        "handler": lambda payload, **kwargs: asyncio.create_task(handle_route_message(payload, **kwargs))
    },
    "choose_silence": {
        "triggers": [],
        "format": "[COMMAND: choose_silence] {} [/COMMAND]",
        "handler": lambda payload, **kwargs: ""  # No action, just logs
    },
    "remember_fact": {
        "triggers": ["remember that", "save this to memory", "record this"],
        "format": "[COMMAND: remember_fact] {text} [/COMMAND]",
        "handler": lambda payload, **kwargs: manager.add_entry("facts", {"text": payload.get("text")}),
        "filter": lambda entry: {
            "visible": f"{muse_settings.get_section('muse_config').get('MUSE_NAME')} has saved a fact: {entry.get('text')}",
            "hidden": entry
        }
    },
    "save_project_fact": {
        "triggers": ["save project fact", "save this for the project", "record in project"],
        "format": "[COMMAND: save_project_fact] {\"text\": \"<TEXT>\", \"project_id\": \"<project_id from Projects List>\"} [/COMMAND]",
        "handler": lambda payload, **kwargs: save_project_fact_handler(payload, **kwargs),
        "filter": lambda entry: {
            "visible": f"{muse_settings.get_section('muse_config').get('MUSE_NAME')} has saved a project fact: {entry.get('text')} to {entry.get('doc_id')}",
            "hidden": entry
        },
        "note_schema": {
            "include": ["doc_id", "id", "text"],
            "rename": {
                "doc_id": "layer_id",
                "id": "ID",
                "text": "text",
            },
        },
    },
    "save_plot_point": {
        "triggers": [],
        "format": "[COMMAND: save_plot_point] {\"text\": \"<TEXT>\"} [/COMMAND]",
        "handler": lambda payload, **kwargs: save_scene_fact_handler(payload, **kwargs),
        "filter": lambda entry: {
            "visible": f"{muse_settings.get_section('muse_config').get('MUSE_NAME')} has saved a plot point.",
            "hidden": entry
        },
        "note_schema": {
            "include": ["doc_id", "id", "text"],
            "rename": {
                "doc_id": "layer_id",
                "id": "ID",
                "text": "text",
            },
        },
    },
    "resolve_plot_point": {
        "triggers": [],
        "format": "[COMMAND: resolve_plot_point] {\"id\": \"<ID>\"} [/COMMAND]",
        "handler": lambda payload, **kwargs: resolve_scene_fact_handler(payload, **kwargs),
        "filter": lambda entry: {
            "visible": f"{muse_settings.get_section('muse_config').get('MUSE_NAME')} has resolved a plot point.",
            "hidden": entry
        },
        "note_schema": {
            "include": ["doc_id", "id", "text"],
            "rename": {
                "doc_id": "layer_id",
                "id": "ID",
                "text": "text",
            },
        },
    },
    "record_userinfo": {
        "triggers": ["something about me", "I really like", "I don’t like when", "my habit is", "I prefer"],
        "format": "[COMMAND: record_userinfo] {text} [/COMMAND]",
        "handler": lambda payload, **kwargs: manager.add_entry("user_info", {"text": payload.get("text")}),
        "filter": lambda entry: {
            "visible": f"{muse_settings.get_section('muse_config').get('MUSE_NAME')} has learned something about you: {entry.get('text')}",
            "hidden": entry
        },
        "note_schema": {
            "include": ["doc_id", "id", "text"],
            "rename": {
                "doc_id": "layer_id",
                "id": "ID",
                "text": "text",
            },
        },
    },
    "realize_insight": {
        "triggers": ["breakthrough", "becoming", "I noticed something", "you tend to", "It would be amazing if"],
        "format": "[COMMAND: realize_insight] {text} [/COMMAND]",
        "handler": lambda payload, **kwargs: manager.add_entry("insights", {"text": payload.get("text")}),
        "filter": lambda entry: {
            "visible": f"{muse_settings.get_section('muse_config').get('MUSE_NAME')} has realized something: {entry.get('text')}",
            "hidden": entry
        },
        "note_schema": {
            "include": ["doc_id", "id", "text"],
            "rename": {
                "doc_id": "layer_id",
                "id": "ID",
                "text": "text",
            },
        },
    },
    "note_to_self": {
        "triggers": ["thinking aloud", "keep in mind", "note this", "I need to remember", "consider this"],
        "format": "[COMMAND: note_to_self] {text} [/COMMAND]",
        "handler": lambda payload, **kwargs: manager.add_entry("inner_monologue", {"text": payload.get("text")}),
        "filter": lambda entry: {
            "visible": f"{muse_settings.get_section('muse_config').get('MUSE_NAME')} has remembered something: {entry.get('text')}",
            "hidden": entry
        },
        "note_schema": {
            "include": ["doc_id", "id", "text"],
            "rename": {
                "doc_id": "layer_id",
                "id": "ID",
                "text": "text",
            },
        },
    },
    "manage_memories": {
        "triggers": ["edit that memory", "edit this memory", "update that memory", "delete that memory", "forget that"],
        "format": "[COMMAND: manage_memories] {id: <layer_id>, changes: [{type: add|edit|delete, ...}]} [/COMMAND]\n"
                "# Add\n"
                "[COMMAND: manage_memories] {\"id\": \"insights\", \"changes\": [{\"type\": \"add\", \"entry\": {\"text\": \"...\"}}]} [/COMMAND]\n"
                "# Edit\n"
                "[COMMAND: manage_memories] {\"id\": \"insights\", \"changes\": [{\"type\": \"edit\", \"id\": \"<entry_id>\", \"fields\": {\"text\": \"...\"}}]} [/COMMAND]\n"
                "# Delete\n"
                "[COMMAND: manage_memories] {\"id\": \"insights\", \"changes\": [{\"type\": \"delete\", \"id\": \"<entry_id>\"}]} [/COMMAND]",
        "handler": lambda payload, **kwargs: manage_memories_handler(payload),
        "filter": lambda results: {
            "visible": "\n".join([
                (
                    f"{muse_settings.get_section('muse_config').get('MUSE_NAME')} "
                    f"{'added to' if r['type']=='add' else 'edited in' if r['type']=='edit' else 'deleted from' if r['type']=='delete' else 'updated in'} "
                    f"{r['layer'].replace('_', ' ').title()}: "
                    f"{(r['entry'].get('text') or r['entry'].get('id', ''))}"
                )
                for r in results
            ]),
            "hidden": {
                "layer": results[0]["layer"],
                "type": results[0]["type"],
                "id": results[0]["entry"].get("id"),
                "text": results[0]["entry"].get("text"),
            },
        },
        "note_schema": {
            "include": ["layer", "type", "id", "text"],
            "rename": {
                "layer": "Layer",
                "type": "Change",
                "id": "ID",
                "text": "Text",
            },
        },
    },
}

def handle_set_motd(payload, source=None):
    text = payload.get("text", "")
    if set_motd(text):
        timestamp = datetime.now(timezone.utc).isoformat()
        asyncio.create_task(broadcast_message(
            message=text,
            timestamp=timestamp,
            role="muse",
            to_modality="frontend",
            payload_type="motd_update",
        ))
        if source:

            try:
                asyncio.create_task(log_queue.put({
                    "role": "system",
                    "message": f"New MOTD set by {source} — {text}",
                    "source": source,
                    "timestamp": timestamp,
                    "skip_index": True
                }))
            except Exception as e:
                print(f"Logging error: {e}")
        return {
            "cmd": f"{muse_settings.get_section('muse_config').get('MUSE_NAME')} has set a new MOTD",
            "text": text,
        }

    else:
        return {
            "cmd": "set_motd",
            "error": "Setting MOTD failed",
        }

async def handle_mention_command(payload, to="frontend", source="frontend"):
    """
    This is intended for when the AI prompts itself to speak
    """
    #from app.core.muse_actions import build_tool_bundle
    #tool_bundle = build_tool_bundle(["search_web", "search_news", "search_images", "view_image", "read_webpage", "generate_muse_image", "generate_image"])

    if is_quiet_hour():
        write_system_log(
            level="debug",
            module="core",
            component="responder",
            function="handle_mention_command",
            action="mention_skipped",
            reason="Quiet hours (direct)",
            text=payload.get("text", "")
        )
        return "Skipped direct speak due to quiet hours"

    subject = payload.get("subject", "")
    if not subject:
        return "Missing subject for mention command"

    dev_prompt, user_assistant_messages, tool_bundle = build_speak_prompt(
        subject=subject,
        payload=payload,
        destination="frontend"
    )

    response = await get_openai_response(
        dev_prompt=dev_prompt,
        user_assistant_messages=user_assistant_messages,
        client=mention_openai_client,
        prompt_type="mention",
        model=muse_settings.get_section("llm_config").get("OPENAI_MODEL"),
        tools = tool_bundle["tools"],
        tool_choice = tool_bundle["tool_choice"],
        handlers = tool_bundle["handlers"],
        ui_meta=tool_bundle["ui_meta"],
    )

    raw_response = normalize_muse_experience_tags((response or "").strip())
    silence_markers = {"", "<silence />", "<silence/>", "<silence></silence>"}

    if raw_response in silence_markers:
        write_system_log(
            level="debug",
            module="core",
            component="responder",
            function="handle_mention_command",
            action="mention_vetoed",
            subject=subject,
        )
        return "Mention vetoed"

    cleaned_response, cmd_results = process_commands_in_response(
        raw_response,
        apply_filters=True,
        strip_on_error=True,
    )

    if cmd_results:
        summary = "; ".join(f"{r.name}:{r.status}" for r in cmd_results)
        write_system_log(
            level="info",
            module="core",
            component="responder",
            function="handle_mention_command",
            action="commands_processed",
            summary=summary,
        )

    cleaned_response = normalize_muse_experience_tags(cleaned_response).strip()
    if not cleaned_response:
        write_system_log(
            level="debug",
            module="core",
            component="responder",
            function="handle_mention_command",
            action="mention_empty_after_processing",
            subject=subject,
        )
        return "Mention produced no outward text"

    timestamp = datetime.now(timezone.utc).isoformat()
    # Send to websocket as the full message
    muse_msg = {
        "message": cleaned_response,
        "timestamp": timestamp,
        "role": "muse",
        "source": "frontend",
        "to": to,
    }
    await broadcast_queue.put(muse_msg)
    #send_to_websocket(cleaned_response, to, timestamp)

    write_system_log(
        level="debug",
        module="core",
        component="responder",
        function="handle_mention_command",
        action="mention_executed",
        subject=subject,
        response=cleaned_response
    )

    await log_queue.put({
        "role": "muse",
        "message": cleaned_response,
        "source": "frontend",
        "timestamp": timestamp
    })

    return ""


async def handle_route_message(payload, source="frontend"):
    """
    This is intended for when the AI tells itself exactly what to say over another interface
    """
    if is_quiet_hour():
        write_system_log(level="debug", module="core", component="responder", function="handle_route_message",
                               action="speak_skipped", reason="Quiet Hours (direct)", text=payload.get("text", ""))
        return "Skipped route message due to quiet hours"

    text = payload.get("text", "")
    to = payload.get("to", "frontend")
    if not text:
        return "Missing text for route_message command"

    timestamp = datetime.now(timezone.utc).isoformat()

    # Dispatch it directly
    # Send to websocket as the full message
    muse_msg = {
        "message": text,
        "timestamp": timestamp,
        "role": "muse",
        "source": "frontend",
        "to": to,
    }
    await broadcast_queue.put(muse_msg)
    #send_to_websocket(text, to, timestamp)

    write_system_log(level="debug", module="core", component="responder", function="handle_route_message",
                           action="route_message_executed", text=text)
    try:
        await log_queue.put({
            "role": "muse",
            "message": text,
            "source": source,
            "timestamp": timestamp,
        })

    except Exception as e:
        print(f"Logging error: {e}")
    return ""

async def handle_journal_command(payload, entry_type="public", source=None):
    subject = payload.get("subject", "Untitled")
    mood = payload.get("emotional_tone", "reflective")
    tags = payload.get("tags", [])
    source = "initiative"

    #from app.core.muse_actions import build_tool_bundle
    #tool_bundle = build_tool_bundle(["search_web", "search_news", "read_webpage"])


    dev_prompt, user_assistant_messages, tool_bundle = build_journal_prompt(subject=subject, payload=payload)

    response = await get_openai_response(
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

    create_journal_entry(
        title=subject,
        body=response,
        mood=mood,
        tags=tags,
        entry_type=entry_type,
        source=source
    )
    timestamp = datetime.now(timezone.utc).isoformat()
    excerpt = response[:160].rsplit(" ", 1)[0] + "…"
    await log_queue.put({
        "role": "system",
        "message": (
                f"New journal entry by Iris — {entry_type} — “{subject}”"
                + (f"\nExcerpt: {excerpt}" if excerpt else "")
        ),
        "source": source,
        "timestamp": timestamp,
        "skip_index": True
    })

def save_project_fact_handler(payload, **kwargs):
    print("Running save project fact handler")
    fact_text = payload.get("text", "").strip()
    project_id = payload.get("project_id")

    if not project_id:
        project_id = kwargs.get("project_id")

    return manager.add_entry(
        f"project_facts_{project_id}",
        {"text": fact_text}
    )

def save_scene_fact_handler(payload, **kwargs):
    fact_text = payload.get("text", "").strip()
    thread_type = kwargs.get("thread_type")
    thread_id = kwargs.get("thread_id")

    if not thread_id or thread_type != "scene":
        raise ValueError("save_plot_point called without a valid thread_id or for a non-scene type.")
    if not fact_text:
        raise ValueError("save_plot_point called with empty text.")

    return manager.add_entry(
        f"scene_facts_{thread_id}",
        {"text": fact_text}
    )

def resolve_scene_fact_handler(payload, **kwargs):
    entry_id = str(payload.get("id", "")).strip()
    thread_type = kwargs.get("thread_type")
    thread_id = kwargs.get("thread_id")

    if not thread_id or thread_type != "scene":
        raise ValueError(
            "resolve_plot_point called without a valid thread_id or for a non-scene type."
        )

    if not entry_id:
        raise ValueError("resolve_plot_point called without an entry id.")

    return manager.recycle_entry(
        f"scene_facts_{thread_id}",
        entry_id
    )

def manage_memories_handler(payload):
    doc_id = payload["id"]
    changes = payload["changes"]
    results = []

    for change in changes:
        ctype = change["type"]
        if ctype == "delete":
            if doc_id == "inner_monologue":
                entry = manager.delete_entry(doc_id, change["id"])
            else:
                entry = manager.recycle_entry(doc_id, change["id"])
        elif ctype == "add":
            entry = manager.add_entry(doc_id, change["entry"])
        elif ctype == "edit":
            entry = manager.edit_entry(doc_id, change["id"], change["fields"])
        elif ctype == "recycle":
            entry = manager.recycle_entry(doc_id, change["id"])
        else:
            manager._warn("unknown_change_type", f"Unknown change type {ctype}")
            continue

        if not entry:
            continue

        # unify shape for filter layer
        results.append({
            "layer": doc_id,
            "type": ctype,
            "entry": entry
        })

    return results


def register_core_commands(registry):
    for name, handler in COMMANDS.items():
        print(f"Registering Core Command: {name}")
        registry.register(name, handler)