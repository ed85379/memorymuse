# <editor-fold desc="🔧 Imports and Configuration">
import json
import time
import asyncio
import re
from datetime import datetime, timedelta, timezone
from dateutil.parser import parse as parse_datetime
from bson import ObjectId
from bson.errors import InvalidId
from sentence_transformers import SentenceTransformer, util
from app import config
from app.config import muse_config, MONGO_URI, MONGO_DB, MONGO_CONVERSATION_COLLECTION, MONGO_PROJECTS_COLLECTION, \
    MONGO_THREADS_COLLECTION, MONGO_MEMORY_COLLECTION, QDRANT_CONVERSATION_COLLECTION, QDRANT_MEMORY_COLLECTION, SENTENCE_TRANSFORMER_MODEL
from app.core.utils import write_system_log, SOURCES_CHAT, SOURCES_CONTEXT, SOURCES_ALL
from app.core import utils
from app.databases.mongo_connector import mongo, mongo_system
from app.services.openai_client import get_openai_autotags
from app.databases import memory_indexer
from app.api.queues import index_memory_queue
from app.databases.qdrant_connector import delete_point, search_collection, delete_qdrant_message
from app.databases.graphdb_connector import get_graphdb_connector as graphdb
from app.core.states_core import get_active_time_skip_window

# </editor-fold>

# --------------------------
# Setup and Configuration
# --------------------------
# <editor-fold desc="🗂 Directory Setup & Constants">
VALID_ROLES = {"user", "muse", "friend"}
model = SentenceTransformer(SENTENCE_TRANSFORMER_MODEL)


# </editor-fold>

