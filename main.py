import asyncio
import json
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

app = FastAPI(title="Gemini Live Audio Proxy")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "gemini-3.1-flash-live-preview"


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

    client = genai.Client(api_key=GEMINI_API_KEY)

    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=types.Content(parts=[types.Part(text="You are a helpful voice assistant. Be concise and natural.")]),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")),
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )

    try:
        async with client.aio.live.connect(model=MODEL, config=config) as session:

            async def client_to_gemini():
                """Forward audio from WebSocket client to Gemini."""
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
                """Forward audio and events from Gemini back to WebSocket client."""
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
                            await ws.send_text(json.dumps({"type": "turn_complete"}))

                        if sc.interrupted:
                            await ws.send_text(json.dumps({"type": "interrupted"}))
                except WebSocketDisconnect:
                    pass

            await asyncio.gather(client_to_gemini(), gemini_to_client())

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
