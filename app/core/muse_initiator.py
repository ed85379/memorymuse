# muse_initiator.py
# This handles Muse's internal thought triggers and initiative logic
from app.config import muse_settings
from app.core.utils import write_system_log
from app.core.muse_responder import handle_muse_decision
from app.core import prompt_profiles
from app.core.threads_core import apply_thread_summary
from app.services.openai_client import continuity_openai_client, get_openai_response



# <editor-fold desc="run_thread_summarization">
async def run_thread_summarization(
        thread_id: str,
):
    print("\nThread summarization starting...")

    dev_prompt, user_assistant_messages, tool_bundle, messages_meta = prompt_profiles.build_thread_summarization_prompt(
        allow_summarization=False,
        thread_id=thread_id,
        extended_history=True,
        unsummarized_only=True,
        )

    print("Prompt built. Sending to model...")
    print(f"user_assist: {user_assistant_messages}")
    print(f"messages_meta: {messages_meta}")
    response = await get_openai_response(
        dev_prompt,
        client=continuity_openai_client,
        user_assistant_messages=user_assistant_messages,
        prompt_type="summarizer",
        model=muse_settings.get_section("llm_config").get("OPENAI_WHISPER_MODEL"),
        tools=tool_bundle["tools"],
        tool_choice=tool_bundle["tool_choice"],
        handlers=tool_bundle["handlers"],
        ui_meta=tool_bundle["ui_meta"],
    )


    result = apply_thread_summary(thread_id, response, messages_meta["extended_history"])

    write_system_log(level="info", module="core", component="initiator", function="run_thread_summarization",
                           action="summarizer_response", response=response)

    print("Thread summarization response:", response[:200].replace("\n", " ") + ("..." if len(response) > 200 else ""))
    return result

# </editor-fold>


# <editor-fold desc="run_dream_gate">
def run_dream_gate():
    # Just like journaling, but goes to a separate index, and the contents are encouraged to be dream-like or fictional.
    return ""

# </editor-fold>

# <editor-fold desc="run_introspection_engine">
def run_introspection_engine():
    # Look at muse_thoughts
    # If over 7 days old and not referenced in journal/convo, delete
    # If repeated theme, promote
    # If encrypted but never used, archive
    return ""

# </editor-fold>

# <editor-fold desc="run_modality_manager">


# </editor-fold>