# --------------------------
# Chronicle Logging
# --------------------------
# <editor-fold desc="📝 Logging Functions">
async def log_message(
        role,
        message,
        source="webui",
        metadata=None,
        flags=None,
        user_tags=None,
        timestamp=None,
        project_id=None,
        project_ids=None,
        thread_ids=None,
        message_id=None,
        skip_index: bool = False
):
    """
    Log a message from any source into the Muse system.
    If timestamp is provided (as str or datetime), use/normalize it; otherwise, use now().
    """
    # Normalize timestamp if provided
    if timestamp:
        if isinstance(timestamp, str):
            try:
                timestamp = parse_datetime(timestamp)
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                else:
                    timestamp = timestamp.astimezone(timezone.utc)
            except Exception as e:
                print(f"[timestamp parse error]: {e}")
                timestamp = datetime.now(timezone.utc)
        elif not isinstance(timestamp, datetime):
            # Unknown format, fallback
            print(f"[timestamp type error]: Unrecognized timestamp type: {type(timestamp)}")
            timestamp = datetime.now(timezone.utc)
    else:
        timestamp = datetime.now(timezone.utc)

    # Always auto-tag the message
    try:
        auto_tags = get_openai_autotags(message)
    except Exception as e:
        auto_tags = []
        print(f"[auto-tag error]: {e}")

    log_entry = {
        "timestamp": timestamp,
        "role": role,
        "source": source,
        "message": message,
        "auto_tags": auto_tags,
        "user_tags": [],
        "flags": flags,
        "metadata": metadata or {},
        "updated_on": timestamp
    }
    # Only add if provided (and not None)
    if project_id is not None:
        log_entry["project_id"] = ObjectId(project_id)
    if project_ids is not None:
        log_entry["project_ids"] = project_ids
    if thread_ids is not None:
        log_entry["thread_ids"] = thread_ids


    try:
        if not message_id:
            message_id = memory_indexer.assign_message_id(log_entry)

        log_entry["message_id"] = message_id

        mongo.insert_log(MONGO_CONVERSATION_COLLECTION, log_entry)
        if not skip_index:
            await memory_indexer.build_index(message_id=log_entry["message_id"])
    except Exception as e:
        write_system_log(
            level="error",
            module="core",
            component="memory_core",
            function="log_message",
            action="log_failed",
            error=str(e),
            message=str(json.dumps(log_entry))
        )
        with open("message_backup.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, default=str) + "\n")
    return {"message_id": log_entry["message_id"]}


async def do_import(collection):
    temp_coll = mongo_system.db[collection]
    main_coll = mongo.db[MONGO_CONVERSATION_COLLECTION]

    imported = 0
    total = temp_coll.count_documents({"imported": {"$ne": True}})
    for doc in temp_coll.find({"imported": {"$ne": True}}):
        await log_message(
            role=doc.get("role"),
            message=doc.get("message"),
            source=doc.get("source"),
            timestamp=doc.get("timestamp"),
        )
        temp_coll.update_one({"_id": doc["_id"]}, {"$set": {"imported": True}})
        imported += 1

    mongo_system.db.import_history.update_one(
        {"collection": collection},
        {"$set": {"processing": False, "status": "imported"}}
    )
    print(f"Imported {imported} of {total} messages for {collection}")

def get_message_by_id(message_id: str):
    """
    Fetch a single message document by message_id.
    Returns the document dict or None.
    """
    return mongo.find_one_document(
        MONGO_CONVERSATION_COLLECTION,
        {"message_id": message_id},
    )

def purge_message(message_id: str) -> bool:
    """
    Hard-delete a single message from Qdrant, Memgraph, and Mongo.
    Only operates on messages already marked is_deleted=True.
    Returns True if fully purged, False otherwise.
    """

    # Safety check: only purge soft-deleted messages
    msg = get_message_by_id(message_id)
    if not msg:
        print(f"Purge skipped: {message_id} not found in Mongo.")
        return False

    # Missing is_deleted counts as False / not deletable
    if not msg.get("is_deleted", False):
        print(f"Purge skipped: {message_id} is not soft-deleted (is_deleted != True).")
        return False

    graph = graphdb()
    # Now it’s safe to actually purge
    qdrant_ok = delete_qdrant_message(message_id)
    memgraph_ok = graph.delete_memgraph_message(message_id)

    if qdrant_ok and memgraph_ok:
        mongo_ok = mongo.delete_mongo_message(MONGO_CONVERSATION_COLLECTION, message_id)
        if mongo_ok:
            return True

        print(f"Purge failed at Mongo for {message_id}.")
        return False

    print(f"Purge failed upstream for {message_id}; Mongo delete skipped.")
    return False

async def purge_message_job(message_id: str) -> None:
    # Run the blocking purge in a worker thread
    await asyncio.to_thread(purge_message, message_id)

# </editor-fold>

# --------------------------
# Memory Vector Indexing
# --------------------------
# <editor-fold desc="📚 Memory Vector Indexing">
def get_excluded_project_ids(public: bool = False) -> set:
    query = {"is_hidden": True}

    if public:
        # In public mode, also exclude private projects
        query = {
            "$or": [
                {"is_hidden": True},
                {"is_private": True},
            ]
        }

    projection = {"_id": 1}
    projects = mongo.find_documents(
        collection_name=MONGO_PROJECTS_COLLECTION,
        query=query,
        projection=projection,
    )
    return {p["_id"] for p in projects}

def get_excluded_thread_ids(public: bool = False) -> set:
    query = {"is_hidden": True}

    if public:
        # In public mode, also exclude private projects
        query = {
            "$or": [
                {"is_hidden": True},
                {"is_private": True},
            ]
        }

    projection = {"_id": 0, "thread_id": 1}
    threads = mongo.find_documents(
        collection_name=MONGO_THREADS_COLLECTION,
        query=query,
        projection=projection,
    )
    return {t["thread_id"] for t in threads}

def get_immediate_context(
    n: int = 10,
    hours: int = 0, # Set to 0 to disable time check
    sources=None,
    public: bool = False,
    anchor_message_id: str | None = None,
    thread_id=None,
    before: int | None = None,
    after: int = 0,
    extended_history: bool = False,
    unsummarized_only: bool = True,
):
    """
    Return a list of messages, starting from a moment and working backward.

    Modes:
    - Default recent mode:
        Uses rolling time window from "now" (or anchored "now" if anchor_message_id is provided).
    - Around mode:
        If before is provided with anchor_message_id, returns context around that anchor.
        If after > 0, the effective anchor is shifted forward by `after` matching messages,
        then a backward fetch returns before + after + 1 messages total.

    Notes:
    - `sources` controls which messages are eligible to appear in results.
    - Only chat/conversational messages count toward the returned message total.
    - This allows system/context messages to be interleaved without reducing
      the number of actual conversation turns shown.
    - In around mode, use `sources=utils.SOURCES_CHAT` if you want true conversational windows.
    - Accepts anchor_message_id to start the search, otherwise starts with "now".

    TODO:
    - Add scene_id functionality for Roleplays or other types of bounded sessions.
    """

    if sources is None:
        sources = utils.SOURCES_CHAT
    sources_list = list(sources)

    excluded_project_ids = get_excluded_project_ids(public=public)
    excluded_thread_ids = get_excluded_thread_ids(public=public)

    # Ask states_core what time looks like right now (sync version)
    active_skip, skip_start, skip_end = get_active_time_skip_window(
        excluded_project_ids=excluded_project_ids,
        excluded_thread_ids=excluded_thread_ids,
    )

    def build_base_query():
        q = {
            "is_hidden": {"$ne": True},
            "is_deleted": {"$ne": True},
            "source": {"$in": sources_list},
        }
        if public:
            q["is_private"] = {"$ne": True}
        return q

    def build_project_clause():
        if not excluded_project_ids:
            return None

        excluded = list(excluded_project_ids)
        return {
            "$or": [
                {"project_id": {"$nin": excluded}},
                {"project_id": {"$exists": False}},
                {"project_ids": {"$elemMatch": {"$nin": excluded}}},
            ]
        }

    def build_thread_clause():
        if thread_id:
            return {"thread_ids": thread_id}

        if excluded_thread_ids:
            excluded = list(excluded_thread_ids)
            return {
                "$or": [
                    {"thread_ids": {"$exists": False}},
                    {"thread_ids": {"$size": 0}},
                    {"thread_ids": {"$elemMatch": {"$nin": excluded}}},
                ]
            }

        return None

    def combine_clauses(*parts):
        clauses = [part for part in parts if part]
        return {"$and": clauses} if clauses else {}

    def find_message_by_id(message_id: str):
        return mongo.find_one_document(
            collection_name=MONGO_CONVERSATION_COLLECTION,
            query={"message_id": message_id},
        )

    def find_anchor_message(message_id: str):
        anchor = mongo.find_one_document(
            collection_name=MONGO_CONVERSATION_COLLECTION,
            query={"message_id": message_id},
        )
        if not anchor:
            raise ValueError(f"No message found for id={message_id}")
        return anchor

    def find_thread_doc(thread_id: str):
        return mongo.find_one_document(
            collection_name=MONGO_THREADS_COLLECTION,
            query={"thread_id": str(thread_id)},
        )

    def build_unsummarized_clause():
        if not (unsummarized_only and extended_history and thread_id):
            return None

        thread = find_thread_doc(thread_id)
        if not thread:
            return None
        thread_summary = thread.get("summary", {})

        last_summarized_message_id = thread_summary.get("last_summarized_message_id")
        if not last_summarized_message_id:
            return None

        last_summarized_msg = find_message_by_id(last_summarized_message_id)
        if not last_summarized_msg:
            # Don't break prompt assembly because a stored summary boundary is stale.
            # The caller can still get full extended history.
            return None

        return {
            "timestamp": {"$gt": last_summarized_msg["timestamp"]}
        }

    def resolve_shifted_anchor(anchor: dict, after_count: int):
        if after_count <= 0:
            return anchor

        forward_query = combine_clauses(
            build_base_query(),
            build_project_clause(),
            build_thread_clause(),
            {"timestamp": {"$gte": anchor["timestamp"]}},
        )

        forward_results = mongo.find_documents(
            collection_name=MONGO_CONVERSATION_COLLECTION,
            query=forward_query,
            sort_field="timestamp",
            sort=1,
            limit=after_count + 1,
        )

        if not forward_results:
            return anchor

        return forward_results[-1]

    def build_time_clause(now_value):
        if active_skip and skip_start and skip_end:
            return {
                "$or": [
                    {"timestamp": {"$lte": skip_start}},
                    {"timestamp": {"$gte": skip_end}},
                ]
            }

        if thread_id:
            return {}

        if hours == 0:
            return {}

        since = now_value - timedelta(hours=hours)

        if anchor is not None:
            return {"timestamp": {"$gte": since, "$lte": now_value}}

        return {"timestamp": {"$gte": since}}

    # 1) Establish "now" (or anchored "now")
    anchor = None

    if anchor_message_id is not None:
        anchor = find_anchor_message(anchor_message_id)

    around_mode = anchor is not None and before is not None

    if around_mode:
        anchor = resolve_shifted_anchor(anchor, after)
        now = anchor["timestamp"]
        convo_count = before + after + 1
    elif anchor is not None:
        now = anchor["timestamp"]
        convo_count = n
    else:
        now = datetime.utcnow()
        if extended_history and thread_id:
            convo_count = None
        else:
            convo_count = n

    if extended_history and thread_id:
        overfetch_limit = None  # or a generous safety cap
    else:
        overfetch_limit = max(convo_count * 2, convo_count + 10)

    # 2) Build final query
    base_query = build_base_query()
    project_clause = build_project_clause()
    thread_clause = build_thread_clause()
    time_clause = build_time_clause(now)
    unsummarized_clause = build_unsummarized_clause()

    final_query = combine_clauses(
        base_query,
        project_clause,
        thread_clause,
        time_clause,
        unsummarized_clause,
    )

    # 3) Fetch + post-filter to desired count
    raw_messages = mongo.find_logs(
        collection_name=MONGO_CONVERSATION_COLLECTION,
        query=final_query,
        limit=overfetch_limit,
        sort_field="timestamp",
        ascending=False,
    )

    # Count only conversational/chat messages toward the requested total.
    # Non-chat messages may still appear in the returned slice if included
    # by `sources`, but they do not consume the message budget.
    selected = []
    convo_seen = 0
    if extended_history and thread_id:
        selected = list(reversed(raw_messages))
        return selected

    for msg in raw_messages:
        selected.append(msg)

        if msg.get("source") in utils.SOURCES_CHAT:
            convo_seen += 1
            if convo_seen >= convo_count:
                break

    selected.reverse()
    return selected

def recency_weight(ts, now=None, half_life_hours=36):
    if not ts:
        return 1.0
    if half_life_hours is None or half_life_hours <= 0:
        return 1.0
    if now is None:
        now = datetime.now(timezone.utc).timestamp()

    if isinstance(ts, datetime):
        ts = ts.timestamp()
    elif isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
            ts = ts.timestamp()
        except Exception:
            return 1.0

    age_hours = (now - ts) / 3600
    return 2 ** (-age_hours / half_life_hours)

def tag_weight(payload, tag_boost=1.2, muse_boost=1.15, remembered_boost=2.0, project_boost=1.25):
    score = 1.0
    if payload.get("user_tags"):
        score *= tag_boost
    if payload.get("muse_tags"):
        score *= muse_boost
    if payload.get("remembered"):
        score *= remembered_boost
    if payload.get("project_id"):  # Any non-empty project_id
        score *= project_boost
    return score

def get_payload_project_ids(payload: dict) -> set[str]:
    """
    Return the complete normalized project membership for a Qdrant payload.

    `project_ids` is canonical. `project_id` is included for legacy messages
    and any payloads not yet backfilled.
    """
    raw_project_ids = payload.get("project_ids") or []

    if isinstance(raw_project_ids, str):
        raw_project_ids = [raw_project_ids]

    legacy_project_id = payload.get("project_id")
    if legacy_project_id:
        raw_project_ids.append(legacy_project_id)

    return {str(project_id) for project_id in raw_project_ids if project_id}


def has_project_overlap(project_ids, target_project_ids) -> bool:
    """True when the entry belongs to at least one target project."""
    return bool(set(project_ids) & {str(project_id) for project_id in target_project_ids})


def projects_are_fully_excluded(project_ids, excluded_project_ids) -> bool:
    """
    Exclude only when the entry has project membership and *all* of its
    projects are excluded.

    A global/no-project entry remains eligible.
    """
    project_ids = set(project_ids)
    excluded_project_ids = {str(project_id) for project_id in excluded_project_ids}

    return bool(project_ids) and project_ids.issubset(excluded_project_ids)

def search_indexed_memory(
    query,
    projects_in_focus=None,     # List[str], e.g. ["proj_abc123"]
    blend_ratio=1.0,            # float: 1.0 = hard project focus, 0.1–0.99 = blended
    thread_id=None,
    top_k=10,
    collection_name=QDRANT_CONVERSATION_COLLECTION,
    bias_author_id=None,
    bias_source=None,
    score_boost=0.1,
    source_boost=0.1,
    penalize_muse=False,
    muse_penalty=0.05,
    recency_half_life=48,
    tag_boost=1.2, muse_boost=1.15, remembered_boost=2.0,
    project_boost=1.25, non_project_penalty=0.2,
    thread_boost=1.25,
    public: bool = False,
    start_time=None,
    end_time=None,
):
    """
    Search indexed memory via Qdrant, with Project Focus support.
    """
    if projects_in_focus is None:
        projects_in_focus = []
    #query_vector = model.encode([query])[0]
    overfetch_k = top_k * 5

    QDRANT_COLLECTION = collection_name

    excluded_project_ids = [str(oid) for oid in get_excluded_project_ids(public=public)]
    excluded_thread_ids = get_excluded_thread_ids(public=public)
    query_filter = {
        "must_not": [
            {"key": "is_hidden", "match": {"value": True}},
            {"key": "is_deleted", "match": {"value": True}},
        ]
    }
    if public:
        query_filter["must_not"].append(
            {"key": "is_private", "match": {"value": True}}
        )
    if excluded_project_ids:
        query_filter["must_not"].append(
            {"key": "project_id", "match": {"any": excluded_project_ids}}
        )

    if excluded_thread_ids:
        query_filter["must_not"].append(
            {"key": "thread_ids", "match": {"any": list(excluded_thread_ids)}}
        )

    # Project focus: hard filter for 100%
    if projects_in_focus and blend_ratio == 1.0:
        query_filter["should"] = [
            {"key": "project_id", "match": {"any": projects_in_focus}},
            {"key": "project_ids", "match": {"any": projects_in_focus}},
        ]

    if "must" not in query_filter:
        query_filter["must"] = []

    if start_time is not None or end_time is not None:
        range_filter = {"key": "timestamp", "range": {}}
        if start_time is not None:
            range_filter["range"]["gte"] = start_time
        if end_time is not None:
            range_filter["range"]["lte"] = end_time

        query_filter["must"].append(range_filter)

    #client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    #search_result = client.search(
    #    collection_name=QDRANT_COLLECTION,
    #    query_vector=query_vector.tolist(),
    #    limit=overfetch_k,
    #    query_filter=query_filter
    #)
    search_result = search_collection(collection_name=QDRANT_COLLECTION,
                                 search_query=query,
                                 limit=overfetch_k,
                                 query_filter=query_filter)

    #print("\n[Raw Search Results]")
    #for i, hit in enumerate(search_result[:50]):
    #    pid = hit.payload.get("project_id")
    #    pids = hit.payload.get("project_ids")
    #    print(f"  Result[{i}] id={hit.payload.get('message_id')[:6]}, proj_id={pid}, proj_ids={pids}")

    results = []
    now = time.time()
    for hit in search_result:
        entry = {
            "timestamp": hit.payload.get("timestamp"),
            "message_id": hit.payload.get("message_id"),
            "role": hit.payload.get("role"),
            "source": hit.payload.get("source"),
            "message": hit.payload.get("message"),
            "metadata": hit.payload.get("metadata", {}),
            "score": hit.score,
            "user_tags": hit.payload.get("user_tags"),
            "muse_tags": hit.payload.get("muse_tags"),
            "remembered": hit.payload.get("remembered", False),
            "project_id": hit.payload.get("project_id"),  # legacy visibility
            "project_ids": list(get_payload_project_ids(hit.payload)),
            "thread_ids": hit.payload.get("thread_ids"),
        }
        # Biases
        if bias_author_id and entry["metadata"].get("author_id") == bias_author_id:
            entry["score"] += score_boost
        if bias_source and entry.get("source") == bias_source:
            entry["score"] += source_boost
        if penalize_muse and entry.get("role") == "muse":
            entry["score"] -= muse_penalty

        # Recency & tag weighting
        entry["score"] *= recency_weight(entry["timestamp"], now, half_life_hours=recency_half_life)
        entry["score"] *= tag_weight(entry, tag_boost, muse_boost, remembered_boost, project_boost)
        results.append(entry)

    filtered_results = []
    for entry in results:
        pids = entry.get("project_ids")
        tids = entry.get("thread_ids")

        # Project visibility:
        # Remove an entry only if all of its project memberships are excluded.
        if projects_are_fully_excluded(pids, excluded_project_ids):
            continue

        # Thread filter
        if tids is not None and tids:
            if all(tid in excluded_thread_ids for tid in tids):
                continue

        filtered_results.append(entry)

    if thread_id:
        for i, entry in enumerate(filtered_results):
            tids = entry.get("thread_ids") or []
            if thread_id in tids:
                pre_score = entry["score"]
                entry["score"] *= thread_boost  # e.g. 1.25
                post_score = entry["score"]

                # Optional tiny debug, mirroring the project blend logging
                if i < 5:
                    print(
                        f"[Thread Focus] entry[{i}] id={entry.get('message_id')[:6]}..., "
                        f"thread_match=True, "
                        f"thread_id={thread_id}, "
                        f"tids={tids}, "
                        f"pre={pre_score:.3f}, post={post_score:.3f}"
                    )

    # Project focus blending: only if 10-99% (not hard filter)
    if projects_in_focus and 0.0 < blend_ratio < 1.0:
        # Optional: print blend context
        #print(f"\n[Project Focus Blend] projects_in_focus={projects_in_focus}, blend_ratio={blend_ratio}")
        for i, entry in enumerate(filtered_results):
            project_ids = entry.get("project_ids") or []
            in_focus = has_project_overlap(project_ids, projects_in_focus)
            pre_score = entry["score"]
            if in_focus:
                entry["score"] *= 1 + (blend_ratio * project_boost)
            else:
                entry["score"] *= 1 - (blend_ratio * non_project_penalty)
            post_score = entry["score"]

            # Print a compact summary for first few entries
            if i < 5:  # Avoid log spam
                print(
                    f"  Entry[{i}] id={entry.get('message_id')[:6]}..., "
                    f"in_focus={in_focus}, "
                    f"proj_id={entry.get('project_id')}, "
                    f"proj_ids={project_ids}, "
                    f"pre={pre_score:.3f}, post={post_score:.3f}"
                )
        #print(f"[Project Focus Blend] Sampled {min(len(filtered_results), 5)} of {len(filtered_results)} entries.")

    # At 100% focus, optionally post-filter any stragglers (such as project_ids files) for complete purity:
    if projects_in_focus and blend_ratio == 1.0:
        before = len(filtered_results)
        filtered_results = [
            entry
            for entry in filtered_results
            if has_project_overlap(
                entry.get("project_ids") or [],
                projects_in_focus,
            )
        ]
        after = len(filtered_results)
        print(f"[Hard Project Filter] {after}/{before} entries match projects_in_focus={projects_in_focus}")
        # Optionally print a sample of result IDs
        print("  IDs:", [entry.get("message_id")[:6] for entry in filtered_results[:5]])


    sorted_results = sorted(filtered_results, key=lambda x: x["score"], reverse=True)
    print("[Final Results] Top entries after blending/filtering:")
    for i, entry in enumerate(sorted_results[:5]):
        print(
            f"  Rank {i + 1}: id={entry.get('message_id')[:6]}..., "
            f"score={entry['score']:.3f}, "
            f"proj_id={entry.get('project_id')}, "
            f"proj_ids={entry.get('project_ids')}"
        )

    return sorted_results[:top_k]

def search_memory_semantic(query, project_ids=None, start_time=None, end_time=None, limit=5, public=False):
    from datetime import datetime, time
    from zoneinfo import ZoneInfo
    from app.core.time_location_utils import _load_user_location

    loc = _load_user_location()
    user_tz = ZoneInfo(loc.timezone)

    def normalize_time_for_qdrant(value, *, is_end=False):
        if not value:
            return None

        value = value.rstrip("Z")

        if len(value) == 10:
            # Date-only input: expand to local day boundary.
            local_date = datetime.strptime(value, "%Y-%m-%d").date()
            local_dt = datetime.combine(
                local_date,
                time.max if is_end else time.min,
                tzinfo=user_tz,
            )
        else:
            # Full local datetime input.
            local_dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=user_tz)

        utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")

    start_time_qdrant = normalize_time_for_qdrant(start_time, is_end=False)
    end_time_qdrant = normalize_time_for_qdrant(end_time, is_end=True)

    internal_k = max(20, limit * 5)

    kwargs = {
        "query": query,
        "top_k": internal_k,
        "public": public,
        "recency_half_life": 0,
    }

    if start_time_qdrant:
        kwargs["start_time"] = start_time_qdrant

    if end_time_qdrant:
        kwargs["end_time"] = end_time_qdrant

    if project_ids:
        kwargs["projects_in_focus"] = project_ids
        kwargs["blend_ratio"] = 1.0

    results = search_indexed_memory(**kwargs)

    hydrated = []

    for r in results:
        mid = r.get("message_id")
        if not mid:
            continue

        doc = get_message_by_id(mid)
        if not doc:
            continue

        doc["_semantic_score"] = r.get("score")
        doc["_semantic_meta"] = r

        hydrated.append(doc)

        if len(hydrated) >= limit:
            break

    return hydrated

