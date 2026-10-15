import os
import json
from sentence_transformers import SentenceTransformer
from app.config import muse_settings, QDRANT_JOURNAL_COLLECTION, SENTENCE_TRANSFORMER_MODEL, JOURNAL_DIR, JOURNAL_CATALOG_PATH
from app.databases import qdrant_connector
from app.core import utils
from app.core.time_location_utils import get_formatted_datetime

# ----------------------
# Qdrant Search Helper
# ----------------------


def search_journal(query_vector, top_k=5, query_filter=None):
    client = qdrant_connector.get_qdrant_client()
    results = client.search(
        collection_name=QDRANT_JOURNAL_COLLECTION,
        query_vector=query_vector,
        query_filter=query_filter,
        limit=top_k,
        with_payload=True
    )
    return results


# ----------------------
# Utilities
# ----------------------

def load_journal_index():
    with open(JOURNAL_CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_journal_index(index):
    with open(JOURNAL_CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

def ensure_journal_dir():
    os.mkdir(JOURNAL_DIR)
    #JOURNAL_DIR.mkdir(parents=True, exist_ok=True)

def load_journal_catalog():
    with open(JOURNAL_CATALOG_PATH, "r") as f:
        return json.load(f)

def save_journal_catalog(entries):
    with open(JOURNAL_CATALOG_PATH, "w") as f:
        json.dump(entries, f, indent=2)

def format_journal_entry(t):
    entry_date = t.get("entry_date", "Unknown date")
    title = t.get("title") or "Untitled"
    body = t.get("text", "")

    chunk_index = t.get("chunk_index", 0) + 1
    chunk_count = t.get("chunk_count", "?")

    return (
        f"Date: {entry_date}\n"
        f"Title: {title}\n"
        f"Journal Entry ID: {t.get('journal_entry_id')}\n"
        f"Paragraph {chunk_index}/{chunk_count}\n"
        f"{body}"
    )

# ----------------------
# Search Function
# ----------------------

def search_indexed_journal(query, top_k=5, include_private=False):
    query_vector = SentenceTransformer(SENTENCE_TRANSFORMER_MODEL).encode(query).tolist()
    results = []

    qdrant_results = search_journal(query_vector, top_k=top_k)

    for item in qdrant_results:
        payload = item.payload or {}
        if not include_private and payload.get("entry_type") == "private":
            continue
        results.append({
            "entry_id": payload.get("entry_id"),
            "paragraph_index": payload.get("paragraph_index"),
            "text": payload.get("text", ""),
            "mood": payload.get("mood"),
            "tags": payload.get("tags"),
            "score": item.score,
            "entry_type": payload.get("entry_type"),
            "timestamp": payload.get("timestamp")
        })
    return results



# ----------------------
# Core Function
# ----------------------

def create_journal_entry(title, body, mood="reflective", tags=None, entry_type="public", source="manual"):
    #ensure_journal_dir()
    now = get_formatted_datetime()
    slug = utils.slugify(title)
    filename = f"{now.replace(':', '-').replace('.', '-')}_{slug}.md"
    filepath = f"{JOURNAL_DIR}/{filename}"

    if tags is None:
        tags = []

    encrypted = False
    encrypted_body = body
    if entry_type == "private":
        if not muse_settings.get_section('muse_features').get('ENABLE_PRIVATE_JOURNAL'):
            raise Exception("Private journal entries are disabled in config.")
        encrypted_body = utils.encrypt_text(body)
        encrypted = True

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(encrypted_body)

    # Basic summary: first non-empty line
    summary_line = next((line.strip() for line in body.splitlines() if line.strip()), "")

    catalog = load_journal_catalog()
    catalog.append({
        "title": title,
        "mood": mood,
        "tags": tags,
        "source": source,
        "datetime": now,
        "date": now.split("T")[0],
        "filename": filename,
        "entry_type": entry_type,
        "encrypted": encrypted,
        "summary": summary_line
    })
    save_journal_catalog(catalog)

    # Chunk, embed, index (private and public both included)
    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    for i, paragraph in enumerate(paragraphs):
        vector = SentenceTransformer(SENTENCE_TRANSFORMER_MODEL).encode(paragraph).tolist()
        metadata = {
            "entry_id": filename,
            "paragraph_index": i,
            "entry_type": entry_type,
            "mood": mood,
            "tags": tags,
            "source": source,
            "timestamp": now,
            "text": paragraph
        }
        # Only Qdrant indexing now!
        qdrant_connector.upsert_embedding(
            vector=vector,
            metadata=metadata,
            collection=QDRANT_JOURNAL_COLLECTION
        )
