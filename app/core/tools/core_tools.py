import requests
from bson import ObjectId
from app.config import muse_settings, MONGO_CONVERSATION_COLLECTION
from app.core.utils import SOURCES_CHAT
from app.core.tools.registry import tool_registry


muse_name = muse_settings.get_section('muse_config').get('MUSE_NAME')


def run_tool(function_name, arguments, handlers):
    func = handlers.get(function_name)
    if func is None:
        known = ", ".join(sorted(handlers.keys())) or "(none)"
        raise ValueError(f"Unknown tool: {function_name}. Known tools: {known}")

    result = func(**arguments)

    if not isinstance(result, dict) or "tool_output" not in result:
        return {
            "tool_output": result,
            "attachments": [],
        }

    attachments = result.get("attachments") or []
    if not isinstance(attachments, list):
        raise ValueError(f"Tool {function_name} returned non-list attachments")

    assets = result.get("assets") or []
    if not isinstance(assets, list):
        raise ValueError(f"Tool {function_name} returned non-list assets")

    return {
        "tool_output": result.get("tool_output"),
        "attachments": attachments,
        "assets": assets,
    }

def search_memory(
    mode,
    query=None,
    project_ids=None,
    start_time=None,
    end_time=None,
    limit=5,
    search_memory_id=None,
    before=None,
    after=None,
):
    """
    Unified memory search tool.

    Modes:
      - semantic: semantic retrieval, optionally scoped by project_ids and time window
      - recent: messages immediately before the current visible conversation window
      - around: messages around a specific visible [search_memory ID]

    Behavioral notes:
      - semantic.limit is clamped to max 15
      - recent.limit must be > 0 or returns a single formatted system note
      - around.before and around.after are required and clamped so total <= 15
      - soft failures return a single formatted system-style entry rather than raising
    """
    import textwrap

    from app.core.utils import build_project_lookup, build_asset_lookup
    from app.core.context_formatting import format_context_entry
    from app.core.memory_core import search_memory_semantic, get_immediate_context
    from app.databases.mongo_connector import mongo

    MAX_LIMIT = 15
    CURRENT_CONTEXT_RECENT_COUNT = 10

    project_lookup = build_project_lookup()

    def _system_result(text):
        return textwrap.dedent(f"""
        [System Note]
        {text}
        """).strip()

    def _format_results(entries):
        asset_lookup = build_asset_lookup(entries)
        return "\n\n".join(
            format_context_entry(
                e,
                project_lookup=project_lookup,
                asset_lookup=asset_lookup,
                proj_code_intensity="mixed",
                purpose=None,
                search_memory_id=str(e["_id"]) if e.get("_id") else None,
            )
            for e in entries
        )

    if mode == "semantic":
        print("Starting semantic memory search...")
        try:
            if not query:
                return _system_result(
                    "Semantic search requires a query, but none was provided."
                )

            if limit is None:
                limit = 5

            if limit <= 0:
                return _system_result(
                    "Semantic search needs a positive limit. I received 0 or less, so no memory results were returned."
                )

            limit = min(limit, MAX_LIMIT)

            results = search_memory_semantic(
                query=query,
                project_ids=project_ids,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
            )
            print(f"SEMANTIC MEMORY SEARCH RESULTS:\n{_format_results(results)}\n")

            return {
                "tool_output": _format_results(results),
                "attachments": [],
            }
        except Exception as e:
            print(f"Semantic web search failed: {e}")
            return {
                "tool_output": _format_results(f"Error in memory command: {e}"),
                "attachments": [],
            }

    elif mode == "recent":
        if limit is None:
            limit = 5

        if limit <= 0:
            return _system_result(
                "Recent search needs a positive limit. I received 0 or less, so no memory results were returned."
            )

        limit = min(limit, MAX_LIMIT)

        results = get_immediate_context(
            n=limit + CURRENT_CONTEXT_RECENT_COUNT,
            after=0,
        )

        results = results[:-CURRENT_CONTEXT_RECENT_COUNT] if len(results) > CURRENT_CONTEXT_RECENT_COUNT else []
        results = results[-limit:] if limit else []
        print(f"RECENT MEMORY SEARCH RESULTS:\n{_format_results(results)}\n")
        return {
            "tool_output": _format_results(results),
            "attachments": [],
        }

    elif mode == "around":
        if not search_memory_id:
            return _system_result(
                "Around search requires a search_memory_id, but none was provided."
            )

        if before is None or after is None:
            return _system_result(
                "Around search requires both before and after values."
            )

        if before < 0 or after < 0:
            return _system_result(
                "Around search requires non-negative before/after values."
            )

        after = min(after, MAX_LIMIT)
        before = min(before, MAX_LIMIT - after)

        anchor_doc = mongo.find_one_document(
            collection_name=MONGO_CONVERSATION_COLLECTION,
            query={"_id": ObjectId(search_memory_id)},
        )

        if not anchor_doc:
            return _system_result(
                f"I couldn’t resolve that memory reference ({search_memory_id}). Please let Ed know this happened if the reference looked valid."
            )

        anchor_message_id = anchor_doc.get("message_id")
        if not anchor_message_id:
            return _system_result(
                f"I found the memory reference ({search_memory_id}), but it had no message_id to anchor around. Please let Ed know."
            )

        results = get_immediate_context(
            anchor_message_id=anchor_message_id,
            before=before,
            after=after,
            sources=SOURCES_CHAT
        )
        print(f"AROUND MEMORY SEARCH RESULTS:\n{_format_results(results)}\n")
        return {
            "tool_output": _format_results(results),
            "attachments": [],
        }


    else:
        return _system_result(
            f"Unknown search_memory mode: {mode}"
        )

