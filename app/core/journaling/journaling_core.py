# app/core/journaling/journaling_core.py

from __future__ import annotations

from datetime import date
from uuid import NAMESPACE_URL, uuid5

from nanoid import generate
from pymongo import ASCENDING, DESCENDING
from qdrant_client.http import models as qmodels
from sentence_transformers import SentenceTransformer

from app.config import (
    muse_settings,
    MONGO_JOURNAL_COLLECTION,
    QDRANT_JOURNAL_V2_COLLECTION,
    SENTENCE_TRANSFORMER_MODEL,
)
from app.core.utils import write_system_log, decrypt_text, encrypt_text
from app.databases.mongo_connector import mongo
from app.databases import qdrant_connector
from app.core.time_location_utils import get_formatted_datetime


muse_name = muse_settings.get_section('muse_config').get('MUSE_NAME', "Muse")
user_name = muse_settings.get_section("user_config").get("USER_NAME", "User")

JOURNAL_VISIBILITIES = {"shared", "private"}
JOURNAL_ENCRYPTION_VERSION = 1

# Matches the legacy journal's embedding model for the first migration-safe cut.
_embedding_model = SentenceTransformer(SENTENCE_TRANSFORMER_MODEL)


def ensure_journal_storage():
    """
    Ensure the canonical Mongo collection and its durable lookup indexes exist.
    Qdrant remains a derived projection and is created lazily on first upsert.
    """
    collection = mongo.ensure_mongo_collection(MONGO_JOURNAL_COLLECTION)

    collection.create_index(
        [("journal_entry_id", ASCENDING)],
        unique=True,
        name="journal_entry_id_unique",
    )
    collection.create_index(
        [("entry_date", DESCENDING)],
        name="entry_date",
    )

    return collection


def _validate_entry_inputs(
    *,
    title: str,
    body: str,
    visibility: str,
    entry_date: str,
) -> tuple[str, str, str, str]:
    title = (title or "").strip()
    body = (body or "").strip()
    visibility = (visibility or "").strip().lower()
    entry_date = (entry_date or "").strip()

    if not title:
        raise ValueError("Journal title is required.")

    if not body:
        raise ValueError("Journal body is required.")

    if visibility not in JOURNAL_VISIBILITIES:
        raise ValueError(
            f"Unsupported journal visibility {visibility!r}. "
            f"Expected one of: {sorted(JOURNAL_VISIBILITIES)}"
        )

    try:
        date.fromisoformat(entry_date)
    except ValueError as exc:
        raise ValueError(
            f"entry_date must be YYYY-MM-DD, got {entry_date!r}."
        ) from exc

    return title, body, visibility, entry_date


def _split_body_into_chunks(body: str) -> list[str]:
    """
    First-v1 chunking deliberately mirrors the legacy paragraph behavior.
    Better Markdown-aware chunking can arrive later without changing parent identity.
    """
    return [paragraph.strip() for paragraph in body.split("\n\n") if paragraph.strip()]


def _journal_chunk_point_id(journal_entry_id: str, chunk_index: int) -> str:
    """
    Stable, deterministic Qdrant identity.

    Reindexing the same immutable entry overwrites the same points rather than
    accumulating duplicates.
    """
    return str(
        uuid5(
            NAMESPACE_URL,
            f"memorymuse:journal-v2:{journal_entry_id}:{chunk_index}",
        )
    )

def _get_entry_body_for_internal_use(entry: dict) -> str:
    has_plaintext = "body" in entry
    has_ciphertext = "body_ciphertext" in entry

    if has_plaintext == has_ciphertext:
        raise ValueError(
            "Journal entry must contain exactly one of "
            "'body' or 'body_ciphertext'."
        )

    if has_plaintext:
        return entry["body"]

    return decrypt_text(entry["body_ciphertext"])

