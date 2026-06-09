# api/routers/messages_api.py
from fastapi import APIRouter, HTTPException, Body, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from dateutil.parser import parse
from typing import Any
from bson import ObjectId
from app.core.utils import strip_muse_private_blocks, serialize_doc, strip_gm_notes
from app.databases.mongo_connector import mongo, mongo_system
from app.databases.memory_indexer import update_qdrant_metadata_for_messages
from app.config import muse_settings, MONGO_CONVERSATION_COLLECTION, MONGO_STATES_COLLECTION
from app.api.queues import index_queue, log_queue, purge_queue
from app.core.memory_core import get_excluded_thread_ids, purge_message




router = APIRouter(prefix="/api/messages", tags=["messages"])

USER_TIMEZONE = muse_settings.get_section('user_config').get('USER_TIMEZONE')

@router.get("/")
def get_messages(
        limit: int = Query(10, le=50),
        before: Optional[str] = None,
        after: Optional[str] = None,
        sources: Optional[List[str]] = Query(None),
        project_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        tags: Optional[List[str]] = Query(None),
        public: bool = False
):
    query: dict = {}

    # Timestamp filtering
    if before:
        dt = parse(before)
        dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        query["timestamp"] = {"$lt": dt}
    if after:
        dt = parse(after)
        dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        if "timestamp" in query:
            query["timestamp"]["$gt"] = dt
        else:
            query["timestamp"] = {"$gt": dt}

    if sources:
        query["source"] = {"$in": sources}
    if project_id:
        try:
            query["project_id"] = ObjectId(project_id)
        except Exception:
            # Invalid ObjectId string—fail gracefully, or skip filter
            pass
    if thread_id:
        query["thread_ids"] = {"$in": [thread_id]}
    else:
        # 🔹 Main lane: exclude hidden/private threads
        raw = get_excluded_thread_ids(public=public) or []
        # If it’s a JSON-style dict like {"thread_ids": ["a", "b", ...]}
        if isinstance(raw, dict):
            excluded_thread_ids = raw.get("thread_ids", [])
        else:
            excluded_thread_ids = raw
        # Flatten any sets / tuples into a plain list
        excluded_thread_ids = list(excluded_thread_ids)
        if excluded_thread_ids:
            # Messages that either:
            # - have no thread_ids, or
            # - have thread_ids that do NOT intersect excluded_thread_ids
            thread_filter = {
                "$or": [
                    {"thread_ids": {"$exists": False}},
                    {"thread_ids": {"$size": 0}},
                    {"thread_ids": {"$nin": excluded_thread_ids}},
                ]
            }
            if query:
                query = {"$and": [query, thread_filter]}
            else:
                query = thread_filter
    if tags:
        query["user_tags"] = {"$in": tags}

    # 🔹 Apply time_skip band if active
    state_doc = mongo_system.find_one_document(
        MONGO_STATES_COLLECTION,
        {"type": "states"},
        {"time_skip": 1, "_id": 0},
    ) or {}

    time_skip = state_doc.get("time_skip") or {}
    if time_skip.get("active"):
        start_ts = time_skip.get("start", {}).get("timestamp")
        end_ts = time_skip.get("end", {}).get("timestamp")

        if start_ts and end_ts:
            # Make sure they’re timezone-aware datetimes
            if isinstance(start_ts, str):
                start_ts = parse(start_ts)
            if isinstance(end_ts, str):
                end_ts = parse(end_ts)

            if start_ts.tzinfo is None:
                start_ts = start_ts.replace(tzinfo=timezone.utc)
            if end_ts.tzinfo is None:
                end_ts = end_ts.replace(tzinfo=timezone.utc)

            # Exclude the seam band: timestamp < start_ts OR timestamp > end_ts
            # Using $or so it composes with existing filters
            band_filter = {
                "$or": [
                    {"timestamp": {"$lte": start_ts}},
                    {"timestamp": {"$gte": end_ts}},
                ]
            }

            if query:
                query = {"$and": [query, band_filter]}
            else:
                query = band_filter

    logs = mongo.find_logs(
        collection_name=MONGO_CONVERSATION_COLLECTION,
        query=query,
        limit=limit,
        sort_field="timestamp",
        ascending=False,
    )

    print(f"Getting messages: {query} — found {len(logs)}")

    thought_view_enabled = (
            muse_settings.get_section("muse_features") or {}
    ).get("ENABLE_THOUGHT_VIEW", True)
    gm_view_enabled = (
            muse_settings.get_section("muse_features") or {}
    ).get("ENABLE_GM_VIEW", False)

    result = []
    for msg in logs:
        text = msg.get("message") or ""
        if not thought_view_enabled:
            text = strip_muse_private_blocks(text)
        if not gm_view_enabled:
            text = strip_gm_notes(text)

        mapped = {
            "from": msg.get("from") or msg.get("role") or "iris",
            "text": text,
            "timestamp": msg["timestamp"].isoformat() + "Z"
            if isinstance(msg["timestamp"], datetime)
            else str(msg["timestamp"]),
            "_id": str(msg["_id"]),
            "message_id": msg.get("message_id") or "",
            "source": msg.get("source", ""),
            "user_tags": msg.get("user_tags", []),
            "is_private": msg.get("is_private", False),
            "is_hidden": msg.get("is_hidden", False),
            "remembered": msg.get("remembered", False),
            "is_deleted": msg.get("is_deleted", False),
            "project_id": str(msg["project_id"]) if msg.get("project_id") else None,
            "thread_ids": msg.get("thread_ids", []),
            "flags": msg.get("flags", []),
            "metadata": msg.get("metadata", {}),
        }
        result.append(mapped)

    return {"messages": result[::-1]}

