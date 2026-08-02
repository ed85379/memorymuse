# MemoryMuse Asset Model

## Purpose

An **asset** is a durable MemoryMuse record for a file, image, generated artifact, or externally sourced resource.

Assets are first-class objects. They are not owned by a project, thread, message, or indexing system. Those systems may **reference** an asset, but the asset retains its own identity, storage state, provenance, lifecycle, presentation metadata, and optional retrieval projections.

This document defines the current asset contract and the invariants future code should preserve.

---

## Core principles

1. **`asset_id` / `_id` is the durable identity of an asset.**  
   It survives renames, reuse, indexing, lifecycle changes, deletion, and byte purging.

2. **An asset is not owned by a thread or message.**  
   Messages, conversation attachments, prompt injections, scene state, and indexing records point to assets. Assets do not accumulate `thread_ids`.

3. **Current MemoryMuse-owned bytes are described by `storage`.**  
   Original upload locations and public URLs are provenance—not canonical storage.

4. **Only currently available bytes participate in hash-based deduplication.**  
   A purged or deleted asset must not be silently returned as a usable duplicate merely because an old hash remains in its record.

5. **URL deduplication precedes byte/hash deduplication for URL ingestion.**  
   If an incoming public URL matches a living asset's original provenance URL, reuse that asset without downloading it again. Otherwise, download the content and check its content hash.

6. **Provenance is immutable initial-origin metadata.**  
   The canonical asset records how it first entered MemoryMuse. Later deduplicated reuse does not append every additional message, URL, or ingestion event to the provenance record.

7. **`source_type` is origin classification, not prompt-library membership.**  
   It answers *how did this asset enter MemoryMuse?* It does not answer whether the asset is eligible for ordinary prompt injection.

8. **`injection_enabled` is explicit curation state.**  
   It answers whether an asset belongs on the ordinary prompt-injection shelf. It is separate from provenance, lifecycle, storage, and indexing.

9. **`project_ids` are optional scope metadata, not ownership.**  
   An empty list means the asset is general/unscoped—not orphaned or broken.

10. **Indexing is derived projection work, not the asset itself.**  
    An asset may have no indexing, conversation-recall indexing, one or more project-document indexes, or future indexing targets. Those projections may be rebuilt or removed while the asset remains intact.

11. **Asset deletion and byte purging are distinct operations.**  
    A deleted asset may retain its durable record and metadata. A purged asset no longer has usable stored bytes.

---

## Asset document shape

```python
{
    "_id": asset_id,

    # Human-facing and semantic identity.
    "filename": filename,
    "display_name": filename,
    "mimetype": mimetype or "application/octet-stream",
    "asset_type": asset_type,
    "source_type": source_type,
    
    # Optional source attribution for first-pass deduplication
    "source_url": source_url,

    # Explicit prompt-library curation state.
    # Creation-path defaults set this value; users may later change it.
    "injection_enabled": injection_enabled,

    # Asset-record timestamps, authoritative at the asset level.
    "created_at": now,
    "updated_at": now,

    # Current MemoryMuse-owned byte representation.
    "storage": {
        "backend": "local",
        "path": relative_path,
        "bytes_status": "available",
        "size": size,
        "content_sha256": content_sha256,
        "purged_at": None,
    },

    # Retention and deletion policy/state.
    "lifecycle": {
        "status": "available",
        "permanent": False,
        "expires_at": expires_at,
        "deleted_at": None,
    },

    # Optional organizational scope. Never implies ownership.
    "project_ids": project_ids or [],

    # Immutable initial-origin metadata.
    "provenance": {
        "origin_message_id": origin_message_id,
        "original_url": original_url,
        "ingested_at": now,

        "created_by_tool": created_by_tool,
        "provider": provider,
        "model": model,

        "prompt": prompt,
        "explicit": explicit,
        "moderation": moderation,
        "seed": seed,
        "image_size": image_size,
        "source_images": source_images,
        "source_assets": source_assets,
        "quality": quality,
        "output_format": output_format,

        "provider_response": provider_response,
    },

    # Optional derived retrieval/index projections.
    # Empty or omitted means the asset has no retrieval projections.
    "indexing": [
        {
            "kind": "conversation_recall",
            "status": "indexed",
            "indexed_at": now,
            "message_ids": message_ids,
            "num_chunks": len(message_ids),
        },
    ],
}
```

Fields whose values are unavailable for a creation path may be omitted or stored as `None`, following the existing project convention. Avoid creating speculative empty subtrees merely because they might become useful later.

---

## Root-level identity and presentation fields

