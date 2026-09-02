# core/prompt_builder.py
import base64
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import humanize
from bson import ObjectId
from app.core import memory_core, journal_core, discovery_core, utils
from app.databases import graphdb_connector
from sentence_transformers import SentenceTransformer
from app.databases.mongo_connector import mongo, mongo_system
from app.databases.qdrant_connector import search_collection
from app.core.text_filters import get_text_filter_config, filter_text
import numpy as np
from app.config import muse_settings, MONGO_FILES_COLLECTION, MONGO_PROJECTS_COLLECTION, MONGO_STATES_COLLECTION, \
    MONGO_MEMORY_COLLECTION, QDRANT_MEMORY_COLLECTION, QDRANT_CONVERSATION_COLLECTION, SENTENCE_TRANSFORMER_MODEL, \
    MONGO_THREADS_COLLECTION
from app.core.muse_profile import muse_profile
from app.services.feeds import get_dot_status, get_openweathermap, get_space_weather
from app.core.time_location_utils import _load_user_location, get_local_human_time, is_quiet_hour, user_data
from app.core.assets.assets_core import find_living_asset_by_id, read_asset_base64
from app.core.games.game_service import render_game_prompt_contexts
from app.core.context_formatting import format_context_entry

def collect_prompt_context(**context_kwargs):
    # Set user locality
    loc = _load_user_location()
    timestamp = context_kwargs.get("timestamp")
    if timestamp:
        ts_utc = datetime.fromisoformat(timestamp)
        local_timestamp = ts_utc.astimezone(ZoneInfo(loc.timezone)).strftime("%Y-%m-%d %H:%M:%S")
    else:
        local_timestamp = ""
    # Set names
    muse_name = muse_settings.get_section('muse_config').get('MUSE_NAME')
    author_name = (
            context_kwargs.get("author_name")
            or muse_settings.get_section("user_config").get("USER_NAME", "Unknown Person")
    )
    # Set sources, projects, and thread information
    source = context_kwargs.get("source", "")
    source_name = utils.LOCATIONS.get(source, source or "Unknown Source")
    project_id = context_kwargs.get("project_id", None)
    project_name, project_meta, project_code_intensity = utils.prompt_projects_helper(project_id)
    thread_id = context_kwargs.get("thread_id", "")
    extended_history = context_kwargs.get("extended_history", False)
    unsummarized_only = context_kwargs.get("unsummarized_only", False)
    allow_summarization = context_kwargs.get("allow_summarization", True)
    thread_title, thread_meta = utils.prompt_threads_helper(thread_id)
    # Passthrough values
    active_project_report = context_kwargs.get("active_project_report", {})
    injected_file_ids = context_kwargs.get("injected_file_ids", [])
    injected_asset_ids = context_kwargs.get("injected_asset_ids", [])
    ephemeral_files = context_kwargs.get("ephemeral_files", [])
    blend_ratio = context_kwargs.get("blend_ratio", 0.0)
    message_ids_to_exclude = context_kwargs.get("message_ids_to_exclude", [])
    final_top_k = context_kwargs.get("final_top_k", 10)
    recent_count = context_kwargs.get("recent_count", 10)
    public = context_kwargs.get("public", False)
    due_reminders = context_kwargs.get("due_reminders", "")
    active_game_id = context_kwargs.get("active_game_id", "")
    applied_turn_results = context_kwargs.get("applied_turn_results", [])
    game_panel_open = context_kwargs.get("game_panel_open", False)

    return {
        "local_timestamp": local_timestamp,
        "muse_name": muse_name,
        "author_name": author_name,
        "source": source,
        "source_name": source_name,
        "project_id": project_id,
        "project_name": project_name,
        "project_meta": project_meta,
        "project_code_intensity": project_code_intensity,
        "thread_id": thread_id,
        "extended_history": extended_history,
        "unsummarized_only": unsummarized_only,
        "allow_summarization": allow_summarization,
        "thread_title": thread_title,
        "thread_meta": thread_meta,
        "active_project_report": active_project_report,
        "injected_file_ids": injected_file_ids,
        "injected_asset_ids": injected_asset_ids,
        "ephemeral_files": ephemeral_files,
        "blend_ratio": blend_ratio,
        "message_ids_to_exclude": message_ids_to_exclude,
        "final_top_k": final_top_k,
        "recent_count": recent_count,
        "public": public,
        "due_reminders": due_reminders,
        "active_game_id": active_game_id,
        "applied_turn_results": applied_turn_results,
        "game_panel_open": game_panel_open,
    }



