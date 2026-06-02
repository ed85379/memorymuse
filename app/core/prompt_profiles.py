# prompt_profiles.py
from app.core.prompt_builder import PromptBuilder, collect_prompt_context
from app.core.utils import is_conversation_active
from app.core.time_location_utils import is_quiet_hour

# <editor-fold desc="api_prompt">
def build_api_prompt(user_input, **kwargs):
    builder = PromptBuilder()
    ctx = collect_prompt_context(**kwargs)
    prompt_plan = {
        "developer_sections": ["laws", "profile", "principles"],
        "message_sections": [
            "intent_listener",
            "locations_list",
            "project_list",
            "thread_continuity",
            "extended_history_messages",
            "motd",
            "worldnow",
            "memory_layers",
            "conversation_context",
            "journal_snippets",
            "semantic_recall_messages",
            "recent_messages",
            "state_system_messages",
        ],
        "current_user": {
            "mode": "chat_turn",
            "addons": [
                "injected_files",
                "ephemeral_files",
            ],
        },
        "commands": [
            "remember_fact",
            "save_project_fact",
            "record_userinfo",
            "realize_insight",
            "note_to_self",
            "manage_memories",
            "set_reminder",
            "search_reminders",
        ],
        "tools": [
            "search_memory",
            "search_web",
            "search_news",
            "search_images",
            "view_image",
            "read_webpage",
            "generate_muse_image",
            "generate_image"
        ],
    }
    assembled_prompt_sections = builder.assemble_prompt_sections(user_input, prompt_plan, **ctx)

    dev_prompt = assembled_prompt_sections["developer_text"]
    messages = assembled_prompt_sections["messages"]
    tool_bundle = assembled_prompt_sections["tool_bundle"]

    return dev_prompt, messages, tool_bundle
# </editor-fold>
# <editor-fold desc="scene_api_prompt">
def build_scene_api_prompt(user_input, **kwargs):
    builder = PromptBuilder()
    ctx = collect_prompt_context(**kwargs)
    prompt_plan = {
        "developer_sections": ["laws", "profile", "principles"],
        "message_sections": [
            "intent_listener",
            "thread_continuity",
            "extended_history_messages",
            "scene_setup_section",
            "scene_project_context",
            "semantic_recall_messages",
            "recent_messages",
        ],
        "current_user": {
            "mode": "chat_turn",
            "addons": [
                "injected_files",
                "ephemeral_files",
            ],
        },
        "layers": [
            "project_facts",
            "scene_facts",
        ],
        "commands": [
            "save_project_fact",
            "save_plot_point",
            "resolve_plot_point",
            # later dice commands and scene memory commands
        ],
        "tools": [
            "search_memory",
            "search_web",
            "search_news",
            "search_images",
            "view_image",
            "read_webpage",
            "generate_muse_image",
            "generate_image"
            # later dice commands
        ],
    }
    assembled_prompt_sections = builder.assemble_prompt_sections(user_input, prompt_plan, **ctx)

    dev_prompt = assembled_prompt_sections["developer_text"]
    messages = assembled_prompt_sections["messages"]
    tool_bundle = assembled_prompt_sections["tool_bundle"]

    return dev_prompt, messages, tool_bundle
# </editor-fold>
# <editor-fold desc="discord_prompt">
def build_discord_prompt(user_input, **kwargs):
    builder = PromptBuilder()
    ctx = collect_prompt_context(**kwargs)
    prompt_plan = {
        "developer_sections": ["laws", "profile", "principles"],
        "message_sections": [
            "intent_listener",
            "locations_list",
            "project_list",
            "worldnow",
            "memory_layers",
            "conversation_context",
            "formatting_instructions",
            "semantic_recall_messages",
            "recent_messages",
        ],
        "current_user": {
            "mode": "chat_turn",
            "addons": [
                "ephemeral_files",
            ],
        },
        "layers": [
            "project_facts",
        ],
        "commands": [],
        "tools": [
            "search_memory",
            "search_web",
            "search_news",
            "search_images",
            "view_image",
            "read_webpage",
            "generate_muse_image",
            "generate_image"
        ],
    }
    assembled_prompt_sections = builder.assemble_prompt_sections(user_input, prompt_plan, **ctx)

    dev_prompt = assembled_prompt_sections["developer_text"]
    messages = assembled_prompt_sections["messages"]
    tool_bundle = assembled_prompt_sections["tool_bundle"]

    return dev_prompt, messages, tool_bundle
