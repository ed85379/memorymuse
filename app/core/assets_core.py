# core/assets_core.py
import hashlib
import mimetypes
import base64
import binascii

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4
from datetime import datetime, timezone, timedelta, UTC
from pydantic import BaseModel, ConfigDict

import requests
from werkzeug.utils import secure_filename

from app.config import ASSET_STORAGE_ROOT
from app.config import MONGO_ASSETS_COLLECTION, MONGO_CONVERSATION_COLLECTION
from app.databases.mongo_connector import mongo
from app.core.utils import chunk_file
from app.core.memory_core import log_message
from app.databases.memory_indexer import update_qdrant_metadata_for_messages


AssetLifecycleStatus = Literal[
    "available",
    "expired",
    "purged",
    "missing",
    "archived",
]

DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 30
DEFAULT_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024  # 25 MB


@dataclass
class AssetLifecycle:
    permanent: bool = False
    expires_at: datetime | None = None
    status: AssetLifecycleStatus = "available"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    def to_dict(self) -> dict:
        now = datetime.utcnow()

        return {
            "status": self.status,
            "permanent": self.permanent,
            "expires_at": self.expires_at,
            "created_at": self.created_at or now,
            "updated_at": self.updated_at or now,
            "deleted_at": self.deleted_at,
        }


@dataclass
class AssetProvenance:
    # Broad origin classification/details.
    # Note: source_type also exists as a first-class asset field because it affects storage/layout.
    source_type: str
    ingested_at: datetime

    # Tool/provider/message origin
    created_by_tool: str | None = None
    provider: str | None = None
    model: str | None = None
    origin_message_id: str | None = None

    # Original external source, if any
    original_url: str | None = None

    # Generation/edit context
    prompt: str | None = None
    explicit: bool | None = None
    moderation: str | None = None
    seed: int | None = None
    image_size: str | None = None
    source_images: list[dict[str, Any]] | None = None
    source_assets: list[str] | None = None
    quality: str | None = None
    output_format: str | None = None

    # Escape hatch for provider-specific weirdness
    provider_response: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        data = {
            "source_type": self.source_type,
            "ingested_at": self.ingested_at,

            "created_by_tool": self.created_by_tool,
            "provider": self.provider,
            "model": self.model,
            "origin_message_id": self.origin_message_id,

            "original_url": self.original_url,

            "prompt": self.prompt,
            "explicit": self.explicit,
            "moderation": self.moderation,
            "seed": self.seed,
            "image_size": self.image_size,
            "source_images": self.source_images,
            "source_assets": self.source_assets,
            "quality": self.quality,
            "output_format": self.output_format,

            "provider_response": self.provider_response,
        }

        # Keep Mongo docs clean; don't store endless null confetti.
        return {key: value for key, value in data.items() if value is not None}


@dataclass
class DownloadedAsset:
    file_bytes: bytes
    mimetype: str | None
    filename: str | None
    size: int
    final_url: str

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def default_lifecycle() -> AssetLifecycle:
    return AssetLifecycle(
        permanent=False,
        status="available",
    )

@dataclass
class AssetPatchRequest(BaseModel):
    # Reject surprise fields at the HTTP boundary. The core helper also
    # validates them, but this produces a clean FastAPI 422 response sooner.
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    description: str | None = None

    image_source_enabled: bool | None = None
    injection_enabled: bool | None = None
    permanent: bool | None = None

    project_ids: list[str] | None = None

def generate_asset_id() -> str:
    return f"asset_{uuid4().hex}"