def get_semantic_episode_context(
    collection_name: str,
    n_recent: int = 6,
    hours: int | None = 0.5,
    similarity_threshold: float = 0.75,
    public=False,
    anchor_message_id: str | None = None,
    proj_code_intensity="mixed"
):
    """
    Return a trimmed list of recent messages forming a 'semantic episode'.

    Logic:
    - Fetch last N recent messages from Mongo (existing helper).
    - Fetch their vectors from Qdrant (by message_id).
    - Sort messages by timestamp ascending.
    - Walk from newest backwards, comparing each message's vector
      to the one immediately before it (episode continuity).
    - Stop when similarity drops below threshold.
    - Return the contiguous tail slice that forms the episode.
    - Accepts an anchor_message_id to start the backward search from there.
    """

    # 1) Get recent messages from Mongo (your existing function)
    recent = get_immediate_context(
        n=n_recent,
        hours=hours if hours is not None else 0.5,
        sources=SOURCES_CHAT,
        public=public,
        anchor_message_id=anchor_message_id
    )

    if not recent:
        return []

    # Ensure chronological order (oldest -> newest)
    recent.sort(key=lambda m: m["timestamp"])

    message_ids = [m["message_id"] for m in recent]

    # 2) Fetch vectors from Qdrant
    query_filter = {
        "must": [
    	    {"key": "message_id", "match": {"any": message_ids}}
    	]
    }

    response = search_collection(collection_name="muse_memory",
                 search_query=None,
                 limit=len(message_ids),
                 query_filter=query_filter,
                 with_payload=True,
                 with_vectors=True)

    id_to_vec: dict[str, list[float]] = {}


    for hit in response:
        payload = hit.payload
        mid = hit.payload.get("message_id")
        vec = hit.vector
        if mid is None or vec is None:
            continue
        id_to_vec[str(mid)] = vec


    # If we somehow have no vectors, just fall back to the raw recent list
    if not id_to_vec:
        return recent

    # 3) Walk backwards, find where the episode "breaks"

    # Start from the newest message and walk backward until similarity breaks.
    # We'll track an index where the contiguous episode starts.
    episode_start_idx = len(recent) - 1  # default: just the last message

    # Work with indices i and i-1
    for i in range(len(recent) - 1, 0, -1):
        curr = recent[i]
        prev = recent[i - 1]

        curr_vec = id_to_vec.get(curr["message_id"])
        prev_vec = id_to_vec.get(prev["message_id"])

        # If either vector is missing, treat it as a break
        if curr_vec is None or prev_vec is None:
            episode_start_idx = i
            break

        sim = util.cos_sim(prev_vec, curr_vec).item()

        if sim < similarity_threshold:
            # Episode starts at the current message (i)
            episode_start_idx = i
            break
        else:
            # Still in the same episode; move the start back one more
            episode_start_idx = i - 1

    # 4) Return the tail slice that forms the episode
    return recent[episode_start_idx:]

