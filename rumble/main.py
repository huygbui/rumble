import json
import logging
import os

import anyio
import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types

from converter import OpusPacketDecoder, OpusPacketEncoder

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

MODEL = "gemini-3.1-flash-live-preview"
TURN_COMPLETE_MSG = json.dumps({"type": "turn_complete"})
INTERRUPTED_MSG = json.dumps({"type": "interrupted"})

# JWT_SECRET = os.environ["JWT_SECRET"]
# JWT_ISSUER = os.environ.get("JWT_ISSUER", "laravel")
# JWT_AUDIENCE = os.environ.get("JWT_AUDIENCE", "python-ai")
# ALLOWED_ORIGINS = [
#     "http://localhost:5173",
#     "http://127.0.0.1:5173",
# ]

app = FastAPI(title="Gemini Live Audio")

# # CORS only matters for /health (HTTP). WebSockets are not subject to CORS,
# # but we explicitly check the Origin header on /ws/audio below as a defense.
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=ALLOWED_ORIGINS,
#     allow_credentials=False,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

_client = genai.Client()
_live_config = types.LiveConnectConfig(
    response_modalities=[types.Modality.AUDIO],
    system_instruction=types.Content(parts=[types.Part(text="You are a helpful voice assistant. Be concise and natural.")]),
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")),
    ),
    realtime_input_config=types.RealtimeInputConfig(
        automatic_activity_detection=types.AutomaticActivityDetection(
            start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
            end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
        ),
    ),
    input_audio_transcription=types.AudioTranscriptionConfig(),
    output_audio_transcription=types.AudioTranscriptionConfig(),
)


def _decode_input_audio(
        frame_data: bytes,
        input_codec: str,
        opus_decoder: OpusPacketDecoder | None,
) -> bytes:
    if input_codec == "pcm" or input_codec is None:
        return frame_data
    if input_codec == "opus":
        if opus_decoder is None:
            raise RuntimeError("Opus decoder is not initialized")
        return opus_decoder.decode_packet(frame_data)
    raise RuntimeError(f"unsupported input codec: {input_codec}")

def _encode_output_audio(
        pcm_data: bytes,
        output_codec: str,
        opus_encoder: OpusPacketEncoder | None,
) -> list[bytes]:
    if output_codec == "pcm" or output_codec is None:
        return [pcm_data] if pcm_data else []
    if output_codec == "opus":
        if opus_encoder is None:
            raise RuntimeError("Opus encoder is not initialized")
        return opus_encoder.encode_chunk(pcm_data)
    raise RuntimeError(f"unsupported output codec: {output_codec}")


# def _validate_ai_token(token: str) -> dict:
#     """
#     Self-contained validation of the ai_token minted by Laravel.
#     Raises jwt.PyJWTError on any failure (expired, bad signature, wrong
#     issuer/audience). The caller closes the WebSocket on exception.
#     """
#     return jwt.decode(
#         token,
#         JWT_SECRET,
#         algorithms=["HS256"],
#         issuer=JWT_ISSUER,
#         audience=JWT_AUDIENCE,
#         options={"require": ["exp", "iat", "sub", "iss", "aud"]},
#     )


