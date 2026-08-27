# states_core.py
from datetime import datetime, timezone
from typing import Dict, Any
import asyncio
import humanize
from app.config import muse_settings, MONGO_STATES_COLLECTION, MONGO_CONVERSATION_COLLECTION
from app.api.queues import log_queue
from app.databases.mongo_connector import mongo_system, mongo
from app.databases.memory_indexer import assign_message_id


SOURCES_CHAT = ["frontend", "webui", "discord", "chatgpt"]


STATES_DOC = "states"

def get_states_doc():
    filter_query = {"type": STATES_DOC}
    states_doc = mongo_system.find_one_document(
        MONGO_STATES_COLLECTION,
        query=filter_query,
        projection=None,
    )
    return states_doc

def get_active_project_state():
    filter_query = {"type": STATES_DOC}
    projection = {"_id": 0, "projects": 1}

    state_doc = mongo_system.find_one_document(
        MONGO_STATES_COLLECTION,
        query=filter_query,
        projection=projection
    ) or {}

    return state_doc.get("projects", {})

def get_per_project_states():
    filter_query = {"type": STATES_DOC}
    projection = {"_id": 0, "projects.per_project": 1}

    per_projects_doc = mongo_system.find_one_document(
        MONGO_STATES_COLLECTION,
        query=filter_query,
        projection=projection
    )
    return per_projects_doc

def extract_pollable_states() -> dict:
    """
    From the full `states` doc, return only the top-level fields
    whose value is a dict with `pollable: True`.
    """
    states_doc = mongo_system.find_one_document(
        MONGO_STATES_COLLECTION,
        {"type": STATES_DOC},
        projection=None,
    ) or {}

    if not states_doc:
        return {}

    pollable = {}
    for key, value in states_doc.items():
        # skip metadata / type markers
        if key in ("_id", "type"):
            continue

        if isinstance(value, dict) and value.get("pollable") is True:
            pollable[key] = value

    return pollable

def set_active_project(project_id: str):
    filter_query = {"type": STATES_DOC}
    projection = {"projects": 1}

    state_doc = mongo_system.find_one_document(
        MONGO_STATES_COLLECTION,
        query=filter_query,
        projection=projection,
    )

    # If doc doesn't exist, create it with exactly what we were given
    if not state_doc:
        new_doc = {
            "type": "states",
            "projects.project_id": project_id,
            "projects.default_project_settings": { "auto_assign": True, "blend_ratio": 0.5 }
        }
        mongo_system.insert_one_document(MONGO_STATES_COLLECTION, new_doc)

        return {
            "project_id": {
                "changed": True,
                "previous": None,
                "current": project_id,
            },
        }

    # Ensure fields exist even on legacy docs
    stored_project_id = (state_doc.get("projects") or {}).get("project_id")

    updates: Dict[str, Any] = {}
    changes: Dict[str, Dict[str, Any]] = {}

    # --- project_id ---
    if stored_project_id != project_id:
        updates["projects.project_id"] = project_id
        changes["project_id"] = {
            "changed": True,
            "previous": stored_project_id,
            "current": project_id,
        }
    else:
        changes["project_id"] = {
            "changed": False,
            "previous": stored_project_id,
            "current": stored_project_id,
        }

    if updates:
        mongo_system.update_one_document(
            MONGO_STATES_COLLECTION,
            filter_query=filter_query,
            update_data=updates,
        )

    return changes


def set_project_states(project_id: str, updates: dict) -> bool:
    """
    Partially update states.projects.per_project[project_id] with the given fields.

    Example:
      project_id = "68743eebc6c3ad0a405db259"
      updates = {"auto_assign": False, "blend_ratio": 0.7}
    """
    if not isinstance(updates, dict) or not updates:
        return False
    if not project_id:
        return False

    # Build the per_project.* keys
    per_project_prefix = f"projects.per_project.{project_id}"
    set_fields = {
        f"{per_project_prefix}.{k}": v
        for k, v in updates.items()
    }

    # Just $set these fields; no $setOnInsert, no upsert
    result = mongo_system.update_one_document(
        MONGO_STATES_COLLECTION,
        {"type": STATES_DOC},
        set_fields,
    )

    # If no doc matched, result will be None
    return bool(result)