def search_indexed_memories(
    query,
    collections_weights,  # e.g., {'main': 0.3, 'project_A': 0.7}
    top_k=10,
    **kwargs
):
    """
    Search multiple Qdrant collections, blend and score results by source.
    """
    results_by_collection = {}
    for collection, weight in collections_weights.items():
        res = search_indexed_memory(
            query=query,
            collection_name=collection,
            top_k=int(top_k * 2),  # Overfetch for dedupe later
            **kwargs
        )
        # Annotate each result with its source and weight for later blending
        for r in res:
            r["_collection"] = collection
            r["_weight"] = weight
        results_by_collection[collection] = res

    # Merge, dedupe by message_id, blend scores
    merged = {}
    for collection, results in results_by_collection.items():
        for r in results:
            mid = r["message_id"]
            # If duplicate, keep the one with highest weighted score
            weighted_score = r["score"] * r["_weight"]
            if mid not in merged or weighted_score > merged[mid]["_blended_score"]:
                r["_blended_score"] = weighted_score
                merged[mid] = r

    # Sort all merged by blended score
    deduped_sorted = sorted(merged.values(), key=lambda x: x["_blended_score"], reverse=True)
    # Return only top_k
    return deduped_sorted[:top_k]


# </editor-fold>



# --------------------------
# MuseCortex Interface
# --------------------------
# <editor-fold desc="🧠 MuseCortex Backends (Mongo + Local)">
try:
    from pymongo import MongoClient, ReturnDocument
    MONGO_ENABLED = True
