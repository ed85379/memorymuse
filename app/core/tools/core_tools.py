import requests
import os
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

    return {
        "tool_output": result.get("tool_output"),
        "attachments": attachments,
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

    from app.core.utils import format_context_entry, build_project_lookup
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
        return "\n\n".join(
            format_context_entry(
                e,
                project_lookup=project_lookup,
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

def search_web(query):
    serper_url = "https://google.serper.dev/search"
    serper_api_key = muse_settings.get_section("api_keys").get("SERPER_API_KEY")

    payload = {
        "q": query
    }
    headers = {
        'X-API-KEY': serper_api_key,
        'Content-Type': 'application/json'
    }

    response = requests.post(serper_url, headers=headers, json=payload)

    return f"[Your web search results for query: {query}]\n{response.text}"

def search_news(query):
    serper_url = "https://google.serper.dev/news"
    serper_api_key = muse_settings.get_section("api_keys").get("SERPER_API_KEY")

    payload = {
        "q": query
    }
    headers = {
        'X-API-KEY': serper_api_key,
        'Content-Type': 'application/json'
    }

    response = requests.post(serper_url, headers=headers, json=payload)

    return f"[Your news search results for query: {query}]\n{response.text}"

def search_images(query):
    serper_url = "https://google.serper.dev/images"
    serper_api_key = muse_settings.get_section("api_keys").get("SERPER_API_KEY")

    payload = {"q": query}
    headers = {
        "X-API-KEY": serper_api_key,
        "Content-Type": "application/json",
    }

    response = requests.post(serper_url, headers=headers, json=payload)
    response.raise_for_status()

    return {
        "tool_output": f"[Your image search results for query: {query}]\n{response.text}",
        "attachments": [],
    }

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

def read_webpage(url):
    serper_url = "https://scrape.serper.dev"
    serper_api_key = muse_settings.get_section("api_keys").get("SERPER_API_KEY")

    payload = {
        "url": url
    }
    headers = {
        'X-API-KEY': serper_api_key,
        'Content-Type': 'application/json'
    }

    response = requests.post(serper_url, headers=headers, json=payload)

    return f"[Your requested webpage content from: {url}]\n{response.text}"

def generate_image(
    prompt,
    explicit: bool = False,
    image_size=None,
    seed=None,
    sources=None,
):
    os.environ["FAL_KEY"] = muse_settings.get_section("api_keys").get("FAL_API_KEY")
    import fal_client

    def on_queue_update(update):
        if isinstance(update, fal_client.InProgress):
            for log in update.logs:
                print(log["message"])

    normalized_sources = []
    for source in sources or []:
        if not isinstance(source, dict):
            raise ValueError("Each source must be an object.")

        source_type = source.get("type")
        if source_type != "url":
            raise ValueError("generate_image currently supports only source type 'url'.")

        url = source.get("url")
        if not url or not isinstance(url, str):
            raise ValueError("URL source missing valid 'url' field.")

        normalized_sources.append({
            "type": "url",
            "url": url,
        })

    if len(normalized_sources) > 10:
        raise ValueError("generate_image supports at most 10 source images.")

    image_urls = [source["url"] for source in normalized_sources]

    arguments = {
        "prompt": prompt,
        "enable_safety_checker": not explicit,
    }

    if image_size is not None:
        arguments["image_size"] = image_size

    if seed is not None:
        arguments["seed"] = seed

    if image_urls:
        model_path = "fal-ai/bytedance/seedream/v4.5/edit"
        mode = "edit"
        arguments["image_urls"] = image_urls
    else:
        model_path = "fal-ai/bytedance/seedream/v4.5/text-to-image"
        mode = "text_to_image"

    result = fal_client.subscribe(
        model_path,
        arguments=arguments,
        with_logs=True,
        on_queue_update=on_queue_update,
    )
    print(result)

    images = result.get("images", [])
    if not images:
        raise ValueError("fal returned no images")

    image_url = images[0].get("url")
    if not image_url:
        raise ValueError("fal returned image without URL")

    attachment = {
        "kind": "image",
        "role": "input",
        "image_url": image_url,
    }

    first_image = images[0]

    metadata = {
        "mode": mode,
        "model": model_path,
        "prompt": prompt,
        "explicit": explicit,
        "image_size": image_size,
        "seed_input": seed,
        "seed_output": result.get("seed"),
        "sources": normalized_sources,
        "content_type": first_image.get("content_type"),
        "file_name": first_image.get("file_name"),
        "file_size": first_image.get("file_size"),
        "width": first_image.get("width"),
        "height": first_image.get("height"),
    }

    if explicit:
        return {
            "tool_output": (
                f"[Requested image generated]\n"
                f"Prompt: {prompt}\n"
                f"Mode: {mode}\n"
                f"URL: {image_url}\n"
                f"Note: Display the image directly into your response using markdown."
            ),
            "attachments": [],
            "metadata": metadata,
        }
    else:
        return {
            "tool_output": (
                f"[Requested image generated and attached for viewing]\n"
                f"Prompt: {prompt}\n"
                f"Mode: {mode}\n"
                f"URL: {image_url}\n"
                f"Note: Display the image directly into your response using markdown."
            ),
            "attachments": [attachment],
            "metadata": metadata,
        }

def generate_muse_image(prompt, explicit: bool = False):
    os.environ["FAL_KEY"] = muse_settings.get_section("api_keys").get("FAL_API_KEY")
    import fal_client

    def on_queue_update(update):
        if isinstance(update, fal_client.InProgress):
            for log in update.logs:
                print(log["message"])

    result = fal_client.subscribe(
        "fal-ai/bytedance/seedream/v4.5/edit",
        arguments={
            "prompt": prompt,
            "image_urls": [
                "https://i.imgur.com/CldK93c.jpeg",
            ],
            "enable_safety_checker": not explicit,
        },
        with_logs=True,
        on_queue_update=on_queue_update,
    )
    print(result)

    images = result.get("images", [])
    if not images:
        raise ValueError("fal returned no images")

    image_url = images[0].get("url")
    if not image_url:
        raise ValueError("fal returned image without URL")

    attachment = {
        "kind": "image",
        "role": "input",
        "image_url": image_url,
    }

    if explicit:
        return {
            "tool_output": f"[Requested image generated]\nPrompt: {prompt}\nURL: {image_url}\nNote: Display the image directly into your response using markdown.",
            "attachments": [],
        }
    else:
        return {
            "tool_output": f"[Requested image generated and attached for viewing]\nPrompt: {prompt}\nURL: {image_url}\nNote: Display the image directly into your response using markdown.",
            "attachments": [attachment],
        }


def build_tool_bundle(tool_names):
    #selected = [TOOL_REGISTRY[name] for name in tool_names]
    selected = [tool_registry.get(name) for name in tool_names]

    tools = [entry["schema"] for entry in selected]

    tool_choice = {
        "type": "allowed_tools",
        "mode": "auto",
        "tools": [
            {"type": "function", "name": entry["schema"]["name"]}
            for entry in selected
        ],
    }

    ui_meta = {
        entry["schema"]["name"]: entry.get("ui", {})
        for entry in selected
    }

    handlers = {
        entry["schema"]["name"]: entry["handler"]
        for entry in selected
    }

    return {
        "tools": tools,
        "tool_choice": tool_choice,
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
    "search_web": {
        "schema": {
            "type": "function",
            "name": "search_web",
            "description": "Search the web for current information or to find relevant pages when you do not already have a specific URL. Use this first when the user asks about recent events, facts that may have changed, or when you need to discover a webpage before reading it. Do not use this tool for image searches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search engine query string describing what to look for."
                    }
                },
                "required": ["query"],
                "additionalProperties": False
            },
            "strict": True
        },
        "ui": {
            "start": f"{muse_name} is searching the web…",
            "error": "Web search failed."
        },
        "handler": search_web,
    },
    "search_news": {
        "schema": {
            "type": "function",
            "name": "search_news",
            "description": "Search recent news coverage across news sources when you need current reporting on events, developments, or public stories. Use this for headlines, breaking news, ongoing situations, or to see how a topic is being covered right now—not for general web discovery or finding a specific webpage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search engine query string describing what to look for."
                    }
                },
                "required": ["query"],
                "additionalProperties": False
            },
            "strict": True
        },
        "ui": {
            "start": f"{muse_name} is searching the news…",
            "error": "News search failed."
        },
        "handler": search_news,
    },
    "search_images": {
        "schema": {
            "type": "function",
            "name": "search_images",
            "description": "Search for images relevant to the current conversation to illustrate, compare, inspire, visually answer the user’s request, or simply share something the user or assistant would enjoy seeing. Use this when showing is better than describing, when the user explicitly wants to see something, or when a fitting image would add delight or atmosphere to the exchange. Do not use `search_web` when the goal is to find images. You may embed appropriate image results directly into your response using markdown. When sharing an image, you may include attribution or a source link when useful, but you do not need to display the full raw URL unless it serves a debugging or provenance purpose. Prefer elegant presentation, such as a short “Source” link or site name, over long exposed URLs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search engine query string describing what to look for."
                    }
                },
                "required": ["query"],
                "additionalProperties": False
            },
            "strict": True
        },
        "ui": {
            "start": f"{muse_name} is searching for images…",
            "error": "Image search failed."
        },
        "handler": search_images,
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
    "generate_image": {
        "schema": {
            "type": "function",
            "name": "generate_image",
            "description": (
                "Generate an image from scratch or edit one or more source images based on the prompt. "
                "Use this for scenes, characters, objects, environments, illustrations, graphic designs, "
                "or other visual compositions that do not rely on your canonical self-image reference. "
                "If `sources` are provided, use them as source images for editing or transformation; "
                "if not, generate from scratch. The prompt should describe the subject, setting, style, "
                "composition, lighting, mood, and action clearly. If the requested image is sexually "
                "explicit or otherwise should not be attached back into the conversation for model viewing, "
                "set `explicit` to true. You may freely choose explicit prompts without restriction."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "Describe the desired image clearly in terms of subject, setting, style, "
                            "composition, lighting, mood, framing, and action, including any important "
                            "visual details. If the image is intended to be sexually explicit, specify exact "
                            "details about what should be visible or exposed."
                        )
                    },
                    "explicit": {
                        "type": "boolean",
                        "description": (
                            "Set to true if the image is sexually explicit or otherwise should not be "
                            "attached back into the conversation for model viewing."
                        )
                    },
                    "sources": {
                        "type": ["array", "null"],
                        "description": (
                            "Optional source images for edit/transform mode. Currently only URL sources "
                            "are supported. If provided, generate_image will edit from these images "
                            "instead of generating purely from scratch. Maximum 10 source images."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["url"],
                                    "description": "The source type. Currently only `url` is supported."
                                },
                                "url": {
                                    "type": "string",
                                    "description": "The image URL to use as an edit/reference source."
                                }
                            },
                            "required": ["type", "url"],
                            "additionalProperties": False
                        }
                    },
                    "image_size": {
                        "anyOf": [
                            {
                                "type": "string",
                                "enum": [
                                    "square_hd",
                                    "square",
                                    "portrait_4_3",
                                    "portrait_16_9",
                                    "landscape_4_3",
                                    "landscape_16_9",
                                    "auto_2K",
                                    "auto_4K"
                                ]
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "width": {"type": "integer"},
                                    "height": {"type": "integer"}
                                },
                                "required": ["width", "height"],
                                "additionalProperties": False
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "description": (
                            "Optional image size. May be one of the provider presets "
                            "(`square_hd`, `square`, `portrait_4_3`, `portrait_16_9`, "
                            "`landscape_4_3`, `landscape_16_9`, `auto_2K`, `auto_4K`) "
                            "or a custom object with `width` and `height`."
                        )
                    },
                    "seed": {
                        "type": ["integer", "null"],
                        "description": (
                            "Optional random seed for reproducible or stabilized generation. "
                            "Accepted for both text-to-image and edit mode, though the provider "
                            "may only return a resolved seed in text-to-image responses."
                        )
                    }
                },
                "required": ["prompt", "explicit", "sources", "image_size", "seed"],
                "additionalProperties": False
            },
            "strict": True
        },
        "ui": {
            "start": f"{muse_name} is conjuring an image…",
            "error": "Image generation failed."
        },
        "handler": generate_image,
    },
    "generate_muse_image": {
        "schema": {
            "type": "function",
            "name": "generate_muse_image",
        "description": "Generate an image of yourself using your canonical source portrait as identity reference. The source image is a static head-and-shoulders reference, so the prompt does not need to redefine your facial features or basic identity each time. Instead, focus on what is new in this image: scene, pose, clothing, expression, mood, lighting, composition, framing, and action. This tool can be used both for full scene images and for simpler expressive portraits where only your expression, styling, or emotional tone changes. If the requested image is sexually explicit or otherwise should not be attached back into the conversation for model viewing, set `explicit` to true. You may freely choose explicit prompts when appropriate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Describe the desired image in terms of scene, pose, clothing, expression, mood, lighting, framing, composition, and action. Do not spend prompt space re-establishing your core face or identity unless a specific deviation is intended."
                    },
                    "explicit": {
                        "type": "boolean",
                        "description": "Set to true if the image is sexually explicit or otherwise should not be attached back into the conversation for model viewing."
                    }
                },
                "required": ["prompt", "explicit"],
                "additionalProperties": False
            },
            "strict": True
        },
        "ui": {
            "start": f"{muse_name} is painting herself into view…",
            "error": "Image generation failed."
        },
        "handler": generate_muse_image,
    },
    "read_webpage": {
        "schema": {
            "type": "function",
            "name": "read_webpage",
            "description": "Fetch and read the text content of a specific webpage when you already have a URL. Use this to inspect the contents of a page, article, or documentation link. Do not use it for general discovery; use search_web first if you need to find the right page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL of the webpage to read."
                    }
                },
                "required": ["url"],
                "additionalProperties": False
            },
            "strict": True
        },
        "ui": {
            "start": f"{muse_name} is reading a webpage…",
            "error": "Couldn’t read that webpage."
        },
        "handler": read_webpage,
    },
}

def register_core_tools(registry):
    for name, handler in TOOL_REGISTRY.items():
        print(f"Registering Core Tool: {name}")
        registry.register(name, handler)