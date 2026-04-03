import json
import os

import anyio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

app = FastAPI(title="Gemini Live Audio Proxy")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "gemini-3.1-flash-live-preview"
TURN_COMPLETE_MSG = json.dumps({"type": "turn_complete"})
INTERRUPTED_MSG = json.dumps({"type": "interrupted"})

_client = genai.Client(api_key=GEMINI_API_KEY)
_live_config = types.LiveConnectConfig(
    response_modalities=[types.Modality.AUDIO],
    system_instruction=types.Content(parts=[types.Part(text="You are a helpful voice assistant. Be concise and natural.")]),
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")),
    ),
    input_audio_transcription=types.AudioTranscriptionConfig(),
    output_audio_transcription=types.AudioTranscriptionConfig(),
)


@app.websocket("/ws/audio")
async def audio_proxy(ws: WebSocket):
    """
    WebSocket endpoint for bidirectional audio streaming with Gemini Live.

    Client sends: raw 16kHz 16-bit PCM mono audio bytes
    Server sends:
      - binary frames: raw 24kHz 16-bit PCM mono audio bytes from model
      - text frames: JSON messages for transcriptions and turn events
    """
    await ws.accept()

    try:
        async with _client.aio.live.connect(model=MODEL, config=_live_config) as session:

            async def client_to_gemini():
                try:
                    while True:
                        message = await ws.receive()
                        if message.get("bytes"):
                            pcm_data = message["bytes"]
                            await session.send_realtime_input(
                                audio=types.Blob(
                                    data=pcm_data,
                                    mime_type="audio/pcm;rate=16000",
                                )
                            )
                        elif message.get("text"):
                            payload = json.loads(message["text"])
                            if "text" in payload:
                                await session.send_realtime_input(text=payload["text"])
                except WebSocketDisconnect:
                    pass

            async def gemini_to_client():
                try:
                    async for response in session.receive():
                        sc = response.server_content
                        if sc is None:
                            continue

                        if sc.model_turn and sc.model_turn.parts:
                            for part in sc.model_turn.parts:
                                if part.inline_data and part.inline_data.data:
                                    await ws.send_bytes(part.inline_data.data)

                        if sc.input_transcription:
                            await ws.send_text(
                                json.dumps(
                                    {
                                        "type": "input_transcription",
                                        "text": sc.input_transcription.text,
                                    }
                                )
                            )

                        if sc.output_transcription:
                            await ws.send_text(
                                json.dumps(
                                    {
                                        "type": "output_transcription",
                                        "text": sc.output_transcription.text,
                                    }
                                )
                            )

                        if sc.turn_complete:
                            await ws.send_text(TURN_COMPLETE_MSG)

                        if sc.interrupted:
                            await ws.send_text(INTERRUPTED_MSG)
                except WebSocketDisconnect:
                    pass

            async with anyio.create_task_group() as tg:

                async def run_then_cancel(func):
                    await func()
                    tg.cancel_scope.cancel()

                tg.start_soon(run_then_cancel, client_to_gemini)
                tg.start_soon(run_then_cancel, gemini_to_client)

    except Exception as e:
        try:
            await ws.send_text(json.dumps({"type": "error", "message": str(e)}))
            await ws.close(code=1011, reason=str(e)[:120])
        except Exception:
            pass


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
