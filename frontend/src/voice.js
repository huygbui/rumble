import { api } from './api.js';
import { requireLogin, clearToken } from './auth.js';
import { MicCapture, PlaybackQueue, pcm16BufferToFloat32 } from './audio.js';

requireLogin();

const PYTHON_WS_URL = import.meta.env.VITE_PYTHON_WS_URL;

const talkBtn  = document.getElementById('talkBtn');
const statusEl = document.getElementById('status');
const logEl    = document.getElementById('log');
const whoEl    = document.getElementById('who');
const logoutBt = document.getElementById('logoutBtn');

const log = (...args) => {
    console.log(...args);
    logEl.textContent += args.map(a =>
        typeof a === 'string' ? a : JSON.stringify(a)
    ).join(' ') + '\n';
    logEl.scrollTop = logEl.scrollHeight;
};
const setStatus = (s, cls = '') => {
    statusEl.textContent = s;
    statusEl.className = 'status' + (cls ? ' ' + cls : '');
};

// ----- Persistent state (survives token refreshes) ---------------------

const playback = new PlaybackQueue(24000);
let mic        = null;
let ws         = null;
let isPressing   = false;
let shuttingDown = false;
let reconnecting = false;

// ----- WebSocket lifecycle ---------------------------------------------

async function openWs() {
    const { ai_token } = await api.aiToken();
    log('got fresh ai_token');

    return new Promise((resolve, reject) => {
        const socket = new WebSocket(`${PYTHON_WS_URL}/ws/audio?token=${encodeURIComponent(ai_token)}`);
        socket.binaryType = 'arraybuffer';

        socket.addEventListener('open', () => {
            log('ws open');
            setStatus(isPressing ? 'talking' : 'live', isPressing ? 'talking' : 'live');
            resolve(socket);
        });

        socket.addEventListener('message', (ev) => {
            if (ev.data instanceof ArrayBuffer) {
                // Model audio @ 24 kHz
                playback.enqueue(pcm16BufferToFloat32(ev.data));
                return;
            }
            // JSON event frame
            try {
                const msg = JSON.parse(ev.data);
                switch (msg.type) {
                    case 'input_transcription':  log('You:', msg.text); break;
                    case 'output_transcription': log('AI :', msg.text); break;
                    case 'turn_complete':        /* end of turn */     break;
                    case 'interrupted':          playback.flush();      break;
                    case 'error':                log('server error:', msg.message); break;
                }
            } catch {
                /* ignore */
            }
        });

        socket.addEventListener('error', () => log('ws error'));

        socket.addEventListener('close', (e) => {
            log('ws closed', `code=${e.code}`, `reason=${e.reason || '(empty)'}`);
            ws = null;
            if (e.code === 4401) {
                // Token expired or invalid mid-session — reconnect transparently.
                if (!shuttingDown) scheduleReconnect();
            } else if (!shuttingDown) {
                scheduleReconnect();
            }
            // If we never opened, surface the failure to the awaiting promise.
            if (socket.readyState === WebSocket.CLOSED && socket.readyState !== WebSocket.OPEN) {
                reject(new Error(`closed before open (${e.code})`));
            }
        });
    });
}

async function scheduleReconnect() {
    if (reconnecting || shuttingDown) return;
    reconnecting = true;
    setStatus('reconnecting…');
    talkBtn.disabled = true;
    try {
        ws = await openWs();
        talkBtn.disabled = false;
        setStatus(isPressing ? 'talking' : 'live', isPressing ? 'talking' : 'live');
    } catch (e) {
        log('reconnect failed:', e.message || e);
        setStatus('error — retrying', 'err');
        setTimeout(() => { reconnecting = false; scheduleReconnect(); }, 1500);
        return;
    }
    reconnecting = false;
}

// ----- Mic -> WS streaming ---------------------------------------------

function sendMicChunk(buffer) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        try { ws.send(buffer); } catch { /* ignore — reconnect will catch */ }
    }
}

// ----- Boot ------------------------------------------------------------

async function boot() {
    setStatus('starting…');

    // Show user identity in the topbar.
    try {
        const me = await api.me();
        whoEl.textContent = me.email;
    } catch {
        return; // api.js already redirects on 401
    }

    mic = new MicCapture({
        sampleRate: 16000,
        onChunk: sendMicChunk,
    });

    try {
        await mic.start();
        ws = await openWs();
    } catch (e) {
        log('startup error:', e.message || e);
        setStatus('error', 'err');
        talkBtn.textContent = 'Error — reload page';
        return;
    }

    talkBtn.disabled = false;
    talkBtn.textContent = 'Hold to talk';
}

// ----- Push-to-talk button ---------------------------------------------

talkBtn.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    if (talkBtn.disabled) return;
    isPressing = true;
    talkBtn.classList.add('pressing');
    playback.flush();          // barge-in: stop AI mid-sentence
    mic?.open();
    setStatus('talking', 'talking');
});

const releasePress = () => {
    if (!isPressing) return;
    isPressing = false;
    talkBtn.classList.remove('pressing');
    mic?.close();
    if (ws) setStatus('listening for reply', 'live');
};
talkBtn.addEventListener('pointerup',     releasePress);
talkBtn.addEventListener('pointerleave',  releasePress);
talkBtn.addEventListener('pointercancel', releasePress);

logoutBt.addEventListener('click', async () => {
    shuttingDown = true;
    try { ws?.close(); } catch {}
    try { await api.logout(); } catch {}
    clearToken();
    location.href = '/';
});

window.addEventListener('beforeunload', () => {
    shuttingDown = true;
    try { ws?.close(); } catch {}
    mic?.stop();
});

boot();