@app.websocket("/ws/audio")
async def audio_proxy(ws: WebSocket):
    """
    WebSocket endpoint for bidirectional audio streaming with Gemini Live.

    Auth: ai_token JWT passed as ?token=... query param. Token is minted by
    Laravel (HS256, 5-min TTL) and validated here against the shared secret.

    Wire format:
      Client -> Server: binary frames, raw 16kHz 16-bit PCM mono
      Server -> Client:
        - binary frames: raw 24kHz 16-bit PCM mono from the model
        - text frames:   JSON {type, text} for transcripts and turn events
    """
    # # 1) Validate origin (defense in depth — WS isn't subject to CORS).
    # origin = ws.headers.get("origin")
    # if origin and origin not in ALLOWED_ORIGINS:
    #     await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="origin not allowed")
    #     return

    # # 2) Validate the ai_token.
    # token = ws.query_params.get("token")
    # if not token:
    #     await ws.close(code=4401, reason="missing token")
    #     return
    # try:
    #     claims = _validate_ai_token(token)
    # except jwt.ExpiredSignatureError:
    #     await ws.close(code=4401, reason="token expired")
    #     return
    # except jwt.PyJWTError as e:
    #     logger.warning("ai_token validation failed: %s", e)
    #     await ws.close(code=4401, reason="invalid token")
    #     return

    # user_id = claims["sub"]
    # logger.info("WS accepted for user sub=%s", user_id)

    user_id = "You" # TODO: change later
    await ws.accept()

    try:
        input_codec = ws.query_params.get("input_codec", "pcm").lower()
        output_codec = ws.query_params.get("output_codec", "pcm").lower()
        if input_codec not in {"pcm", "opus"}:
            raise RuntimeError(f"unsupported input codec: {input_codec}") 
        if output_codec not in {"pcm", "opus"}:
            raise RuntimeError(f"unsupported output codec: {output_codec}")
        opus_decoder = OpusPacketDecoder() if input_codec == "opus" else None
        opus_encoder = OpusPacketEncoder() if output_codec == "opus" else None

        async with _client.aio.live.connect(model=MODEL, config=_live_config) as session:

            async def client_to_gemini():
                try:
                    while True:
                        message = await ws.receive()
                        if message.get("types") == "websocket.disconnect":
                            break
                        if message.get("bytes"):
                            frame_data = message["bytes"]
                            logger.debug("[rx] binary frame: codec=%s size=%d bytes hex_head=%s", input_codec, len(frame_data), frame_data[:8].hex())
                            try:
                                pcm_data = _decode_input_audio(frame_data, input_codec, opus_decoder)
                            except Exception as e:
                                logger.warning("input audio decode error (skipping frame): %s", e)
                                continue

                            if not pcm_data:
                                continue
                            logger.debug("[tx->gemini] audio packet: pcm_bytes=%d", len(pcm_data))
                            await session.send_realtime_input(
                                audio=types.Blob(
                                    data=pcm_data,
                                    mime_type="audio/pcm;rate=16000",
                                )
                            )
                        elif message.get("text"):
                            raw_text = message["text"]
                            logger.debug("[rx] text message: %s", raw_text[:200])
                            try:
                                payload = json.loads(raw_text)
                            except json.JSONDecodeError as e:
                                logger.warning("invalid client JSON payload: %s", e)
                                continue

                            if "text" in payload:
                                logger.debug("[tx->gemini] text input: %s", payload["text"][:200])
                                await session.send_realtime_input(text=payload["text"])
                except WebSocketDisconnect:
                    pass

            async def gemini_to_client():
                try:
                    while True:
                        async for response in session.receive():
                            sc = response.server_content
                            if sc is None:
                                continue

                            logger.debug(
                                "[rx<-gemini] server_content: turn_complete=%s interrupted=%s has_model_turn=%s",
                                getattr(sc, "turn_complete", False),
                                getattr(sc, "interrupted", False),
                                sc.model_turn is not None,
                            )

                            if sc.model_turn and sc.model_turn.parts:
                                for part in sc.model_turn.parts:
                                    if part.inline_data and part.inline_data.data:
                                        pcm_bytes = len(part.inline_data.data)
                                        logger.debug("[rx<-gemini] audio part: pcm_bytes=%d mime=%s", pcm_bytes, part.inline_data.mime_type)
                                        output_frames = _encode_output_audio(
                                            part.inline_data.data,
                                            output_codec,
                                            opus_encoder
                                        )
                                        for output_frame in output_frames:
                                            logger.debug("[tx->client] audio frame: codec=%s size=%d bytes", output_codec, len(output_frame))
                                            await ws.send_bytes(output_frame)

                            if sc.input_transcription:
                                logger.info("[%s] User said: %s", user_id, sc.input_transcription.text)
                                await ws.send_text(
                                    json.dumps(
                                        {
                                            "type": "input_transcription",
                                            "text": sc.input_transcription.text,
                                        }
                                    )
                                )

                            if sc.output_transcription:
                                logger.info("[%s] AI said: %s", user_id, sc.output_transcription.text)
                                await ws.send_text(
                                    json.dumps(
                                        {
                                            "type": "output_transcription",
                                            "text": sc.output_transcription.text,
                                        }
                                    )
                                )

                            if sc.turn_complete:
                                logger.debug("[tx->client] turn_complete")
                                await ws.send_text(TURN_COMPLETE_MSG)

                            if sc.interrupted:
                                logger.debug("[tx->client] interrupted")
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
        logger.exception("audio_proxy error")
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