| Field               | Meaning                                                               | Mutability |
|---------------------|-----------------------------------------------------------------------|---|
| `_id`               | Durable MemoryMuse asset identity.                                    | Immutable |
| `filename`          | Original technical filename.                                          | Normally immutable |
| `display_name`      | User-facing editable asset label.                                     | Editable |
| `mimetype`          | MIME type of the canonical stored representation.                     | Normally immutable |
| `asset_type`        | Broad media category, such as `image`, `text`, `audio`, or `file`.    | Normally immutable |
| `source_type`       | How the asset first entered MemoryMuse.                               | Immutable after creation |
| `source_url`        | If an asset is uploaded via URL, it is stored here.                   | Immutable after creation |
| `injection_enabled` | Whether this asset is eligible for ordinary prompt-library injection. | Editable |
| `created_at`        | Immutable birth time of the asset record.                             | Immutable |
| `updated_at`        | Last meaningful asset-level mutation.                                 | Updated on asset changes |

### `source_type`

`source_type` is a broad initial-origin classification. Expected values may include:

```text
user_upload
chat_upload
generated
url_ingest
tts_cache
```

The exact enum may grow, but the meaning must remain stable:

> `source_type` explains **how the asset entered MemoryMuse**. It does not imply ownership, permanence, visibility, indexing, or injection eligibility.

### `injection_enabled`

`injection_enabled` is the durable per-asset state used by the File Manager and prompt-injection workflows.

Suggested creation defaults:

| Creation path | `source_type` | Default `injection_enabled` |
|---|---|---:|
| File Manager upload | `user_upload` | `true` |
| Chat attachment/drop | `chat_upload` | `false` |
| Generated image/file | `generated` | `false` |
| URL ingestion | `url_ingest` | `false` |
| TTS cache | `tts_cache` | `false` |

This field is intentionally independent from `lifecycle.permanent`.

An asset can be:

- permanent but not injectable — for example, a generated image shown in chat;
- injectable without being indexed;
- indexed without being manually injectable;
- retained indefinitely while remaining outside the ordinary prompt-library shelf.

---

## Storage

The `storage` object describes the **current MemoryMuse-owned byte representation**.

```python
"storage": {
    "backend": "local",
    "path": "assets/generated/2026/07/example.png",
    "bytes_status": "available",
    "size": 2840012,
    "content_sha256": "abc123...",
    "purged_at": None,
}
```

| Field | Meaning |
|---|---|
| `backend` | Storage backend holding the current bytes, initially `local`. |
| `path` | MemoryMuse-owned relative storage path. Not an external provider URL. |
| `bytes_status` | Current availability of the stored bytes. |
| `size` | Byte size of the current stored representation. |
| `content_sha256` | SHA-256 of available stored bytes, used for byte-level deduplication. |
| `purged_at` | Timestamp when bytes were actually removed, if applicable. |

### Storage invariants

- `storage.content_sha256` is the sole canonical dedupe hash. There is no root-level duplicate hash.
- `storage.size` belongs with the stored representation, not the abstract asset.
- `storage.path` and `storage.content_sha256` are meaningful only while stored bytes remain available.
- When bytes are permanently purged, clear fields that could cause the asset to be reused as a living dedupe match:

```python
"storage": {
    "backend": "local",
    "path": None,
    "bytes_status": "purged",
    "size": None,
    "content_sha256": None,
    "purged_at": now,
}
```

- Future variants—thumbnails, converted previews, alternate encodings—belong under `storage`, not at the root asset level.

Possible future shape:

```python
"storage": {
    "backend": "local",
    "path": "...",
    "bytes_status": "available",
    "size": 2840012,
    "content_sha256": "...",
    "variants": {
        "thumbnail": {
            "path": "...",
            "mimetype": "image/webp",
            "size": 42182,
        }
    },
}
```

---

## Lifecycle

Lifecycle expresses retention and deletion state. It does not describe provenance, ownership, storage layout, or injection eligibility.

```python
"lifecycle": {
    "status": "available",
    "permanent": True,
    "expires_at": None,
    "deleted_at": None,
}
```

| Field | Meaning |
|---|---|
| `status` | Current asset lifecycle state. |
| `permanent` | Whether normal expiration/reaper policy should retain the asset indefinitely. |
| `expires_at` | Scheduled expiration point for non-permanent assets, if applicable. |
| `deleted_at` | When the asset was soft-deleted. |

Suggested lifecycle statuses:

```text
available
deleted
purged
missing
```

The exact enum should stay small and operationally meaningful.

### Lifecycle invariants

- `created_at` and `updated_at` live at the root asset level and are authoritative.
- Setting `lifecycle.permanent = false` does not itself require an immediate `expires_at` value. Cleanup policy may assign one later.
- Soft deletion preserves the asset record, allowing message history and File Manager views to show a useful unavailable/deleted state.
- Deletion must cascade to active indexing projections, making their retrieval records unavailable.
- Byte purging may happen later, according to retention/reaper policy.

---