def set_motd(text: str):
    """
    Sets the MOTD message that appears in the UI
    """
    if not text:
        return False
    now = datetime.now(timezone.utc)
    result = mongo_system.update_one_document(
        MONGO_STATES_COLLECTION,
        {"type": STATES_DOC},
        {"motd.text": text, "motd.updated_on": now},
    )

    return bool(result)

async def create_time_skip(message_id: str):
    from app.core.time_location_utils import ensure_aware_utc
    time_start_mid = message_id
    # Find timestamp from message_id
    start_msg = mongo.find_one_document(
        MONGO_CONVERSATION_COLLECTION,
        { "message_id": time_start_mid },
        { "timestamp": 1, "project_id": 1, "_id": 0 }
    )
    if not start_msg:
        return  # or raise/log, but don’t continue
    # Pull the timestamp for the states doc
    start_ts = start_msg.get("timestamp")
    # Normalize to aware UTC datetime
    start_ts_utc = ensure_aware_utc(start_ts)
    # Pull the project_id for setting the active project
    project_id = start_msg.get("project_id")

    # Generate end message_id and message
    end_timestamp = datetime.now(timezone.utc)

    htime = humanize.naturaltime(start_ts_utc, when=end_timestamp)
    source = "system"
    role = "system"
    message = (
        f"{muse_settings.get_section('user_config').get('USER_NAME')} has returned to a previous conversation from {htime}.\n"
        "The previous messages will appear to be from the past, but consider them directly preceding "
        "the following messages."
    )
    # Build msg dict to get the end message_id
    msg = {
        "source": source,
        "role": role,
        "timestamp": end_timestamp,
        "message": message,
    }
    time_end_mid = assign_message_id(msg)

    # Create the message in the Mongo conversation log
    try:
        await log_queue.put({
            "role": role,
            "message": message,
            "source": source,
            "timestamp": end_timestamp,
            "skip_index": True
        })
    except Exception as e:
        print(f"Logging error: {e}")

    # Add time_skip anchor state doc
    set_fields = {
        "time_skip.pollable": True,
        "time_skip.start.message_id": time_start_mid,
        "time_skip.start.timestamp": start_ts,
        "time_skip.end.message_id": time_end_mid,
        "time_skip.end.timestamp": end_timestamp,
        "time_skip.active": True
    }
    mongo_system.update_one_document(
        MONGO_STATES_COLLECTION,
        {"type": STATES_DOC},
        set_fields,
    )

    # Set the active project_id for the UI
    if project_id is not None:
        mongo_system.update_one_document(
            MONGO_STATES_COLLECTION,
            {"type": STATES_DOC},
            {"projects.project_id": str(project_id)},
        )
    return True

def get_active_time_skip_window(
    excluded_project_ids=None,
    excluded_thread_ids=None,
):
    """
    Return (active, start_ts, end_ts) for the current time_skip,
    after applying the auto-expire rule.
    """
    state = mongo_system.find_one_document(
        MONGO_STATES_COLLECTION,
        {"type": STATES_DOC},
        {"time_skip": 1, "_id": 0},
    )
    time_skip = (state or {}).get("time_skip") or {}
    if not time_skip.get("active"):
        return False, None, None

    start_ts = time_skip.get("start", {}).get("timestamp")
    end_ts = time_skip.get("end", {}).get("timestamp")
    if not end_ts:
        return False, None, None

    # Hard-coded freshness limit to match Chat scrollback
    EXPIRE_AFTER_N = 30
    query =  {
            "timestamp": {"$gt": end_ts},
            "is_deleted": {"$ne": True},
            "is_hidden": {"$ne": True},
            "source": {"$in": SOURCES_CHAT}
    }
    # Project scope
    if excluded_project_ids:
        excluded = list(excluded_project_ids)
        project_scope = [
            {"project_id": {"$nin": excluded}},
            {"project_id": {"$exists": False}},
            {"project_ids": {"$elemMatch": {"$nin": excluded}}},
        ]
    else:
        project_scope = []

    # Thread scope (messages have thread_ids: [..])
    thread_scope = []
    if excluded_thread_ids:
        excluded_t = list(excluded_thread_ids)
        thread_scope.append({"thread_ids": {"$nin": excluded_t}})
        # If you ever add a single `thread_id` field, we’d mirror that here.

    if project_scope or thread_scope:
        query["$and"] = []
        if project_scope:
            query["$and"].append({"$or": project_scope})
        if thread_scope:
            query["$and"].extend(thread_scope)

    recent_count = mongo.count_logs(
        MONGO_CONVERSATION_COLLECTION,
        query,
    )
    print(f"DEBUG: RECENT COUNT: {recent_count}")

    if recent_count > EXPIRE_AFTER_N:
        clear_time_skip()
        return False, None, None

    return True, start_ts, end_ts