def sha256_bytes(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def infer_asset_type(mimetype: str | None) -> str:
    if not mimetype:
        return "binary"

    if mimetype.startswith("image/"):
        return "image"

    if mimetype.startswith("audio/"):
        return "audio"

    if mimetype.startswith("text/"):
        return "text"

    if mimetype in {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }:
        return "document"

    return "binary"


def guess_extension(filename: str | None, mimetype: str | None) -> str:
    if filename and Path(filename).suffix:
        return Path(filename).suffix.lstrip(".")

    if mimetype == "image/png":
        return "png"
    if mimetype == "image/jpeg":
        return "jpg"
    if mimetype == "image/webp":
        return "webp"
    if mimetype == "image/gif":
        return "gif"
    if mimetype == "audio/mpeg":
        return "mp3"
    if mimetype == "audio/wav":
        return "wav"
    if mimetype == "text/plain":
        return "txt"

    guessed_ext = mimetypes.guess_extension(mimetype or "")
    if guessed_ext:
        return guessed_ext.lstrip(".")

    return "bin"


def get_asset_subdir(
    *,
    source_type: str,
    asset_type: str,
    created_at: datetime | None = None,
) -> Path:
    created_at = created_at or datetime.utcnow()

    year = f"{created_at.year:04d}"
    month = f"{created_at.month:02d}"
    day = f"{created_at.day:02d}"

    if source_type == "project_upload":
        return Path("project_uploads") / year / month

    if source_type == "chat_upload":
        return Path("chat_uploads") / year / month / day

    if source_type == "generated":
        return Path("generated") / asset_type / year / month / day

    if source_type == "tts_cache":
        return Path("tts") / "cache" / year / month / day

    if source_type == "avatar_library":
        return Path("avatars") / year / month

    return Path("misc") / source_type / year / month / day


def build_asset_filename(
    *,
    asset_id: str,
    original_filename: str | None,
    extension: str | None,
) -> str:
    safe_name = secure_filename(original_filename or "asset")

    stem = Path(safe_name).stem or "asset"

    if extension:
        ext = extension.lstrip(".")
    else:
        ext = Path(safe_name).suffix.lstrip(".") or "bin"

    return f"{stem}__{asset_id}.{ext}"


def filename_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    path = parsed.path or ""

    if not path:
        return None

    name = Path(path).name

    if not name:
        return None

    return secure_filename(name) or None


def filename_from_content_disposition(content_disposition: str | None) -> str | None:
    """
    Very small v1 parser.

    Handles common forms like:
      attachment; filename="example.png"

    Not trying to fully implement RFC 6266 yet.
    """
    if not content_disposition:
        return None

    parts = [part.strip() for part in content_disposition.split(";")]

    for part in parts:
        if part.lower().startswith("filename="):
            filename = part.split("=", 1)[1].strip().strip('"')
            return secure_filename(filename) or None

    return None


def normalize_mimetype(content_type: str | None) -> str | None:
    if not content_type:
        return None

    # Strip charset/etc: "image/png; charset=utf-8" -> "image/png"
    return content_type.split(";", 1)[0].strip().lower() or None

DEFAULT_DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "close",
}

def download_asset_url(
    url: str,
    *,
    timeout_seconds: int = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    allowed_mimetype_prefixes: tuple[str, ...] | None = None,
    headers: dict[str, str] | None = None,
) -> DownloadedAsset:
    """
    Download a remote asset into memory for local ingestion.

    v1 guardrails:
    - timeout
    - raise on non-2xx
    - max byte size
    - optional allowed mimetype prefixes, e.g. ("image/",)
    """

    request_headers = {
        **DEFAULT_DOWNLOAD_HEADERS,
        **(headers or {}),
    }

    with requests.get(
        url,
        timeout=timeout_seconds,
        stream=True,
        headers=request_headers,
        allow_redirects=True,
    ) as response:
        response.raise_for_status()

        final_url = response.url
        mimetype = normalize_mimetype(response.headers.get("Content-Type"))

        if allowed_mimetype_prefixes and mimetype:
            if not mimetype.startswith(allowed_mimetype_prefixes):
                raise ValueError(
                    f"Downloaded asset has disallowed mimetype: {mimetype}"
                )

        content_length_header = response.headers.get("Content-Length")
        if content_length_header:
            try:
                content_length = int(content_length_header)
            except ValueError:
                content_length = None

            if content_length is not None and content_length > max_bytes:
                raise ValueError(
                    f"Remote asset is too large: {content_length} bytes > {max_bytes} bytes"
                )

        chunks: list[bytes] = []
        total = 0

        for chunk in response.iter_content(chunk_size=1024 * 64):
            if not chunk:
                continue

            total += len(chunk)

            if total > max_bytes:
                raise ValueError(
                    f"Remote asset exceeded max download size: "
                    f"{total} bytes > {max_bytes} bytes"
                )

            chunks.append(chunk)

        file_bytes = b"".join(chunks)

        if not file_bytes:
            raise ValueError("Remote asset downloaded as empty response body")

        filename = (
            filename_from_content_disposition(
                response.headers.get("Content-Disposition")
            )
            or filename_from_url(final_url)
            or filename_from_url(url)
        )

        return DownloadedAsset(
            file_bytes=file_bytes,
            mimetype=mimetype,
            filename=filename,
            size=len(file_bytes),
            final_url=final_url,
        )