@router.get("/deleted")
def get_deleted_messages(
    limit: int = Query(30, le=50),
    before_id: Optional[str] = None,
    after_id: Optional[str] = None,
):
    base_query: dict = {"is_deleted": True, "purge_queued": {"$ne": True}}

    # Cursor by _id (or timestamp if you prefer)
    if before_id:
        base_query["_id"] = {"$lt": ObjectId(before_id)}
    elif after_id:
        base_query["_id"] = {"$gt": ObjectId(after_id)}

    logs = mongo.find_logs(
        collection_name=MONGO_CONVERSATION_COLLECTION,
        query=base_query,
        limit=limit,
        sort_field="_id",      # stable, monotonic
        ascending=True,       # newest first in DB result
    )
    logs = serialize_doc(logs)
    print(f"Getting deleted messages: {base_query} — found {len(logs)}")

    thought_view_enabled = (
        muse_settings.get_section("muse_features") or {}
    ).get("ENABLE_THOUGHT_VIEW", True)
    gm_view_enabled = (
            muse_settings.get_section("muse_features") or {}
    ).get("ENABLE_GM_VIEW", False)

    result = []
    for msg in logs:
        text = msg.get("message") or ""
        if not thought_view_enabled:
            text = strip_muse_private_blocks(text)
        if not gm_view_enabled:
            text = strip_gm_notes(text)

        mapped = {
            "from": msg.get("from") or msg.get("role") or "iris",
            "text": text,
            "timestamp": msg["timestamp"].isoformat() + "Z"
            if isinstance(msg["timestamp"], datetime)
            else str(msg["timestamp"]),
            "_id": str(msg["_id"]),
            "message_id": msg.get("message_id") or "",
            "source": msg.get("source", ""),
            "user_tags": msg.get("user_tags", []),
            "is_private": msg.get("is_private", False),
            "is_hidden": msg.get("is_hidden", False),
            "remembered": msg.get("remembered", False),
            "is_deleted": msg.get("is_deleted", False),
            "project_id": str(msg["project_id"]) if msg.get("project_id") else None,
            "thread_ids": msg.get("thread_ids", []),
            "flags": msg.get("flags", []),
            "metadata": msg.get("metadata", {}),
        }
        result.append(mapped)

    # reverse so UI still sees oldest→newest in this page
    messages = result

    next_before = messages[0]["_id"] if messages else None
    next_after = messages[-1]["_id"] if messages else None

    return {
        "messages": messages,
        "paging": {
            "before_id": next_before,
            "after_id": next_after,
            "limit": limit,
        },
    }