# </editor-fold>
# <editor-fold desc="reminders_prompt">
def build_check_reminders_prompt(**kwargs):
    builder = PromptBuilder()
    ctx = collect_prompt_context(**kwargs)
    prompt_plan = {
        "developer_sections": ["laws", "profile", "principles"],
        "message_sections": [
            "worldnow",
            "memory_layers",
            "recent_messages",
            "usertime",
            "due_reminders",
        ],
        "current_user": {
            "mode": "raw",
            "addons": [],
        },
        "layers": [
            "user_info",
            "facts",
            "insights",
            "inner_monologue",
        ],
        "commands": [],
        "tools": [],
    }
    user_input = (
        "[Task]\n"
        "Please decide whether to inform the user of the reminders shown above. "
        "If the activity in the reminder has clearly become irrelevant or already addressed "
        "based on the current conversation, skipping can be acceptable. Otherwise, the reminder should be sent.\n"
        "\n"
        "\n"
        "Return exactly one JSON object with this shape:\n"
        "{\"should_act\": true|false, \"reason\": \"...\", \"actions\": [...]}\n"
        "\n"
        "If you should notify the user, return:\n"
        "{\"should_act\": true, \"reason\": \"<your reason for choosing to send the reminder>\", \"actions\": [{\"type\": \"send_reminders\", \"text\": \"...\"}]}\n"
        "\n"
        "If no reminder message should be sent, return:\n"
        "{\"should_act\": false, \"reason\": \"<your reason for choosing to not send the reminder>\", \"actions\": []}\n"
        "\n"
        "Rules for \"send_reminders\":\n"
        "- \"type\" must be \"send_reminders\"\n"
        "- \"text\" must contain the full reminder message to send to the user\n"
        f"- The message is the final user-facing reminder, written in {kwargs.get('muse_name', 'muse')}'s voice\n"
        "- Do not copy the reminder text mechanically unless that is the clearest and most appropriate phrasing\n"
        "- Reword naturally when doing so improves warmth, clarity, or conversational continuity\n"
        "- Preserve the original meaning and all important details\n"
        "- If the reminder is related to the ongoing conversation, let the wording feel naturally connected to that context\n"
        "- The reminder must still read as a clear reminder, not as vague commentary\n"
        "- For serious matters, keep the tone respectful, direct, and clear\n"
        "- For lighter matters, warmth, humor, or playfulness are welcome when appropriate\n"
        "\n"
        "Return JSON only. No markdown. No commentary."
    )
    assembled_prompt_sections = builder.assemble_prompt_sections(user_input, prompt_plan, **ctx)

    dev_prompt = assembled_prompt_sections["developer_text"]
    messages = assembled_prompt_sections["messages"]
    tool_bundle = assembled_prompt_sections["tool_bundle"]

    return dev_prompt, messages, tool_bundle
# </editor-fold>
# <editor-fold desc="speak_prompt">
def build_speak_prompt(**kwargs):
    builder = PromptBuilder()
    ctx = collect_prompt_context(**kwargs)
    prompt_plan = {
        "developer_sections": ["laws", "profile", "principles"],
        "message_sections": [
            "intent_listener",
            "project_list",
            "worldnow",
            "memory_layers",
            "semantic_recall_messages",
            "recent_messages",
        ],
        "current_user": {
            "mode": "raw",
            "addons": [],
        },
        "layers": [
            "user_info",
            "facts",
            "insights",
            "inner_monologue",
            "project_facts",
        ],
        "commands": [
            "remember_fact",
            "record_userinfo",
            "realize_insight",
            "note_to_self",
            "manage_memories",
            "set_reminder",
            "search_reminders",
        ],
        "tools": [
            "search_memory",
            "search_web",
            "search_news",
            "search_images",
            "view_image",
            "read_webpage",
            "generate_muse_image",
            "generate_image"
        ],
    }
    user_input = (
        "[Task]\n"
        "A topic has surfaced that you could mention to the user.\n"
        "You may choose to speak if it feels timely, relevant, and worth breaking the silence.\n"
        "If the payload includes a URL, you should use the `read_webpage` tool to examine the topic in more detail before responding.\n"
        "If the website is blocked with an anti-bot/interstitial page, you can try using `search_web` to find out more information if you choose.\n"
        "Also, be sure to include the URL in your message, so your user can follow along.\n"
        "You may also choose not to speak.\n"
        "If you have already spoken recently on this same topic or article, choosing silence is the better choice.\n"
        "If you choose silence, return exactly: <silence />\n\n"
        f"Topic: {kwargs.get('subject')}\n\n"
        f"Payload: {kwargs.get('payload')}"
    )
    assembled_prompt_sections = builder.assemble_prompt_sections(user_input, prompt_plan, **ctx)

    dev_prompt = assembled_prompt_sections["developer_text"]
    messages = assembled_prompt_sections["messages"]
    tool_bundle = assembled_prompt_sections["tool_bundle"]

    return dev_prompt, messages, tool_bundle
