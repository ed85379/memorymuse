import os
import requests
import time
from elevenlabs import stream, VoiceSettings
from elevenlabs.client import ElevenLabs
from app.config import muse_settings, admin_config, AUDIO_OUTPUT_PATH


# Load ElevenLabs API credentials
ELEVEN_API_KEY = muse_settings.get_section("tts_config").get("ELEVENLABS_API_KEY")

client = ElevenLabs(
    api_key=muse_settings.get_section("tts_config").get("ELEVENLABS_API_KEY")
)

HEADERS = {
    "xi-api-key": ELEVEN_API_KEY,
    "Content-Type": "application/json"
}

def synthesize_speech(text: str, stability=0.5, similarity_boost=0.75) -> str:
    url = f"{admin_config.get_section('apis').get('TTS_API_URL')}{muse_settings.get_section('tts_config').get('ELEVENLABS_VOICE_ID')}"

    payload = {
        "text": text,
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost
        }
    }

    response = requests.post(url, json=payload, headers=HEADERS)

    if response.status_code == 200:
        os.makedirs(os.path.dirname(AUDIO_OUTPUT_PATH), exist_ok=True)
        with open(AUDIO_OUTPUT_PATH, "wb") as f:
            f.write(response.content)
        return AUDIO_OUTPUT_PATH
    else:
        raise Exception(f"ElevenLabs TTS failed: {response.status_code} {response.text}")


async def stream_speech(text: str, overrides: dict | None = None):
    started = time.monotonic()
    overrides = overrides or {}

    tts_config = muse_settings.get_section("tts_config")
    voice_id = tts_config.get("ELEVENLABS_VOICE_ID")
    model = tts_config.get("ELEVENLABS_MODEL")

    voice_stability = float(
        overrides.get("stability", tts_config.get("ELEVENLABS_VOICE_STABILITY"))
    )
    voice_similarity = float(
        overrides.get("similarity", tts_config.get("ELEVENLABS_VOICE_SIMILARITY"))
    )
    voice_speed = float(
        overrides.get("speed", tts_config.get("ELEVENLABS_VOICE_SPEED"))
    )

    print(f"Calling ElevenLabs at +{time.monotonic() - started:.3f}s")
    response = client.text_to_speech.stream(
        text=text,
        voice_id=voice_id,
        model_id=model,
        output_format="mp3_44100_128",
        voice_settings=VoiceSettings(
            stability=voice_stability,
            similarity_boost=voice_similarity,
            speed=voice_speed,
        ),
    )
    print(f"Got response object at +{time.monotonic() - started:.3f}s")

    first = True
    for chunk in response:
        if isinstance(chunk, bytes):
            if first:
                print(f"First chunk at +{time.monotonic() - started:.3f}s")
                first = False
            yield chunk