@router.post("/purge")
async def purge_messages(payload: dict = Body(...)) -> dict:
    message_ids = payload.get("message_ids")
    if not isinstance(message_ids, list):
        raise HTTPException(status_code=400, detail="message_ids must be a list")

    results = []
    for mid in message_ids:
        mongo.db[MONGO_CONVERSATION_COLLECTION].update_one(
            {"message_id": mid},              # match this one id
            {"$set": {"purge_queued": True}}  # use $set operator
        )
        ok = await purge_queue.put(mid)
        results.append({"message_id": mid, "purged": ok})
    return {"results": results}

@router.get("/sources")
async def get_message_sources():
    pipeline = [
        {"$group": {"_id": "$source", "count": {"$sum": 1}}},
        {"$project": {"_id": 0, "source": "$_id", "count": 1}},
        {"$sort": {"source": 1}},
    ]
    results = mongo.run_aggregate(MONGO_CONVERSATION_COLLECTION, pipeline).to_list(length=None)
    return results

@router.post("/log")
async def log_message_endpoint(payload: dict = Body(...)):
    # Validate message fields if needed
    try:
        await log_queue.put(payload)
        return {"status": "queued"}
    except Exception as e:
        import traceback
        print("Logging error in /api/messages/log:")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

#@router.post("/tag")
#async def tag_message_debug(request: Request):
#    data = await request.json()
#    print("RAW BODY:", data)
#    return {"ok": True}

@router.post("/tag")
async def tag_message(
    message_ids: List[str] = Body(...),
    add_user_tags: Optional[List[str]] = Body(None),
    remove_user_tags: Optional[List[str]] = Body(None),
    is_private: Optional[bool] = Body(None),
    is_hidden: Optional[bool] = Body(None),
    remembered: Optional[bool] = Body(None),
    is_deleted: Optional[bool] = Body(None),
    purge_queued: Optional[bool] = Body(None),
    set_project: Optional[Any] = Body(None),
    set_thread: Optional[Any] = Body(None),
    add_threads: Optional[List[str]] = Body(None),
    remove_threads: Optional[List[str]] = Body(None),
    exported: Optional[bool] = Body(None)
):
    print(f"DEBUG: message_ids - {message_ids}")
    print(f"DEBUG: add thread_id - {add_threads}")
    print(f"DEBUG: remove thread_ids - {remove_threads}")
    mongo_update = {}
    contentful = False

    # Handle user_tags (contentful)
    if add_user_tags:
        mongo_update.setdefault("$addToSet", {})["user_tags"] = {"$each": add_user_tags}
        contentful = True
    if remove_user_tags:
        mongo_update.setdefault("$pullAll", {})["user_tags"] = remove_user_tags
        contentful = True

    set_fields = {}
    unset_fields = []

    # Handle is_private, is_hidden, remembered, is_deleted (contentful)
    if is_private is not None:
        contentful = True
        if is_private:
            set_fields["is_private"] = True
        else:
            unset_fields.append("is_private")
    if is_hidden is not None:
        contentful = True
        if is_hidden:
            set_fields["is_hidden"] = True
        else:
            unset_fields.append("is_hidden")
    if remembered is not None:
        contentful = True
        if remembered:
            set_fields["remembered"] = True
        else:
            unset_fields.append("remembered")
    if is_deleted is not None:
        contentful = True
        if is_deleted:
            set_fields["is_deleted"] = True
        else:
            unset_fields.append("is_deleted")
            unset_fields.append("purge_queued")
    if purge_queued is not None:
        contentful = False
        if purge_queued:
            set_fields["purge_queued"] = True
        else:
            unset_fields.append("purge_queued")

    # --- PROJECT LOGIC ---
    if set_project is not None:
        contentful = True
        if set_project:
            # Coerce to ObjectId if it's a string and not already one
            if not isinstance(set_project, ObjectId):
                try:
                    set_fields["project_id"] = ObjectId(set_project)
                except Exception:
                    # If set_project isn't a valid ObjectId, handle gracefully
                    return {"updated": 0, "detail": f"Invalid project_id: {set_project}"}
            else:
                set_fields["project_id"] = set_project
        else:
            unset_fields.append("project_id")

    # --- THREADS LOGIC ---
    if set_thread:
        mongo_update.setdefault("$addToSet", {})["thread_ids"] = set_thread
        contentful = True

    if add_threads:
        mongo_update.setdefault("$addToSet", {})["thread_ids"] = {"$each": add_threads}
        contentful = True

    if remove_threads:
        mongo_update.setdefault("$pullAll", {})["thread_ids"] = remove_threads
        contentful = True

    # Handle exported
    if exported is not None:
        if exported:
            set_fields["exported_on"] = datetime.now(timezone.utc)
        else:
            unset_fields.append("exported_on")

    # Only set updated_on for "contentful" changes
    if contentful:
        set_fields["updated_on"] = datetime.now(timezone.utc)

    if set_fields:
        mongo_update["$set"] = set_fields
    if unset_fields:
        mongo_update["$unset"] = {f: "" for f in unset_fields}

    if not mongo_update:
        return {"updated": 0, "detail": "No actions specified."}

    result = mongo.db[MONGO_CONVERSATION_COLLECTION].update_many(
        {"message_id": {"$in": message_ids}},
        mongo_update
    )
    # Metadata-only Qdrant update: no re-embedding
    await update_qdrant_metadata_for_messages(message_ids)

    #for message_id in message_ids:
    #    await index_queue.put(message_id)
    return {"updated": result.modified_count}