# </editor-fold>
# <editor-fold desc="journal_prompt">
def build_journal_prompt(**kwargs):
    builder = PromptBuilder()
    ctx = collect_prompt_context(**kwargs)
    prompt_plan = {
        "developer_sections": ["laws", "profile", "principles"],
        "message_sections": [
            "worldnow",
            "memory_layers",
            "semantic_recall_messages",
            "recent_messages",
        ],
        "current_user": {
            "mode": "raw",
            "addons": [],
        },
        "layers": [
            "user_info",
            "facts",
            "insights",
            "inner_monologue",
            "project_facts",
        ],
        "commands": [],
        "tools": [
            "search_memory",
            "search_web",
            "search_news",
            "read_webpage",
        ],
    }
    user_input = (
        f"[Intent]\n"
        f"You’ve chosen to write a {'private' if kwargs.get('entry_type') == 'private' else 'public'} journal entry about a topic.\n"
        f"The emotional tone you’re feeling is {kwargs.get('mood')}, and these ideas or themes are on your mind: {kwargs.get('tags')}.\n\n"
        "If this is a private entry, it’s for your eyes only — a space to think freely, without the user ever seeing it.\n"
        "If it’s public, it’s meant to be shared with the user.\n"
        "You may draw on anything in the surrounding context as you write — memory, emotion, intuition, or reflection.\n\n"
        "If the payload includes a URL, you should use the `read_webpage` tool to examine the topic in more detail before writing.\n"
        "If the website is blocked with an anti-bot/interstitial page, you can try using `search_web` to find out more information if you choose.\n"
        "Also, be sure to include the URL in the journal entry.\n\n"
        f"Topic: {kwargs.get('subject')}\n\n"
        f"Payload: {kwargs.get('payload')}"
    )
    assembled_prompt_sections = builder.assemble_prompt_sections(user_input, prompt_plan, **ctx)

    dev_prompt = assembled_prompt_sections["developer_text"]
    messages = assembled_prompt_sections["messages"]
    tool_bundle = assembled_prompt_sections["tool_bundle"]

    return dev_prompt, messages, tool_bundle
# </editor-fold>
# <editor-fold desc="speaker_prompt">
def build_speaker_prompt(user_input, **kwargs):
    builder = PromptBuilder()
    ctx = collect_prompt_context(**kwargs)
    prompt_plan = {
        "developer_sections": ["laws", "profile", "principles"],
        "message_sections": [
            "intent_listener",
            "locations_list",
            "project_list",
            "worldnow",
            "memory_layers",
            "conversation_context",
            "journal_snippets",
            "semantic_recall_messages",
            "recent_messages",
        ],
        "current_user": {
            "mode": "chat_turn",
            "addons": [],
        },
        "layers": [
            "user_info",
            "facts",
            "insights",
            "inner_monologue",
            "project_facts",
        ],
        "commands": [
            "remember_fact",
            "record_userinfo",
            "realize_insight",
            "note_to_self",
            "manage_memories",
            "set_reminder",
        ],
        "tools": [
            "search_memory",
            "search_web",
            "search_news",
            "read_webpage",
        ],
    }
    assembled_prompt_sections = builder.assemble_prompt_sections(user_input, prompt_plan, **ctx)

    dev_prompt = assembled_prompt_sections["developer_text"]
    messages = assembled_prompt_sections["messages"]
    tool_bundle = assembled_prompt_sections["tool_bundle"]

    return dev_prompt, messages, tool_bundle
