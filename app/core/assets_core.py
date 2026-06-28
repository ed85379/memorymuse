# core/assets_core.py
import hashlib
import mimetypes
import base64
import binascii
from bson import ObjectId
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

import requests
from werkzeug.utils import secure_filename

from app.config import ASSET_STORAGE_ROOT
from app.config import MONGO_ASSETS_COLLECTION
from app.databases.mongo_connector import mongo


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

    # Tool/provider origin
    created_by_tool: str | None = None
    provider: str | None = None
    model: str | None = None

    # Original external source, if any
    original_url: str | None = None
    final_url: str | None = None

    # Generation/edit context
    prompt: str | None = None
    explicit: bool | None = None
    seed: int | None = None
    image_size: str | None = None
    source_images: list[dict[str, Any]] | None = None

    # Escape hatch for provider-specific weirdness
    provider_response: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        data = {
            "source_type": self.source_type,
            "ingested_at": self.ingested_at,

            "created_by_tool": self.created_by_tool,
            "provider": self.provider,
            "model": self.model,

            "original_url": self.original_url,
            "final_url": self.final_url,

            "prompt": self.prompt,
            "explicit": self.explicit,
            "seed": self.seed,
            "image_size": self.image_size,
            "source_images": self.source_images,

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


def default_lifecycle() -> AssetLifecycle:
    return AssetLifecycle(
        permanent=False,
        status="available",
    )


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
    content_sha256: str | None = None,
    source_url: str | None = None,
    project_ids: list[str] | None = None,
    message_ids: list[str] | None = None,
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
        "size": size,

        "asset_type": asset_type,
        "source_type": source_type,
        "content_sha256": content_sha256,
        "source_url": source_url,

        "storage": {
            "backend": "local",
            "path": relative_path,
            "bytes_status": "available",
            "content_sha256": content_sha256,
            "purged_at": None,
        },

        "lifecycle": lifecycle_doc,

        "message_ids": message_ids or [],
        "project_ids": project_ids or [],
        "thread_ids": [],

        "text_indexing": {
            "is_text_indexed": False,
            "chunk_message_ids": [],
            "exclude_chunks_when_injected": True,
            "injected_message_ids": [],
        },

        "provenance": provenance_doc,

        "tombstone": None,
    }


def create_local_asset_from_bytes(
    *,
    file_bytes: bytes,
    filename: str | None,
    mimetype: str | None,
    source_type: str,
    asset_id: str | None = None,
    url: str | None = None,
    project_ids: list[str] | None = None,
    message_ids: list[str] | None = None,
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
        asset_type=asset_type,
        relative_path=str(relative_path).replace("\\", "/"),
        content_sha256=content_hash,
        source_url=url,
        project_ids=project_ids,
        message_ids=message_ids,
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
    message_ids: list[str] | None = None,
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
    if isinstance(provenance, AssetProvenance) and provenance.final_url is None:
        provenance.final_url = downloaded.final_url

    return create_local_asset_from_bytes(
        asset_id=asset_id,
        file_bytes=downloaded.file_bytes,
        filename=filename or downloaded.filename,
        mimetype=mimetype or downloaded.mimetype,
        source_type=source_type,
        url=url,
        project_ids=project_ids,
        message_ids=message_ids,
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
    message_ids: list[str] | None = None,
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
        message_ids=message_ids,
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
        "size": asset_doc.get("size"),

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

    return {
        "asset_id": asset_id,
        "asset_type": asset.get("asset_type"),
        "source_type": asset.get("source_type"),

        "filename": asset.get("filename"),
        "display_name": asset.get("display_name") or asset.get("filename"),
        "mimetype": asset.get("mimetype"),
        "size": asset.get("size"),

        "project_ids": [str(pid) for pid in asset.get("project_ids", [])],

        "lifecycle": {
            "status": lifecycle.get("status"),
            "permanent": lifecycle.get("permanent"),
            "expires_at": lifecycle.get("expires_at"),
        },

        "storage": {
            "status": storage.get("status"),
            "bytes_status": storage.get("bytes_status"),
        },

        "indexing": {
            "mode": indexing.get("mode", "none"),
            "status": indexing.get("status", "not_indexed"),
            "num_chunks": indexing.get("num_chunks"),
        },

        "width": dimensions.get("width"),
        "height": dimensions.get("height"),

        "created_at": asset.get("created_at"),
        "updated_at": asset.get("updated_at"),

        "content_url": f"/api/assets/{asset_id}/content",
    }

def build_asset_list_query(
    *,
    project_id: str | None = None,
    project_mode: str | None = None,
    source_type: str | None = None,
    asset_type: str | None = None,
    lifecycle_status: str | None = "available",
) -> dict:
    query: dict = {}

    if lifecycle_status:
        query["lifecycle.status"] = lifecycle_status

    if source_type:
        query["source_type"] = source_type

    if asset_type:
        query["asset_type"] = asset_type

    if project_id:
        try:
            project_oid = ObjectId(project_id)
        except Exception:
            raise ValueError("Invalid project_id")

        if project_mode in (None, "only"):
            query["project_ids"] = project_oid

        elif project_mode == "exclude":
            query["project_ids"] = {"$ne": project_oid}

        else:
            raise ValueError(
                "With project_id, project_mode must be 'only' or 'exclude'"
            )

    else:
        if project_mode is None:
            pass

        elif project_mode == "general":
            query["$or"] = [
                {"project_ids": {"$exists": False}},
                {"project_ids": {"$size": 0}},
                {"project_ids": None},
            ]

        elif project_mode == "linked":
            query["project_ids"] = {"$exists": True, "$ne": []}

        elif project_mode in ("only", "exclude"):
            raise ValueError(
                "project_mode='only' or 'exclude' requires project_id"
            )

        else:
            raise ValueError(
                "project_mode must be 'general', 'linked', 'only', or 'exclude'"
            )

    return query

def list_assets(
    *,
    project_id: str | None = None,
    project_mode: str | None = None,
    source_type: str | None = None,
    asset_type: str | None = None,
    lifecycle_status: str | None = "available",
    limit: int = 100,
    skip: int = 0,
) -> dict:
    query = build_asset_list_query(
        project_id=project_id,
        project_mode=project_mode,
        source_type=source_type,
        asset_type=asset_type,
        lifecycle_status=lifecycle_status,
    )

    limit = max(1, min(limit, 500))
    skip = max(0, skip)

    assets = mongo.find_documents(
        collection_name=MONGO_ASSETS_COLLECTION,
        query=query,
        sort=[("created_at", -1)],
        skip=skip,
        limit=limit,
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
            "limit": limit,
            "skip": skip,
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
        "content_sha256": content_sha256,
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