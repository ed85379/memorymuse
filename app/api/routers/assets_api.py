from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form, Body
from fastapi.responses import FileResponse
from datetime import datetime, timezone
from app.config import ASSET_STORAGE_ROOT, MONGO_ASSETS_COLLECTION
from app.databases.mongo_connector import mongo
from app.core.assets_core import (
    list_assets,
    AssetLifecycle,
    create_local_asset_from_bytes,
    index_asset_text_for_recall,
    is_text_asset_mimetype,
    mark_asset_recall_indexed,
    asset_for_ui,
    soft_delete_asset,
)

router = APIRouter(
    prefix="/api/assets",
    tags=["assets"],
)


ALLOWED_ASSET_VARIANTS = {"original", "display", "thumbnail"}

@router.get("/")
def list_assets_endpoint(
    project_id: str | None = None,
    project_mode: str | None = None,
    source_type: str | None = None,
    asset_type: str | None = None,
    lifecycle_status: str | None = "available",
    limit: int = 100,
    skip: int = 0,
):
    try:
        result = list_assets(
            project_id=project_id,
            project_mode=project_mode,
            source_type=source_type,
            asset_type=asset_type,
            lifecycle_status=lifecycle_status,
            limit=limit,
            skip=skip,
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{asset_id}/content")
async def get_asset_content(
    asset_id: str,
    size: str | None = Query(default=None),
    variant: str | None = Query(default=None),
    download: bool = Query(default=False),
):
    requested_variant = variant or size or "original"

    if requested_variant not in ALLOWED_ASSET_VARIANTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported asset variant: {requested_variant}",
        )

    asset_doc = mongo.find_one_document(
        MONGO_ASSETS_COLLECTION,
        {"_id": asset_id},
    )

    if not asset_doc:
        raise HTTPException(status_code=404, detail="Asset not found")

    storage = asset_doc.get("storage") or {}
    lifecycle = asset_doc.get("lifecycle") or {}

    if lifecycle.get("status") in {"purged", "expired", "missing"}:
        raise HTTPException(status_code=410, detail="Asset is no longer available")

    if storage.get("bytes_status") != "available":
        raise HTTPException(status_code=410, detail="Asset bytes are not available")

    variants = asset_doc.get("variants") or {}

    variant_doc = variants.get(requested_variant)

    # v1 fallback: thumbnail/display requests fall back to original bytes
    if not variant_doc:
        variant_doc = {
            "path": storage.get("path"),
            "mimetype": asset_doc.get("mimetype"),
            "filename": asset_doc.get("filename"),
        }

    relative_path = variant_doc.get("path")

    if not relative_path:
        raise HTTPException(status_code=404, detail="Asset file path not found")

    full_path = Path(ASSET_STORAGE_ROOT) / relative_path

    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="Asset file missing from storage")

    mimetype = (
        variant_doc.get("mimetype")
        or asset_doc.get("mimetype")
        or "application/octet-stream"
    )

    filename = (
        variant_doc.get("filename")
        or asset_doc.get("filename")
        or asset_id
    )

    # Images display inline by default.
    # Non-images download by default.
    # `?download=true` forces attachment behavior.
    is_image = mimetype.startswith("image/")
    as_attachment = download or not is_image

    return FileResponse(
        path=full_path,
        media_type=mimetype,
        filename=filename if as_attachment else None,
    )

@router.post("/upload")
async def upload_asset(
    file: UploadFile = File(...),
    project_ids: list[str] = Form(default=[]),
    index_for_recall: bool = Form(False),
):
    data = await file.read()

    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    mimetype = file.content_type or "application/octet-stream"
    filename = file.filename or "uploaded-file"

    try:
        asset_doc = create_local_asset_from_bytes(
            file_bytes=data,
            filename=filename,
            mimetype=mimetype,
            source_type="user_upload",
            project_ids=project_ids or [],
            lifecycle=AssetLifecycle(
                status="available",
                permanent=True,
            ),
            provenance={
                "source": "files_manager_upload",
            },
        )

        if index_for_recall and is_text_asset_mimetype(mimetype, filename):
            message_ids = await index_asset_text_for_recall(asset_doc)
            await mark_asset_recall_indexed(asset_doc["_id"], message_ids)

            # Keep returned doc in sync without needing to re-query Mongo.
            asset_doc.setdefault("indexing", {})
            asset_doc["indexing"].update({
                "recall_indexed": True,
                "indexed_on": datetime.now(timezone.utc),
                "message_ids": message_ids,
                "num_chunks": len(message_ids),
            })

        return {"asset": asset_for_ui(asset_doc)}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Asset upload failed: {e}")

@router.delete("/{asset_id}")
async def delete_asset(asset_id: str):
    return await soft_delete_asset(
        asset_id,
        deleted_by="user",
    )