except ImportError:
    MONGO_ENABLED = False

class MuseCortexInterface:
    def add_memory(self, layer, entry):
        raise NotImplementedError

    def get_memory(self, layer, entry_id):
        raise NotImplementedError

    def edit_memory(self, layer, entry_id, updates):
        raise NotImplementedError

    def delete_memory(self, layer, entry_id):
        raise NotImplementedError

    def get_entries_by_type(self, type_name):
        raise NotImplementedError

    def get_entries(self, query=None):
        raise NotImplementedError

    def add_entry(self, entry):
        raise NotImplementedError

    def edit_entry(self, entry_id, new_data):
        raise NotImplementedError

    def delete_entry(self, entry_id):
        raise NotImplementedError

    def get_all_entries(self):
        raise NotImplementedError

    def search_by_tag(self, tag):
        raise NotImplementedError

    def get_doc(self, id):
        raise NotImplementedError

    def update_doc(self, doc_id, updated_fields):
        raise NotImplementedError

class MongoCortexClient(MuseCortexInterface):
    def __init__(self):
        uri = MONGO_URI
        self.client = MongoClient(uri)
        self.db = self.client[MONGO_DB]
        self.collection = self.db[MONGO_MEMORY_COLLECTION]

    def add_memory(self, layer: str, entry: dict):
        # applies charter rules, timestamps, etc
        return mongo[layer].insert_one(entry)

    def get_memory(self, layer: str, entry_id: str):
        return mongo[layer].find_one({"id": entry_id})

    def edit_memory(self, layer: str, entry_id: str, updates: dict):
        updates["last_updated"] = datetime.utcnow().isoformat()
        return mongo[layer].update_one({"id": entry_id}, {"$set": updates})

    def delete_memory(self, layer: str, entry_id: str):
        return mongo[layer].delete_one({"id": entry_id})

    def get_entries_by_type(self, type_name):
        return list(self.collection.find({"type": type_name}))

    def get_entries(self, query=None):
        if query is None:
            query = {}
        return list(self.collection.find(query))

    def add_entry(self, entry):
        entry["created_at"] = datetime.now(timezone.utc).isoformat()
        self.collection.insert_one(entry)

    def edit_entry(self, entry_id, new_data):
        # Try as ObjectId first, fall back to plain string if it fails
        query = {"_id": None}
        try:
            query["_id"] = ObjectId(entry_id)
        except (InvalidId, TypeError):
            query["_id"] = entry_id
        res = self.collection.update_one(query, {"$set": new_data})
        return res.modified_count > 0

    def delete_entry(self, entry_id):
        query = {"_id": None}
        try:
            query["_id"] = ObjectId(entry_id)
        except (InvalidId, TypeError):
            query["_id"] = entry_id
        res = self.collection.delete_one(query)
        return res.deleted_count > 0

    def get_all_entries(self):
        return list(self.collection.find())

    def search_by_tag(self, tag):
        return list(self.collection.find({"tags": tag}))

    def get_doc(self, doc_id):
        doc = self.collection.find_one({"id": doc_id})
        if not doc:
            # Optionally, initialize a new doc if not found
            doc = {"id": doc_id, "entries": []}
            self.collection.insert_one(doc)
        return doc

    def update_doc(self, doc_id, updated_fields):
        # Only updating the 'entries' field as per your handler
        updated = self.collection.find_one_and_update(
            {"id": doc_id},
            {"$set": updated_fields},
            return_document=ReturnDocument.AFTER
        )
        return updated


