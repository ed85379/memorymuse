import os
import time

import httpx
import requests

from app.config import muse_settings, admin_config, AUDIO_OUTPUT_PATH


# Load ElevenLabs API credentials
ELEVEN_API_KEY = muse_settings.get_section("tts_config").get("ELEVENLABS_API_KEY")

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
    provider = (tts_config.get("TTS_PROVIDER") or "elevenlabs").lower()

    if provider == "voicestudio":
        async for chunk in stream_voicestudio_speech(
            text,
            overrides=overrides,
            started=started,
        ):
            yield chunk
        return

    if provider == "elevenlabs":
        for chunk in stream_elevenlabs_speech(
            text,
            overrides=overrides,
            started=started,
        ):
            yield chunk
        return

    raise ValueError(f"Unknown TTS provider: {provider}")

def stream_elevenlabs_speech(
    text: str,
    *,
    overrides: dict,
    started: float,
):
    from elevenlabs import VoiceSettings
    from elevenlabs.client import ElevenLabs

    tts_config = muse_settings.get_section("tts_config")

    client = ElevenLabs(
        api_key=tts_config.get("ELEVENLABS_API_KEY")
    )

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

    print(f"Got ElevenLabs response at +{time.monotonic() - started:.3f}s")

    first = True
    for chunk in response:
        if isinstance(chunk, bytes):
            if first:
                print(f"First chunk at +{time.monotonic() - started:.3f}s")
                first = False
            yield chunk


async def stream_voicestudio_speech(
    text: str,
    *,
    overrides: dict,
    started: float,
):
    tts_config = muse_settings.get_section("tts_config")

    base_url = tts_config.get(
        "VOICESTUDIO_BASE_URL",
        "http://127.0.0.1:3900",
    ).rstrip("/")

    payload = {
        "model": tts_config.get("VOICESTUDIO_MODEL", "omnivoice"),
        "input": text,
        "voice": tts_config.get("VOICESTUDIO_VOICE_ID", "default"),
        "instructions": overrides.get(
            "instructions",
            tts_config.get("VOICESTUDIO_INSTRUCTIONS", ""),
        ),
        "response_format": "mp3",
        "speed": float(
            overrides.get("speed", tts_config.get("VOICESTUDIO_SPEED", 1.0))
        ),
        "stream_format": "audio",
    }

    headers = {}
    api_key = tts_config.get("VOICESTUDIO_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    print(f"Calling VoiceStudio at +{time.monotonic() - started:.3f}s")

    first = True
    timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            f"{base_url}/v1/audio/speech",
            json=payload,
            headers=headers,
        ) as response:
            response.raise_for_status()

            print(
                f"Got VoiceStudio response at "
                f"+{time.monotonic() - started:.3f}s"
            )

            print(
                "VoiceStudio upstream:",
                response.status_code,
                response.headers.get("content-type"),
                response.headers.get("content-length"),
            )

            total_bytes = 0
            prefix = bytearray()

            async for chunk in response.aiter_bytes():
                if not chunk:
                    continue

                total_bytes += len(chunk)

                if len(prefix) < 16:
                    prefix.extend(chunk[: 16 - len(prefix)])

                if first:
                    print(
                        f"First VoiceStudio chunk at "
                        f"+{time.monotonic() - started:.3f}s "
                        f"({len(chunk)} bytes; prefix={prefix.hex()})"
                    )
                    first = False

                yield chunk

            print(
                f"VoiceStudio completed: {total_bytes} bytes; "
                f"prefix={prefix.hex()}"
            )