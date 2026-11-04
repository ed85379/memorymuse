# /app/core/threads_core.py
from typing import List, Dict
import json
from app.core.utils import generate_new_id
from app.core.time_location_utils import get_local_human_time
from datetime import datetime
from app.core.utils import serialize_doc
from app.databases.mongo_connector import (
    mongo,
)
from app.config import MONGO_CONVERSATION_COLLECTION, MONGO_THREADS_COLLECTION


def get_threads():
    mongo.ensure_mongo_collection(collection_name=MONGO_THREADS_COLLECTION)
    query = {}
    projection = {"_id": 0}
    threads = mongo.find_documents(
        collection_name=MONGO_THREADS_COLLECTION,
        query=query,
        projection=projection
    )
    results = []
    for thread in threads:
        mapped = {
            "thread_id": thread.get("thread_id"),
            "type": thread.get("type") or "thread",
            "title": thread.get("title") or "",
            "is_hidden": thread.get("is_hidden", False),
            "is_private": thread.get("is_private", False),
            "is_archived": thread.get("is_archived", False),
            "created_at": str(thread.get("created_at", None)),
            "updated_at": str(thread.get("updated_at", None)),
            "guidance": thread.get("guidance", None),
            "scene": thread.get("scene", None),
        }
        results.append(mapped)
    return results


def get_thread_message_ids(thread_id: str):
    """
    Return a list of message_ids that belong to the given thread_id.
    """
    documents = mongo.find_documents(MONGO_CONVERSATION_COLLECTION, {"thread_ids": thread_id}, {"message_id": 1, "_id": 0})
    return [doc["message_id"] for doc in documents]


def get_thread_message_count(thread_id: str) -> int:
    """
    Return a count of messages that belong to the given thread_id.
    Useful for ThreadManager UI.
    """
    return mongo.count_matching_documents(MONGO_CONVERSATION_COLLECTION, {"thread_ids": thread_id})

def get_thread_type(thread_id: str):
    thread_doc = mongo.find_one_document(MONGO_THREADS_COLLECTION, {"thread_id": thread_id})
    return thread_doc.get("type") or "thread"

def create_thread(thread_id=None, title=None, type="thread"):
    mongo.ensure_mongo_collection(collection_name=MONGO_THREADS_COLLECTION)
    now = datetime.utcnow()
    if thread_id is None:
        thread_id = generate_new_id()
    default_title = f"Thread - {get_local_human_time(time_format='thread')}"
    thread = {
        "thread_id": thread_id,
        "type": type,
        "title": title or default_title,
        "is_hidden": False,
        "is_private": False,
        "is_archived": False,
        "created_at": now,
        "updated_at": now
    }
    try:
        mongo.insert_one_document(MONGO_THREADS_COLLECTION, thread)
        # Return the stored representation (you can strip _id in the API if needed)
        return thread
    except Exception as e:
        print(f"Error creating thread: {e}")
        # Let the caller decide how to surface this
        raise

