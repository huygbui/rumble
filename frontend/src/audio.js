// Audio plumbing for the voice page. The Python proxy uses raw binary
// frames (no base64), so we send/receive Int16 PCM directly.
//
//   Mic capture: 16 kHz mono PCM16 (sent as binary)
//   Playback:    24 kHz mono PCM16 (received as ArrayBuffer)
//
// The playback queue schedules buffers contiguously on a single AudioContext
// so chunks don't overlap.

export function float32ToPcm16(float32) {
    const pcm16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
        let s = Math.max(-1, Math.min(1, float32[i]));
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return pcm16;
}

export function pcm16BufferToFloat32(arrayBuffer) {
    const view = new DataView(arrayBuffer);
    const out  = new Float32Array(arrayBuffer.byteLength / 2);
    for (let i = 0; i < out.length; i++) {
        out[i] = view.getInt16(i * 2, true) / 0x8000;
    }
    return out;
}

export class PlaybackQueue {
    constructor(sampleRate = 24000) {
        this.sampleRate = sampleRate;
        this.ctx = null;
        this.nextTime = 0;
    }

    enqueue(float32) {
        if (!this.ctx) {
            this.ctx = new AudioContext({ sampleRate: this.sampleRate });
            this.nextTime = this.ctx.currentTime;
        }
        const buffer = this.ctx.createBuffer(1, float32.length, this.sampleRate);
        buffer.copyToChannel(float32, 0);
        const src = this.ctx.createBufferSource();
        src.buffer = buffer;
        src.connect(this.ctx.destination);
        const startAt = Math.max(this.nextTime, this.ctx.currentTime);
        src.start(startAt);
        this.nextTime = startAt + buffer.duration;
    }

    flush() {
        if (this.ctx) this.nextTime = this.ctx.currentTime;
    }
}

export class MicCapture {
    constructor({ sampleRate = 16000, onChunk } = {}) {
        this.sampleRate = sampleRate;
        this.onChunk = onChunk;
        this.stream = null;
        this.ctx = null;
        this.source = null;
        this.node = null;
        this.gateOpen = false;
    }

    async start() {
        this.stream = await navigator.mediaDevices.getUserMedia({
            audio: {
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
            },
        });
        this.ctx    = new AudioContext({ sampleRate: this.sampleRate });
        this.source = this.ctx.createMediaStreamSource(this.stream);
        // ScriptProcessorNode is deprecated but trivial. Fine for a demo.
        this.node = this.ctx.createScriptProcessor(4096, 1, 1);
        this.node.onaudioprocess = (ev) => {
            if (!this.gateOpen) return;
            const input = ev.inputBuffer.getChannelData(0);
            const pcm16 = float32ToPcm16(input);
            this.onChunk?.(pcm16.buffer);
        };
        this.source.connect(this.node);
        this.node.connect(this.ctx.destination); // required for the node to fire
    }

    open()  { this.gateOpen = true; }
    close() { this.gateOpen = false; }

    stop() {
        try { this.node?.disconnect(); } catch {}
        try { this.source?.disconnect(); } catch {}
        try { this.ctx?.close(); } catch {}
        if (this.stream) this.stream.getTracks().forEach(t => t.stop());
    }
}