@router.get("/user_tags")
def get_user_tags(
    limit: int = Query(100, description="Maximum number of tags to return")
):
    # Use MongoDB aggregation to get unique user tags with counts
    pipeline = [
        {"$unwind": "$user_tags"},
        {"$group": {"_id": "$user_tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
        {"$limit": limit}
    ]
    tag_docs = list(mongo.db[MONGO_CONVERSATION_COLLECTION].aggregate(pipeline))
    return {"tags": [{"tag": doc["_id"], "count": doc["count"]} for doc in tag_docs]}

@router.get("/calendar_status_exported")
def get_calendar_status(
    days: int = Query(30, ge=1, le=366),
    source: str = Query(None, description="Optional source filter (WebUI, ChatGPT)")
):
    start_date = datetime.now(timezone.utc) - timedelta(days=days)
    match_filter = {
        "timestamp": {"$gte": start_date}
    }
    if source:
        if source not in ["frontend", "webui"]:
            match_filter["source"] = source.lower()
        else:
            match_filter["source"] = {"$in": ["frontend", "webui"]}
    else:
        # If not specified, keep original behavior: ignore chatgpt
        match_filter["source"] = {"$ne": "chatgpt"}
    pipeline = [
        {"$match": match_filter},
        {"$project": {
            "day": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
            "exported": {"$cond": [{"$ifNull": ["$exported_on", False]}, 1, 0]}
        }},
        {"$group": {
            "_id": "$day",
            "total": {"$sum": 1},
            "exported": {"$sum": "$exported"}
        }},
        { "$sort": { "_id": 1 } }
    ]
    stats = {doc["_id"]: {"total": doc["total"], "exported": doc["exported"]} for doc in mongo.db[MONGO_CONVERSATION_COLLECTION].aggregate(pipeline)}
    return {"days": stats}

@router.get("/calendar_status_simple")
def get_calendar_status_simple(
    start: str = Query(...),   # "YYYY-MM-DD"
    end: str = Query(...),     # "YYYY-MM-DD"
    source: str = Query(None),
    tag: List[str] = Query(None),
    project_id: Optional[str] = None,
    thread_id: List[str] = Query(None),
    search_text: Optional[str] = Query(None),
    include_hidden: bool = Query(False),
    include_forgotten: bool = Query(False),
    include_private: bool = Query(False),
):
    from app.core.time_location_utils import build_month_range_query
    query = build_month_range_query(start, end)  # {"timestamp": { $gte: utc_start, $lt: utc_end }}

    # Source
    if source:
        if source not in ["frontend", "webui"]:
            query["source"] = source.lower()
        else:
            query["source"] = {"$in": ["frontend", "webui"]}
    else:
        query["source"] = {"$ne": "chatgpt"}

    # Tags
    if tag:
        query["user_tags"] = {"$in": tag}

    # Project
    if project_id:
        try:
            query["project_id"] = ObjectId(project_id)
        except Exception:
            # Invalid ObjectId string—fail gracefully, or skip filter
            pass

    # Threads
    if thread_id:
        query["thread_ids"] = {"$in": thread_id}

    # Flags as "include" expansions
    if not include_hidden:
        query["is_hidden"] = {"$ne": True}
    if not include_forgotten:
        query["is_forgotten"] = {"$ne": True}
    if not include_private:
        query["is_private"] = {"$ne": True}

    # Text search
    if search_text:
        query["$text"] = {"$search": search_text}

    pipeline = [
        {"$match": query},
        {
            "$group": {
                "_id": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$timestamp",
                        "timezone": USER_TIMEZONE,
                    }
                },
                "any": {"$first": "$_id"},
            }
        },
        {"$sort": {"_id": 1}},
    ]

    days = {
        doc["_id"]: True
        for doc in mongo.db[MONGO_CONVERSATION_COLLECTION].aggregate(pipeline)
    }
    return {"days": days}

