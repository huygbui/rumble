# Audio Streaming — Backend Spec

## Flow

```
User Device → Backend → AI Service (ws://<host>:8000/ws/audio) → Gemini → back
```

## WebSocket Contract with AI Service

### Send (Backend → AI)

| Frame  | Format                              |
|--------|-------------------------------------|
| Binary | Raw PCM: **16kHz**, 16-bit LE, mono |
| Text   | `{"text": "message"}` (optional)    |

Stream audio in small chunks (~100-200ms). No headers, no container — raw PCM bytes only.

### Receive (AI → Backend)

| Frame  | Format                              |
|--------|-------------------------------------|
| Binary | Raw PCM: **24kHz**, 16-bit LE, mono |
| Text   | JSON events (see below)             |

```json
{"type": "input_transcription", "text": "..."}
{"type": "output_transcription", "text": "..."}
{"type": "turn_complete"}
{"type": "interrupted"}
{"type": "error", "message": "..."}
```

## What Backend Needs To Do

1. **Transcode inbound** device audio (Opus/AAC/WebM) → PCM 16kHz 16-bit mono LE before forwarding
2. **Transcode outbound** PCM 24kHz from AI → device playback format before sending to client
3. **Relay text frames** (transcriptions/events) to client as-is or mapped to your protocol
4. **1 WS connection per user session** to AI service; close when user disconnects
5. **Plan for reconnection** — upstream Gemini sessions cap at ~10-15 min

## Notes

- Sample rates differ: **16kHz in, 24kHz out**
- VAD is handled by AI service — don't detect speech boundaries
- Health check: `GET /health`
