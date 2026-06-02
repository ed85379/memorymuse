from app.config import muse_settings
from app.core.utils import write_system_log
from app.core.muse_responder import handle_muse_decision
from app.core import prompt_profiles
from app.services.openai_client import continuity_openai_client

async def run_initiative():
    print("\nInitiative: Evaluating...")

    dev_prompt, user_assistant_messages, tool_bundle = prompt_profiles.build_initiative_prompt()

    print("Prompt built. Sending to model...")

    response = await handle_muse_decision(dev_prompt=dev_prompt, user_assistant_messages=user_assistant_messages, tool_bundle=tool_bundle, client=continuity_openai_client, model=muse_settings.get_section("llm_config").get("OPENAI_WHISPER_MODEL"), source="initiative")
    #print("Initiative prompt:", prompt)
    write_system_log(level="info", module="core", component="initiator", function="run_initiative",
                           action="initiative_response", response=response)

    print("Initiative response:", response[:200].replace("\n", " ") + ("..." if len(response) > 200 else ""))
