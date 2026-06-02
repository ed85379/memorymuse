from fastapi import APIRouter, Request, UploadFile, File, WebSocket
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from .tts_core import synthesize_speech, stream_speech
import numpy as np
import time
import traceback
from fastapi import WebSocketDisconnect
from moonshine_voice import (
    Transcriber,
    TranscriptEventListener,
    get_model_for_language,
    ModelArch,
)

tts_router = APIRouter(prefix="/api/tts", tags=["tts"])

@tts_router.post("/")
async def tts(request: Request):
    data = await request.json()
    text = data.get("text", "")
    if not text:
        return JSONResponse(status_code=400, content={"error": "No text provided"})

    try:
        path = synthesize_speech(text)
        return FileResponse(path, media_type="audio/mpeg")
    except Exception as e:
        print("TTS error:", e)
        return JSONResponse(status_code=500, content={"error": str(e)})

@tts_router.post("/stream")
async def stream_tts(request: Request):
    data = await request.json()
    text = data.get("text", "")
    if not text:
        return JSONResponse({"error": "Missing 'text' in request body"}, status_code=400)

    overrides = data.get("overrides") or {}

    async def audio_stream():
        async for chunk in stream_speech(text, overrides=overrides):
            yield chunk

    return StreamingResponse(audio_stream(), media_type="audio/mpeg")

@tts_router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    from app.services.openai_client import audio_openai_client
    try:
        audio_data = await file.read()
        with open("temp_audio.wav", "wb") as f:
            f.write(audio_data)

        with open("temp_audio.wav", "rb") as audio_file:
            transcript = audio_openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )
        return {"text": transcript.text}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

model_path, model_arch = get_model_for_language("en", ModelArch.MEDIUM_STREAMING)

class ConsoleListener(TranscriptEventListener):
    def on_line_started(self, event):
        print(f"{event.line.start_time:.2f}s: started: {event.line.text}")

    def on_line_text_changed(self, event):
        print(f"{event.line.start_time:.2f}s: changed: {event.line.text}")

    def on_line_completed(self, event):
        print(f"{event.line.start_time:.2f}s: completed: {event.line.text}")


@tts_router.websocket("/stream-moonshine")
async def moonshine_stream(websocket: WebSocket):
    start = time.monotonic()
    transcriber = None

    print("[server] handler entered t=0.0")
    await websocket.accept()
    print(f"[server] accepted t={time.monotonic() - start:.1f}s")

    try:
        config = await websocket.receive_json()
        sample_rate = config["sample_rate"]
        print(f"[server] config received t={time.monotonic() - start:.1f}s sample_rate={sample_rate}")

        transcriber = Transcriber(model_path=model_path, model_arch=model_arch)
        transcriber.remove_all_listeners()
        transcriber.add_listener(ConsoleListener())
        transcriber.start()
        print(f"[server] transcriber started t={time.monotonic() - start:.1f}s")

        chunk_count = 0
        last_log = start

        while True:
            chunk_bytes = await websocket.receive_bytes()
            chunk_count += 1

            now = time.monotonic()
            if now - last_log >= 5:
                print(f"[server] receiving audio t={now - start:.1f}s chunks={chunk_count}")
                last_log = now

            audio_int16 = np.frombuffer(chunk_bytes, dtype=np.int16)
            audio_float = audio_int16.astype(np.float32) / 32768.0

            transcriber.add_audio(audio_float.tolist(), sample_rate)

    except WebSocketDisconnect as e:
        print(f"[server] WebSocketDisconnect t={time.monotonic() - start:.1f}s code={e.code}")
    except Exception as e:
        print(f"[server] EXCEPTION t={time.monotonic() - start:.1f}s {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        print(f"[server] handler exiting t={time.monotonic() - start:.1f}s")
        if transcriber is not None:
            try:
                transcriber.stop()
                print(f"[server] transcriber stopped t={time.monotonic() - start:.1f}s")
            except Exception as e:
                print(f"[server] transcriber.stop() exception: {type(e).__name__}: {e}")