def clear_time_skip():
    # 1) Grab current time_skip block
    state = mongo_system.find_one_document(
        MONGO_STATES_COLLECTION,
        {"type": STATES_DOC},
        {"time_skip": 1, "_id": 0},
    )
    time_skip = (state or {}).get("time_skip", {})
    end_mid = time_skip.get("end", {}).get("message_id")

    # 2) Clear the active flag
    mongo_system.update_one_document(
        MONGO_STATES_COLLECTION,
        {"type": STATES_DOC},
        {"time_skip.active": False},
    )

    # 3) Soft-delete the end system message, if present
    if end_mid:
        mongo.update_one_document(
            MONGO_CONVERSATION_COLLECTION,
            {"message_id": end_mid},
            {"is_deleted": True},
        )

def update_thread_state(payload: dict):
    allowed_keys = {"open_thread_id"}
    updates = {}

    for key, value in payload.items():
        if key not in allowed_keys:
            continue

        if key == "open_thread_id":
            # allow None to clear
            if value is not None and not isinstance(value, str):
                raise ValueError("open_thread_id must be a string or null.")
            updates["threads.open_thread_id"] = value


    if not updates:
        raise ValueError("No valid thread state fields to update.")

    updated = mongo_system.update_one_document(
        collection_name=MONGO_STATES_COLLECTION,
        filter_query={"type": STATES_DOC},  # your fixed states doc locator
        update_data=updates
    )

    return updated.get("threads", {})

def update_nav_state(payload: dict):
    allowed_keys = {"main_tab", "tools_panel_tab"}
    updates = {}

    for key, value in payload.items():
        if key not in allowed_keys:
            continue

        if key == "main_tab":
            # allow None to clear
            if value is not None and not isinstance(value, str):
                raise ValueError("main_tab must be a string or null.")
            updates["nav.main_tab"] = value

        elif key == "tools_panel_tab":
            if value is not None and not isinstance(value, str):
                raise ValueError("tools_panel_tab must be a string or null.")
            updates["nav.tools_panel_tab"] = value

    if not updates:
        raise ValueError("No valid nav state fields to update.")

    updated = mongo_system.update_one_document(
        collection_name=MONGO_STATES_COLLECTION,
        filter_query={"type": STATES_DOC},  # your fixed states doc locator
        update_data=updates
    )

    return updated.get("nav", {})

def update_files_state(payload: dict):
    allowed_keys = {"source_type", "asset_type", "lifecycle_status", "order_by", "project_mode", "page_size"}
    updates = {}

    for key, value in payload.items():
        if key not in allowed_keys:
            continue

        if value is not None and not isinstance(value, (str, int)):
            raise ValueError(f"{key} must be a string, integer, or null.")
        updates[f"files.{key}"] = value

    if not updates:
        raise ValueError("No valid files state fields to update.")

    updated = mongo_system.update_one_document(
        collection_name=MONGO_STATES_COLLECTION,
        filter_query={"type": STATES_DOC},  # your fixed states doc locator
        update_data=updates
    )

    return updated.get("files", {})

def update_game_state(payload: dict):
    allowed_keys = {"open_game_id", "muse_plan"}
    updates = {}

    for key, value in payload.items():
        if key not in allowed_keys:
            continue

        if key == "open_game_id":
            # allow None to clear
            if value is not None and not isinstance(value, str):
                raise ValueError("open_game_id must be a string or null.")
            updates["games.open_game_id"] = value

        if key == "muse_plan":
            # allow None to clear
            if value is not None and not isinstance(value, str):
                raise ValueError("muse_plan must be a string or null.")
            updates["games.muse_plan"] = value

    if not updates:
        raise ValueError("No valid game state fields to update.")

    updated = mongo_system.update_one_document(
        collection_name=MONGO_STATES_COLLECTION,
        filter_query={"type": STATES_DOC},  # your fixed states doc locator
        update_data=updates
    )

    return updated.get("games", {})