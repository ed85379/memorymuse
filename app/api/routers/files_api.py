# app/routers/files_api.py
from fastapi import APIRouter, HTTPException, Form, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from typing import Optional
from datetime import datetime
import os
from bson import ObjectId
from app.databases.mongo_connector import mongo
from app.config import MONGO_PROJECTS_COLLECTION, MONGO_FILES_COLLECTION, MONGO_MEMORY_COLLECTION, MONGO_CONVERSATION_COLLECTION
from app.core import files_core
from app.core.utils import serialize_doc
from app.api.queues import index_queue


router = APIRouter(prefix="/api/files", tags=["files"])

@router.get("/")
def get_files(
    project_id: str = None,
    mode: str = None
):
    """
    File listing endpoint with explicit mode/project_id logic.

    - If neither project_id nor mode: all files (no filter)
    - If project_id only: only files linked to that project (mode='only')
    - If mode only:
        - mode='only': only unlinked/orphan files
        - mode='exclude': only linked files (no orphans)
    - If both project_id and mode:
        - mode='only': only files linked to that project
        - mode='exclude': all files except those linked to that project
    """

    query = {}
    query["is_deleted"] = {"$ne": True }

    if project_id and not mode:
        # project_id only: default to 'only'
        query["project_ids"] = ObjectId(project_id)

    elif not project_id and mode:
        if mode == "only":
            # Only unlinked/orphans
            query["$or"] = [
                {"project_ids": {"$exists": False}},
                {"project_ids": {"$size": 0}}
            ]
        elif mode == "exclude":
            # Only files linked to at least one project
            query["project_ids"] = {"$exists": True, "$ne": []}
        else:
            raise HTTPException(status_code=400, detail="mode must be 'only' or 'exclude'")

    elif project_id and mode:
        if mode == "only":
            query["project_ids"] = ObjectId(project_id)
        elif mode == "exclude":
            query["project_ids"] = {"$ne": ObjectId(project_id)}
        else:
            raise HTTPException(status_code=400, detail="mode must be 'only' or 'exclude'")

    # else: no project_id and no mode → query remains {}, so all files

    files = mongo.find_documents(
        collection_name=MONGO_FILES_COLLECTION,
        query=query
    )
    result = [serialize_doc(f) for f in files]
    return {"files": result}

@router.get("/{file_id}/raw")
def get_file_raw(file_id: str):
    file_doc = mongo.find_one_document(
        collection_name=MONGO_FILES_COLLECTION,
        query={"_id": ObjectId(file_id)}
    )
    if not file_doc or not file_doc.get("path"):
        raise HTTPException(status_code=404, detail="File not found")

    file_path = file_doc["path"]
    filename = file_doc.get("filename", "download")
    mimetype = file_doc.get("mimetype") or "application/octet-stream"
    # When serving text/plain, add charset
    if mimetype.startswith("text/") and "charset" not in mimetype:
        mimetype = mimetype + "; charset=utf-8"

    # 3. Open file as stream
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File missing on disk")

    def iterfile():
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk

    # 4. Set content-disposition (inline for images/text/pdf, attachment for others)
    inline_types = ["image/", "text/", "application/pdf"]
    disposition_type = "inline" if any(mimetype.startswith(t) for t in inline_types) else "attachment"
    content_disposition = f'{disposition_type}; filename="{filename}"'

    return StreamingResponse(
        iterfile(),
        media_type=mimetype,
        headers={
            "Content-Disposition": content_disposition
        }
    )

@router.post("/upload")
async def upload_file(
    project_ids: Optional[str] = Form(default=None),
    file: UploadFile = File(...)
):
    # Parse project_ids from JSON string to list
    if project_ids:
        import json
        project_ids = json.loads(project_ids)
    else:
        project_ids = []
    # If 'project_id' is still used in frontend, fold it in for compatibility
    if not project_ids:
        project_id = None
        try:
            # Try to extract single project_id from form fields (if present)
            project_id = (await file.form()).get("project_id")
        except Exception:
            pass
        if project_id:
            project_ids = [project_id]
    try:
        # Accept only pure text and image types for now
        if file.content_type.startswith("text/"):
            result = await files_core.handle_text_file_upload(project_ids, file)
            return JSONResponse(status_code=200, content=result)
        elif file.content_type.startswith("image/"):
            try:
                result = await files_core.handle_image_file_upload(project_ids, file)
                return JSONResponse(status_code=200, content=result)
            except NotImplementedError as e:
                raise HTTPException(status_code=501, detail=str(e))
        else:
            raise HTTPException(
                status_code=415,  # Unsupported Media Type
                detail="Only pure text files and images are supported at this time."
            )
    except HTTPException as e:
        raise e
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": f"File upload failed: {str(e)}"}
        )

@router.delete("/{file_id}")
async def delete_file(file_id: str):
    file_id = ObjectId(file_id)
    # 1. Fetch the file document
    file_doc = mongo.find_one_document(MONGO_FILES_COLLECTION, {"_id": file_id})
    now = datetime.utcnow()

    if not file_doc or file_doc.get("is_deleted"):
        return {"status": "not_found_or_already_deleted"}

    # 2. Mark linked messages and facts as deleted & update timestamps
    for mid in file_doc.get("message_ids", []):
        mongo.update_one_document_array(
            MONGO_CONVERSATION_COLLECTION,
            {"message_id": mid},
            {"$set": {"is_deleted": True, "updated_on": now}}
        )
        await index_queue.put(mid)

    fact_id = file_doc.get("fact_id")
    if fact_id:
        mongo.update_one_document_array(
            MONGO_MEMORY_COLLECTION,
            {"_id": fact_id},
            {"$set": {"is_deleted": True, "updated_on": now}}
        )

    # 3. Mark the file itself as deleted
    mongo.update_one_document_array(
        MONGO_FILES_COLLECTION,
        {"_id": file_id},
        {"$set": {"is_deleted": True, "updated_on": now}}
    )

    # 4. Move file_id from file_ids to deleted_file_ids in each project
    for pid in file_doc.get("project_ids", []):
        mongo.update_one_document_array(
            MONGO_PROJECTS_COLLECTION,
            {"_id": pid},
            {
                "$pull": {"file_ids": file_id},
                "$addToSet": {"deleted_file_ids": file_id},
                "$set": {"updated_on": now}
            }
        )

    return {"status": "deleted", "file_id": str(file_id)}


