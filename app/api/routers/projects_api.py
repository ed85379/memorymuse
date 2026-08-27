# /api/routers/projects_api.py
from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from app.config import MONGO_FILES_COLLECTION, MONGO_PROJECTS_COLLECTION, MONGO_MEMORY_COLLECTION, MONGO_CONVERSATION_COLLECTION
from app.core import projects_core
from app.core.utils import serialize_doc, ensure_list
from app.api.queues import index_queue
from app.databases.mongo_connector import mongo


router = APIRouter(prefix="/api/projects", tags=["projects"])

@router.get("/")
def get_projects():
    query = {}
    projects = mongo.find_documents(
        collection_name=MONGO_PROJECTS_COLLECTION,
        query=query,
    )
    result = []
    for project in projects:
        mapped = {
            "_id": str(project["_id"]),
            "name": project.get("name") or "",
            "description": project.get("description") or "",
            "shortdesc": project.get("shortdesc") or "",
            "tags": project.get("tags", []),
            "notes": project.get("notes", []),
            "is_hidden": project.get("is_hidden", False),
            "is_private": project.get("is_private", False),
            "archived": project.get("archived", False),
            "code_intensity": project.get("code_intensity", "MIXED")
        }
        result.append(mapped)

    return {"projects": result[::-1]}

@router.get("/{key}")
def get_project(key: str):
    query = {"_id": ObjectId(key)}
    project = mongo.find_one_document(
        collection_name=MONGO_PROJECTS_COLLECTION,
        query=query,
    )
    project = {
        "_id": str(project["_id"]),
        "name": project.get("name") or "",
        "description": project.get("description") or "",
        "shortdesc": project.get("shortdesc") or "",
        "tags": project.get("tags", []),
        "notes": project.get("notes", []),
        "is_hidden": project.get("is_hidden", False),
        "is_private": project.get("is_private", False),
        "archived": project.get("archived", False),
        "code_intensity": project.get("code_intensity", "MIXED")
    }

    return {"project": project}

@router.post("/")
def create_project():
    now = datetime.utcnow()
    project_id = ObjectId()
    try:
        project = {
            "_id": project_id,
            "name": "New Project",
            "is_hidden": False,
            "is_private": False,
            "notes": [],
            "tags": [],
            "created_at": now,
            "updated_at": now
        }
        mongo.insert_one_document(MONGO_PROJECTS_COLLECTION, project)

        # Create the companion Project Facts doc
        project_facts = {
            "id": f"project_facts_{str(project_id)}",
            "type": "project_layer",
            "project_id": project_id,
            "name": "Project Facts",
            "purpose": "Project-scoped truths, specific to one project. Mostly user-managed. Add when instructed, preserve verbatim. Useful for accuracy and reference.",
            "max_entries": 50,
            "order": 98,
            "entries": [],
            "created_at": now,
            "updated_at": now
        }
        mongo.insert_one_document(MONGO_MEMORY_COLLECTION, project_facts)

        return serialize_doc(project)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{key}/visibility")
def toggle_project_visibility(key: str):
    try:
        result = projects_core.toggle_visibility({"_id": key})
        return {"status": "ok", "key": key, "is_hidden": result.is_hidden}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{key}/privacy")
def toggle_project_privacy(key: str):
    try:
        result = projects_core.toggle_privacy({"_id": key})
        return {"status": "ok", "key": key, "is_private": result.is_private}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{key}/archive")
def toggle_project_archived(key: str):
    try:
        result = projects_core.toggle_archived({"_id": key})
        return {"status": "ok", "key": key, "archived": result.archived}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/{key}")
def edit_project(key: str, patch_fields: dict):
    try:
        print("PATCH fields received:", patch_fields)
        result = projects_core.edit_project_fields({"_id": key}, patch_fields)
        result = [serialize_doc(result)]
        return {"status": "ok", "key": key, "project": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{key}/tags")
def get_project_tags(key: str):
    # Build the aggregation pipeline
    pipeline = [
        {"$match": {"project_id": ObjectId(key)}},
        {"$unwind": "$user_tags"},
        {"$group": {"_id": "$user_tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}}
    ]
    tag_docs = list(mongo.db[MONGO_CONVERSATION_COLLECTION].aggregate(pipeline))
    return {"tags": [{"tag": doc["_id"], "count": doc["count"]} for doc in tag_docs]}

@router.get("/files")
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

@router.get("/{key}/files")
def get_project_files(key: str):
    # 1. Fetch the project doc by key
    project = mongo.find_one_document(
        collection_name=MONGO_PROJECTS_COLLECTION,
        query={"_id": ObjectId(key)}
    )

    if not project or not project.get("file_ids"):
        return {"files": []}  # No files attached

    file_ids = project["file_ids"]

    # 2. Query the files collection for these IDs
    files = mongo.find_documents(
        collection_name=MONGO_FILES_COLLECTION,
        query={"_id": {"$in": file_ids}}
    )

    # 3. Build the response
    result = []
    for file in files:
        mapped = {
            "_id": str(file["_id"]),
            "filename": file.get("filename", ""),
            "tags": file.get("tags", []),
            "mimetype": file.get("mimetype", ""),
            "size": file.get("size", ""),
            "uploaded_on": file.get("uploaded_on"),
            "path": file.get("path"),
            "message_ids": file.get("message_ids"),
            "caption": file.get("caption", "")
            # ...add any other fields you need
        }
        result.append(mapped)

    return {"files": result}