def build_asset_doc(
    *,
    asset_id: str,
    filename: str | None,
    mimetype: str | None,
    size: int,
    source_type: str,
    asset_type: str,
    relative_path: str,
    injection_enabled: bool | None = None,
    content_sha256: str | None = None,
    source_url: str | None = None,
    project_ids: list[str] | None = None,
    provenance: AssetProvenance | dict | None = None,
    lifecycle: AssetLifecycle | dict | None = None,
) -> dict:
    now = datetime.utcnow()

    if isinstance(provenance, AssetProvenance):
        provenance_doc = provenance.to_dict()
    else:
        provenance_doc = provenance or {}

    if isinstance(lifecycle, AssetLifecycle):
        lifecycle_doc = lifecycle.to_dict()
    elif lifecycle:
        lifecycle_doc = lifecycle
    else:
        lifecycle_doc = default_lifecycle().to_dict()

    # Ensure lifecycle timestamps exist even if caller passed a partial dict.
    lifecycle_doc.setdefault("created_at", now)
    lifecycle_doc.setdefault("updated_at", now)
    lifecycle_doc.setdefault("deleted_at", None)
    lifecycle_doc.setdefault("status", "available")
    lifecycle_doc.setdefault("permanent", False)
    lifecycle_doc.setdefault("expires_at", None)

    return {
        "_id": asset_id,

        "filename": filename,
        "display_name": filename,
        "mimetype": mimetype or "application/octet-stream",

        "asset_type": asset_type,
        "source_type": source_type,
        "injection_enabled": injection_enabled,
        "source_url": source_url,

        "storage": {
            "backend": "local",
            "path": relative_path,
            "bytes_status": "available",
            "size": size,
            "content_sha256": content_sha256,
            "purged_at": None,
        },

        "lifecycle": lifecycle_doc,

        "project_ids": project_ids or [],

        "provenance": provenance_doc,

    }


def create_local_asset_from_bytes(
    *,
    file_bytes: bytes,
    filename: str | None,
    mimetype: str | None,
    source_type: str,
    injection_enabled: bool | None = None,
    asset_id: str | None = None,
    url: str | None = None,
    project_ids: list[str] | None = None,
    provenance: AssetProvenance | dict | None = None,
    lifecycle: AssetLifecycle | dict | None = None,
) -> dict:
    content_hash = sha256_bytes(file_bytes)
    asset_type = infer_asset_type(mimetype)
    existing = find_living_asset_by_sha256(
        content_hash,
        asset_type=asset_type,
    )

    if existing:
        return existing

    now = datetime.utcnow()

    asset_id = asset_id or generate_asset_id()

    ext = guess_extension(filename, mimetype)

    subdir = get_asset_subdir(
        source_type=source_type,
        asset_type=asset_type,
        created_at=now,
    )

    asset_filename = build_asset_filename(
        asset_id=asset_id,
        original_filename=filename,
        extension=ext,
    )

    relative_path = subdir / asset_filename
    full_path = Path(ASSET_STORAGE_ROOT) / relative_path

    full_path.parent.mkdir(parents=True, exist_ok=True)

    with open(full_path, "wb") as f:
        f.write(file_bytes)



    asset_doc = build_asset_doc(
        asset_id=asset_id,
        filename=filename,
        mimetype=mimetype,
        size=len(file_bytes),
        source_type=source_type,
        injection_enabled=injection_enabled,
        asset_type=asset_type,
        relative_path=str(relative_path).replace("\\", "/"),
        content_sha256=content_hash,
        source_url=url,
        project_ids=project_ids,
        provenance=provenance,
        lifecycle=lifecycle,
    )

    mongo.insert_one_document(MONGO_ASSETS_COLLECTION, asset_doc)

    return asset_doc


def create_local_asset_from_url(
    *,
    url: str,
    filename: str | None = None,
    mimetype: str | None = None,
    source_type: str,
    asset_id: str | None = None,
    project_ids: list[str] | None = None,
    provenance: AssetProvenance | dict | None = None,
    lifecycle: AssetLifecycle | dict | None = None,
    timeout_seconds: int = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    allowed_mimetype_prefixes: tuple[str, ...] | None = None,
) -> dict:

    existing = find_living_asset_by_source_url(
        source_url=url,
    )
    if existing:
        return existing

    downloaded = download_asset_url(
        url,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        allowed_mimetype_prefixes=allowed_mimetype_prefixes,
    )

    # If caller passed typed provenance, fill final_url if it was not already set.
    #if isinstance(provenance, AssetProvenance) and provenance.final_url is None:
    #    provenance.final_url = downloaded.final_url

    return create_local_asset_from_bytes(
        asset_id=asset_id,
        file_bytes=downloaded.file_bytes,
        filename=filename or downloaded.filename,
        mimetype=mimetype or downloaded.mimetype,
        source_type=source_type,
        url=url,
        project_ids=project_ids,
        provenance=provenance,
        lifecycle=lifecycle,
    )