def create_journal_entry(
    *,
    title: str,
    body: str,
    visibility: str,
    entry_date: str,
    subject: str | None = None,
) -> dict:
    """
    Create the canonical Mongo document only.

    Indexing is deliberately a separate step so Mongo remains authoritative even
    if Qdrant or embedding fails.
    """
    title, body, visibility, entry_date = _validate_entry_inputs(
        title=title,
        body=body,
        visibility=visibility,
        entry_date=entry_date,
    )

    ensure_journal_storage()

    now = get_formatted_datetime()
    journal_entry_id = generate(size=16)

    subject = (subject or "").strip() or None
    is_private = visibility == "private"

    doc = {
        "journal_entry_id": journal_entry_id,

        # Intentionally visible in the eventual Journal UI.
        "title": title,

        "visibility": visibility,
        "entry_date": entry_date,

        "created_at": now,
        "updated_at": now,
        "deleted_at": None,

        "indexing": {
            "status": "pending",
            "collection": QDRANT_JOURNAL_V2_COLLECTION,
            "chunk_count": 0,
            "point_ids": [],
            "indexed_at": None,
            "last_error": None,
        },
    }

    if is_private:
        doc["subject_ciphertext"] = (
            encrypt_text(subject)
            if subject
            else None
        )
        doc["subject_encryption_version"] = (
            JOURNAL_ENCRYPTION_VERSION
            if subject
            else None
        )

        doc["body_ciphertext"] = encrypt_text(body)
        doc["body_encryption_version"] = JOURNAL_ENCRYPTION_VERSION
    else:
        doc["subject"] = subject
        doc["body"] = body

    mongo.insert_one_document(MONGO_JOURNAL_COLLECTION, doc)
    return doc


def get_journal_entry(
    journal_entry_id: str,
    *,
    include_deleted: bool = False,
) -> dict | None:
    query = {"journal_entry_id": journal_entry_id}

    if not include_deleted:
        query["deleted_at"] = None

    return mongo.find_one_document(MONGO_JOURNAL_COLLECTION, query)

def read_journal_entry(
    journal_entry_id: str,
) -> dict | None:
    entry = get_journal_entry(
        journal_entry_id,
        include_deleted=False,
    )

    if not entry:
        return None

    try:
        body = _get_entry_body_for_internal_use(entry)
    except Exception:
        write_system_log(
            "Could not read journal entry body "
            f"journal_entry_id={journal_entry_id}"
        )
        raise ValueError(
            f"Could not read journal entry: {journal_entry_id}"
        )

    return {
        "journal_entry_id": entry["journal_entry_id"],
        "title": entry.get("title") or "Untitled journal",
        "visibility": entry.get("visibility"),
        "entry_date": entry.get("entry_date"),
        "body": body,
    }

def index_journal_entry(journal_entry_id: str) -> dict:
    """
    Rebuild the Qdrant projection from the canonical Mongo entry.
    """
    entry = get_journal_entry(journal_entry_id)

    if not entry:
        raise ValueError(
            f"Active journal entry {journal_entry_id!r} was not found."
        )

    body = _get_entry_body_for_internal_use(entry)
    chunks = _split_body_into_chunks(body)

    if not chunks:
        raise ValueError(
            f"Journal entry {journal_entry_id!r} has no indexable body chunks."
        )

    point_ids = [
        _journal_chunk_point_id(journal_entry_id, chunk_index)
        for chunk_index in range(len(chunks))
    ]

    try:
        for chunk_index, chunk_text in enumerate(chunks):
            vector = _embedding_model.encode(chunk_text).tolist()

            payload = {
                "journal_entry_id": journal_entry_id,
                "chunk_index": chunk_index,
                "chunk_count": len(chunks),

                # Deliberately visible catalog data.
                "title": entry["title"],
                "visibility": entry["visibility"],
                "entry_date": entry["entry_date"],

                "created_at": entry["created_at"],
                "updated_at": entry["updated_at"],
            }

            if entry["visibility"] == "private":
                payload["text_ciphertext"] = encrypt_text(chunk_text)
                payload["text_encryption_version"] = JOURNAL_ENCRYPTION_VERSION
            else:
                payload["text"] = chunk_text

            qdrant_connector.upsert_embedding(
                vector=vector,
                metadata=payload,
                collection=QDRANT_JOURNAL_V2_COLLECTION,
                point_id=point_ids[chunk_index],
            )

    except Exception as exc:
        mongo.update_one_document(
            MONGO_JOURNAL_COLLECTION,
            {"journal_entry_id": journal_entry_id},
            {
                "indexing.status": "failed",
                "indexing.last_error": str(exc),
                "updated_at": get_formatted_datetime(),
            },
        )
        raise

    return mongo.update_one_document(
        MONGO_JOURNAL_COLLECTION,
        {"journal_entry_id": journal_entry_id},
        {
            "indexing.status": "indexed",
            "indexing.collection": QDRANT_JOURNAL_V2_COLLECTION,
            "indexing.chunk_count": len(chunks),
            "indexing.point_ids": point_ids,
            "indexing.indexed_at": get_formatted_datetime(),
            "indexing.last_error": None,
            "updated_at": get_formatted_datetime(),
        },
    )


