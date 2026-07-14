
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from bson import ObjectId
from datetime import datetime, timezone
from app.config import muse_settings
from app.core.files_core import get_all_message_ids_for_files
from app.core.utils import get_adaptive_top_k, strip_muse_private_blocks, strip_gm_notes
from app.core.states_core import set_active_project
from app.core.muse_responder import route_user_input
from app.core.prompt_profiles import build_webui_prompt, build_scene_webui_prompt, build_discord_prompt, build_speaker_prompt
from app.services.openai_client import api_openai_client
from app.api.queues import broadcast_queue, log_queue
from app.interfaces.websocket_server import broadcast_message
from app.core.threads_core import get_thread_type
from app.databases.memory_indexer import assign_message_id
from app.core.assets_core import create_local_asset_from_base64, get_all_message_ids_for_assets, find_living_asset_by_id, asset_doc_to_ref

async def handle_conversation_turn(data: dict, client):
    ## Shared client fields
    user_input = data.get("prompt", "")
    source = data.get("source", "webui")
    to_modality = data.get("to_modality", source)
    prompt_type = data.get("prompt_type", "webui")

    ## Optional client fields
    user_timestamp = data.get("timestamp")
    injected_files = data.get("injected_files", [])
    injected_assets = data.get("injected_assets", [])
    ephemeral_files = data.get("ephemeral_files", [])

    auto_assign = data.get("auto_assign", False)
    blend_ratio = data.get("blend_ratio", 0.0)
    project_id = normalize_project_id(data.get("project_id"))
    thread_id = data.get("thread_id")

    broadcast_user = data.get("broadcast_user", True)
    broadcast_muse = data.get("broadcast_muse", True)
    log_user = data.get("log_user", True)
    log_muse = data.get("log_muse", True)

    extended_history = muse_settings.get_section('muse_features').get('ENABLE_THREAD_EXTENDED_HISTORY')
    unsummarized_only = muse_settings.get_section('muse_features').get('HIDE_SUMMARIZED_THREAD_MESSAGES')

    if not user_input:
        return JSONResponse(status_code=400, content={"error": "No prompt provided."})

    ## File/context prep
    injected_file_ids = [ObjectId(fid) for fid in injected_files]
    message_ids_to_exclude = get_all_message_ids_for_files(injected_file_ids)

    injected_asset_ids = [aid for aid in injected_assets]
    message_ids_to_exclude = get_all_message_ids_for_assets(injected_asset_ids)

    num_injected_chunks = len(message_ids_to_exclude)
    num_ephemeral_chunks = len(ephemeral_files)
    total_chunks = num_injected_chunks + num_ephemeral_chunks

    default_top_k = 10 # Move this to an advanced setting
    min_top_k = 3 # Move this to an advanced setting
    final_top_k = get_adaptive_top_k(min_top_k, default_top_k, total_chunks)

    ## Optional UI/project state
    # We might want multiple states once we have a mobile app, or they can share.
    active_project_report = None
    if project_id:
        active_project_report = set_active_project(project_id=project_id)

    ## Thread/prompt resolution
    thread_type = None
    if thread_id:
        thread_type = get_thread_type_or_404(thread_id)

    # Converts thread-capable prompt types to scene when appropriate
    prompt_type = resolve_prompt_type(
        prompt_type=prompt_type,
        thread_id=thread_id,
        thread_type=thread_type,
    )

    timestamp_for_context = datetime.now(timezone.utc).isoformat()

    prompt_kwargs = {
        "source": source,
        "timestamp": timestamp_for_context,
        "message_ids_to_exclude": message_ids_to_exclude,
        "final_top_k": final_top_k,
        "ephemeral_files": ephemeral_files,

        ## Only relevant when in project-capable prompt type with pre-uploaded files
        "injected_file_ids": injected_file_ids,
        "injected_asset_ids": injected_asset_ids,

        ## Only relevant when in a thread-capable prompt type
        "extended_history": extended_history,
        "unsummarized_only": unsummarized_only,

        ## Optional project/thread UI-ish states
        "thread_id": thread_id,
        "project_id": project_id,
        "blend_ratio": blend_ratio,
        "active_project_report": active_project_report,
    }

    dev_prompt, user_assistant_messages, tool_bundle = build_prompt_for_type(
        prompt_type=prompt_type,
        user_input=user_input,
        prompt_kwargs=prompt_kwargs,
    )

    user_msg = {
        "message": user_input,
        "timestamp": user_timestamp or datetime.now(timezone.utc).isoformat(),
        "role": "user",
        "source": source,
        "payload_type": "user_message",
    }

    user_message_id = assign_message_id(user_msg)
    user_msg["message_id"] = user_message_id

    if project_id and auto_assign:
        user_msg["project_id"] = project_id
    if thread_id:
        user_msg["thread_id"] = thread_id

    asset_refs = []

    # 1. Newly dropped / ephemeral chat files: ingest, then reference.
    for index, file_obj in enumerate(ephemeral_files or []):
        name = file_obj.get("name") or "untitled"
        mimetype = file_obj.get("type") or "application/octet-stream"

        asset_doc = create_local_asset_from_base64(
            asset_id=file_obj.get("asset_id"),
            data=file_obj.get("data") or "",
            filename=name,
            mimetype=mimetype,
            source_type="chat_upload",
            project_ids=[project_id] if project_id else None,
            provenance={
                "source_type": "chat_upload",
                "original_filename": name,
                "uploaded_via": source,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            },
            lifecycle={
                "permanent": False,
            },
        )

        asset_refs.append(
            asset_doc_to_ref(
                asset_doc,
                role=file_obj.get("role") or "attachment",
                display=file_obj.get("display"),
                order=file_obj.get("order", index),
            )
        )

    # 2. Existing deliberately injected assets: resolve, then reference.
    injected_order_start = len(asset_refs)

    for offset, injected_asset in enumerate(injected_assets or []):
        # Adapt this depending on whether injected_assets is already a list
        # of IDs or small frontend objects like {"asset_id": "..."}.
        asset_id = (
            injected_asset.get("asset_id")
            if isinstance(injected_asset, dict)
            else injected_asset
        )

        if not asset_id:
            continue

        asset_doc = find_living_asset_by_id(asset_id)
        if not asset_doc:
            # Ideally this was already filtered earlier during injection
            # resolution, so this is just a harmless final guard.
            continue

        asset_refs.append(
            asset_doc_to_ref(
                asset_doc,
                role="injected_asset",
                order=injected_order_start + offset,
            )
        )

    if asset_refs:
        user_msg.setdefault("metadata", {})
        user_msg["metadata"]["assets"] = asset_refs

    if broadcast_user:
        await broadcast_queue.put(user_msg)

    ## The commands run by the muse may need this additional context, so we provide it here
    command_context = build_command_context(
        project_id=project_id,
        thread_id=thread_id,
        thread_type=thread_type,
    )

    result, final_text = await run_model_turns_with_optional_followup(
        dev_prompt=dev_prompt,
        user_assistant_messages=user_assistant_messages,
        client=client,
        prompt_type=prompt_type,
        tool_bundle=tool_bundle,
        command_context=command_context,
        to_modality=to_modality,
    )


    if not final_text.strip():
        # Only commands were present; nothing to display
        return

    response_timestamp = datetime.now(timezone.utc).isoformat()

    muse_msg = {
        "message": final_text,
        "timestamp": response_timestamp,
        "role": "muse",
        "source": source,
        "to": to_modality,
        "metadata": {
            "usage": result.usage,
            "tool_calls": result.tool_calls,
            "assets": result.assets,
        },
    }

    muse_message_id = assign_message_id(muse_msg)
    muse_msg["message_id"] = muse_message_id

    if project_id and auto_assign:
        muse_msg["project_id"] = project_id
    if thread_id:
        muse_msg["thread_id"] = thread_id

    broadcast_text = apply_output_visibility_filters(final_text, to_modality)

    muse_broadcast_msg = muse_msg.copy()
    muse_broadcast_msg["message"] = broadcast_text

    if broadcast_muse:
        await broadcast_queue.put(muse_broadcast_msg)

    if log_user:
        await log_queue.put(user_msg)
    if log_muse:
        await log_queue.put(muse_msg)

    return {"response": broadcast_text}