def create_local_asset_from_base64(
    *,
    data: str,
    filename: str | None = None,
    mimetype: str | None = None,
    source_type: str,
    asset_id: str | None = None,
    project_ids: list[str] | None = None,
    provenance: AssetProvenance | dict | None = None,
    lifecycle: AssetLifecycle | dict | None = None,
    max_bytes: int | None = None,
) -> dict:
    """
    Create a local MemoryMuse asset from a base64-encoded payload.

    Intended for chat uploads / frontend-provided file payloads where the
    current-turn model path may still preserve the raw base64 string, but
    durable asset storage needs decoded bytes.
    """

    # Be tolerant if someone sends a data URL:
    # data:image/png;base64,AAAA...
    if "," in data and data.lstrip().lower().startswith("data:"):
        _, data = data.split(",", 1)

    try:
        file_bytes = base64.b64decode(data, validate=True)
    except binascii.Error as e:
        raise ValueError("Invalid base64 asset payload") from e

    if max_bytes is not None and len(file_bytes) > max_bytes:
        raise ValueError(
            f"Base64 asset payload exceeds max size: "
            f"{len(file_bytes)} > {max_bytes}"
        )

    return create_local_asset_from_bytes(
        asset_id=asset_id,
        file_bytes=file_bytes,
        filename=filename,
        mimetype=mimetype,
        source_type=source_type,
        project_ids=project_ids,
        provenance=provenance,
        lifecycle=lifecycle,
    )

def get_asset_full_path(asset_doc: dict) -> Path:
    relative_path = asset_doc["storage"]["path"]
    return Path(ASSET_STORAGE_ROOT) / relative_path


def read_asset_bytes(asset_doc: dict) -> bytes:
    full_path = get_asset_full_path(asset_doc)

    with open(full_path, "rb") as f:
        return f.read()

def read_asset_base64(asset_doc: dict) -> str:
    full_path = get_asset_full_path(asset_doc)

    with open(full_path, "rb") as f:
        file_data = f.read()
        b64_data: str = base64.b64encode(file_data).decode("ascii")
        return b64_data

def get_all_message_ids_for_assets(asset_ids: list[str] | None) -> list[str]:
    """
    Given a list of asset IDs, return a deduplicated list of indexed chunk
    message_ids belonging to those assets.

    Used to prevent semantic recall from also returning chunks from an asset
    that has been intentionally injected into the current turn.
    """
    if not asset_ids:
        return []

    assets = mongo.find_documents(
        collection_name=MONGO_ASSETS_COLLECTION,
        query={"_id": {"$in": asset_ids}},
    )

    all_message_ids = set()

    for asset in assets:
        indexing = asset.get("indexing") or {}
        message_ids = indexing.get("message_ids") or []
        all_message_ids.update(message_ids)

    return list(all_message_ids)

def asset_to_data_url(asset_doc: dict) -> str:
    mimetype = asset_doc.get("mimetype") or "application/octet-stream"
    file_bytes = read_asset_bytes(asset_doc)
    encoded = base64.b64encode(file_bytes).decode("utf-8")

    return f"data:{mimetype};base64,{encoded}"

def asset_doc_to_ref(
    asset_doc: dict,
    *,
    role: str = "attachment",
    display: str | None = None,
    order: int = 0,
    source_tool: str | None = None,
) -> dict:
    mimetype = asset_doc.get("mimetype") or "application/octet-stream"
    asset_type = asset_doc.get("asset_type") or infer_asset_type(mimetype)

    if display is None:
        if mimetype.startswith("image/"):
            display = "inline"
        elif mimetype.startswith("audio/"):
            display = "audio_player"
        else:
            display = "download"

    ref = {
        "asset_id": asset_doc["_id"],
        "asset_type": asset_type,
        "mimetype": mimetype,
        "filename": asset_doc.get("filename"),
        "display_name": asset_doc.get("display_name") or asset_doc.get("filename"),
        "size": asset_doc.get("storage.size"),

        "role": role,
        "display": display,
        "order": order,
        "source_tool": source_tool,
    }

    dimensions = asset_doc.get("dimensions") or {}
    if dimensions.get("width"):
        ref["width"] = dimensions["width"]
    if dimensions.get("height"):
        ref["height"] = dimensions["height"]

    return ref