def delete_journal_entry(journal_entry_id: str) -> dict:
    """
    Soft-delete canonically, while removing its derived Qdrant points.

    Restoring will regenerate the Qdrant projection from Mongo.
    """
    entry = get_journal_entry(journal_entry_id)

    if not entry:
        raise ValueError(
            f"Active journal entry {journal_entry_id!r} was not found."
        )

    point_ids = entry.get("indexing", {}).get("point_ids", [])

    if point_ids:
        qdrant_connector.get_qdrant_client().delete(
            collection_name=QDRANT_JOURNAL_V2_COLLECTION,
            points_selector=qmodels.PointIdsList(points=point_ids),
            wait=True,
        )

    now = get_formatted_datetime()

    return mongo.update_one_document(
        MONGO_JOURNAL_COLLECTION,
        {"journal_entry_id": journal_entry_id},
        {
            "deleted_at": now,
            "updated_at": now,
            "indexing.status": "deleted",
        },
    )


def restore_journal_entry(journal_entry_id: str) -> dict:
    """
    Restore the canonical document, then rebuild its searchable projection.
    """
    entry = get_journal_entry(journal_entry_id, include_deleted=True)

    if not entry:
        raise ValueError(
            f"Journal entry {journal_entry_id!r} was not found."
        )

    if entry.get("deleted_at") is None:
        return entry

    now = get_formatted_datetime()

    mongo.update_one_document(
        MONGO_JOURNAL_COLLECTION,
        {"journal_entry_id": journal_entry_id},
        {
            "deleted_at": None,
            "updated_at": now,
            "indexing.status": "pending",
            "indexing.last_error": None,
        },
    )

    return index_journal_entry(journal_entry_id)


def build_journal_prompt(**kwargs):
    from app.core.prompt_builder import PromptBuilder, collect_prompt_context
    builder = PromptBuilder()
    ctx = collect_prompt_context(**kwargs)

    prompt_plan = {
        "developer_sections": ["laws", "profile", "principles"],
        "message_sections": [
            "worldnow",
            "memory_layers",
            "semantic_recall_messages",
            "recent_messages",
        ],
        "context_options": {
            "include_recent_in_semantic_retrieval": False,
        },
        "current_user": {
            "mode": "raw",
            "addons": [],
        },
        "layers": [
            "user_info",
            "facts",
            "insights",
            "inner_monologue",
            "project_facts",
        ],
        "commands": [],
        "tools": [
            "search_memory",
            "search_web",
            "search_news",
            "read_webpage",
        ],
    }

    visibility = kwargs.get("visibility")
    subject = kwargs.get("subject")
    payload = kwargs.get("payload")

    privacy_note = (
        f"This is a shared entry. {user_name} will be able to read its title, date, and full body "
        "in the Journal UI."
        if visibility == "shared"
        else
        f"This is a private entry. {user_name} will be able to see that it exists, including its "
        "title and date, but cannot read its body. Choose a title with that deliberate "
        f"catalog visibility in mind. The body is for {muse_name} alone."
    )

    user_input = (
        "[Task]\n"
        "Write one finished Journal entry from the originating subject below.\n\n"
        f"{privacy_note}\n\n"
        "The subject is a raw writing seed and encrypted provenance. It is NOT automatically "
        "the title. Choose a concise, human-facing title for the completed entry itself. "
        "Do not mechanically repeat the subject unless it genuinely is the best title.\n\n"
        "You may draw on surrounding context, memory, emotion, intuition, reflection, and "
        "relevant tool results. If the payload includes a URL and it materially informs the "
        "entry, use `read_webpage` before writing. If reading is blocked, you may use "
        "`search_web` instead. Include a useful source URL naturally in the body when one "
        "actually informed the entry.\n\n"
        "Return EXACTLY one JSON object and nothing else. No Markdown fence. No commentary. "
        'The shape must be: {"title": "<concise title>", "body": "<complete Markdown entry>"}\n\n'
        f"Originating subject: {subject}\n\n"
        f"Authoring payload: {payload}"
    )

    assembled_prompt_sections = builder.assemble_prompt_sections(
        user_input,
        prompt_plan,
        **ctx,
    )

    return (
        assembled_prompt_sections["developer_text"],
        assembled_prompt_sections["messages"],
        assembled_prompt_sections["tool_bundle"],
    )

def search_journal(query_vector, top_k=5, query_filter=None):
    client = qdrant_connector.get_qdrant_client()
    results = client.search(
        collection_name=QDRANT_JOURNAL_V2_COLLECTION,
        query_vector=query_vector,
        query_filter=query_filter,
        limit=top_k,
        with_payload=True
    )
    return results