## Provenance

`provenance` records the immutable facts of how the canonical asset **first entered MemoryMuse**.

```python
"provenance": {
    "origin_message_id": "msg_...",

    # Present only for URL ingestion or another meaningful external source.
    "original_url": "https://example.com/source.png",

    "ingested_at": now,

    "created_by_tool": "generate_image",
    "provider": "openai",
    "model": "gpt-image-1",

    "prompt": "...",
    "explicit": False,
    "seed": 12345,
    "image_size": "portrait_4_3",
    "source_images": [
        {
            "asset_id": "asset_source_1",
        }
    ],

    "provider_response": {
        # Provider-specific data when genuinely useful.
    },
}
```

### `origin_message_id`

`origin_message_id` identifies the first chat message that introduced the asset into MemoryMuse, when applicable.

It is intentionally **not** a list of every message that has ever referenced the asset.

If later we need to answer:

> “Where has this asset appeared?”

the source of truth is the conversation/message collection, queried through structured asset references, asset IDs, or attachment metadata.

Provenance says where the asset began—not every room it has visited.

### URL provenance and URL deduplication

A public source URL belongs under the main document

```python
"source_url": source_url,
```

For URL ingestion, deduplication proceeds in this order:

1. Check whether a living asset already has the exact same `source_url`.
2. If a match exists, reuse that canonical asset without downloading it again.
3. If no URL match exists, download the public URL.
4. Calculate SHA-256 for the downloaded bytes.
5. Search living assets by available stored-byte hash:

```python
{
    "storage.bytes_status": "available",
    "storage.content_sha256": content_sha256,
}
```

6. If a live hash match exists, reuse the canonical asset.
7. Otherwise, create a new asset record.

The URL check is intentionally modest:

> “Have we already fetched this exact public URL into a living asset?”

It does not attempt to establish canonical URL identity across redirects, query normalization, CDN aliases, or other web archaeology. Byte-level SHA-256 dedupe remains the more durable second check.

### Provenance immutability

MemoryMuse does **not** maintain a full ingestion-event audit history in the asset document.

When an existing living asset is reused through deduplication:

- do not replace its immutable first-origin provenance;
- do not append every later chat message or reuse location;
- do not create competing histories merely to document reuse.

If future debugging requires it, operational logs can record ingestion attempts separately from the canonical asset record.

---

## Project scope

```python
"project_ids": [
    "68743eebc6c3ad0a405db259",
]
```

`project_ids` identifies optional organizational/project scope.

It is not ownership. Assets may be:

- unscoped/general assets with `project_ids: []`;
- associated with one project;
- associated with multiple projects;
- referenced in conversations or threads unrelated to their initial project scope.

The asset record should not carry `thread_ids`. Threads and messages own the relationship by storing asset references at the use site.

---

## Indexing and retrieval projections

Indexing is optional derived work performed on an asset, usually text assets.

Each item in `indexing` is one derived retrieval projection of the asset.

```python
"indexing": [
    {
        "kind": "conversation_recall",
        "status": "indexed",
        "indexed_at": now,
        "message_ids": [
            "chunk_message_1",
            "chunk_message_2",
        ],
        "num_chunks": 2,
    },
]
```

An absent or empty `indexing` list means the asset has no retrieval projections.

An indexing entry answers:

> “Where and how has this asset been projected for retrieval?”

It does **not** change what the asset is.

### Conversation-recall projection

The current recall flow chunks a text asset into message-like records and indexes those records through the ordinary conversation semantic-recall system.

```python
{
    "kind": "conversation_recall",
    "status": "indexed",
    "indexed_at": now,
    "message_ids": message_ids,
    "num_chunks": len(message_ids),
}
```

`message_ids` are linked conversation-chunk message IDs for this projection only. They do not belong at the root asset level.

These chunk records should:

- carry the asset ID in their metadata;
- be excluded from immediate/recent conversation history by source filtering;
- be eligible for semantic recall only while their indexing projection remains active;
- render as informational source context when recalled, not as user or assistant speech.

### Project-document vector-store projection

A project-specific vector store is a different retrieval projection. It must not masquerade as conversation history.

Possible future shape:

```python
{
    "kind": "project_vector_store",
    "status": "indexed",

    "project_id": "68743eebc6c3ad0a405db259",
    "backend": "qdrant",
    "collection": "project_68743eebc6c3ad0a405db259",

    "index_profile": "project_documents_v1",
    "embedding_profile": "canon_oracle_v1",
    "chunking_profile": "document_semantic_small_v1",

    "indexed_at": now,
    "num_chunks": 42,
}
```

Project-vector entries should carry enough information to answer:

- which project scope the projection serves;
- which backend and collection hold the vectors;
- which indexing/chunking/embedding profile created them;
- whether the projection is active, indexed, pending, failed, or removed;
- how many chunks were created.