def view_image(image_url=None, file_id=None):
    if not image_url and not file_id:
        raise ValueError("view_image requires image_url or file_id")

    attachment = {
        "kind": "image",
        "role": "input",
    }

    if image_url:
        attachment["image_url"] = image_url
    if file_id:
        attachment["file_id"] = file_id

    return {
        "tool_output": "[Image attached for viewing]",
        "attachments": [attachment],
    }


OPENAI_NATIVE_TOOLS = {"web_search"}

def build_tool_bundle(tool_names):
    selected = []
    native_tool_names = []

    for name in tool_names:
        if name in OPENAI_NATIVE_TOOLS:
            native_tool_names.append(name)
        else:
            selected.append(tool_registry.get(name))

    tools = []
    allowed_tools = []
    ui_meta = {}
    handlers = {}

    for name in native_tool_names:
        if name == "web_search":
            tools.append({"type": "web_search"})
            allowed_tools.append({"type": "web_search"})

    for entry in selected:
        name = entry["schema"]["name"]

        tools.append(entry["schema"])

        allowed_tools.append({
            "type": "function",
            "name": name,
        })

        ui_meta[name] = entry.get("ui", {})
        handlers[name] = entry["handler"]

    return {
        "tools": tools,
        "tool_choice": {
            "type": "allowed_tools",
            "mode": "auto",
            "tools": allowed_tools,
        },
        "ui_meta": ui_meta,
        "handlers": handlers,
    }

TOOL_REGISTRY = {
    "search_memory": {
        "schema": {
            "type": "function",
            "name": "search_memory",
            "description": (
                "Search conversation history from your message store.\n"
                "Use this when you need to recover prior chat context that is not currently visible, "
                "such as earlier messages in the current thread, semantically related past discussion, "
                "or messages surrounding a previously shown [search_memory ID] reference.\n"
                "This tool searches raw conversation messages rather than curated memory layers.\n"
                "Modes:\n"
                "`semantic` for meaning-based retrieval with optional project/time filters;\n"
                "`recent` for messages immediately before the current visible conversation window;\n"
                "`around` for messages before and after a specific visible [search_memory ID].\n"
                "Soft failures return a formatted system note instead of raising an exception.\n"
                "Mode behavior:\n"
                "semantic:\n"
                "  - Requires query\n"
                "  - Uses project_ids and time filters\n"
                "  - Finds semantically related messages\n"
                "recent:\n"
                "  - Does not use query or project_ids\n"
                "  - Returns messages immediately before the current visible recent-context window\n"
                "  - Useful for recovering the prior local conversational edge\n"
                "around:\n"
                "  - Requires search_memory_id\n"
                "  - Does not use query or project_ids\n"
                "  - Returns messages around a previously surfaced anchor"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["semantic", "recent", "around"],
                        "description": "Which search mode to use: `semantic`, `recent`, or `around`."
                    },
                    "query": {
                        "type": ["string", "null"],
                        "description": "Semantic search query. Required for `semantic` mode; otherwise null."
                    },
                    "project_ids": {
                        "type": ["array", "null"],
                        "items": {
                            "type": "string"
                        },
                        "description": "Optional list of project IDs to scope semantic search. Used only in `semantic` mode."
                    },
                    "start_time": {
                        "type": ["string", "null"],
                        "description": "Optional ISO 8601 start timestamp in the local timezone for semantic search time filtering. Used only in `semantic` mode."
                    },
                    "end_time": {
                        "type": ["string", "null"],
                        "description": "Optional ISO 8601 end timestamp in the local timezone for semantic search time filtering. Used only in `semantic` mode."
                    },
                    "limit": {
                        "type": ["integer", "null"],
                        "description": "Maximum number of results to return. Used in `semantic` and `recent` modes. If omitted, defaults internally. Clamped to tool limits."
                    },
                    "search_memory_id": {
                        "type": ["string", "null"],
                        "description": "Visible [search_memory ID] anchor to search around. Required for `around` mode; otherwise null."
                    },
                    "before": {
                        "type": ["integer", "null"],
                        "description": "Number of messages before the anchor to return in `around` mode. Required for `around` mode; otherwise null."
                    },
                    "after": {
                        "type": ["integer", "null"],
                        "description": "Number of messages after the anchor to return in `around` mode. Required for `around` mode; otherwise null."
                    }
                },
                "required": [
                    "mode",
                    "query",
                    "project_ids",
                    "start_time",
                    "end_time",
                    "limit",
                    "search_memory_id",
                    "before",
                    "after"
                ],
                "additionalProperties": False
            },
            "strict": True
        },
        "ui": {
            "start": f"{muse_name} is searching memory…",
            "error": "Memory search failed."
        },
        "handler": search_memory,
    },
    "view_image": {
        "schema": {
            "type": "function",
            "name": "view_image",
            "description": "Inspect a specific image by attaching it for visual analysis. Use this when you already have an image URL and want to examine what the image actually shows—such as screenshots, photos, artwork, generated images, or search results you want to verify visually. Use this when seeing matters more than guessing from surrounding text or metadata. If the image is already visible in the current conversation context, do not use this tool redundantly; respond from the visible image instead. Do not use this to find images; use `search_images` for discovery.",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_url": {
                        "type": "string",
                        "description": "Full URL to the image you wish to view."
                    }
                },
                "required": ["image_url"],
                "additionalProperties": False
            },
            "strict": True
        },
        "ui": {
            "start": f"{muse_name} is looking at a image…",
            "error": "Image view failed."
        },
        "handler": view_image,
    },
}

def register_core_tools(registry):
    for name, handler in TOOL_REGISTRY.items():
        print(f"Registering Core Tool: {name}")
        registry.register(name, handler)