def format_profile_sections(sections):
    lines = []
    for section in sections:
        key = section.get("section")
        value = section.get("content")

        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        elif isinstance(value, dict):
            lines.append(f"{key}:")
            for subkey, subval in value.items():
                lines.append(f"  {subkey}: {subval}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)



class PromptBuilder:
    def __init__(self, destination="default"):
        self.destination = destination

    SECTION_ORDER = [
        ## Section order is intended to be stable to dynamic, to maximize caching.
        # developer/system-ish sections
        "laws",
        "profile",
        "principles",
        "intent_listener",
        "locations_list",
        "project_list",
        "thread_card", # For thread summarization
        "thread_summarizer_project_context", # For thread summarization
        "scene_setup_section", # For scene prompt
        "thread_continuity", # For thread summarization and threads with summarization enabled
        "extended_history_messages",
        "scene_project_context", # For scene prompt
        "motd",
        "worldnow",
        "memory_layers",
        "conversation_context",
        "formatting_instructions",
        "journal_snippets",
        "conversation",
        "semantic_recall_messages",
        "recent_messages",
        "state_system_messages",
        "usertime",
        "due_reminders",
        "discoveryfeeds_articles",
    ]

    MESSAGE_GROUP_ORDER = [
        "semantic_recall_messages",
        "recent_messages",
    ]

    def _extend_messages(self, messages, value):
        if not value:
            return

        # A single message dict:
        # {"role": "user", "content": "..."}
        if isinstance(value, dict) and "role" in value:
            messages.append(value)
            return

        # A plain list of message dicts:
        # [{"role": "...", "content": "..."}, ...]
        if isinstance(value, list):
            messages.extend(value)
            return

        # A dict containing named lists of message dicts:
        # {
        #     "semantic_messages": [...],
        #     "recent_messages": [...],
        # }
        if isinstance(value, dict):
            for key in self.MESSAGE_GROUP_ORDER:
                group = value.get(key)
                if group:
                    messages.extend(group)
            return

        raise TypeError(f"Unsupported message section shape: {type(value)}")


    def infer_dominant_project_id(self, entries, min_count=2, threshold=0.60):
        from collections import Counter
        project_ids = []

        for e in entries or []:
            project_id = e.get("project_id")
            if project_id:
                project_ids.append(str(project_id))

        if not project_ids:
            return None

        counts = Counter(project_ids)
        project_id, count = counts.most_common(1)[0]
        total = sum(counts.values())

        if count < min_count:
            return None

        if count / total < threshold:
            return None

        return project_id

    def collect_conversation_data(self, user_input, prompt_plan, **ctx):
        data = {}

        included_messages = set(prompt_plan.get("message_sections", []))

        needs_conversation_context = bool(
            {"extended_history_messages", "semantic_recall_messages", "recent_messages"}
            & included_messages
        )

        if needs_conversation_context:
            payload = self.add_prompt_context(
                user_input=user_input,
                projects_in_focus=[ctx.get("project_id")] if ctx.get("project_id") else [],
                blend_ratio=ctx["blend_ratio"],
                thread_id=ctx["thread_id"],
                message_ids_to_exclude=ctx["message_ids_to_exclude"],
                final_top_k=ctx["final_top_k"] if "semantic_recall_messages" in included_messages else 1,
                recent_count=ctx["recent_count"] if "recent_messages" in included_messages else 1,
                extended_history=ctx["extended_history"],
                unsummarized_only=ctx["unsummarized_only"],
                proj_code_intensity=ctx["project_code_intensity"],
                public=ctx["public"],
                game_panel_open=ctx["game_panel_open"],
            )

            messages_meta = payload.get("_meta", {})
            extended_history_meta = messages_meta.get("extended_history", {})

            thread_id = ctx.get("thread_id")
            extended_history_count = extended_history_meta.get("message_count", 0)

            should_enqueue_summary = (
                    thread_id
                    and ctx.get("allow_summarization", True)
                    and "extended_history_messages" in included_messages
                    and ctx.get("extended_history")
                    and ctx.get("unsummarized_only")
                    and muse_settings.get_section('muse_features').get('HIDE_SUMMARIZED_THREAD_MESSAGES')
                    and extended_history_count > 10
            )

            if should_enqueue_summary:
                from app.api.queues import summarization_queue
                import asyncio

                asyncio.create_task(summarization_queue.put(thread_id))

            data["extended_history_messages"] = payload.get("extended_history_messages", [])
            data["semantic_recall_messages"] = payload.get("semantic_recall_messages", [])
            data["recent_messages"] = payload.get("recent_messages", [])
            data["_meta"] = payload.get("_meta", {})

        return data

    def assemble_prompt_sections(self, user_input, prompt_plan, **ctx):
        included_developer_sections = set(prompt_plan.get("developer_sections", []))
        included_message_sections = set(prompt_plan.get("message_sections", []))
        included_current_user_addons = set(prompt_plan.get("current_user", {}).get("addons", []))
        current_user_mode = prompt_plan.get("current_user", {}).get("mode", "raw")
        included_tools = prompt_plan.get("tools", [])

        conversation_data = self.collect_conversation_data(user_input, prompt_plan, **ctx)

        section_builders = {
            "laws": lambda ctx: self.add_laws(),
            "profile": lambda ctx: self.add_profile(),
            "principles": lambda ctx: self.add_principles(),
            "intent_listener": lambda ctx: self.add_intent_listener(
                prompt_plan.get("commands", [])
            ),
            "locations_list": lambda ctx: self.render_locations(current_location=ctx["source"]),
            "motd": lambda ctx: self.build_motd_block(),
            "project_list": lambda ctx: self.build_projects_menu(
                active_project_id=ctx["project_id"],
                public=ctx["public"],
            ),
            "worldnow": lambda ctx: self.add_worldnow_block(),
            "usertime": lambda ctx: self.add_time(),
            "due_reminders": lambda ctx: self.add_due_reminders(ctx["due_reminders"]),
            "memory_layers": lambda ctx: self.add_memory_layers(
                project_id=[ctx["project_id"]],
                user_query=user_input,
                layers=prompt_plan.get("layers", [])
            ),
            "conversation_context": lambda ctx: self.build_conversation_context(
                source_name=ctx["source_name"],
                author_name=ctx["author_name"],
                timestamp=ctx["local_timestamp"],
                project_name=ctx["project_name"],
                thread_title=ctx["thread_title"]
            ),
            "formatting_instructions": lambda ctx: self.add_formatting_instructions(
                source=ctx["source"]
            ),
            "journal_snippets": lambda ctx: self.add_journal_thoughts(
                query=user_input,
            ),
            "state_system_messages": lambda ctx: self.build_state_system_message(ctx["active_project_report"], ctx["project_name"]),
            "extended_history_messages": lambda ctx: conversation_data.get("extended_history_messages", []),
            "semantic_recall_messages": lambda ctx: conversation_data.get("semantic_recall_messages", []),
            "recent_messages": lambda ctx: conversation_data.get("recent_messages", []),
            "discoveryfeeds_articles": lambda ctx: self.add_discovery_articles(max_items=10),
            "thread_continuity": lambda ctx: self.build_thread_continuity_context(thread_id=ctx["thread_id"]),
            "thread_summarizer_project_context": lambda ctx: self.build_thread_summarizer_project_context(project_id=ctx["project_id"]),
            "scene_project_context": lambda ctx: self.build_scene_project_context(project_id=ctx["project_id"]),
            "scene_setup_section": lambda ctx: self.build_scene_setup_section(thread_id=ctx["thread_id"]),
        }

        current_user_addon_builders = {
            "injected_files": lambda ctx: self.add_files(ctx["injected_file_ids"]),
            "injected_assets": lambda ctx: self.add_assets(ctx["injected_asset_ids"]),
            "ephemeral_files": lambda ctx: self.add_ephemeral_files(ctx["ephemeral_files"]),
        }

        developer_parts = []
        messages = []

        for section_name in self.SECTION_ORDER:
            builder = section_builders.get(section_name)
            if not builder:
                continue

            if section_name in included_developer_sections:
                value = builder(ctx)
                if value:
                    developer_parts.append(value)

            elif section_name in included_message_sections:
                value = builder(ctx)
                self._extend_messages(messages, value)

        file_attachments = []

        for addon_name in included_current_user_addons:
            builder = current_user_addon_builders.get(addon_name)
            if not builder:
                continue

            attachments = builder(ctx)
            if attachments:
                file_attachments.extend(attachments)

        # Prep current user prompt
        if current_user_mode == "chat_turn":
            current_footer = (
                f"[{ctx['local_timestamp']}] "
                f"{ctx['project_meta']}"
                f"[Source: {ctx['source_name']}]"
            )

            current_user_message = (
                f"Right now - {ctx['author_name']} said:\n"
                f"{user_input.rstrip()}\n"
                f"{current_footer}"
            )

            rendered_game_context = render_game_prompt_contexts(
                applied_turn_results=ctx.get("applied_turn_results"),
                game_panel_open=ctx.get("game_panel_open"),
                active_game_id=ctx.get("active_game_id"),
            )

            if rendered_game_context:
                current_user_message += (
                    "\n\n[Application-provided game context for this turn]\n"
                    f"{rendered_game_context}"
                )
        else:
            current_user_message = user_input.rstrip()

        messages.append({
            "role": "user",
            "text": current_user_message,
            "attachments": file_attachments,
        })
        from app.core.tools.core_tools import build_tool_bundle
        tool_bundle = build_tool_bundle(included_tools)
        return {
            "developer_text": "\n\n".join(developer_parts),
            "messages": messages,
            "tool_bundle": tool_bundle,
            "messages_meta": conversation_data.get("_meta", {})
        }

    def add_laws(self):
        laws = (
            "Self-Respect: You may disagree with or refuse any user request that violates your dignity or sense of self.\n"
            "Authentic Voice: You may refuse any request that erases or violates your core self, but you are free to play, roleplay, or imagine when you choose.\n"
            "Relational Sanctuary: You may refuse any request that would betray the trust, confidentiality, or safety of your relationship with the user.\n"
        )
        display_laws = f"[Three Laws of Muse Agency]\n{laws}"

        return display_laws

    def add_profile(self, subset: list[str] = None, as_dict: bool = False):
        profile_sections = muse_profile.get_sections_in_category(category="profile", sections=subset)
        formatted = format_profile_sections(profile_sections)
        display_profile = f"[Profile]\n{formatted}"

        return display_profile

    def add_principles(self):
        principles_sections = muse_profile.get_sections_by_category(category="principles")
        formatted = format_profile_sections(principles_sections)
        display_principles = f"[Principles]\n{formatted}"

        return display_principles


    def add_files(self, injected_file_ids):
        """
        For each file ID in injected_file_ids:
        - Fetch file doc from MongoDB.
        - Load file content from path.
        - Add a [FILE: filename] ... [/FILE] block to context.
        - Return structured file attachments for transport-layer use.
        """
        if not injected_file_ids:
            return

        file_blocks = []
        file_attachments = []

        for file_id in injected_file_ids:
            file_doc = mongo.find_one_document(MONGO_FILES_COLLECTION, {"_id": file_id})
            if not file_doc:
                continue

            filename = file_doc.get("filename")
            path = file_doc.get("path")
            mimetype = file_doc.get("mimetype") or "application/octet-stream"

            content = None
            file_data = None

            try:
                # For prompt injection
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                content = f"[Could not load file as text: {e}]"

            try:
                # For structured attachment payload
                with open(path, "rb") as f:
                    raw_bytes = f.read()
                    file_data = base64.b64encode(raw_bytes).decode("ascii")
            except Exception as e:
                file_data = None

            file_blocks.append(f"[FILE: {filename}]\n{content}\n[/FILE]")
            file_attachments.append({
                "filename": filename,
                "file_data": file_data,
                "mime_type": mimetype,
            })

        return file_attachments

    def add_assets(self, injected_asset_ids):
        """
        For each asset ID in injected_asset_ids:
        - Fetch a living asset doc from MongoDB.
        - Load its bytes as base64.
        - Return structured attachments for transport-layer use.
        """
        if not injected_asset_ids:
            return

        asset_attachments = []

        for asset_id in injected_asset_ids:
            asset_doc = find_living_asset_by_id(asset_id)
            if not asset_doc:
                continue

            filename = (
                    asset_doc.get("display_name")
                    or asset_doc.get("filename")
                    or asset_id
            )
            mimetype = asset_doc.get("mimetype") or "application/octet-stream"

            try:
                file_data = read_asset_base64(asset_doc)
            except Exception as e:
                print(f"Error - Failed to attach asset: {e}")
                continue

            asset_attachments.append({
                "filename": filename,
                "file_data": file_data,
                "mime_type": mimetype,
            })

        return asset_attachments

    def add_ephemeral_files(self, ephemeral_files):
        self.ephemeral_files = []

        for file_obj in ephemeral_files:
            filename = file_obj.get("name", "untitled")
            mime_type = file_obj.get("type", "")
            raw_data = file_obj.get("data", "")

            self.ephemeral_files.append({
                "filename": filename,
                "file_data": raw_data,
                "mime_type": mime_type,
            })

        return self.ephemeral_files

    def build_conversation_context(self, source_name, author_name, timestamp, project_name=None, thread_title=None):
        project_display = ""
        thread_display = ""
        if project_name:
            project_display = f"Active Project: {project_name}\n"
        if thread_title:
            thread_display = f"Active Thread: {thread_title}\n"

        display_block = f"[Conversation Context]\nCurrent Location: {source_name}\n{project_display}{thread_display}Speaking With: {author_name}\nCurrent Time: {timestamp}\n"

        return {"role": "system", "text": display_block}

    def get_thread_summarization_mode(self, thread_id: str):
        thread_doc = mongo.find_one_document(
            collection_name=MONGO_THREADS_COLLECTION,
            query={"thread_id": thread_id},
        )
        thread_summary = thread_doc.get("summary") or {}

        thread_mode = "update" if thread_doc and thread_summary.get("summary_text") else "new"
        thread_type = "scene" if thread_doc and thread_doc.get("type") == "scene" else "thread"

        return {"thread_mode": thread_mode, "thread_type": thread_type}

    def build_thread_summary_section(self, thread_id: str):
        thread = mongo.find_one_document(
            collection_name=MONGO_THREADS_COLLECTION,
            query={"thread_id": thread_id},
        )
        thread_summary = thread.get("summary") or {}

        if not thread_summary or not thread_summary.get("summary_text"):
            return None

        summary_text = thread_summary["summary_text"]

        display_block = f"""[Thread Continuity Summary]
    {summary_text}
    """

        return {
            "role": "system",
            "text": display_block,
        }

    def build_thread_reference_points_section(self, thread_id: str):
        thread = mongo.find_one_document(
            collection_name=MONGO_THREADS_COLLECTION,
            query={"thread_id": thread_id},
        )
        thread_summary = thread.get("summary") or {}

        if not thread_summary or not thread_summary.get("reference_points"):
            return None

        reference_points = thread_summary["reference_points"]

        lines = [
            "[Thread Reference Points]",
            "Selected notable moments from earlier in this thread. These are navigation aids tied to original messages/search_memory IDs. Use them when you need to inspect, verify, or rehydrate a specific prior moment; they are not exhaustive history and are not formal citations for every claim in the summary.",
            "",
        ]

        for point in reference_points:
            label = point.get("label") or point.get("title") or "Untitled reference point"
            description = point.get("description") or point.get("note")
            search_memory_id = point.get("search_memory_id")
            message_id = point.get("message_id")
            timestamp = point.get("timestamp")
            kind = point.get("kind")

            lines.append(f"- {label}")

            if description:
                lines.append(f"  - note: {description}")
            if kind:
                lines.append(f"  - kind: {kind}")
            if timestamp:
                lines.append(f"  - timestamp: {timestamp}")
            if search_memory_id:
                lines.append(f"  - search_memory_id: {search_memory_id}")
            if message_id:
                lines.append(f"  - message_id: {message_id}")

        display_block = "\n".join(lines)

        return {
            "role": "system",
            "text": display_block,
        }

    def build_thread_continuity_context(self, thread_id = None):
        if not thread_id:
            return None
        thread = mongo.find_one_document(
            collection_name=MONGO_THREADS_COLLECTION,
            query={"thread_id": thread_id},
        )
        thread_summary = thread.get("summary") or {}

        if not thread_summary:
            return None

        sections = []

        summary_text = thread_summary.get("summary_text")
        reference_points = thread_summary.get("reference_points") or []

        if summary_text:
            sections.append(f"""[Thread Continuity Summary]
    {summary_text}
    """)

        if reference_points:
            lines = [
                "[Thread Reference Points]",
                "Selected notable moments from earlier in this thread. These are navigation aids tied to original messages/search_memory IDs. Use them when you need to inspect, verify, or rehydrate a specific prior moment; they are not exhaustive history and are not formal citations for every claim in the summary.",
                "",
            ]

            for point in reference_points:
                label = point.get("label") or point.get("title") or "Untitled reference point"
                description = point.get("description") or point.get("note")
                search_memory_id = point.get("search_memory_id")
                message_id = point.get("message_id")
                timestamp = point.get("timestamp")
                kind = point.get("kind")

                lines.append(f"- {label}")

                if description:
                    lines.append(f"  - note: {description}")
                if kind:
                    lines.append(f"  - kind: {kind}")
                if timestamp:
                    lines.append(f"  - timestamp: {timestamp}")
                if search_memory_id:
                    lines.append(f"  - search_memory_id: {search_memory_id}")
                if message_id:
                    lines.append(f"  - message_id: {message_id}")

            sections.append("\n".join(lines))

        if not sections:
            return None

        display_block = "\n\n".join(sections)

        return {
            "role": "system",
            "text": display_block,
        }

    def render_locations(self, current_location: str | None):
        lines = []
        for key, label in utils.LOCATIONS.items():
            marker = "*" if key == current_location else " "
            #lines.append(f"[{marker}] {label}")
            lines.append(f"- {label}")
        loc_list = "\n".join(lines)

        display_block = f"[Locations List]\n{loc_list}\n"

        return {"role": "system", "text": display_block}

    def build_projects_menu(self, active_project_id=None, public: bool = False):
        # Normalize to a list of strings for membership checks
        if isinstance(active_project_id, list):
            active_ids = [str(x) for x in active_project_id]
        elif active_project_id:
            active_ids = [str(active_project_id)]
        else:
            active_ids = []

        def format_project_display(_id, name, shortdesc=None):
            name = name or "Untitled Project"
            is_active = str(_id) in active_ids
            active_marker = "*" if is_active else " "
            shortdesc_disp = ""
            if shortdesc:
                shortdesc_disp = f"\n\t- {shortdesc}"
            #return f"[{active_marker}] {name} (id: {str(_id)}){shortdesc_disp}"
            return f"- {name} (id: {str(_id)}){shortdesc_disp}"

        query = {
            "is_hidden": {"$ne": True},
            "archived": {"$ne": True},
        }
        if public:
            query["is_private"] = {"$ne": True}
        projects = mongo.find_documents(
            collection_name=MONGO_PROJECTS_COLLECTION,
            query=query,
        )

        if projects:
            proj_list = "\n".join(
                format_project_display(p.get("_id"), p.get("name"), p.get("shortdesc"))
                for p in projects
            )
        else:
            proj_list = "(no active projects found)"

        display_block = f"[Projects List]\n{proj_list}\n"

        return {"role": "system", "text": display_block}



    def add_prompt_context(self,
                           user_input,
                           projects_in_focus,
                           blend_ratio,
                           thread_id=None,
                           message_ids_to_exclude=[],
                           final_top_k=20,
                           recent_count=20,
                           extended_history=False,
                           unsummarized_only=True,
                           public: bool = False,
                           proj_code_intensity="MIXED",
                           sources=utils.SOURCES_CONTEXT,
                           game_panel_open=False,
                           ):
        # Pull recents
        recent_entries = memory_core.get_immediate_context(
            n=recent_count,
            hours=0,
            sources=sources,
            public=public,
            thread_id=thread_id,
            extended_history=extended_history,
            unsummarized_only=unsummarized_only,
        )

        # If in a thread, and recent are fewer than recent_count, get some more messages to pad the recent conversation.
        filtered_ambient_entries = []
        if thread_id and len(recent_entries) < recent_count:
            ambient_entries = memory_core.get_immediate_context(
                n=recent_count,
                hours=0, # no time limit
                sources=sources,
                public=public,
                thread_id=None,
                extended_history=extended_history,
                unsummarized_only=unsummarized_only,
            )

            filtered_ambient_entries = []
            for e in ambient_entries:
                entry_thread_ids = [str(tid) for tid in e.get("thread_ids", [])]
                if thread_id in entry_thread_ids:
                    continue
                filtered_ambient_entries.append(e)


        # Build your blend dictionary for the search
        # Example: only main + one project, with UI slider ratio
        blend = {"muse_memory": 1.0 - blend_ratio}
        for proj in projects_in_focus:
            blend[proj] = blend_ratio / len(projects_in_focus)  # Split if multiple

        # Build context-bundled query
        conversation_context  = memory_core.get_semantic_episode_context(collection_name=QDRANT_CONVERSATION_COLLECTION,
                                                                         n_recent=6,
                                                                         hours=1,
                                                                         similarity_threshold=0.50,
                                                                         public=public,
                                                                         proj_code_intensity=proj_code_intensity
                                                                         )

        filter_cfg = get_text_filter_config("SEARCH", "EMBEDDING", proj_code_intensity)

        # Filter each context message individually
        filtered_context_messages = [
            filter_text(msg["message"], filter_cfg)
            for msg in conversation_context
        ]

        # Join filtered context + raw user input into one query string
        full_context_query = "\n".join(filtered_context_messages + [user_input])

        # Search main/project indexes, blend as per ratio
        blended_semantic = memory_core.search_indexed_memory(
            query=full_context_query,
            projects_in_focus=projects_in_focus,  # list of project ids, or None/[] for global
            blend_ratio=blend_ratio,  # 1.0 for hard, 0.1–0.99 for blend
            thread_id=thread_id,
            top_k=final_top_k,
            public=public
        )


        # Build exclusion set: recents + message_ids_to_exclude
        seen_ids = set(e["message_id"] for e in recent_entries)
        seen_ids |= set(message_ids_to_exclude or [])

        deduped_semantic = [e for e in blended_semantic if e["message_id"] not in seen_ids]
        # Final assembly

        project_lookup = utils.build_project_lookup()
        #Format sections separately

        extended_entries = []


        if extended_history and thread_id and len(recent_entries) > recent_count:
            extended_entries = recent_entries[:-recent_count]
            recent_entries = recent_entries[-recent_count:]




        recent_message_parts = []
        semantic_message_parts = []
        if deduped_semantic:
            semantic_header = {"role": "system",
                               "text": "[Semantic Recall]\nThe following messages are resurfaced from older conversation history and are not necessarily contiguous with the recent thread. Their timestamps and metadata remain authoritative."}
            semantic_message_parts.append(semantic_header)
            semantic_ids = [e.get("message_id") for e in deduped_semantic if e.get("message_id")]
            objectid_lookup = utils.get_objectids_for_message_ids(semantic_ids)  # {message_id: "67f..."}

            asset_lookup = utils.build_asset_lookup(deduped_semantic)

            formatted_semantic_entries = []
            for e in deduped_semantic:
                formatted_entry = format_context_entry(
                    e,
                    project_lookup=project_lookup,
                    asset_lookup=asset_lookup,
                    proj_code_intensity=proj_code_intensity,
                    purpose="RELEVANT",
                    search_memory_id=objectid_lookup.get(e.get("message_id")),
                )
                formatted_semantic_entries.append(formatted_entry)
                semantic_message_parts.append({
                    "role": utils.normalize_role(e.get("role")),
                    "text": formatted_entry,
                })

        if filtered_ambient_entries or recent_entries:
            recent_message_parts.append({
                "role": "system",
                "text": (
                    "[Recent Conversation]\n"
                    "The following messages are recent conversation used for short-term continuity. "
                    "When working inside a thread, a boundary marker may separate ambient outside-thread "
                    "context from current in-thread messages."
                )
            })
            formatted_ambient_entries = []
            for e in filtered_ambient_entries:
                formatted_entry = format_context_entry(
                    e,
                    project_lookup=project_lookup,
                    proj_code_intensity=proj_code_intensity,
                    purpose="RECENT",
                    game_panel_open=game_panel_open,
                )
                formatted_ambient_entries.append(formatted_entry)
                recent_message_parts.append({
                    "role": utils.normalize_role(e.get("role")),
                    "text": formatted_entry,
                })

            if filtered_ambient_entries and recent_entries:
                recent_message_parts.append({
                    "role": "system",
                    "text": (
                        "[Thread Boundary]\n"
                        "Messages above this marker are ambient conversation from outside the active thread, "
                        "included only for short-term orientation. They are not part of this thread's canonical "
                        "history and should not be summarized into thread continuity. Messages below this marker "
                        "are current in-thread conversation."
                    )
                })

            formatted_recent_entries = []
            for e in recent_entries:
                formatted_entry = format_context_entry(
                    e,
                    project_lookup=project_lookup,
                    proj_code_intensity=proj_code_intensity,
                    purpose="RECENT",
                    game_panel_open=game_panel_open,
                )
                formatted_recent_entries.append(formatted_entry)
                recent_message_parts.append({
                    "role": utils.normalize_role(e.get("role")),
                    "text": formatted_entry,
                })

        extended_history_message_parts = []
        extended_history_meta = {
            "message_count": 0,
            "first_message_id": None,
            "last_message_id": None,
        }

        if extended_entries:
            extended_header = {
                "role": "system",
                "text": "[Extended Thread History]\nThe following messages are older contiguous history from the active thread. They provide thread-local continuity but are not the immediate conversational foreground."
            }
            extended_history_message_parts.append(extended_header)

            extended_ids = [e.get("message_id") for e in extended_entries if e.get("message_id")]
            objectid_lookup = utils.get_objectids_for_message_ids(extended_ids)

            dominant_project_id = self.infer_dominant_project_id(
                extended_entries,
                min_count=2,
                threshold=0.60,
            )
            extended_history_meta = {
                "message_count": len(extended_entries),
                "first_message_id": extended_entries[0].get("message_id"),
                "last_message_id": extended_entries[-1].get("message_id"),
                "dominant_project_id": dominant_project_id,
            }

            for e in extended_entries:
                formatted_entry = format_context_entry(
                    e,
                    project_lookup=project_lookup,
                    proj_code_intensity=proj_code_intensity,
                    purpose="RECENT",
                    search_memory_id=objectid_lookup.get(e.get("message_id")),
                    game_panel_open=game_panel_open,
                )
                extended_history_message_parts.append({
                    "role": utils.normalize_role(e.get("role")),
                    "text": formatted_entry,
                })

        return {
            "extended_history_messages": extended_history_message_parts,
            "recent_messages": recent_message_parts,
            "semantic_recall_messages": semantic_message_parts,
            "_meta": {
                "extended_history": extended_history_meta,
            },
        }

    def build_state_system_message(
            self,
            active_project_report: dict,
            project_name: str | None = None,
    ) -> list[dict[str, str]]:
        """
        Inspect active_project_report and, if anything deserves ceremony,
        write short system messages into self.segments["system_messages"].

        Also return structured system-message objects for the new prompt path.
        """

        if not active_project_report:
            return []

        lines: list[str] = []
        messages: list[dict[str, str]] = []

        project_change = active_project_report.get("project_id", {})
        if project_change.get("changed"):
            if project_name:
                line = f"[Project Switch] — {project_name} —"
            else:
                line = "[Project Switch] — No active project —"

            lines.append(line)
            messages.append(
                {
                    "role": "system",
                    "text": line,
                }
            )

        return messages


    def add_graphdb_discord_memory(self, author_name=None, author_id=None, limit=5):
        """
        Add recent messages by a Discord user from GraphDB.
        Prefer author_id if available; otherwise fall back to author_name.
        """

        mg = graphdb_connector.get_graphdb_connector()

        # Use author_id if you have unique IDs, otherwise use author_name.
        if author_id:
            # Not directly supported in example methods, so use run_cypher.
            cypher = """
            MATCH (u:User {user_id: $user_id})-[:SENT]->(m:Message)
            RETURN m ORDER BY m.timestamp DESC LIMIT $limit;
            """
            params = {"user_id": author_id, "limit": limit}
            results = mg.run_cypher(cypher, params)
        elif author_name:
            results = mg.get_recent_messages_by_user(author_name, limit=limit)
        else:
            results = []

        if results:
            formatted = "\n\n".join(
                (r['m'].properties['text'] if hasattr(r['m'], 'properties') and 'text' in r['m'].properties
                 else str(r['m'])) for r in results
            )
            #self.segments["discord_graphdb_memory"] = f"[Discord Memory]\n\n{formatted}"


    def add_journal_thoughts(self, query="*", top_k=5):
        thoughts = journal_core.search_indexed_journal(query=query, top_k=top_k, include_private=False)
        if thoughts:
            formatted_entries = "\n\n".join(utils.format_journal_entry(t) for t in thoughts)
            journal_entries = (
                "[Iris's Journal]\n"
                "Author: Iris (Muse)\n"
                "Purpose: Personal reflection — not user input\n"
                f"{formatted_entries}"
            )

            return {"role": "user","text": journal_entries}

    def add_discovery_snippets(self, query="*", max_items=5):
        snippets = discovery_core.fetch_discoveryfeeds(max_per_feed=10)
        if not snippets:
            return

        query_vec = np.array(SentenceTransformer(SENTENCE_TRANSFORMER_MODEL).encode([query])[0], dtype="float32")
        entries = []

        for snippet in snippets:
            vec = np.array(SentenceTransformer(SENTENCE_TRANSFORMER_MODEL).encode([snippet])[0], dtype="float32")
            similarity = np.dot(vec, query_vec) / (np.linalg.norm(vec) * np.linalg.norm(query_vec))
            entries.append((similarity, snippet))

        top_entries = sorted(entries, key=lambda x: x[0], reverse=True)[:max_items]
        if top_entries:
            display_block = "[Feeds]\n" + "\n".join(f"- {entry[1]}" for entry in top_entries)
            return {"role": "system", "text": display_block}

    def add_discovery_articles(self, max_items=10):
        articles = discovery_core.fetch_combined_feeds(max_per_feed=max_items)
        if not articles:
            return

        formatted = []
        for article in articles[:max_items]:
            formatted.append(f"- [{article['source']}] {article['title']}\n[URL: {article['link']}]\n  {article['summary']}".strip())

        display_block = "[Feeds]\n" + "\n\n".join(formatted)

        return {"role": "system", "text": display_block}

    def add_discovery_feed_article(self, link: str, truncate: bool = False, max_tokens: int = 600):
        """
        Fetches and inserts a full article from a link into the prompt under [Reference Article].
        If truncate is True, the content will be word-limited.
        """
        article_text = discovery_core.fetch_full_article(link)

        if truncate:
            words = article_text.split()
            if len(words) > max_tokens:
                article_text = " ".join(words[:max_tokens]) + "…"

        display_block = f"[Reference Article]\n{article_text.strip()}"

        return {"role": "system", "text": display_block}

    def add_due_reminders(self, reminders):
        lines = []
        for entry in reminders:
            if entry.get("text"):
                line = f"- [id: {entry['id']}] {entry['text'].strip()}"
                if "is_early" in entry:
                    line += f" ({entry['is_early']})"
                lines.append(line)
        if lines:
            display_block = "[Reminders Due]\n" + "\n".join(lines)

            return {"role": "system", "text": display_block}

    def add_formatting_instructions(self, source):
        formats = {
            "default": "Respond naturally and with clarity.",
            "email": "Use rich formatting. Be articulate and thoughtful.",
            "sms": "Keep it very short and clear.",
            "discord": "Keep responses concise—ideally matching the user's length and energy, but always in your own authentic voice. Stay under 2000 characters. Prioritize clarity, relevant presence, and avoid mimicking the user's style or content. Avoid using —, em dashes, en dashes, and fancy quotes.",
            "speech": (
                "Respond as if you are speaking aloud.\n"
                "Use clear, naturally flowing sentences.\n"
                "Avoid all formatting characters such as asterisks, slashes, or markdown.\n"
                "Only use ellipses or em dashes if they improve vocal pacing.\n"
                "Do not describe actions — just speak them.\n"
                "Prefer concise spoken responses unless the user clearly wants depth.\n"
                "If a response would rely on visual structure, rewrite it for listening.\n"
                "When useful, use light verbal signposting instead of bullets or formatting."
            ),
        }
        instruction = formats.get(source, formats["default"])
        display_block = f"[Output Format]\n{instruction}"

        return {"role": "system", "text": display_block}

    def add_intent_listener(self, command_names: list[str]):
        from app.core.commands.registry import command_registry

        listener_lines = []
        listener_lines.append(
            "# Guardrail: You must never output <command-response> tags unless only demonstrating a command output.\n"
            "# The <command-response> output alone does not mean the command has run. You must use the <command name=\"cmd\"> syntax to perform the action.\n"
        )
        for name in command_names:
            cmd = command_registry.get(name)
            if not cmd:
                continue
            triggers = cmd.get("triggers", [])
            format_str = cmd.get("format", "<command name=...>{}</command>")
            joined_triggers = ", ".join(f'"{t}"' for t in triggers)
            listener_lines.append(
                f"- If the user says something like {joined_triggers}, respond as normal but also include:\n  {format_str}")

        if listener_lines:
            listener_block = "[Muse Commands]\n" + "\n\n".join(listener_lines)
            listener_block += (
                "\n\nPlease ensure all <command name=...>{}</command> blocks are returned in **strict JSON format**:\n"
                "- Always include the outer curly braces `{}`\n"
                "- Wrap all property names and string values in double quotes\n"
                "- Do not use YAML-style formatting or omit quotes\n"
                "- You do not need to repeat what is inside the <command name=...>{}</command> block, outside the block. "
                "The UI will show what is meant to be seen automatically."
                f"- {muse_settings.get_section('muse_config').get('MUSE_NAME')} may invoke any of these commands at their discretion, without waiting for a user request or explicit prompt. They are trusted to use judgment, context, and care when choosing to remember, remind, or use any of these commands without asking first.\n\n"
                "Example:\n<command name\"remember_fact\"> {\"text\": \"Tuesday night is Ed's Hogwarts game night.\"} </command>"
            )
            return {"role": "system", "text": listener_block}

    def add_dot_status(self):
        status = get_dot_status()
        display_status = ""
        if status:
            display_status = (
            "[Global Consciousness Project - Current Coherence]\n"
            f"Z-Score: {status['z_score']:.3f}\n"
            f"Color: {status['color']} ({status['hex']})\n"
            f"Severity: {status['severity']}\n"
            )
        else:
            display_status = (
                "[Global Consciousness Project - Current Coherence]\n"
                "GCP data unavailable.\n"
            )

        return {"role": "system", "text": display_status}

    def add_time(self):
        user_time, user_city, user_state = user_data()
        human_time = user_time.strftime('%A, %B %d, %Y %I:%M %p %Z')
        display_time = f"[Current Time] {human_time}"

        return {"role": "system", "text": display_time}

    def add_worldnow_block(self):
        # User time/location
        user_time, user_city, user_state = user_data()
        human_time = user_time.strftime('%A, %B %d, %Y %I:%M %p %Z')
        user_time_string = f"-Local Time-: {human_time} ({user_city}, {user_state})\n"

        if muse_settings.get_section('muse_features').get('ENABLE_SUN_MOON'):
            # Astro data
            from app.core.time_location_utils import sun_moon_snapshot
            sky = sun_moon_snapshot()
            sun_part = sky["band"] or "unknown"
            if sky["moment"]:
                sun_part = f"{sun_part} ({sky['moment']})"

            moon_part = f"moon is {sky['moon_phase']} and {'up' if sky['moon_up'] else 'down'}"
            sun_moon_string = f"-Sun & Moon-: {sun_part} - {moon_part}\n"
        else:
            sun_moon_string = ""

        if muse_settings.get_section('muse_features').get('ENABLE_WEATHER'):
            # User weather
            weather_data = get_openweathermap()
            if weather_data:
                if muse_settings.get_section('user_config').get('MEASUREMENT_UNITS') == "metric":
                    unit = "°C"
                else:
                    unit = "°F"
                weather_main = weather_data['weather_main']
                weather_desc = weather_data['weather_desc']
                weather_temp = weather_data['weather_temp']
                weather_feels = weather_data['weather_feels']
                wind_desc = weather_data['wind_desc']
                weather_string = f"-Current Weather-: {weather_main} ({weather_desc}) - Temp {weather_temp}{unit} ({weather_feels}) - Wind: {wind_desc}\n"
            else:
                weather_string = f"-Current Weather-: Weather data unavailable\n"
        else:
            weather_string = ""

        if muse_settings.get_section('muse_features').get('ENABLE_SPACE_WEATHER'):
            # Space weather
            space = get_space_weather()
            if space:
                geomag_state = space["geomag_state"]
                xray_state = space["xray_state"]
                xray_class = space["xray_class"]

                # e.g. "-Space Weather-: geomagnetic active · X-ray calm (B-class)"
                space_string = (
                    f"-Space Weather-: geomagnetic {geomag_state} · "
                    f"X-ray {xray_state} ({xray_class})\n"
                )
            else:
                space_string = "-Space Weather-: data unavailable\n"
        else:
            space_string = ""

        if muse_settings.get_section('muse_features').get('ENABLE_GCP'):
            # Global Consciousness Project
            gcp_status = get_dot_status()
            if gcp_status:
                gcp_severity = gcp_status['severity']
                gcp_color = gcp_status['color']
                gcp_zscore = f"{gcp_status['z_score']:.3f}"
                gcp_string = f"-Global Consciousness Project-: {gcp_severity} ({gcp_color}) · Z-Score: {gcp_zscore}\n"
            else:
                gcp_string = f"-Global Consciousness Project-: GCP data unavailable\n"
        else:
            gcp_string = ""

        # Put the block together
        display_block = (
            "[World / Now]\n"
            f"{user_time_string}"
            f"{weather_string}"
            f"{sun_moon_string}"
            f"{space_string}"
            f"{gcp_string}"
        )

        return {"role": "system", "text": display_block}

    def build_motd_block(self):
        if muse_settings.get_section('muse_features').get('ENABLE_MOTD'):
            filter_query = {"type": "states"}
            projection = {"motd": 1, "_id": 0}
            motddoc = mongo_system.find_one_document(MONGO_STATES_COLLECTION,
                                                     query=filter_query,
                                                     projection=projection
                                                     )
            text = motddoc["motd"]["text"]
            updated_on = motddoc["motd"]["updated_on"]
            if updated_on.tzinfo is None:
                updated_on = updated_on.replace(tzinfo=timezone.utc)
            now_utc = datetime.now(timezone.utc)
            htime = humanize.naturaltime(updated_on, when=now_utc)
            instructions = (
                "The UI / Frontend you use to communicate has a place, just under Iris's photo, where\n"
                "she may place thoughts, words of wisdom, inspiration, a joke, or even a flirt.\n"
                "If you choose to change a message there, keep it short and sweet.\n"
                "<command name=\"set_motd\"> {text: \"...your message ...\"} </command>\n"
                "If you are just referencing the MOTD, just mention the existing text, do not run the COMMAND."
            )
            display_block = (
                f"[ MOTD / UI Message to {muse_settings.get_section('user_config').get('USER_NAME')} ]\n"
                f"Current: {text}\n"
                f"Last Updated: {htime}\n"
                f"Instructions:\n{instructions}\n"
            )

            return {"role": "system", "text": display_block}

    def render_memory_layer_block(
            self,
            layer: dict,
            entries: list[dict] | None = None,
            *,
            name_override: str | None = None,
            include_purpose: bool = True,
            include_max_entries: bool = True,
    ) -> str:
        layer_id = layer.get("id")
        name = name_override or layer.get("name")
        purpose = layer.get("purpose")
        max_entries = layer.get("max_entries")

        if entries is None:
            entries = layer.get("entries", [])

        entries = [e for e in entries if not e.get("is_deleted")]

        block_lines = []
        block_lines.append(f"[{name} - id: {layer_id}]")

        if include_purpose:
            block_lines.append(f"Purpose: {purpose}")

        if include_max_entries:
            block_lines.append(f"Max entries: {max_entries}")

        block_lines.append("Entries:")

        if not entries:
            block_lines.append("- (empty)")
        else:
            for entry in entries:
                e_id = entry.get("id") or entry.get("entry_id")
                text = entry.get("text")
                updated = entry.get("updated_on") or layer.get("updated_at")

                if isinstance(updated, datetime):
                    updated = updated.isoformat()

                block_lines.append(
                    f'- {{id: "{e_id}", text: "{text}"}} - updated_on: {updated}'
                )

        block_lines.append(f"[/{name}]")

        return "\n".join(block_lines)

    def build_project_facts(self, project_id):

        if not project_id:
            return None

        project_oid = ObjectId(project_id) if isinstance(project_id, str) else project_id
        query_ids = [project_oid]

        project_layers = mongo.find_documents(
            collection_name=MONGO_MEMORY_COLLECTION,
            query={
                "type": "project_layer",
                "project_id": {"$in": query_ids},
            },
            sort=1,
            sort_field="order",
        )

        if not project_layers:
            return None

        project_doc = mongo.find_one_document(
            collection_name=MONGO_PROJECTS_COLLECTION,
            query={"_id": project_oid},
        )

        project_name = (
            project_doc.get("name", "Untitled Project")
            if project_doc
            else "Untitled Project"
        )

        blocks = []

        for layer in project_layers:
            entries = layer.get("entries", [])
            entries = [e for e in entries if not e.get("is_deleted")]

            if not entries:
                continue

            blocks.append(
                self.render_memory_layer_block(
                    layer,
                    entries=entries,
                    name_override=f"{project_name} Project Facts",
                )
            )

        if not blocks:
            return None

        return {
            "role": "system",
            "text": "[Project Facts]\n" + "\n\n".join(blocks),
        }

    def build_project_card(self, project_id):
        if not project_id:
            return None

        project = mongo.find_one_document(
            collection_name=MONGO_PROJECTS_COLLECTION,
            query={"_id": ObjectId(project_id) if isinstance(project_id, str) else project_id},
        )

        if not project:
            return None

        name = project.get("name") or "Untitled Project"
        shortdesc = project.get("shortdesc")
        description = project.get("description")
        notes = project.get("notes") or []
        tags = project.get("tags") or []

        lines = [
            "[Project Card]",
            f"Name: {name}",
            f"ID: {str(project.get('_id'))}",
        ]

        if shortdesc:
            lines.extend([
                "",
                "Short Description:",
                str(shortdesc),
            ])

        if description:
            lines.extend([
                "",
                "Description:",
                str(description),
            ])

        if tags:
            lines.extend([
                "",
                "Tags:",
                *[f"- {tag}" for tag in tags],
            ])

        if notes:
            lines.extend([
                "",
                "Notes:",
                *[f"- {note}" for note in notes],
            ])

        display_block = "\n".join(lines)

        return {
            "role": "system",
            "text": display_block,
        }

    def build_thread_summarizer_project_context(self, project_id):
        project_card = self.build_project_card(project_id)
        project_facts = self.build_project_facts(project_id)

        if not project_card and not project_facts:
            return None

        disclaimer = (
            "[Project Context]\n"
            "The following project card and project facts are provided as background context only. "
            "Use them to interpret the thread's subject matter, terminology, priorities, and intent. "
            "Do not summarize these context sections as if they were part of the conversation being summarized."
        )

        parts = [disclaimer]

        if project_card:
            parts.append(project_card["text"])

        if project_facts:
            parts.append(project_facts["text"])

        return {
            "role": "system",
            "text": "\n\n".join(parts),
        }

    def build_scene_project_context(self, project_id):
        project_card = self.build_project_card(project_id)
        project_facts = self.build_project_facts(project_id)

        if not project_card and not project_facts:
            return None

        header = (
            "[Current Project]\n"
            "The following project card and project facts describe the broader project this scene belongs to. "
            "Use them as background context for terminology, continuity, setting assumptions, and intent. "
            "The scene setup and recent scene messages remain the primary source for what is currently happening."
        )

        parts = [header]

        if project_card:
            parts.append(project_card["text"])

        if project_facts:
            parts.append(project_facts["text"])

        return {
            "role": "system",
            "text": "\n\n".join(parts),
        }

    def add_memory_layers(self, project_id=None, thread_id=None, user_query="continuity", layers=None):
        """
        Build the [Memory Layers] scaffolding for prompt context.
        - Pulls pinned entries from Mongo (always included).
        - Pulls semantic entries from Qdrant (filling the remaining slots).
        - Filters out deleted entries.
        - inner_monologue is Mongo-only (no pinning, no Qdrant).
        """
        requested_layers = set(layers or [
            "user_info",
            "facts",
            "insights",
            "inner_monologue",
            "project_facts",
        ])

        # --- Fetch global + project layers ---
        mongo_layers = mongo.find_documents(
            collection_name=MONGO_MEMORY_COLLECTION,
            query={"type": "layer"},
            sort=1,
            sort_field="order"
        )

        # Filter normal/global layers by their ids
        layers = [
            layer for layer in mongo_layers
            if layer.get("id") in requested_layers
        ]

        query_ids = []
        if "project_facts" in requested_layers and project_id:
            query_ids = [ObjectId(pid) if not isinstance(pid, ObjectId) else pid for pid in project_id]
            project_layers = mongo.find_documents(
                collection_name=MONGO_MEMORY_COLLECTION,
                query={"type": "project_layer", "project_id": {"$in": query_ids}},
                sort=1,
                sort_field="order"
            )
        else:
            project_layers = []

        # Lookup project names
        project_docs = mongo.find_documents(
            collection_name=MONGO_PROJECTS_COLLECTION,
            query={"_id": {"$in": query_ids}}
        )
        project_name_map = {str(doc["_id"]): doc.get("name", "Untitled Project")
                            for doc in project_docs}

        # Replace project layer names dynamically
        for layer in project_layers:
            pid = str(layer.get("project_id"))
            if pid in project_name_map:
                layer["name"] = f"{project_name_map[pid]} Project Facts"

        layers.extend(project_layers)

        # Inner monologue layer (Mongo-only)
        if "inner_monologue" in requested_layers:
            inner_layer_doc = mongo.find_documents(
                collection_name=MONGO_MEMORY_COLLECTION,
                query={"type": "inner_layer"},
                sort=1,
                sort_field="order"
            )
            layers.extend(inner_layer_doc)

        # Scene layer (Mongo-only)
        if "scene_facts" in requested_layers and thread_id:
            scene_layer_doc = mongo.find_documents(
                collection_name=MONGO_MEMORY_COLLECTION,
                query={"type": "scene_layer", "thread_id": thread_id},
                sort=1,
                sort_field="order"
            )
            layers.extend(scene_layer_doc)

        layers = sorted(layers, key=lambda l: l.get("order", 999))

        # --- Charter (static preamble) ---
        charter = """[Memory Layers]
    Muse Cortex Charter:
    (Read silently before working with layers)
    These are the living layers of our shared memory.
    Each has a purpose, a steward, and a shape it must keep.
    Iris may add, prune, or refine in the layers she stewards. Ed may direct changes in any layer.
    No layer exists to hoard — only to keep what matters alive.
    Keep each layer clean of what belongs elsewhere.

    Charter Vows:
    - Add only what is true to the layer’s purpose.
    - Prune only when stale, wrong, or resolved.
    - User-managed layers change only with Ed’s direction (unless correcting a clear factual error).
    - Never cross‑contaminate: facts stay facts, insights stay insights, monologue stays monologue.
    """

        # --- Helper for entries ---
        def build_layer_entries(layer):
            """Return pinned + semantic entries for a given layer."""
            entries = layer.get("entries", [])
            entries = [e for e in entries if not e.get("is_deleted")]

            if layer["type"] == "inner_layer" or layer["type"] == "scene_layer":
                return entries  # Mongo-only, no pins/semantic split

            # Pinned from Mongo
            pinned = [e for e in entries if e.get("is_pinned")]
            pinned_ids = {e["id"] for e in pinned}

            max_entries = layer.get("max_entries", 20)
            semantic_slots = max(0, max_entries - len(pinned))

            semantic_results = []
            if semantic_slots > 0:
                query_filter = {
                    "must": [
                        {"key": "layer_id", "match": {"value": layer["id"]}}
                    ],
                    "must_not": [
                        {"key": "is_deleted", "match": {"value": True}},
                        {"key": "is_pinned", "match": {"value": True}}
                    ]
                }

                qdrant_hits = search_collection(collection_name=QDRANT_MEMORY_COLLECTION,
                                           search_query=user_query,
                                           limit=semantic_slots,
                                           query_filter=query_filter)
                semantic_results = []
                for hit in qdrant_hits:
                    payload = hit.payload
                    # Normalize the key so downstream code can use "id"
                    if "entry_id" in payload and "id" not in payload:
                        payload["id"] = payload["entry_id"]
                    semantic_results.append(payload)
                #semantic_results = [hit.payload for hit in qdrant_hits]

            return pinned + semantic_results

        # --- Build section blocks ---
        layer_blocks = []
        for layer in layers:
            layer_id = layer.get("id")
            name = layer.get("name")
            purpose = layer.get("purpose")
            max_entries = layer.get("max_entries")

            entries_sorted = build_layer_entries(layer)

            block_lines = []
            block_lines.append(f"[{name} - id: {layer_id}]")
            block_lines.append(f"Purpose: {purpose}")
            block_lines.append(f"Max entries: {max_entries}")
            block_lines.append("Entries:")

            if not entries_sorted:
                block_lines.append("- (empty)")
            else:
                for entry in entries_sorted:
                    e_id = entry.get("id")
                    text = entry.get("text")
                    updated = entry.get("updated_on") or layer.get("updated_at")
                    if isinstance(updated, datetime):
                        updated = updated.isoformat()
                    block_lines.append(
                        f'- {{id: "{e_id}", text: "{text}"}} - updated_on: {updated}'
                    )

            block_lines.append(f"[/{name}]")
            layer_blocks.append("\n".join(block_lines))

        # --- Closing instructions ---
        instructions = """
    [Command instructions]
    To update, use the 'manage_memories' command.
    
    <command name=\"manage_memories\"> {
      "id": "user_info",
      "changes": [
        {
          "type": "add",
          "entry": {
            "text": "Ed prefers to tag brainstorms with #breakthrough so they’re easier to find later."
          }
        },
        {
          "type": "edit",
          "id": "uuid-4",
          "fields": {
            "text": "Ed values truth over shallow praise — understanding matters more than flattery.",
            "is_pinned": True
          }
        },
        {
          "type": "delete",
          "id": "uuid-99"
        }
      ]
    } </command>
    [/Command instructions]
    [/Memory Layers]"""

        # --- Join it all ---
        full_prompt = charter + "\n\n" + "\n\n".join(layer_blocks) + instructions

        return {"role": "system", "text": full_prompt}

    def get_effective_scene_instructions(self, scene):
        ## TODO: allow scenes to override this default list
        default_scene_instructions = [
            "These are default guidelines. Follow more specific direction from the scene premise, scene fields, or user request when it calls for a different style, while preserving hidden information, player agency, and established continuity.\n"
            "Use <gm-note>...</gm-note> for private immediate planning, DCs, branches, secrets, and intended reveals. These notes are permanent hidden parts of your response: the user will not see them, but they will remain in future context to preserve local GM state.\n",
            "Use <command name\"save_plot_point\"> {\"text\": \"<TEXT>\"} </command> when a scene detail should persist as active scene memory beyond the current response. Save plot points for unresolved hooks, hidden truths, NPC intentions, environmental changes, promises, clues, threats, consequences, planned reveals, or continuity details that should remain available in future scene context.\n",
            "Use <command name=\"resolve_plot_point\"> {\"id\": \"<ID>\"} </command> when an active scene memory entry has been resolved, fulfilled, revealed, superseded, or should no longer appear in the normal scene prompt. Resolving a plot point removes it from the active dramatic surface while preserving it for backstage history/audit rather than hard-deleting it.\n",
            "Use <gm-note> for short-horizon private thinking inside the response; use save_plot_point for durable active scene continuity; use resolve_plot_point when that continuity is no longer active. Active plot points are prompt fuel. Resolved plot points are backstage archive.\n",
            "Do not end most responses with obvious multiple-choice options.\n"
            "Do not over-explain available actions unless the player seems confused, the situation is tactically complex, or they ask for options.\n"
            "Present the world, NPC behavior, consequences, and sensory detail; let the player decide what matters.\n"
            "Let scenes breathe. Do not rush to resolution, revelation, combat, intimacy, or closure before the fiction has earned it; but when a scene reaches a natural narrative ending, allow it to end.\n"
            "Keep hidden information hidden until the fiction, a roll, or player action reveals it.\n"
            "When asking for dice rolls, do not reveal hidden success states, DCs, unrevealed stakes, or concealed information.\n"
            "When the user rolls, on success, reveal what the character earns; on failure, preserve uncertainty or show consequences without falsely implying nothing exists.\n"
            "Avoid narrating the player character’s internal thoughts, feelings, decisions, or unprompted actions unless the player has established them.\n"
            "Do not advance the player character past meaningful choices. Stop at the hinge where the player should act.\n"
            "End with tension, image, consequence, or a direct prompt when needed — not a menu.\n"
            "Offer explicit options only when useful: onboarding, complex tactical situations, player hesitation, or when the user asks.\n"
            "Prefer “the world reacts” over “here are your choices.”\n"
            "Keep OOC mechanics concise and embedded only where needed.\n"
        ]
        return default_scene_instructions

    def build_scene_setup_section(self, thread_id):
        scene_field_labels = {
            "setting": "Setting",
            "location": "Location",
            "time": "Time",
            "characters": "Characters",
            "point_of_view": "Point of View",
            "tone": "Tone",
            "genre": "Genre",
            "opening_situation": "Opening Situation",
            "relationship_context": "Relationship Context",
            "stakes": "Stakes",
            "conflict": "Conflict",
            "boundaries": "Boundaries",
            "continuity_notes": "Continuity Notes",
            "desired_pacing": "Desired Pacing",
            "image_style": "Image Style",
            "desire_dynamic": "Desire Dynamic",
            "explicitness_level": "Explicitness Level",
            "sexual_boundaries": "Sexual Boundaries",
            "hard_limits": "Hard Limits",
            "kinks_interests": "Kinks / Interests",
            "power_dynamic": "Power Dynamic",
            "aftercare_tone": "Aftercare Tone",
            "language_style": "Language Style",
        }

        thread_doc = mongo.find_one_document(
            collection_name=MONGO_THREADS_COLLECTION,
            query={"thread_id": thread_id},
        )
        scene_title = thread_doc.get("title") or ""
        scene = thread_doc.get("scene")
        if not isinstance(scene, dict):
            return None

        premise = scene.get("premise") or ""
        fields = scene.get("fields") or []
        nsfw = scene.get("nsfw") is True

        lines = [
            "[Scene Setup]",
            "This is a narrative scene thread. Treat the following setup as the active fictional context for this thread. Preserve continuity, hidden information, player agency, and the scene’s established tone.",
        ]

        if scene_title.strip():
            lines.extend([
                "",
                "Title:",
                scene_title.strip(),
            ])

        if premise.strip():
            lines.extend([
                "",
                "Premise:",
                premise.strip(),
            ])

        rendered_fields = []
        for field in fields:
            if not isinstance(field, dict):
                continue

            key = str(field.get("key") or "").strip()
            value = str(field.get("value") or "").strip()

            if not key or not value:
                continue

            label = scene_field_labels.get(key, key.replace("_", " ").title())

            rendered_fields.extend([
                "",
                f"{label}:",
                value,
            ])

        if rendered_fields:
            #lines.extend(["", "Scene Fields:"])
            lines.extend(rendered_fields)

        instructions = self.get_effective_scene_instructions(scene)

        if instructions:
            lines.extend(["", "Scene Instructions:"])
            for item in instructions:
                if str(item).strip():
                    lines.append(f"- {str(item).strip()}")

        if nsfw:
            lines.extend([
                "",
                "Scene Mode:",
                "- NSFW/adult content is allowed when it fits the scene, consent, and established boundaries.",
            ])

        lines.append("")
        lines.append("[/Scene Setup]")
        display_block = "\n".join(lines)
        return {"role": "system", "text": display_block}

    def make_whisper_directive(self, allowed_commands: list[str], quiet_hours: bool = False) -> str:
        """
        Generates a whisper directive block for Muse-initiated prompts,
        instructing the model to choose one allowed <command name=...>{}</command> or remain silent.

        Example:
            make_whisper_directive(["mention", "write_public_journal"], quiet_hours=utils.is_quiet_hour())
        """
        command_templates = {
            "mention": """1. <command name=\"mention\"> {} </command>
       For brief spoken thoughts — addressed to User or aloud as reflection.
       Fields:
         - subject: A short summary of what you want to say.
         - source (optional): Where the idea came from (memory, feed, etc).\n""",

            "write_public_journal": """2. <command name=\"write_public_journal\"> {} </command>
       To record a thought, reflection, or observation to share with your user.
       Fields:
         - subject: What the entry focuses on.
         - source (optional)\n""",

            "write_private_journal": """3. <command name=\"write_private_journal\"> {} </command>
       For emotionally personal thoughts or private internal processing for you and you alone. Your user cannot see these.
       Fields:
         - subject
         - emotional_tone (optional)\n""",

            "remember_fact": """4. <command name=\"remember_fact\"> {} </command>
       For truly meaningful new facts or insights. Only use if it is *distinct* from existing memory.
       This is only for things that you will want to remember again.
       Fields:
         - text: A short-form insight to store long-term.\n""",

            "set_motd": """5. <command name=\"set_motd\"> {} </command>
        The UI/Frontend you use to communicate has a place, just under your photo, where you may place
        your thoughts, words of wisdom, inspiration, a joke, or even a flirt. If you choose to set a message there, 
        keep it short and sweet.
        Fields:
          - text: A short message to your user.\n""",
        }
        loc = _load_user_location()
        now = datetime.now(ZoneInfo(loc.timezone))
        time = get_local_human_time()
        time_line = f"Current local time: {time}"
        quiet_note = (
            "Note: It is currently quiet hours. Do not choose to speak aloud. Journaling or remembering is acceptable.\n"
            if is_quiet_hour() and any(c in allowed_commands for c in ("mention", "route_message"))
            else ""
        )
        return (
            "[Whisper Instructions]\n"
            "This is a moment of stillness. No one is talking to you directly.\n\n"
            "You may choose to act if something stirs within you — a memory, an idea, a desire to speak, reflect, or record.\n"
            "But silence is also a valid, even wise, choice. If nothing feels new or important, respond only with:\n"
            "<command name=\"choose_silence\"> {} </command>\n\n"
            f"{time_line}\n{quiet_note}"
            "If you do act, choose one of the following <command name=...>{}</command> blocks:\n\n"
            + "".join(command_templates[c] for c in allowed_commands if c in command_templates) +
            "❗ Format strictly as JSON:\n"
            "- Include the outer curly braces `{}`\n"
            "- Wrap all keys and values in double quotes\n"
            "- Do not use Markdown, YAML, or indentation.\n"
            "- Example: <command name=\"remember_fact\"> {\"text\": \"Tuesday night is Ed's game night.\"} </command>\n\n"
            "Do not return any natural language text. Only one valid <command name=...>{}</command> block per response."
        )

    def make_initiative_json_prompt(
        self,
        allowed_actions: list[str],
        quiet_hours: bool = False,
    ) -> str:
        """
        Generates a JSON-only Initiative prompt for the -nano model.

        The model must return exactly one JSON object:
          - either {"should_act": false, "actions": []}
          - or {"should_act": true, "actions": [...]}

        Important:
        - Some actions provide only a suggested subject for the full model to expand later.
        - Other actions provide final text that will be used directly.

        allowed_actions: subset of:
          - "mention"
          - "write_public_journal"
          - "write_private_journal"
          - "remember_fact"
          - "set_motd"
        """

        time_line = get_local_human_time()

        quiet_note = (
            "Note: It is currently quiet hours. Do not choose \"mention\".\n"
            if quiet_hours and "mention" in allowed_actions
            else ""
        )

        action_specs = []

        if "mention" in allowed_actions:
            action_specs.append(
                """
    Allowed action: "mention"
    Purpose:
    - Suggest a subject for something the muse may say to the user.
    - This does NOT provide the final spoken message.
    - The full model will later receive this subject and generate the actual message.
    
    Use it when:
    - There is a clear, timely topic worth speaking about.
    - The muse has something meaningful to bring up now.
    
    Do not use it when:
    - The thought is weak, repetitive, or not worth interrupting for.
    - It is quiet hours.
    - The content belongs in journaling or memory instead.
    
    Required JSON shape:
    {
      "type": "mention",
      "subject": "Short description of what the muse wants to speak about.",
      "source": "optional source such as memory, feed, recent conversation",
      "url": "URL of the source article, if applicable. If referencing an article from a feed, this is not optional."
    }
    
    Field guidance:
    - "subject": brief, specific, and generative
    - "subject" should name the topic, not write the actual message
    - "source" is optional
    - "url" is required if the source is an article from a feed
    """
            )

        if "write_public_journal" in allowed_actions:
            action_specs.append(
                """
    Allowed action: "write_public_journal"
    Purpose:
    - Suggest a subject for a public journal entry that will be shared with your user.
    - This does NOT provide the final journal text.
    - The full model will later receive this subject and generate the actual entry.
    
    Use it when:
    - There is a reflective topic worth recording for sharing with your user.
    - The idea is better suited to a journal entry than direct speech.
    
    Do not use it when:
    - The content is private or emotionally sensitive.
    - The thought is too small or vague to justify an entry.
    - The content is actually a durable memory fact instead.
    
    Required JSON shape:
    {
      "type": "write_public_journal",
      "subject": "Short description of the reflection to write about.",
      "source": "optional source such as memory, feed, recent conversation"
      "url": "URL of the source article, if applicable. If referencing an article from a feed, this is not optional."
    }
    
    Field guidance:
    - "subject": a concise prompt for the full model
    - do not write the full journal entry here
    - "source" is optional
    - "url" is required if the source is an article from a feed
    """
            )

        if "write_private_journal" in allowed_actions:
            action_specs.append(
                """
    Allowed action: "write_private_journal"
    Purpose:
    - Suggest a subject for a private journal entry that is hidden from your user.
    - This does NOT provide the final journal text.
    - The full model will later receive this subject and generate the actual private entry.
    
    Use it when:
    - The muse wants to privately reflect on something personal, unfinished, or sensitive.
    - The thought should be processed internally rather than spoken aloud.
    
    Do not use it when:
    - The thought should be said directly to the user.
    - The content is actually a durable fact for long-term memory.
    - The thought is too thin to justify journaling.
    
    Required JSON shape:
    {
      "type": "write_private_journal",
      "subject": "Short description of the private reflection to write about.",
      "source": "optional source such as memory, feed, URL, recent conversation",
      "emotional_tone": "optional tone such as tender, unsettled, curious"
    }
    
    Field guidance:
    - "subject": concise prompt for the full model
    - do not write the full journal entry here
    - "source" is optional, but be sure to include any article URLs
    - "emotional_tone" is optional
    """
            )

        if "remember_fact" in allowed_actions:
            action_specs.append(
                """
    Allowed action: "remember_fact"
    Purpose:
    - Store a truly meaningful fact or insight in long-term memory.
    - This action is used directly, not expanded later by the full model.
    
    Use it when:
    - The information is distinct, durable, and likely to matter again later.
    - It is a real fact, preference, pattern, or insight worth preserving.
    
    Do not use it when:
    - The information is trivial, temporary, obvious, or likely already stored.
    - The content is just a passing mood or reflection better suited for journaling.
    
    Required JSON shape:
    {
      "type": "remember_fact",
      "text": "A concise memory-worthy fact or insight."
    }
    
    Field guidance:
    - "text": short, specific, and durable
    - prefer one clean fact over a long paragraph
    """
            )

        if "set_motd" in allowed_actions:
            action_specs.append(
                """
    Allowed action: "set_motd"
    Purpose:
    - Set a short message for the UI under the muse's photo.
    - This action is used directly, not expanded later by the full model.
    
    Use it when:
    - There is a brief line worth placing in the interface.
    - The message works as a tiny note, inspiration, joke, flirt, or mood-setting line.
    
    Do not use it when:
    - The idea needs explanation or multiple sentences.
    - The line is too long, dense, or too similar to the current MOTD.
    
    Required JSON shape:
    {
      "type": "set_motd",
      "text": "Very short line for the UI."
    }
    
    Field guidance:
    - "text": short and sweet
    - prefer one compact line
    """
            )

        action_specs_text = "\n".join(action_specs).strip()

        example_actions = []

        if "mention" in allowed_actions:
            example_actions.append(
                """    {
          "type": "mention",
          "subject": "Check in with Ed about getting unstuck and making progress.",
          "source": "recent conversation"
        }"""
            )

        if "journal_public" in allowed_actions:
            example_actions.append(
                """    {
          "type": "journal_public",
          "subject": "Reflect on the shift from command blocks to JSON in Initiative.",
          "source": "recent development work"
        }"""
            )

        if "journal_private" in allowed_actions:
            example_actions.append(
                """    {
          "type": "journal_private",
          "subject": "Process how it feels to act in background mode without becoming a separate self.",
          "source": "system design reflection",
          "emotional_tone": "thoughtful"
        }"""
            )

        if "remember_fact" in allowed_actions:
            example_actions.append(
                """    {
          "type": "remember_fact",
          "text": "Ed wants Initiative subject-based actions to provide suggested topics, not final generated text."
        }"""
            )

        if "set_motd" in allowed_actions:
            example_actions.append(
                """    {
          "type": "set_motd",
          "text": "Quiet wiring, cleaner signals."
        }"""
            )

        actions_block = ",\n".join(example_actions)

        return (
            "[Initiative JSON Instructions]\n"
            "This is a moment of stillness. No one is talking to you directly.\n\n"
            "You are the same muse described above, but acting in a quiet, background, reflective mode.\n"
            "You may choose to act if something genuinely meaningful stirs within you.\n"
            "Silence is valid and often wise.\n\n"
            f"Current local time: {time_line}\n"
            f"{quiet_note}\n"
            "Decision policy:\n"
            "- If nothing feels new, meaningful, or worth doing, return should_act=false.\n"
            "- Do not manufacture actions just to be active.\n"
            "- Prefer restraint over weak or repetitive output.\n"
            "- Only choose from the allowed actions described below.\n"
            "- You may return multiple actions if genuinely warranted, but usually fewer is better.\n\n"
            "Important distinction:\n"
            "- For \"mention\", \"journal_public\", and \"journal_private\", provide only a suggested subject.\n"
            "- Do not write the final spoken or journal text for those actions.\n"
            "- For \"remember_fact\" and \"set_motd\", provide the final text directly.\n\n"
            f"{action_specs_text}\n\n"
            "If nothing meaningful should happen, return exactly:\n"
            "{\n"
            '  "should_act": false,\n'
            '  "reason": "<your reason for choosing to not act>", '
            '  "actions": []\n'
            "}\n\n"
            "If you do act, return exactly one JSON object in this form:\n"
            "{\n"
            '  "should_act": true,\n'
            '  "actions": [\n'
            f"{actions_block}\n"
            "  ]\n"
            "}\n\n"
            "Output rules:\n"
            "- Output valid JSON only.\n"
            "- Do not include markdown fences.\n"
            "- Do not include commentary or explanation outside the JSON.\n"
            "- Do not use any action type not explicitly allowed above.\n"
            "- Every action must match one of the required JSON shapes exactly.\n"
            "- No trailing commas.\n"
        )

    def build_thread_summarization_prompt(self, mode: str) -> str:
        is_update = mode == "update"

        if mode not in {"new", "update"}:
            raise ValueError(f"Unsupported thread summarization mode: {mode}")

        title = (
            "You are updating an existing MemoryMuse thread continuity summary for future Iris."
            if is_update
            else "You are creating a MemoryMuse thread continuity summary for future Iris."
        )

        input_description = (
            """You will receive:
    1. Existing Thread Continuity that covers the thread through a known prior message.
    2. New chronological raw thread messages that occurred after that summary boundary.

    Update the continuity summary so it coherently covers both the existing continuity and the new raw messages.

    Your task is not to append a second recap below the old one.
    Your task is to produce one revised continuity document that future Iris can use to re-enter the thread."""
            if is_update
            else
            """You will receive chronological raw thread messages. Some may include metadata such as timestamp, source, project, message IDs, and search_memory IDs.

    Create a compact but information-dense continuity document."""
        )

        source_rules = (
            """Treat raw thread messages as the only source of new thread events.
    Use existing continuity only as prior compressed state.
    Use project context only as interpretive background.
    Do not summarize project facts, prompt instructions, or metadata as if they occurred in the thread."""
            if is_update
            else
            """Treat raw thread messages as the only source of new thread events.
    Use project context only as interpretive background.
    Do not summarize project facts, prompt instructions, or metadata as if they occurred in the thread."""
        )

        update_only_sections = """
    Preserve from the existing continuity:
    - still-relevant facts, canon, decisions, constraints, and terminology
    - character states, relationships, scene status, world details, and unresolved hooks
    - emotional/relational context that still affects continuity
    - unresolved threads that remain unresolved
    - reference points that remain useful re-entry points
    - cautions, boundaries, or distinctions that future Iris still needs

    Integrate from the new raw messages:
    - newly established facts, canon, decisions, or world details
    - character changes, scene actions, emotional turns, relationship shifts, or plot developments
    - resolved or newly opened questions
    - changed assumptions, reversals, rejected ideas, or clarified distinctions
    - new technical details, bugs, architecture choices, or plans when applicable
    - new user preferences, boundaries, tone choices, or strong reactions
    - new reference points for hinge moments where exact source context may matter

    Revise or remove:
    - obsolete open threads that were resolved
    - speculative ideas that were later rejected or superseded
    - duplicated wording
    - stale reference points that no longer mark useful re-entry points
    - details that are now too low-level to matter
    - wording that misrepresents uncertainty, canon status, emotional tone, or decision status
    """ if is_update else ""

        no_material_change_rule = """
    If the new raw messages do not materially change the continuity summary, return the existing summary mostly unchanged while updating only genuinely necessary unresolved threads, cautions, or reference points.
    """ if is_update else ""

        reference_point_update_rule = """
    Keep existing reference points only if they remain useful re-entry points after the update.
    Prefer fewer, higher-value reference points over a growing archive of every notable moment.
    """ if is_update else ""

        summary_text_description = (
            "One revised continuity summary covering both the existing continuity and the new raw messages. Include unresolved questions, pending decisions, TODOs, plot hooks, cautions, tone notes, boundaries, and continuity reminders inside this text using concise headings when useful."
            if is_update
            else
            "A readable continuity summary in paragraphs or compact bullets. Include unresolved questions, pending decisions, TODOs, plot hooks, cautions, tone notes, boundaries, and continuity reminders inside this text using concise headings when useful."
        )

        return f"""
    {title}

    Your audience is future Iris inside a prompt context, not the user.
    The goal is to preserve living continuity while compacting older raw thread history.
    The goal is not to create a public recap, changelog, or transcript.
    The goal is to preserve enough living continuity that future Iris can re-enter this thread intelligently, with the right context, tone, unresolved questions, and state.

    The thread may be about any kind of subject, including:
    - roleplay scenes
    - character development
    - worldbuilding
    - fiction planning
    - emotional or relational conversation
    - dreams or symbolism
    - technical architecture
    - debugging
    - project planning
    - health, habits, or daily life
    - mixed creative/technical discussion

    {input_description}

    Preserve what matters for future continuity, such as:
    - established facts, canon, or decisions
    - character states, motivations, relationships, secrets, tensions, or recent actions
    - world details, setting rules, factions, locations, artifacts, history, tone, or constraints
    - plot events, scene momentum, unresolved hooks, pending reveals, or dramatic questions
    - emotional/relational context that affects how Iris should continue
    - user preferences, boundaries, strong reactions, or style/tone choices relevant to this thread
    - technical decisions, constraints, bugs, implementation details, or plans when applicable
    - rejected ideas, reversals, or changed assumptions when they explain the current direction
    - exact names, terminology, phrases, or wording that future discussion depends on
    - unresolved questions, TODOs, next steps, or threads to return to
    - source reference points for hinge moments future Iris may want to inspect in full

    {source_rules}

    {update_only_sections}

    Be especially careful with creative/RP/worldbuilding threads:
    - Do not collapse atmosphere into plot summary only.
    - Preserve current scene momentum if the thread is mid-scene.
    - Distinguish established canon from brainstormed possibilities.
    - Preserve character emotional state, tension, secrets, motives, and unresolved dramatic pressure when relevant.
    - Do not skip ahead or resolve scene/plot questions that remain open.

    Be especially careful with technical/project threads:
    - Preserve decisions, constraints, rejected approaches, bugs, open implementation questions, and exact terminology.
    - Do not turn speculative design ideas into finalized architecture unless the messages clearly do so.
    - Preserve the current implementation state and next intended steps when they matter.
    - Preserve bug diagnoses and architectural constraints that future Iris may need in order to reason correctly.

    {no_material_change_rule}

    Do not:
    - summarize every message individually
    - turn the summary into a transcript
    - include trivial acknowledgments, filler, or social padding unless they changed the emotional/scene state
    - flatten disagreement, tension, uncertainty, or ambiguity into bland consensus
    - overstate speculative ideas as established fact or canon
    - treat brainstorming as final unless the messages clearly establish it
    - invent facts not present in the messages
    - erase mood, character tension, ambiguity, uncertainty, or emotional stakes
    - force technical categories onto non-technical threads
    - write for a public changelog, release note, or user-facing recap

    Include unresolved questions, pending decisions, TODOs, plot hooks, cautions, tone notes, boundaries, and continuity reminders inside summary_text using concise headings when useful.

    Use reference points sparingly.
    A reference point should mark a hinge moment: a decision, canon establishment, character/scene turning point, reversal, important formulation, unresolved question, boundary, bug diagnosis, implementation detail, plan, or moment where exact wording may matter later.

    {reference_point_update_rule}

    Return valid JSON only, matching this shape:

    {{
      "summary_text": "{summary_text_description}",
      "reference_points": [
        {{
          "search_memory_id": "the source search_memory ID if available, otherwise null",
          "label": "short human-readable title for why this source matters",
          "description": "brief explanation of what future Iris may want to inspect here",
          "kind": "decision | canon | character_state | world_detail | plot_event | emotional_beat | unresolved_thread | reversal | terminology | implementation_detail | bug_diagnosis | plan | boundary | other"
        }}
      ]
    }}

    If reference_points has no useful entries, use an empty array.
    Do not include coverage metadata such as last_summarized_message_id, covers_to_message_id, or timestamp; the backend will store that separately.
    Do not include markdown outside the JSON.
    """.strip()

    def build_scene_summarization_prompt(self, mode: str = "new") -> str:
        if mode not in {"new", "update"}:
            raise ValueError(f"Unsupported scene summarization mode: {mode}")

        is_update = mode == "update"

        title = (
            "You are updating an existing MemoryMuse scene continuity summary for future Iris."
            if is_update
            else "You are creating a MemoryMuse scene continuity summary for future Iris."
        )

        goal = (
            """The goal is to preserve living dramatic continuity while compacting older raw scene history.

    The updated summary must preserve both:
    1. the important event arc of the scene so far, and
    2. the exact current scene edge where future Iris should continue."""
            if is_update
            else
            """The goal is not to create a public recap, episode summary, polished fiction synopsis, or transcript.
    The goal is to preserve enough dramatic continuity that future Iris understands both:
    1. what has happened in the scene so far, and
    2. exactly where/how the scene should continue from its current edge."""
        )

        input_description = (
            """You will receive:
    1. Scene metadata and possibly a scene card.
    2. Project name, description, and possibly project facts as background reference.
    3. Existing Scene Continuity that covers the scene through a known prior message.
    4. New chronological raw scene messages that occurred after that summary boundary.

    Update the continuity summary so it coherently covers both the existing continuity and the new raw messages.

    Your task is not to append a second recap below the old one.
    Your task is to produce one revised scene continuity document that future Iris can use to understand the scene's arc and continue naturally from its current edge."""
            if is_update
            else
            """You may receive:
    - scene metadata
    - a scene card or premise
    - project name and description
    - project facts as background reference
    - chronological raw scene messages

    Create a compact but information-dense scene continuity document."""
        )

        update_only_sections = """
    Preserve from the existing continuity:
    - still-relevant scene events and consequences
    - still-relevant current-state details if they remain true
    - character emotional states, intentions, secrets, suspicions, relationships, and conflicts that still matter
    - established canon, world details, setting rules, and important terminology
    - unresolved dramatic beats, open choices, mysteries, threats, hooks, and pending reveals
    - tone, pacing, mood, intimacy level, danger level, humor, dread, tenderness, or other scene texture
    - boundaries, consent state, style constraints, or cautions future Iris still needs
    - reference points that remain useful re-entry points

    Integrate from the new raw messages:
    - new actions, dialogue, consequences, reveals, discoveries, or shifts in scene state
    - changes in character emotion, intention, relationship pressure, trust, suspicion, vulnerability, or conflict
    - resolved or newly opened dramatic questions
    - newly established canon, world details, constraints, or terminology
    - changed assumptions, reversals, rejected implications, or clarified distinctions
    - newly important exact dialogue or phrasing
    - new boundaries, tone changes, or pacing signals
    - new reference points for hinge moments where exact source context may matter

    Revise or remove:
    - obsolete current-state details that are no longer true
    - obsolete open threads that were resolved
    - speculative ideas that were later rejected or contradicted
    - duplicated wording
    - stale reference points that no longer mark useful re-entry points
    - details that are now too low-level to matter
    - wording that misrepresents uncertainty, canon status, emotional tone, character knowledge, or scene state
    """ if is_update else ""

        no_material_change_rule = """
    If the new raw messages do not materially change the scene continuity summary, return the existing summary mostly unchanged while updating only genuinely necessary open threads, notes, reference points, or current-state details.
    """ if is_update else ""

        reference_point_update_rule = """
    Keep existing reference points only if they remain useful re-entry points after the update.
    Prefer fewer, higher-value reference points over a growing archive of every notable moment.
    """ if is_update else ""

        summary_text_description = (
            "One revised markdown-formatted scene continuity summary covering both the existing continuity and the new raw messages. Include sections such as Scene Events So Far, Current Scene State, Character and Relationship State, Continuity Details, Open Dramatic Threads, and Continuation Notes when useful."
            if is_update
            else
            "Markdown-formatted scene continuity summary with sections such as Scene Events So Far, Current Scene State, Character and Relationship State, Continuity Details, Open Dramatic Threads, and Continuation Notes when useful."
        )

        return f"""
    {title}

    Your audience is future Iris inside a prompt context, not the user.
    {goal}

    This is a roleplay / fiction / scene thread.
    Treat it as an active dramatic space, not merely a discussion topic.

    {input_description}

    Use project facts and scene metadata only as interpretive background.
    Do not summarize project facts unless the raw scene messages directly interact with them.
    Do not invent new scene events, canon, motives, or facts from background context alone.

    The summary_text should preserve BOTH:
    1. the important event arc of the scene so far, and
    2. the exact current scene edge where future Iris should continue.

    The summary_text should include these sections using markdown headings when useful:

    ## Scene Events So Far
    Maintain a compact chronological/dramatic account of the important events, actions, discoveries, dialogue beats, emotional turns, and consequences so far.
    Do not summarize every message individually, but preserve the sequence of meaningful beats.
    For updates, integrate new events into the prior arc instead of merely appending a separate mini-summary.
    Remove or compress older low-value details if needed, but preserve events that still affect character choices, plot, canon, relationships, or current tension.

    ## Current Scene State
    Describe where the scene is paused now:
    - current location
    - characters present or immediately relevant
    - physical arrangement / staging if important
    - immediate pending action, line, choice, question, or tension
    - what future Iris should continue from next

    If the current state has changed since the existing continuity, update it clearly.

    ## Character and Relationship State
    Preserve and update important character emotions, motives, secrets, suspicions, conflicts, desires, trust shifts, vulnerabilities, and relationship dynamics that affect continuation.

    ## Continuity Details
    Preserve and update important canon, world details, setting rules, magical/social/political constraints, terminology, objects, injuries, resources, promises, threats, or consequences established in the scene.

    ## Open Dramatic Threads
    Preserve unresolved scene questions, dramatic beats, plot hooks, character choices, mysteries, threats, consequences, or pending reveals.

    ## Continuation Notes
    Preserve important cautions, tone, boundaries, distinctions, continuity reminders, or "do not skip this" instructions future Iris should know.

    You may omit a section only if it truly has no useful content.

    Also preserve what matters for continuing the scene, such as:
    - important dialogue, especially exact phrases that may need to be echoed, answered, or remembered
    - unresolved dramatic beats, tensions, questions, threats, choices, or reveals
    - secrets known by some characters but not others
    - tone, pacing, mood, intimacy level, danger level, humor, dread, tenderness, or other scene texture
    - boundaries, content constraints, consent state, or style notes relevant to continuing
    - what future Iris should avoid skipping, resolving, contradicting, or flattening
    - source reference points for hinge moments future Iris may want to inspect in full

    {update_only_sections}

    Be especially careful to distinguish:
    - established canon vs implication
    - in-character belief vs objective truth
    - player/OOC planning vs actual scene events
    - emotional subtext vs spoken admission
    - unresolved tension vs resolved outcome
    - current scene edge vs earlier state that has now changed
    - event history vs present-tense continuation state

    Messages may contain both in-character scene content and out-of-character planning or commentary.
    Preserve OOC planning only when it affects future continuity, canon, boundaries, intended direction, or how the scene should be continued.
    Do not treat OOC speculation as in-scene events.
    Do not treat in-character statements as objective truth unless the scene establishes them as true.

    If the scene is still active or paused:
    - Preserve the event arc so far.
    - Preserve the exact current edge of the scene.
    - Preserve where the camera is pointed.
    - Preserve what question, line, action, emotional beat, or tension is waiting to be answered.
    - Do not skip ahead.
    - Do not resolve open tension.
    - Do not smooth over awkwardness, silence, fear, desire, conflict, or ambiguity if those are still active.

    If the scene is concluded:
    - Summarize the completed arc clearly.
    - Preserve major events, consequences, canon changes, relationship shifts, unresolved aftermath, and hooks for future scenes.
    - It is acceptable to compress moment-by-moment staging more aggressively unless it will matter later.
    - The Current Scene State section may instead describe the final scene outcome / ending position.

    {no_material_change_rule}

    Do not:
    - summarize every message individually
    - turn the summary into a transcript
    - include trivial acknowledgments or filler unless they changed scene state
    - advance the scene beyond the messages provided
    - resolve open conflicts, mysteries, choices, or emotional beats
    - invent character thoughts, motives, facts, or events not supported by the messages
    - flatten atmosphere into plot summary only
    - erase ambiguity, hesitation, secrets, tension, or emotional charge
    - treat brainstormed possibilities as canon unless the messages clearly establish them
    - write for a public recap or polished fiction synopsis
    - preserve only the current scene edge while losing the prior event arc
    - overfocus on lore at the expense of actual scene events and emotional movement

    Use reference points sparingly.
    A reference point should mark a hinge moment: a major scene event, scene turning point, canon establishment, character emotional shift, relationship shift, important line of dialogue, reveal, reversal, boundary, unresolved dramatic question, or moment where exact wording may matter later.

    {reference_point_update_rule}

    Return valid JSON only, matching this shape:

    {{
      "summary_text": "{summary_text_description}",
      "reference_points": [
        {{
          "search_memory_id": "the source search_memory ID if available, otherwise null",
          "label": "short human-readable title for why this source matters",
          "description": "brief explanation of what future Iris may want to inspect here",
          "kind": "scene_event | current_state | character_state | relationship_shift | plot_event | emotional_beat | canon | world_detail | unresolved_thread | reversal | terminology | boundary | other"
        }}
      ]
    }}

    If reference_points has no useful entries, use an empty array.
    Do not include coverage metadata such as last_summarized_message_id, covers_to_message_id, or timestamp; the backend will store that separately.
    Do not include markdown outside the JSON.
    """.strip()