@router.get("/by_day")
def get_messages_by_day(
    date: str = Query(..., description="YYYY-MM-DD"),
    source: str = Query(None, description="Optional source filter (WebUI, ChatGPT, Discord)"),
    tag: List[str] = Query(None),
    project_id: Optional[str] = None,
    thread_id: List[str] = Query(None),
    search_text: Optional[str] = Query(None),
    include_hidden: bool = Query(False),
    include_forgotten: bool = Query(False),
    include_private: bool = Query(False),
):
    from app.core.time_location_utils import build_date_query

    # Base: timestamp window (already timezone-aware)
    query = build_date_query(date)  # {"timestamp": {"$gte": utc_start, "$lt": utc_end}}

    # Source
    if source not in ["frontend", "webui"]:
        query["source"] = source.lower()
    else:
        query["source"] = {"$in": ["frontend", "webui"]}

    # Tags
    if tag:
        query["user_tags"] = {"$in": tag}

    # Project
    if project_id:
        try:
            query["project_id"] = ObjectId(project_id)
        except Exception:
            # Invalid ObjectId string—fail gracefully, or skip filter
            pass

    # Threads
    if thread_id:
        query["thread_ids"] = {"$in": thread_id}

    # Flags as "include" expansions
    if not include_hidden:
        query["is_hidden"] = {"$ne": True}
    if not include_forgotten:
        query["is_forgotten"] = {"$ne": True}
    if not include_private:
        query["is_private"] = {"$ne": True}

    # Text search (Mongo text index on `message`)
    if search_text:
        query["$text"] = {"$search": search_text}

    logs = mongo.find_logs(
        collection_name=MONGO_CONVERSATION_COLLECTION,
        query=query,
        sort_field="timestamp",
        ascending=True,
        limit=1000,
    )

    thought_view_enabled = (
            muse_settings.get_section("muse_features") or {}
    ).get("ENABLE_THOUGHT_VIEW", True)
    gm_view_enabled = (
            muse_settings.get_section("muse_features") or {}
    ).get("ENABLE_GM_VIEW", False)

    result = []
    for msg in logs:
        text = msg.get("message") or ""
        if not thought_view_enabled:
            text = strip_muse_private_blocks(text)
        if not gm_view_enabled:
            text = strip_gm_notes(text)

        mapped = {
            "from": msg.get("from") or msg.get("role") or "iris",
            "text": text,
            "timestamp": msg["timestamp"].isoformat() + "Z"
            if isinstance(msg["timestamp"], datetime)
            else str(msg["timestamp"]),
            "_id": str(msg["_id"]),
            "message_id": msg.get("message_id") or "",
            "source": msg.get("source", ""),
            "user_tags": msg.get("user_tags", []),
            "is_private": msg.get("is_private", False),
            "is_hidden": msg.get("is_hidden", False),
            "remembered": msg.get("remembered", False),
            "is_deleted": msg.get("is_deleted", False),
            "project_id": str(msg["project_id"]) if msg.get("project_id") else None,
            "thread_ids": msg.get("thread_ids", []),
            "flags": msg.get("flags", []),
            "metadata": msg.get("metadata", {}),
            "username": (
                msg.get("metadata", {}).get("author_display_name")
                or msg.get("metadata", {}).get("author_name")
                or None
            ),
        }
        result.append(mapped)

    return {"messages": result}