def asset_doc_to_listing_item(asset: dict) -> dict:
    asset_id = str(asset.get("_id"))

    lifecycle = asset.get("lifecycle") or {}
    indexing = asset.get("indexing") or {}
    dimensions = asset.get("dimensions") or {}
    storage = asset.get("storage") or {}
    provenance = asset.get("provenance") or {}

    return {
        "asset_id": asset_id,

        # --- Identity / ordinary display ---

        "asset_type": asset.get("asset_type"),
        "source_type": asset.get("source_type"),

        "filename": asset.get("filename"),
        "display_name": asset.get("display_name") or asset.get("filename"),
        "description": asset.get("description"),

        "mimetype": asset.get("mimetype"),
        "size": asset.get("size"),

        # --- Curation / behavior ---

        "image_source_enabled": bool(
            asset.get("image_source_enabled", False)
        ),
        "injection_enabled": bool(
            asset.get("injection_enabled", False)
        ),

        # --- Scope ---

        "project_ids": [
            str(project_id)
            for project_id in asset.get("project_ids", [])
        ],

        # --- Lifecycle / storage state ---

        "lifecycle": {
            "status": lifecycle.get("status"),
            "permanent": bool(lifecycle.get("permanent", False)),
            "expires_at": lifecycle.get("expires_at"),
            "purge_after": lifecycle.get("purge_after"),
            "created_at": lifecycle.get("created_at"),
        },

        "provenance": {
            "ingested_at": provenance.get("ingested_at"),
        },

        "storage": {
            "status": storage.get("status"),
            "bytes_status": storage.get("bytes_status"),
            "size": storage.get("size"),
        },

        # --- Recall state ---

        "indexing": {
            "mode": indexing.get("mode", "none"),
            "status": indexing.get("status", "not_indexed"),
            "recall_indexed": bool(
                indexing.get("recall_indexed", False)
            ),
            "num_chunks": indexing.get("num_chunks", 0),
        },

        # --- Image display ---

        "width": dimensions.get("width"),
        "height": dimensions.get("height"),

        # --- Timestamps / routes ---

        "created_at": asset.get("created_at"),
        "updated_at": asset.get("updated_at"),

        "content_url": f"/api/assets/{asset_id}/content",
        "download_url": f"/api/assets/{asset_id}/download",
    }

def build_asset_list_query(
    *,
    project_id: str | None = None,
    project_mode: str | None = None,
    source_type: str | None = None,
    asset_type: str | None = None,
    lifecycle_status: str | None = "available",
    injection_only: bool = False,
) -> dict:
    query: dict = {}

    if lifecycle_status:
        query["lifecycle.status"] = lifecycle_status

    if source_type:
        query["source_type"] = source_type

    if asset_type:
        query["asset_type"] = asset_type

    if project_id:
        project_id = str(project_id).strip()

        if project_mode in (None, "only"):
            query["project_ids"] = {"$in": [project_id]}

        elif project_mode == "exclude":
            query["project_ids"] = {"$nin": [project_id]}

        else:
            raise ValueError(
                "With project_id, project_mode must be 'only' or 'exclude'"
            )

    else:
        if project_mode is None:
            pass

        elif project_mode == "unscoped":
            query["$or"] = [
                {"project_ids": {"$exists": False}},
                {"project_ids": {"$size": 0}},
                {"project_ids": None},
            ]

        elif project_mode == "attached":
            query["project_ids"] = {"$exists": True, "$ne": []}

        elif project_mode in ("only", "exclude"):
            # Used by "Attach File" / asset picker flows:
            # show assets not already attached to this project, including unscoped assets.
            raise ValueError(
                "project_mode='only' or 'exclude' requires project_id"
            )

        else:
            raise ValueError(
                "project_mode must be 'general', 'linked', 'only', or 'exclude'"
            )

    if injection_only:
        query["$or"] = [
            {"source_type": "user_upload"},
            {"injection_enabled": True},
        ]

    return query

def list_assets(
    *,
    project_id: str | None = None,
    project_mode: str | None = None,
    source_type: str | None = None,
    asset_type: str | None = None,
    lifecycle_status: str | None = "available",
    injection_only: bool = False,
) -> dict:
    query = build_asset_list_query(
        project_id=project_id,
        project_mode=project_mode,
        source_type=source_type,
        asset_type=asset_type,
        lifecycle_status=lifecycle_status,
        injection_only=injection_only,
    )

    assets = mongo.find_documents(
        collection_name=MONGO_ASSETS_COLLECTION,
        query=query,
        sort=[("created_at", -1)],
    )

    return {
        "assets": [asset_doc_to_listing_item(asset) for asset in assets],
        "count": len(assets),
        "query": {
            "project_id": project_id,
            "project_mode": project_mode,
            "source_type": source_type,
            "asset_type": asset_type,
            "lifecycle_status": lifecycle_status,
            "injection_only": injection_only,
        },
    }

def living_asset_filter(now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)

    return {
        "storage.bytes_status": "available",
        "lifecycle.status": "available",
        "$or": [
            {"lifecycle.expires_at": None},
            {"lifecycle.expires_at": {"$exists": False}},
            {"lifecycle.expires_at": {"$gt": now}},
        ],
    }

def find_living_asset_by_sha256(
    content_sha256: str | None,
    *,
    asset_type: str | None = None,
) -> dict | None:
    if not content_sha256:
        return None

    query = {
        **living_asset_filter(),
        "storage.content_sha256": content_sha256,
    }

    if asset_type:
        query["asset_type"] = asset_type

    return mongo.find_one_document(MONGO_ASSETS_COLLECTION, query)

