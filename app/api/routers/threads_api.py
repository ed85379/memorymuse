# /app/api/routers/threads_api.py

from fastapi import APIRouter, HTTPException, status
from typing import Dict
import httpx
from app.core import threads_core
from app.config import API_URL
from app.databases.mongo_connector import mongo
from app.config import MONGO_MEMORY_COLLECTION


router = APIRouter(prefix="/api/threads", tags=["threads"])


@router.get("/")
def get_threads():
    threads = threads_core.get_threads()
    return {"threads": threads}

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_thread(body: dict):
    thread_id = body.get("thread_id")
    title = body.get("title")
    type = body.get("type")
    try:
        thread = threads_core.create_thread(thread_id=thread_id, title=title, type=type)
        # Strip any internal fields if needed
        thread_response = {
            "thread_id": thread.get("thread_id"),
            "type": thread.get("type", "thread"),
            "title": thread.get("title", ""),
            "is_hidden": thread.get("is_hidden", False),
            "is_private": thread.get("is_private", False),
            "is_archived": thread.get("is_archived", False),
            "created_at": thread.get("created_at"),
            "updated_at": thread.get("updated_at"),
        }

        # Create the companion Scene Facts doc
        scene_facts = {
            "id": f"scene_facts_{thread_id}",
            "type": "scene_layer",
            "thread_id": thread_id,
            "name": "Scene Plot Points",
            "purpose": "Scene-local continuity, planning, hidden state, and plot notes.",
            "max_entries": 50,
            "order": 97,
            "entries": [],
            "created_at": thread.get("created_at"),
            "updated_at": thread.get("updated_at"),
        }
        thread_type = body.get("type") or "thread"
        if thread_type == "scene":
            mongo.insert_one_document(MONGO_MEMORY_COLLECTION, scene_facts)


        return {"thread": thread_response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/{key}")
def edit_thread(key: str, patch_fields: dict):
    try:
        print("PATCH fields received:", patch_fields)
        result = threads_core.edit_thread_fields({"thread_id": key}, patch_fields)
        return {"status": "ok", "key": key, "thread": result}
    except ValueError as e:
        # Bad input or not found
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/{thread_id}")
async def delete_thread_only(thread_id: str) -> Dict:
    """
    Delete the thread, keep messages (just remove the thread_id from them).
    """
    message_ids = threads_core.get_thread_message_ids(thread_id)

    if message_ids:
        # Call existing /api/messages/tag endpoint
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{API_URL}/api/messages/tag",
                json={
                    "message_ids": message_ids,
                    "remove_threads": [thread_id],
                },
            )

    # Finally, delete the thread doc itself
    res = threads_core.delete_thread(thread_id)

    return {
        "thread_deleted": res.deleted_count,
        "messages_updated": len(message_ids),
    }


@router.delete("/{thread_id}/with-messages")
async def delete_thread_and_messages(thread_id: str) -> Dict:
    """
    Delete the thread and soft-delete all its messages.
    """
    message_ids = threads_core.get_thread_message_ids(thread_id)

    if message_ids:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{API_URL}/api/messages/tag",
                json={
                    "message_ids": message_ids,
                    "remove_threads": [thread_id],
                    "is_deleted": True,
                },
            )

    res = threads_core.delete_thread(thread_id)

    return {
        "thread_deleted": res.deleted_count,
        "message_ids": message_ids,
        "messages_updated": len(message_ids),
    }