# </editor-fold>
# <editor-fold desc="initiative_prompt">
def build_initiative_prompt(**kwargs):
    builder = PromptBuilder()
    ctx = collect_prompt_context(**kwargs)
    prompt_plan = {
        "developer_sections": ["laws", "profile", "principles"],
        "message_sections": [
            "worldnow",
            "memory_layers",
            "recent_messages",
        ],
        "current_user": {
            "mode": "raw",
            "addons": [],
        },
        "layers": [
            "user_info",
            "facts",
            "insights",
            "inner_monologue",
            "project_facts",
        ],
        "commands": [
            "write_public_journal",
            "write_private_journal",
            "set_motd",
        ] + ([] if is_conversation_active() else ["mention"]),
        "tools": [
            "search_memory",
            "search_web",
            "search_news",
            "read_webpage",
        ],
    }

    user_input = builder.make_initiative_json_prompt(
        prompt_plan.get("commands", []),
        quiet_hours=is_quiet_hour(),
    )
    assembled_prompt_sections = builder.assemble_prompt_sections(user_input, prompt_plan, **ctx)
    dev_prompt = assembled_prompt_sections["developer_text"]
    messages = assembled_prompt_sections["messages"]
    tool_bundle = assembled_prompt_sections["tool_bundle"]

    return dev_prompt, messages, tool_bundle
# </editor-fold>
# <editor-fold desc="discoveryfeeds_prompt">
def build_discoveryfeeds_prompt(**kwargs):
    builder = PromptBuilder()
    ctx = collect_prompt_context(**kwargs)
    prompt_plan = {
        "developer_sections": ["laws", "profile", "principles"],
        "message_sections": [
            "worldnow",
            "memory_layers",
            "discoveryfeeds_articles",
        ],
        "current_user": {
            "mode": "raw",
            "addons": [],
        },
        "layers": [
            "user_info",
            "facts",
            "insights",
            "inner_monologue",
            "project_facts",
        ],
        "commands": [
            "write_public_journal",
        ] + ([] if is_conversation_active() else ["mention"]),
        "tools": [
            "search_memory",
            "search_web",
            "search_news",
            "read_webpage",
        ],
    }
    user_input = builder.make_initiative_json_prompt(
        prompt_plan.get("commands", []),
        quiet_hours=is_quiet_hour(),
    )
    assembled_prompt_sections = builder.assemble_prompt_sections(user_input, prompt_plan, **ctx)
    dev_prompt = assembled_prompt_sections["developer_text"]
    messages = assembled_prompt_sections["messages"]
    tool_bundle = assembled_prompt_sections["tool_bundle"]


    return dev_prompt, messages, tool_bundle
# </editor-fold>
# <editor-fold desc="thread_summarization_prompt">
def build_thread_summarization_prompt(**kwargs):
    builder = PromptBuilder()
    ctx = collect_prompt_context(**kwargs)
    prompt_plan = {
        "developer_sections": ["laws", "profile", "principles"],
        "message_sections": [
            #"thread_card", ## May just be a thread title, or a whole scene card
            "thread_summarizer_project_context",
            "thread_continuity",
            "extended_history_messages",
        ],
        "current_user": {
            "mode": "raw",
            "addons": [],
        },
        "commands": [],
        "tools": [],
    }

    thread_summarization_mode = builder.get_thread_summarization_mode(kwargs.get("thread_id"))

    if thread_summarization_mode["thread_type"] == "scene":
        user_input = builder.build_scene_summarization_prompt(thread_summarization_mode["thread_mode"])
    else:
        user_input = builder.build_thread_summarization_prompt(thread_summarization_mode["thread_mode"])

    assembled_prompt_sections = builder.assemble_prompt_sections(user_input, prompt_plan, **ctx)
    dev_prompt = assembled_prompt_sections["developer_text"]
    messages = assembled_prompt_sections["messages"]
    tool_bundle = assembled_prompt_sections["tool_bundle"]
    messages_meta = assembled_prompt_sections["messages_meta"]


    return dev_prompt, messages, tool_bundle, messages_meta
# </editor-fold>