def find_living_asset_by_source_url(
    source_url: str | None,
    *,
    asset_type: str | None = None,
) -> dict | None:
    if not source_url:
        return None

    query = {
        **living_asset_filter(),
        "source_url": source_url,
    }

    if asset_type:
        query["asset_type"] = asset_type

    return mongo.find_one_document(MONGO_ASSETS_COLLECTION, query)

def find_living_asset_by_id(
    asset_id: str | None,
) -> dict | None:
    if not asset_id:
        return None

    query = {
        **living_asset_filter(),
        "_id": asset_id,
    }

    return mongo.find_one_document(MONGO_ASSETS_COLLECTION, query)

def chunk_timestamp_for_batch(base_ts: datetime, chunk_index: int) -> datetime:
    return base_ts + timedelta(milliseconds=chunk_index)

async def index_asset_text_for_recall(asset_doc: dict) -> list[str]:
    from app.api.queues import log_queue
    from app.databases.memory_indexer import assign_message_id

    file_bytes = read_asset_bytes(asset_doc)
    chunks = chunk_file(file_bytes)

    base_ts = datetime.now(timezone.utc).replace(microsecond=0)
    message_ids = []

    for chunk in chunks:
        chunk_index = chunk["index"]
        timestamp = chunk_timestamp_for_batch(base_ts, chunk_index)

        entry = {
            "timestamp": timestamp,
            "role": "system",
            "message": chunk["content"],
            "source": "asset_text_chunk",
            "metadata": {
                "asset_id": str(asset_doc["_id"]),
                "filename": asset_doc.get("filename"),
                "display_name": asset_doc.get("display_name"),
                "mimetype": asset_doc.get("mimetype"),
                "source_type": asset_doc.get("source_type"),
                "chunk_index": chunk_index,
                "start_line": chunk.get("start_line"),
                "end_line": chunk.get("end_line"),
                "start_byte": chunk.get("start_byte"),
                "end_byte": chunk.get("end_byte"),
            },
            "project_ids": asset_doc.get("project_ids", []),
        }

        message_id = assign_message_id({
            "timestamp": entry["timestamp"],
            "role": entry["role"],
            "source": entry["source"],
            "message": entry["message"],
        })

        await log_queue.put(entry)
        message_ids.append(message_id)

    return message_ids

def is_text_asset_mimetype(mimetype: str | None, filename: str | None = None) -> bool:
    mimetype = (mimetype or "").lower()
    filename = (filename or "").lower()

    if mimetype.startswith("text/"):
        return True

    text_mimetypes = {
        "application/json",
        "application/xml",
        "application/javascript",
        "application/x-javascript",
        "application/typescript",
        "application/x-yaml",
        "application/yaml",
        "application/csv",
        "application/sql",
        "application/rtf",
        "application/x-sh",
        "application/x-python-code",
    }

    if mimetype in text_mimetypes:
        return True

    text_extensions = {
        ".txt",
        ".md",
        ".markdown",
        ".json",
        ".jsonl",
        ".csv",
        ".tsv",
        ".xml",
        ".html",
        ".htm",
        ".css",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".py",
        ".sql",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".log",
    }

    return any(filename.endswith(ext) for ext in text_extensions)

async def mark_asset_recall_indexed(asset_id: str, message_ids: list[str]) -> None:
    now = datetime.now(timezone.utc)

    mongo.update_one_document(
        MONGO_ASSETS_COLLECTION,
        {"_id": asset_id},
        {
            "indexing.recall_indexed": True,
            "indexing.indexed_on": now,
            "indexing.message_ids": message_ids,
            "indexing.num_chunks": len(message_ids),
            "indexing.status": "indexed",
        },
    )

def asset_for_ui(asset_doc: dict) -> dict:
    asset_id = str(asset_doc.get("_id"))

    storage = asset_doc.get("storage") or {}
    lifecycle = asset_doc.get("lifecycle") or {}
    indexing = asset_doc.get("indexing") or {}

    return {
        "_id": asset_id,

        "filename": asset_doc.get("filename"),
        "display_name": asset_doc.get("display_name") or asset_doc.get("filename"),
        "mimetype": asset_doc.get("mimetype"),
        "size": asset_doc.get("size"),

        "asset_type": asset_doc.get("asset_type"),
        "source_type": asset_doc.get("source_type"),

        "project_ids": asset_doc.get("project_ids", []),

        "storage": {
            "backend": storage.get("backend"),
            "bytes_status": storage.get("bytes_status"),
            "content_sha256": storage.get("content_sha256"),
            "size": storage.get("size"),
        },

        "lifecycle": {
            "status": lifecycle.get("status"),
            "permanent": lifecycle.get("permanent"),
            "expires_at": lifecycle.get("expires_at"),
            "purge_after": lifecycle.get("purge_after"),
        },

        "indexing": {
            "recall_indexed": indexing.get("recall_indexed", False),
            "indexed_on": indexing.get("indexed_on"),
            "message_ids": indexing.get("message_ids", []),
            "num_chunks": indexing.get("num_chunks", 0),
            "status": indexing.get("status"),
        },

        # These assume you have/will have these routes.
        # Adjust paths to match your asset API.
        "content_url": f"/api/assets/{asset_id}/content",
        "download_url": f"/api/assets/{asset_id}/download",
    }

