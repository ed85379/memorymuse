# app/core/discord_client.py

from datetime import datetime, timezone
import discord
import traceback
import asyncio
import base64
import re
import websockets
import json
from app.core.utils import strip_muse_private_blocks
from app.config import WEBSOCKET_URL, muse_settings
from app.core.memory_core import log_message
from app.services.openai_client import get_openai_response, discord_openai_client
from app.core.prompt_profiles import build_discord_prompt

DISCORD_TOKEN = muse_settings.get_section("social_config").get("DISCORD_TOKEN")
PRIMARY_USER_DISCORD_ID = muse_settings.get_section("social_config").get("PRIMARY_USER_DISCORD_ID")
DISCORD_GUILD_NAME = muse_settings.get_section("social_config").get("DISCORD_GUILD_NAME")
DISCORD_CHANNEL_NAME = muse_settings.get_section("social_config").get("DISCORD_CHANNEL_NAME")


def get_user_role(author_id):
    """
    Determines the role of the Discord message author based on ID.
    """
    if str(author_id) == PRIMARY_USER_DISCORD_ID:
        return "user"
    else:
        return "friend"

# --- Setup Discord Client ---

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

client = discord.Client(intents=intents)

async def subscribe_to_broadcasts():
    async with websockets.connect(WEBSOCKET_URL) as ws:
        # Identify as Discord listener
        await ws.send(json.dumps({"listen_as": "discord"}))
        print("🔌 Subscribed to broadcast as discord")

        async for msg in ws:
            data = json.loads(msg)
            message = data.get("message", "")
            channel = await get_channel_by_name(DISCORD_GUILD_NAME, DISCORD_CHANNEL_NAME)
            if channel and message:
                await channel.send(message)


# --- Incoming Message Handler ---
async def handle_incoming_discord_message(message):
    try:
        if message.author == client.user:
            return  # Ignore Muse's own messages to prevent loops

        if message.channel.name == DISCORD_CHANNEL_NAME:
            #print(f"📥 Incoming message from {message.author}: {message.content}")

            user_input = message.content.strip()
            attachments = message.attachments  # list[discord.Attachment]

            image_attachments = [
                att for att in attachments
                if att.content_type and att.content_type.startswith("image/")
            ]

            files_payload = []
            for att in message.attachments:
                print(f"DEBUG Content_type: {att.content_type}")
                if att.content_type:
                    data = await att.read()
                    b64 = base64.b64encode(data).decode("ascii")
                    files_payload.append({
                        "name": att.filename,
                        "type": att.content_type,
                        "encoding": "base64",
                        "data": b64,
                    })


            timestamp_for_context = datetime.now(timezone.utc).isoformat()
            # Call prompt_profiles to build the prompt for the frontend UI
            #dev_prompt, system_prompt, user_prompt, ephemeral_images = build_discord_prompt(
            dev_prompt, messages, tool_bundle = build_discord_prompt(
                user_input,
                author_name=message.author.name,
                source="discord",
                timestamp=timestamp_for_context,
                ephemeral_files=files_payload,
                public=True,
            )
            # Log the incoming user message
            await log_message(
                role=get_user_role(message.author.id),
                message=user_input,
                source="discord",
                metadata={
                    "author_id": str(message.author.id),
                    "author_name": str(message.author.name),
                    "author_display_name": str(message.author.display_name),
                    "server": str(message.guild.name) if message.guild else "DM",
                    "channel": str(message.channel.name) if hasattr(message.channel, 'name') else "DM",
                    "modality_hint": "text"
                }
            )

            #print(f"USER PROMPT: {user_prompt}")
            #print(f"ATTACHMENTS: {ephemeral_images}")
            # Get Muse's response
            muse_response = await get_openai_response(
                dev_prompt,
                user_assistant_messages=messages,
                client=discord_openai_client,
                prompt_type="discord",
                tools=tool_bundle["tools"],
                tool_choice=tool_bundle["tool_choice"],
                handlers=tool_bundle["handlers"],
                ui_meta=tool_bundle["ui_meta"],
            )
            #print(messages)
            #print("🧠 Muse response generated:")
            #print(muse_response)

            # Log Muse reply
            await log_message(
                role="muse",
                message=muse_response,
                source="discord",
                metadata={
                    "author_id": str(client.user.id),
                    "author_name": str(client.user.name),
                    "author_display_name": str(client.user.display_name),
                    "server": str(message.guild.name) if message.guild else "DM",
                    "channel": str(message.channel.name) if hasattr(message.channel, 'name') else "DM",
                    "modality_hint": "text"
                }
            )
            #print("✅ Muse response logged.")
            muse_response = strip_muse_private_blocks(muse_response)
            #muse_response = re.sub(r"<muse-experience>.*?</muse-experience>", "", muse_response, flags=re.DOTALL)
            # Send reply
            await message.channel.send(muse_response)
            #print("✅ Muse response sent to Discord.")

    except Exception as e:
        print("⚠️ Exception in handle_incoming_discord_message:")
        traceback.print_exc()

async def get_channel_by_name(guild_name, channel_name):
    for guild in client.guilds:
        if guild.name == guild_name:
            for channel in guild.text_channels:
                if channel.name == channel_name:
                    return channel
    return None

async def shutdown():
    channel = await get_channel_by_name(DISCORD_GUILD_NAME, DISCORD_CHANNEL_NAME)
    if channel:
        await channel.send(f"⚫ {muse_settings.get_section('muse_config').get('MUSE_NAME')} is departing now. The connection sleeps, but memory endures.")
    await client.close()



# --- Event Hooks ---

@client.event
async def on_ready():
    print(f"🟣 {muse_settings.get_section('muse_config').get('MUSE_NAME')} connected to Discord as {client.user}.")
    channel = await get_channel_by_name(DISCORD_GUILD_NAME, DISCORD_CHANNEL_NAME)
    #if channel:
    #    await channel.send(f"🟣 {muse_settings.get_section('muse_config').get('MUSE_NAME')} is now awake in this realm.")

@client.event
async def on_message(message):
    await handle_incoming_discord_message(message)

# --- Public Start Function ---

async def start_discord_listener():
    print("🔄 Starting Discord Listener...")
    await client.start(DISCORD_TOKEN)



# --- Main Event Loop ---
async def main():
    listener_task = asyncio.create_task(start_discord_listener())
#    broadcast_task = asyncio.create_task(subscribe_to_broadcasts())

    try:
#        await asyncio.gather(listener_task, broadcast_task)
        await asyncio.gather(listener_task)
    except KeyboardInterrupt:
        print("[Discord Connector] Ctrl+C caught, shutting down...")
        await shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[Discord Connector] Stopped.")