## This feature is on hold. This def is NOT complete. Do not run it as-is.
@router.post("/update/{file_id}")
async def update_file(
    file_id: str,
    project_id: str,
    file: UploadFile = File(...),
    branch: bool = Form(default=False)
):
    from bson import ObjectId
    from datetime import datetime
    import json

    file_id = ObjectId(file_id)
    now = datetime.utcnow()

    # 1. Fetch existing file doc
    file_doc = mongo.find_one_document(MONGO_FILES_COLLECTION, {"_id": file_id})
    if not file_doc or file_doc.get("is_deleted"):
        return JSONResponse(status_code=404, content={"status": "not_found_or_deleted"})

    # 2. If branching, detach and treat as new upload
    if branch:
        # MOVE THIS TO AFTER SUCCESS: Detach original file from the current project
        await files_core.modify_file_project_link_core(
            project_id,
            str(file_id),
            "detach",
            mongo=mongo,
            index_queue=index_queue,
        )
        # Call your upload logic (text/image distinction handled in files_core)
        if file.content_type.startswith("text/"):
            result = await files_core.handle_text_file_upload(file_doc.get("project_ids", []), file)
        elif file.content_type.startswith("image/"):
            result = await files_core.handle_image_file_upload(file_doc.get("project_ids", []), file)
        else:
            return JSONResponse(status_code=415, content={"status": "unsupported_media_type"})
        # Record provenance
        mongo.update_one_document_array(
            MONGO_FILES_COLLECTION,
            {"_id": ObjectId(result["file_id"])},
            {"$set": {"branched_from": file_id, "updated_on": now}}
        )
        return JSONResponse(status_code=200, content={
            "status": "branched",
            "old_file_id": str(file_id),
            "new_file_id": result.get("file_id")
        })

    # 3. Pre-update checks
    # Filename
    if file.filename != file_doc.get("filename"):
        return JSONResponse(status_code=400, content={
            "status": "filename_mismatch",
            "msg": "Filename differs. Confirm intent before updating."
        })
    # File type/content type
    if file.content_type != file_doc.get("content_type"):
        return JSONResponse(status_code=400, content={
            "status": "file_type_mismatch",
            "msg": "File types must match for updates."
        })
    # Diff (byte-for-byte)
    current_bytes = await files_core.load_file_bytes(file_doc["path"])
    new_bytes = await file.read()
    if current_bytes == new_bytes:
        return JSONResponse(status_code=200, content={
            "status": "no_change",
            "msg": "Uploaded file is identical to existing file."
        })
    # Max revisions check
    max_revisions = 5  # Or load from config
    current_revs = file_doc.get("revisions", [])
    if len(current_revs) >= max_revisions:
        return JSONResponse(status_code=400, content={
            "status": "max_revisions",
            "msg": "Maximum revisions reached. Delete old revisions before updating."
        })

    # 4. Archive current file doc into revisions array
    revision = {k: v for k, v in file_doc.items() if k not in ["_id", "revisions"]}
    revision["revisioned_on"] = now
    new_revs = current_revs + [revision]

    # 5. Store new file data (persist to disk/storage)
    new_file_path, new_size = await files_core.store_file(file)
    update_fields = {
        "filename": file.filename,
        "size": new_size,
        "path": new_file_path,
        "uploaded_on": now,
        "revisions": new_revs,
        "updated_on": now,
    }
    mongo.update_one_document_array(
        MONGO_FILES_COLLECTION,
        {"_id": file_id},
        {"$set": update_fields}
    )

    # 6. Re-process as text or image
    if file.content_type.startswith("text/"):
        # Chunk new text, create new messages, get new IDs
        new_message_ids = await files_core.chunk_and_store_text(file, file_id, project_ids=file_doc.get("project_ids", []))
        # Mark old messages as superseded
        for mid in file_doc.get("message_ids", []):
            mongo.update_one_document_array(
                MONGO_CONVERSATION_COLLECTION,
                {"message_id": mid},
                {"$set": {"superseded": True, "updated_on": now}}
            )
            await index_queue.put(mid)
        # Update file doc with new message_ids
        mongo.update_one_document_array(
            MONGO_FILES_COLLECTION,
            {"_id": file_id},
            {"$set": {"message_ids": new_message_ids}}
        )
    elif file.content_type.startswith("image/"):
        # Re-caption and create new fact
        new_fact_id = await files_core.create_image_fact(file, file_id)
        old_fact_id = file_doc.get("fact_id")
        if old_fact_id:
            mongo.update_one_document_array(
                MONGO_MEMORY_COLLECTION,
                {"_id": old_fact_id},
                {"$set": {"superseded": True, "updated_on": now}}
            )
        mongo.update_one_document_array(
            MONGO_FILES_COLLECTION,
            {"_id": file_id},
            {"$set": {"fact_id": new_fact_id}}
        )

    return JSONResponse(status_code=200, content={
        "status": "updated",
        "file_id": str(file_id),
        "updated_on": now.isoformat()
    })