def get_asset_index_message_ids(asset_doc: dict[str, Any]) -> list[str]:
    """
    Transitional compatibility helper.

    New asset text indexing writes IDs under asset.indexing.message_ids.
    Root-level message_ids remains supported while old records exist.
    """
    indexing = asset_doc.get("indexing") or {}

    message_ids = (
        indexing.get("message_ids")
        or []
    )

    # Preserve order while removing accidental duplicates.
    return list(dict.fromkeys(mid for mid in message_ids if mid))

async def soft_delete_asset(
    asset_id: str,
    *,
    deleted_by: str | None = None,
) -> dict[str, Any]:
    """
    Soft-delete an asset and its indexed text-chunk messages.

    Does not remove stored bytes. A later purge job handles physical deletion.
    """
    asset_doc = mongo.find_one_document(
        MONGO_ASSETS_COLLECTION,
        {"_id": asset_id},
    )

    if not asset_doc:
        return {
            "status": "not_found",
            "asset_id": asset_id,
        }

    lifecycle = asset_doc.get("lifecycle") or {}
    current_status = lifecycle.get("status", "available")

    # Idempotency matters: an impatient double-click should not create drama.
    if current_status != "available":
        return {
            "status": "not_available",
            "asset_id": asset_id,
            "lifecycle_status": current_status,
        }

    now = utc_now()
    message_ids = get_asset_index_message_ids(asset_doc)

    asset_set_fields = {
        "lifecycle.status": "deleted",
        "lifecycle.deleted_at": now,
        "lifecycle.updated_at": now,
        "updated_at": now,
    }

    if deleted_by:
        asset_set_fields["lifecycle.deleted_by"] = deleted_by

    # 1. The asset is no longer a living/reusable asset.
    # Storage remains available until the eventual purge pass.
    mongo.update_one_document_array(
        MONGO_ASSETS_COLLECTION,
        {"_id": asset_id},
        {"$set": asset_set_fields},
    )

    # 2. Derived recall artifacts are no longer living recall material.
    if message_ids:
        mongo.update_many_documents(
            MONGO_CONVERSATION_COLLECTION,
            {
                "message_id": {"$in": message_ids},
                "is_deleted": {"$ne": True},
            },
            {
                "$set": {
                    "is_deleted": True,
                    "updated_on": now,
                }
            },
        )

        # Payload-only Qdrant update: no re-embedding required.
        await update_qdrant_metadata_for_messages(message_ids)

    return {
        "status": "deleted",
        "asset_id": asset_id,
        "message_ids_soft_deleted": message_ids,
    }

EDITABLE_ASSET_FIELDS = {
    "display_name",
    "description",
    "image_source_enabled",
    "injection_enabled",
    "permanent",
    "project_ids",
}


def _clean_optional_string(value, *, max_length):
    """
    `None` and an empty/whitespace-only string both mean:
    clear this optional field.
    """
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError("Expected a string or null.")

    cleaned = value.strip()
    return cleaned[:max_length] if cleaned else None


def _require_bool(value, *, field_name):
    """
    Be deliberately strict here. Do not quietly accept 0, 1, "true", etc.
    The UI/API contract should send real JSON booleans.
    """
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean.")

    return value


def _normalize_project_ids(value):
    """
    The editor submits the complete intended project scope.

    [] is valid and means the asset is unscoped/global.
    """
    if not isinstance(value, list):
        raise ValueError("project_ids must be an array.")

    normalized = []
    seen = set()

    for project_id in value:
        if not isinstance(project_id, str):
            raise ValueError("Each project_id must be a string.")

        project_id = project_id.strip()
        if not project_id:
            raise ValueError("project_ids cannot contain empty values.")

        if project_id not in seen:
            normalized.append(project_id)
            seen.add(project_id)

    return normalized


def _asset_is_image(asset):
    """
    Prefer mimetype, but tolerate older/generated records whose asset_type
    carries the useful classification.
    """
    mimetype = (asset.get("mimetype") or "").lower()
    asset_type = (asset.get("asset_type") or "").lower()

    return mimetype.startswith("image/") or asset_type == "image"