def merge_turn_results(primary, secondary):
    primary.usage.extend(secondary.usage)
    primary.tool_calls.extend(secondary.tool_calls)
    primary.assets.extend(secondary.assets)

    for index, asset in enumerate(primary.assets):
        asset["order"] = index

    return primary

def normalize_project_id(project_id):
    if isinstance(project_id, str) and not project_id.strip():
        return None
    return project_id

def get_thread_type_or_404(thread_id=None):
    if not thread_id:
        return None
    thread_type = get_thread_type(thread_id)
    if thread_type is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread_type

def build_command_context(project_id, thread_id, thread_type):
    return {
        "project_id": project_id,
        "thread_id": thread_id,
        "thread_type": thread_type if thread_id else None,
    }

def resolve_prompt_type(prompt_type: str, thread_id=None, thread_type=None):
    if prompt_type == "webui" and thread_id and thread_type == "scene":
        return "scene"
    return prompt_type

def build_prompt_for_type(prompt_type: str, user_input: str, prompt_kwargs: dict):
    if prompt_type == "scene":
        return build_scene_webui_prompt(
            user_input,
            **prompt_kwargs,
        )

    if prompt_type == "webui":
        return build_webui_prompt(
            user_input,
            **prompt_kwargs,
        )

    if prompt_type == "speaker":
        return build_speaker_prompt(
            user_input,
            **prompt_kwargs,
        )

    if prompt_type == "discord":
        return build_discord_prompt(
            user_input,
            **prompt_kwargs,
        )

    raise ValueError(f"Unknown prompt_type: {prompt_type}")