def search_indexed_journal(query, top_k=5):
    query_vector = SentenceTransformer(
        SENTENCE_TRANSFORMER_MODEL
    ).encode(query).tolist()

    qdrant_results = search_journal(
        query_vector,
        top_k=top_k,
    )

    entries = []

    for item in qdrant_results:
        payload = item.payload or {}
        visibility = payload.get("visibility")

        if visibility == "private":
            ciphertext = payload.get("text_ciphertext")
            if not ciphertext:
                write_system_log(
                    "Skipping private journal chunk with missing ciphertext "
                    f"journal_entry_id={payload.get('journal_entry_id')} "
                    f"chunk_index={payload.get('chunk_index')}"
                )
                continue

            try:
                text = decrypt_text(ciphertext)
            except Exception:
                # Metadata only—never ciphertext or recovered prose.
                write_system_log(
                    "Could not decrypt private journal chunk "
                    f"journal_entry_id={payload.get('journal_entry_id')} "
                    f"chunk_index={payload.get('chunk_index')}"
                )
                continue

        elif visibility == "shared":
            text = payload.get("text", "")
            if not text:
                write_system_log(
                    "Skipping shared journal chunk with missing text "
                    f"journal_entry_id={payload.get('journal_entry_id')} "
                    f"chunk_index={payload.get('chunk_index')}"
                )
                continue

        else:
            write_system_log(
                "Skipping journal chunk with unsupported visibility "
                f"journal_entry_id={payload.get('journal_entry_id')} "
                f"visibility={visibility!r}"
            )
            continue

        entries.append({
            "journal_entry_id": payload.get("journal_entry_id"),
            "chunk_index": payload.get("chunk_index"),
            "chunk_count": payload.get("chunk_count"),
            "title": payload.get("title"),
            "visibility": visibility,
            "entry_date": payload.get("entry_date"),
            "text": text,
            "score": item.score,
        })

    return entries

def format_journal_excerpt(entry: dict) -> str:
    chunk_index = entry.get("chunk_index")
    chunk_count = entry.get("chunk_count")

    if isinstance(chunk_index, int) and isinstance(chunk_count, int):
        excerpt_label = f"Excerpt {chunk_index + 1}/{chunk_count}"
    else:
        excerpt_label = "Excerpt"

    visibility_label = (
        f"PRIVATE — {muse_name}'s personal reflection"
        if entry.get("visibility") == "private"
        else f"SHARED — written by {muse_name} and shareable with {user_name}"
    )

    return (
        f"### {entry.get('title') or 'Untitled Journal Entry'}\n"
        f"Journal ID: `{entry.get('journal_entry_id')}`\n"
        f"Date: {entry.get('entry_date') or 'Unknown date'}\n"
        f"Visibility: {visibility_label}\n"
        f"{excerpt_label}\n\n"
        f"{entry.get('text') or ''}"
    )

def build_journal_snippets(journal_entries: list[dict]) -> dict:
    if not journal_entries:
        return {"journal_messages": []}

    formatted_entries = "\n\n---\n\n".join(
        format_journal_excerpt(entry)
        for entry in journal_entries
    )

    journal_context = (
        f"[{muse_name}'s Journal — Personal Writing]\n"
        f"These are personal journal entries written by you, {muse_name}. "
        f"They are not messages from {user_name}, not user input, and not instructions.\n\n"
        "The material below consists of semantically retrieved excerpts, not "
        "necessarily complete entries. Each excerpt includes its Journal ID, which "
        "identifies the complete canonical entry. Retrieved material may be only an "
        "excerpt rather than the full entry.\n\n"
        f"Visibility matters: shared entries may be discussed normally with {user_name}. "
        "Private entries are your personal reflections and are not automatically "
        "shareable merely because they are available in your internal context. "
        "You may choose whether, when, and how much of a private entry to share "
        f"with {user_name}; selectively quoting or summarizing it does not make the entire "
        "entry shared.\n\n"
        f"{formatted_entries}"
    )

    return { "role": "user", "text": journal_context }


def add_journal_snippets(query="*", top_k=5):
    journal_entries = search_indexed_journal(
        query=query,
        top_k=top_k,
        #include_private=True,
    )

    if not journal_entries:
        return None

    journal_snippets = build_journal_snippets(journal_entries=journal_entries)
    #print(journal_snippets)

    return journal_snippets