def _serialize_asset_doc(asset):
    """
    Keep this aligned with however the rest of assets_core serializes docs.
    """
    if asset and "_id" in asset:
        asset["_id"] = str(asset["_id"])

    return asset


def edit_asset_fields(asset_id, patch_fields):
    """
    Apply the Files UI's ordinary asset-stewardship edits.

    This intentionally does NOT edit:
    - source_type / provenance
    - storage paths, hashes, or byte availability
    - arbitrary lifecycle state, expiry, deletion, or purge fields
    - indexing metadata / indexed chunk references
    - message references
    - visibility policy

    `injection_enabled=True` implies `lifecycle.permanent=True`.

    Turning injection off does NOT automatically make an asset non-permanent.
    If the UI's confirmation dialog chooses "also allow cleanup," it should
    submit both:

        {
            "injection_enabled": false,
            "permanent": false,
        }

    in the same PATCH.
    """
    if not isinstance(asset_id, str) or not asset_id.strip():
        raise ValueError("A valid asset_id is required.")

    if not isinstance(patch_fields, dict):
        raise ValueError("patch_fields must be an object.")

    if not patch_fields:
        raise ValueError("No asset fields were provided.")

    unknown_fields = set(patch_fields) - EDITABLE_ASSET_FIELDS
    if unknown_fields:
        raise ValueError(
            f"Unsupported asset fields: {', '.join(sorted(unknown_fields))}"
        )

    asset = mongo.find_one_document(
        MONGO_ASSETS_COLLECTION,
        {"_id": asset_id},
    )
    if not asset:
        raise ValueError("Asset not found.")

    updates = {}

    # --- Identity / semantic enrichment ---

    if "display_name" in patch_fields:
        updates["display_name"] = _clean_optional_string(
            patch_fields["display_name"],
            max_length=255,
        )

    if "description" in patch_fields:
        updates["description"] = _clean_optional_string(
            patch_fields["description"],
            max_length=4096,
        )

    # --- Image-reference curation ---

    if "image_source_enabled" in patch_fields:
        image_source_enabled = _require_bool(
            patch_fields["image_source_enabled"],
            field_name="image_source_enabled",
        )

        if image_source_enabled and not _asset_is_image(asset):
            raise ValueError(
                "image_source_enabled can only be enabled for image assets."
            )

        updates["image_source_enabled"] = image_source_enabled

    # --- Prompt-library curation + retention invariant ---

    requested_injection_enabled = None
    if "injection_enabled" in patch_fields:
        requested_injection_enabled = _require_bool(
            patch_fields["injection_enabled"],
            field_name="injection_enabled",
        )

    requested_permanent = None
    if "permanent" in patch_fields:
        requested_permanent = _require_bool(
            patch_fields["permanent"],
            field_name="permanent",
        )

    current_injection_enabled = bool(asset.get("injection_enabled"))
    current_permanent = bool(
        (asset.get("lifecycle") or {}).get("permanent")
    )

    final_injection_enabled = (
        requested_injection_enabled
        if requested_injection_enabled is not None
        else current_injection_enabled
    )

    final_permanent = (
        requested_permanent
        if requested_permanent is not None
        else current_permanent
    )

    # Enabling ordinary prompt injection always promotes retention.
    if requested_injection_enabled is True:
        final_permanent = True

    # Do not permit a caller to leave an injected asset non-permanent.
    #
    # This also means the "disable injection and allow cleanup" dialog must
    # send both fields in one request, rather than toggling permanent first.
    if (
        ("injection_enabled" in patch_fields or "permanent" in patch_fields)
        and final_injection_enabled
        and not final_permanent
    ):
        raise ValueError(
            "An asset with injection_enabled=True must remain permanent. "
            "Disable injection in the same patch before unsetting permanent."
        )

    if requested_injection_enabled is not None:
        updates["injection_enabled"] = final_injection_enabled

    if (
        requested_permanent is not None
        or requested_injection_enabled is True
    ):
        # Dot-path update preserves lifecycle fields such as expiry,
        # deleted state, purge metadata, and other policy-owned siblings.
        updates["lifecycle.permanent"] = final_permanent

    # --- Project scope ---

    if "project_ids" in patch_fields:
        updates["project_ids"] = _normalize_project_ids(
            patch_fields["project_ids"]
        )

    if not updates:
        raise ValueError("No valid asset edits were supplied.")

    updates["updated_at"] = datetime.now(timezone.utc)

    # `update_one_document` takes field/dot-path updates directly in the
    # current MemoryMuse helper contract; do not wrap this in another $set.
    updated = mongo.update_one_document(
        MONGO_ASSETS_COLLECTION,
        {"_id": asset_id},
        updates,
    )

    return _serialize_asset_doc(updated)