async def run_conversation_model_turn(
    *,
    dev_prompt,
    user_assistant_messages,
    client,
    prompt_type,
    tool_bundle,
    command_context,
):
    return await route_user_input(
        dev_prompt=dev_prompt,
        user_assistant_messages=user_assistant_messages,
        client=client,
        prompt_type=prompt_type,
        tool_bundle=tool_bundle,
        command_context=command_context,
    )

async def run_model_turns_with_optional_followup(
    *,
    dev_prompt,
    user_assistant_messages,
    client,
    prompt_type,
    tool_bundle,
    command_context,
    to_modality,
):
    result = await run_conversation_model_turn(
        dev_prompt=dev_prompt,
        user_assistant_messages=user_assistant_messages,
        client=client,
        prompt_type=prompt_type,
        tool_bundle=tool_bundle,
        command_context=command_context,
    )

    if not result.response_text.strip():
        return result, ""

    final_text = result.response_text

    if result.followup_turn:
        await broadcast_message(
            message=f"{muse_settings.get_section('muse_config').get('MUSE_NAME')} is adding to their response...",
            timestamp=datetime.now(timezone.utc).isoformat(),
            role="muse",
            to_modality=to_modality,
            payload_type="status_message",
        )

        user_assistant_messages.append(
            build_followup_turn_message(
                previous_response=result.response_text,
                followup_intent=result.followup_turn,
            )
        )

        followup_result = await run_conversation_model_turn(
            dev_prompt=dev_prompt,
            user_assistant_messages=user_assistant_messages,
            client=client,
            prompt_type=prompt_type,
            tool_bundle=tool_bundle,
            command_context=command_context,
        )

        if followup_result.response_text.strip():
            final_text += "\n\n***\n\n" + followup_result.response_text.strip()

        result = merge_turn_results(result, followup_result)

    return result, final_text

def build_followup_turn_message(previous_response: str, followup_intent: str):
    muse_name = muse_settings.get_section('muse_config').get('MUSE_NAME')

    text = (
        f"\n\n{muse_name} said:\n"
        f"{previous_response}\n\n"
        "This is a follow-up turn you chose to take after your previous response.\n"
        f"Your intent for this turn: {followup_intent}\n"
        "Treat this response as a continuation, correction, or completion of the previous response.\n"
        "Do not repeat the previous response unless necessary for a brief correction.\n"
        "Do not use  again in this response."
    )

    return {
        "role": "user", # As part of NoAss philosophy, sending the messages back to the model as 'assistant', flattens the responses.
        "text": text,
    }

PRIVATE_BLOCK_CAPABLE_MODALITIES = {"webui", "mobileui"}

def modality_can_show_private_blocks(to_modality: str) -> bool:
    return to_modality in PRIVATE_BLOCK_CAPABLE_MODALITIES


def thought_view_enabled() -> bool:
    return (
        muse_settings.get_section("muse_features") or {}
    ).get("ENABLE_THOUGHT_VIEW", True)


def gm_view_enabled() -> bool:
    return (
        muse_settings.get_section("muse_features") or {}
    ).get("ENABLE_GM_VIEW", False)


def apply_output_visibility_filters(text: str, to_modality: str) -> str:
    broadcast_text = text

    show_private_blocks = (
        modality_can_show_private_blocks(to_modality)
        and thought_view_enabled()
    )

    if not show_private_blocks:
        broadcast_text = strip_muse_private_blocks(broadcast_text)

    if not gm_view_enabled():
        broadcast_text = strip_gm_notes(broadcast_text)

    return broadcast_text