def edit_thread_fields(filter_query, patch_fields):
    thread = mongo.find_one_document(collection_name=MONGO_THREADS_COLLECTION, query=filter_query)
    if not thread:
        raise ValueError("Thread not found")
    updates = {}
    # Validate and set title
    if "title" in patch_fields:
        raw_title = patch_fields["title"]
        if raw_title is None:
            raise ValueError("Title cannot be null.")
        title = str(raw_title).strip()
        if not title:
            raise ValueError("Title must be at least 1 non-space character.")
        updates["title"] = title[:40]
    if "tags" in patch_fields:
        tags = patch_fields["tags"]
        # Only keep non-empty, trimmed strings, limit length of each tag and total number
        cleaned_tags = [str(t)[:24].strip() for t in tags if str(t).strip()]
        updates["tags"] = cleaned_tags[:10]  # e.g., max 10 tags of max 24 chars each
    if "guidance" in patch_fields:
        raw_guidance = patch_fields["guidance"]

        if raw_guidance is None:
            updates["guidance"] = None
        elif not isinstance(raw_guidance, str):
            raise ValueError("guidance must be a string or null.")
        else:
            guidance = raw_guidance.strip()
            updates["guidance"] = guidance[:4000] or None
    if "is_hidden" in patch_fields:
        is_hidden = patch_fields["is_hidden"]
        updates["is_hidden"] = is_hidden
    if "is_private" in patch_fields:
        is_private = patch_fields["is_private"]
        updates["is_private"] = is_private
    if "is_archived" in patch_fields:
        is_archived = patch_fields["is_archived"]
        updates["is_archived"] = is_archived
    if "summary" in patch_fields:
        summary = patch_fields["summary"]

        if summary is not None:
            if not isinstance(summary, dict):
                raise ValueError("summary must be an object or null.")

            summary_text = summary.get("summary_text")
            if not isinstance(summary_text, str) or not summary_text.strip():
                raise ValueError("summary.summary_text must be a non-empty string.")

            last_id = summary.get("last_summarized_message_id")
            if not isinstance(last_id, str) or not last_id.strip():
                raise ValueError("summary.last_summarized_message_id must be a non-empty string.")

            reference_points = summary.get("reference_points", [])
            if not isinstance(reference_points, list):
                raise ValueError("summary.reference_points must be a list.")

        updates["summary"] = summary
    if "scene" in patch_fields:
        scene = patch_fields["scene"]

        if scene is None:
            updates["scene"] = None
        else:
            if not isinstance(scene, dict):
                raise ValueError("scene must be an object or null.")

            cleaned_scene = {
                "premise": "",
                "nsfw": False,
                "fields": [],
            }

            if "premise" in scene:
                cleaned_scene["premise"] = str(scene.get("premise") or "").strip()

            if "nsfw" in scene:
                nsfw = scene["nsfw"]
                if not isinstance(nsfw, bool):
                    raise ValueError("scene.nsfw must be a boolean.")
                cleaned_scene["nsfw"] = nsfw

            if "fields" in scene:
                fields = scene["fields"]

                if fields is None:
                    cleaned_scene["fields"] = []
                elif not isinstance(fields, list):
                    raise ValueError("scene.fields must be a list.")
                else:
                    cleaned_fields = []

                    for field in fields:
                        if not isinstance(field, dict):
                            raise ValueError("Each scene.fields item must be an object.")

                        field_id = str(field.get("id") or "").strip()
                        key = str(field.get("key") or "").strip()
                        value = str(field.get("value") or "").strip()

                        # Drop entirely blank rows.
                        if not field_id and not key and not value:
                            continue

                        cleaned_field = {
                            "id": field_id[:80],
                            "key": key[:80],
                            "value": value,
                        }

                        cleaned_fields.append(cleaned_field)

                    cleaned_scene["fields"] = cleaned_fields

            updates["scene"] = cleaned_scene
    if updates:
        updates["updated_at"] = datetime.utcnow()
    if not updates:
        raise ValueError("No valid fields to update.")

    updated = mongo.update_one_document(
        collection_name=MONGO_THREADS_COLLECTION,
        filter_query=filter_query,
        update_data=updates
    )
    if updated and "thread_id" in updated:
        updated["thread_id"] = updated["thread_id"]
    return serialize_doc(updated)

def apply_thread_summary(thread_id: str, response_text: str, extended_history_meta: dict):
    payload = json.loads(response_text)

    summary_text = str(payload["summary_text"]).strip()
    last_id = extended_history_meta["last_message_id"]
    reference_points = payload.get("reference_points", [])

    if not summary_text:
        raise ValueError("summary_text is required")
    if not last_id:
        raise ValueError("last_summarized_message_id is required")
    if not isinstance(reference_points, list):
        raise ValueError("reference_points must be a list")

    return edit_thread_fields(
        {"thread_id": thread_id},
        {
            "summary": {
                "summary_text": summary_text,
                "last_summarized_message_id": last_id,
                "reference_points": reference_points,
                "updated_at": datetime.utcnow(),
            }
        }
    )

def delete_thread(thread_id):
    return mongo.delete_one_document(MONGO_THREADS_COLLECTION, {"thread_id": thread_id})