# </editor-fold>

# --------------------------
# Cortex Loader
# --------------------------
# <editor-fold desc="⚙️ Cortex Loader and Global Instance">
def get_cortex():
    try:
        return MongoCortexClient()
    except Exception as e:
        print(f"Mongo unavailable: {e}")


# Global instance
cortex = get_cortex()
# </editor-fold>

class MemoryLayerManager:
    def __init__(self, cortex, utils):
        self.cortex = cortex
        self.utils = utils

    def get_entry(self, doc_id: str, entry_id: str):
        doc = self.cortex.get_doc(doc_id)
        for entry in doc['entries']:
            if entry['id'] == entry_id:
                return entry
        return None

    def add_entry(self, doc_id, entry):
        now = datetime.utcnow()
        text = entry.get("text")

        if text:
            # look for an existing entry with identical text
            existing = self.search_entries(
                doc_id,
                mongo_query={"text": {"$regex": re.escape(text)}},
                limit=1,
            )
            if existing:
                existing_entry = existing[0]
                entry_id = existing_entry["id"]

                # “update” with the same text; edit_entry will bump updated_on
                updated = self.edit_entry(doc_id, entry_id, {"text": text})
                self._log(
                    "add_entry_dedupe",
                    f"Deduped text into existing entry {entry_id} in {doc_id}",
                )
                return updated

        # normal add path
        entry['id'] = self.utils.generate_new_id()
        entry['created_on'] = now
        entry['updated_on'] = now
        doc = self.cortex.get_doc(doc_id)
        doc['entries'].append(entry)
        self.cortex.update_doc(doc_id, doc)
        self._log("add_entry", f"Added entry {entry['id']} to {doc_id}")
        # Only index semantically relevant layers
        if doc_id not in ("inner_monologue", "reminders", "scene_facts"):
            asyncio.create_task(index_memory_queue.put(entry['id']))
        # Add the doc_id only after it is done with entry, before returning it
        entry['doc_id'] = doc_id
        return entry

    def edit_entry(self, doc_id, entry_id, fields):
        doc = self.cortex.get_doc(doc_id)
        entry_map = {e['id']: (i, e) for i, e in enumerate(doc['entries'])}
        if entry_id not in entry_map:
            self._warn("edit_entry_failed", f"Missing ID {entry_id}")
            return None
        idx, entry = entry_map[entry_id]
        entry.update(fields)
        entry['updated_on'] = datetime.utcnow()
        doc['entries'][idx] = entry
        self.cortex.update_doc(doc_id, doc)
        self._log("edit_entry", f"Edited entry {entry_id} in {doc_id}")
        if doc_id not in ("inner_monologue", "reminders"):
            asyncio.create_task(index_memory_queue.put(entry['id']))
        # Add the doc_id only after it is done with entry, before returning it
        entry['doc_id'] = doc_id
        return entry

    def recycle_entry(self, doc_id, entry_id):
        return self.edit_entry(doc_id, entry_id, {"is_deleted": True})

    def pin_entry(self, doc_id, entry_id):
        return self.edit_entry(doc_id, entry_id, {"is_pinned": True})

    def delete_entry(self, doc_id, entry_id):
        doc = self.cortex.get_doc(doc_id)
        new_entries = [e for e in doc['entries'] if e['id'] != entry_id]
        if len(new_entries) == len(doc['entries']):
            self._warn("delete_entry_failed", f"Missing ID {entry_id}")
            return None
        doc['entries'] = new_entries
        self.cortex.update_doc(doc_id, doc)
        self._log("delete_entry", f"Deleted entry {entry_id} from {doc_id}")
        if doc_id not in ("inner_monologue", "reminders"):
            delete_point(entry_id, QDRANT_MEMORY_COLLECTION)
        return {
            "id": entry_id,
            "text": "",
            "doc_id": doc_id,
        }

    def search_entries(self, doc_id, mongo_query=None, limit=5):
        """
        Search entries within a given memory layer (e.g., 'reminders') using
        in‑memory filtering from the cortex document. Supports partial text,
        schedule fields, status, skip/ends filters, and optional limit.
        """
        mongo_query = mongo_query or {}
        doc = self.cortex.get_doc(doc_id)
        if not doc:
            self._warn("search_entries_failed", f"Missing doc {doc_id}")
            return []

        results = []
        now = datetime.utcnow()

        for entry in doc.get("entries", []):
            match = True

            # text regex (case‑insensitive)
            if "text" in mongo_query:
                pattern = mongo_query["text"]["$regex"]
                if not re.search(pattern, entry.get("text", ""), re.I):
                    match = False

            # nested schedule match
            for key, val in mongo_query.items():
                if key.startswith("schedule."):
                    field = key.split(".", 1)[1]
                    if entry.get("schedule", {}).get(field) != val:
                        match = False

            # status check
            if "status" in mongo_query:
                if entry.get("status") != mongo_query["status"]:
                    match = False

            # skip_until active
            if "skip_until" in mongo_query:
                cond = mongo_query["skip_until"]
                if "$gte" in cond:
                    if not entry.get("skip_until") or entry["skip_until"] < cond["$gte"]:
                        match = False

            # ends_on expired
            if "ends_on" in mongo_query:
                cond = mongo_query["ends_on"]
                if "$lt" in cond:
                    if not entry.get("ends_on") or entry["ends_on"] >= cond["$lt"]:
                        match = False

            if match:
                results.append(entry)

        # sort newest‑updated first
        results.sort(key=lambda e: e.get("updated_on", datetime.min), reverse=True)
        return results[:limit]

    def _log(self, action, text):
        self.utils.write_system_log(
            level="info", module="core", component="memory_core",
            function="MemoryLayerManager", action=action, text=text
        )

    def _warn(self, action, text):
        self.utils.write_system_log(
            level="warn", module="core", component="memory_core",
            function="MemoryLayerManager", action=action, text=text
        )

manager = MemoryLayerManager(cortex, utils)