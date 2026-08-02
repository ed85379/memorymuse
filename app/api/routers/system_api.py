from fastapi import APIRouter, HTTPException, Body, Request
from typing import Any
from pydantic import BaseModel
from app.core.time_location_utils import reload_user_location
from app.core.utils import serialize_doc
from app.config import muse_config, muse_settings, admin_config
from app.core.muse_profile import muse_profile
from app.core.states_core import (
    set_project_states,
    extract_pollable_states,
    get_states_doc,
    get_per_project_states,
    create_time_skip,
    clear_time_skip,
    update_thread_state,
    update_game_state,
    update_nav_state,
    update_files_state,
    get_active_time_skip_window,
    )

# --------------------------
# /api/config
# --------------------------
# <editor-fold desc="config">
config_router = APIRouter(prefix="/api/config", tags=["config"])

@config_router.get("/")
def get_full_config():
    return muse_config.as_dict()

@config_router.get("/grouped")
def get_grouped_config():
    return muse_config.as_grouped(include_meta=True)

@config_router.get("/user")
def get_user_config():
    return muse_settings.get_all()

@config_router.get("/admin")
def get_admin_config():
    return admin_config.get_all()

class UserConfigPatch(BaseModel):
    section: str
    data: dict

@config_router.patch("/user")
def patch_user_config(patch: UserConfigPatch):
    # validate allowed sections if you want
    if patch.section not in {
        "api_keys",
        "user_config",
        "muse_config",
        "muse_features",
        "llm_config",
        "tts_config",
        "social_config",
    }:
        raise HTTPException(status_code=400, detail="Invalid section")

    # this uses your existing helper:
    muse_settings.update_section(patch.section, patch.data)

    # return merged doc
    return muse_settings.get_all()

# Old stuff
@config_router.put("/{key}")
def set_config_value(key: str, value: Any = Body(..., embed=True)):
    print(f"key: {key}, value: {value}")
    try:
        muse_config.set(key, value)
        # If any location-related fields changed, refresh the cache:
        if key == "USER_ZIPCODE" or key == "USER_TIMEZONE" or key == "USER_COUNTRYCODE":
            reload_user_location()
            print(f"CONFIG DEBUG: reloaded")
        return {"status": "ok", "key": key, "value": value}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@config_router.delete("/{key}/revert")
def revert_config_value(key: str):
    result = muse_config.live.delete_one({"_id": key})
    if result.deleted_count:
        # If any location-related fields changed, refresh the cache:
        if key == "USER_ZIPCODE" or key == "USER_TIMEZONE" or key == "USER_COUNTRYCODE":
            reload_user_location()
        return {"status": "reverted", "key": key}
    else:
        return {"status": "not_found", "key": key}

# </editor-fold>

# --------------------------
# /api/states
# --------------------------
# <editor-fold desc="states">
states_router = APIRouter(prefix="/api/states", tags=["states"])

@states_router.get("/")
def get_states():
    states_doc = get_states_doc()

    if not states_doc:
        # No doc yet → just return implicit defaults for the UI
        return {
            "type": "states",
            "auto_assign": True,
            "blend_ratio": 0.5,
            "project_id": None,
        }

    state_doc = serialize_doc(states_doc)
    # Drop Mongo’s identity; keep only what the UI actually uses
    states_doc.pop("_id", None)
    return states_doc

@states_router.get("/time_skip")
def get_time_skip_state():
    time_skip_state = get_active_time_skip_window()
    return time_skip_state


@states_router.get("/{project_id}")
def get_project_state(project_id: str):
    per_projects_doc = get_per_project_states()

    # No states doc or no projects/per_project yet → implicit defaults
    if not per_projects_doc:
        return {
            "auto_assign": True,
            "blend_ratio": 0.5
        }

    per_projects_doc = serialize_doc(per_projects_doc)

    # Walk safely down the nested structure
    projects = per_projects_doc.get("projects", {})
    per_project = projects.get("per_project", {})
    project_state = per_project.get(project_id, {})

    auto_assign = project_state.get("auto_assign", True)
    blend_ratio = project_state.get("blend_ratio", 0.5)

    return {
        "auto_assign": auto_assign,
        "blend_ratio": blend_ratio
    }

@states_router.patch("/projects/{project_id}")
async def set_project_states_endpoint(project_id: str, request: Request):
    data = await request.json()
    success = set_project_states(project_id, data)
    return {"status": "ok" if success else "not found"}

@states_router.patch("/threads")
def set_thread_state(payload: dict):
    """
    Update global thread-related state.
    Expected payload keys:
      - open_thread_id: str | null (optional)
    """
    try:
        result = update_thread_state(payload)
        return {"status": "ok", "threads": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")

@states_router.patch("/games")
def set_game_state(payload: dict):
    """
    Update global game-related state.
    Expected payload keys:
      - open_game_id: str | null (optional)
    """
    try:
        result = update_game_state(payload)
        return {"status": "ok", "games": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")

@states_router.patch("/nav")
def set_nav_state(payload: dict):
    """
    Update global nav-related state.
    Expected payload keys:
      - main_tab: str | null (optional)
      - tools_panel_tab: str | null (optional)
    """
    try:
        result = update_nav_state(payload)
        return {"status": "ok", "nav": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")

@states_router.patch("/files")
def set_files_state(payload: dict):
    try:
        result = update_files_state(payload)
        return {"status": "ok", "files": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")

# </editor-fold>

# --------------------------
# /api/uipolling
# --------------------------
# <editor-fold desc="uipolling">
uipolling_router = APIRouter(prefix="/api/uipolling", tags=["uipolling"])

@uipolling_router.get("/")
def get_ui_polling_state():
    # 1) states: anything with pollable: true
    states = extract_pollable_states()

    # 2) muse_profile: any section with pollable: true
    profile_docs = muse_profile.get_pollable()

    # 3) config: any setting with pollable: true
    config_docs = muse_config.as_dict(pollable_only=True)

    return {
        "states": states,
        "muse_profile": profile_docs,
        "config": config_docs,
    }

# </editor-fold>

# --------------------------
# /api/timeskip
# --------------------------
# <editor-fold desc="timeskip">
time_skip_router = APIRouter(prefix="/api/time_skip", tags=["time_skip"])


@time_skip_router.post("/clear")
def clear_time_skip_button():
    clear_time_skip()
    return {"success": True}


@time_skip_router.post("/{message_id}")
async def set_time_skip(message_id: str):
    ok = await create_time_skip(message_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Anchor message not found")
    return {"success": True}



# </editor-fold>