They should **not** normally store every vector or Qdrant point ID.

Instead, every Qdrant point for an asset-backed document projection must carry the asset ID in its payload:

```python
{
    "asset_id": asset_id,
    "project_id": project_id,
    "filename": filename,
    "display_name": display_name,
    "chunk_index": chunk_index,
    "heading_path": heading_path,
    "start_line": start_line,
    "end_line": end_line,
    "text": chunk_text,
}
```

That allows deletion to remove or deactivate vectors by asset ID and collection:

```python
await qdrant_client.delete(
    collection_name=projection["collection"],
    points_selector={
        "filter": {
            "must": [
                {
                    "key": "asset_id",
                    "match": {
                        "value": asset_id,
                    },
                },
            ],
        },
    },
)
```

This keeps the asset document compact even when a large game log or technical document produces hundreds or thousands of vector points.

Project-document retrieval results must be rendered as dedicated **source context**, not replayed as historical conversation messages.

Example prompt assembly:

```text
[SOURCES_PROJECT_DOCUMENTS]
Asset: asset-schema-contract.md
Project: MemoryMuse
Relevant excerpt:
...
[/SOURCES_PROJECT_DOCUMENTS]
```

### Indexing invariants

- An asset can be manually injectable without being indexed.
- An asset can be indexed without being manually injectable.
- An asset can have multiple indexing projections.
- Indexing may be rebuilt without changing asset identity or provenance.
- An unavailable, deleted, or purged asset must not continue surfacing as ordinary semantic-recall content.
- Asset deletion must traverse every indexing projection and deactivate, delete, or make unrecallable all derived retrieval material.

Conceptually:

```python
for projection in asset.get("indexing", []):
    match projection["kind"]:
        case "conversation_recall":
            await delete_or_hide_chunk_messages(
                projection["message_ids"]
            )

        case "project_vector_store":
            await delete_asset_vectors_by_asset_id(
                collection=projection["collection"],
                asset_id=asset["_id"],
            )
```

This is the reason `indexing` is a list rather than a single flat status object: deletion can walk one explicit registry of every retrieval shadow the asset has cast.

---

## Asset deletion and tombstones

There is no root-level empty `tombstone` placeholder.

The lifecycle state is enough until MemoryMuse needs richer deletion semantics.

A soft-deleted asset should retain:

- `_id`;
- enough display metadata for message history and File Manager views;
- basic lifecycle state;
- provenance where appropriate;
- enough information for the UI to render an intentional unavailable/deleted placeholder.

If later needed, add a deliberate deletion object rather than restoring a vague `tombstone` field:

```python
"deletion": {
    "reason": "user_deleted",
    "deleted_by": "user",
    "replacement_asset_id": None,
    "purge_after": None,
}
```

Do not add this until there is a real consumer for one of those facts.

---

## Mutation rules

### Editable fields

Initial expected File Manager edit surface:

```text
display_name
injection_enabled
lifecycle.permanent
project_ids
```

Potential future editable fields:

```text
description
tags
visibility
```

### Immutable or creation-time fields

These should not change through ordinary asset metadata editing:

```text
_id
filename
mimetype
asset_type
source_type
created_at
source_url
provenance
storage.content_sha256
storage.path
```

Storage and lifecycle fields may change through dedicated lifecycle, ingestion, dedupe, restore, indexing, or purge operations—not generic user metadata PATCH calls.

### `updated_at`

Any meaningful asset-level mutation updates root `updated_at`, including:

- display-name edits;
- injection curation changes;
- lifecycle retention changes;
- project-scope changes;
- indexing completion, failure, removal, or rebuild;
- storage availability or purge transitions.

---

## Compact creation defaults

| Creation path | `source_type` | Permanent by default | Injection enabled by default | Indexed by default |
|---|---|---:|---:|---:|
| File Manager upload | `user_upload` | true | true | no; text indexing is opt-in |
| Chat drop/attachment | `chat_upload` | false | false | no |
| Generated image/file | `generated` | true | false | no |
| URL ingestion | `url_ingest` | policy-defined | false | no |
| TTS cache | `tts_cache` | false | false | no |

---

## Message relationship

Messages do not embed full asset documents or raw file bytes. They store compact asset references suitable for immediate rendering:

```python
{
    "asset_id": "asset_abc123",
    "asset_type": "image",
    "mimetype": "image/png",
    "display_name": "glass-asset-tags-purple-light.png",
    "role": "attachment",
    "display": "inline",
    "order": 0,
}
```

The asset record remains the durable artifact authority. The message reference is a display-oriented snapshot for conversation history and immediate UI rendering.

If the asset later becomes unavailable, the frontend should render an intentional unavailable/expired state rather than a broken image, console error, or empty hole.