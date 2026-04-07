# Kids Voice — Gemini Live Demo

A 3-tier voice chat app for kids, talking to Google Gemini Live in real time.
The system is split into three independently runnable services:

| Service          | Folder         | Port  | Purpose                                                            |
| ---------------- | -------------- | ----- | ------------------------------------------------------------------ |
| **Frontend**     | `frontend/`    | 5173  | Vite + vanilla JS. Login page + push-to-talk page.                 |
| **Laravel API**  | (project root) | 8001  | User auth (Passport) and short-lived `ai_token` minting (HS256).   |
| **Python AI**    | `rumble/`      | 8000  | FastAPI WebSocket proxy that streams audio between browser and Gemini Live. |

See [docs/architecture.svg](docs/architecture.svg) for the full diagram.

---

## Prerequisites

- **PHP 8.2+** with the `sodium` extension enabled (XAMPP users: uncomment `extension=sodium` in `php.ini`)
- **Composer 2.x**
- **Python 3.14+** with [`uv`](https://docs.astral.sh/uv/) installed
- **Node.js 18+** and **npm**
- A **Gemini API key** ([get one here](https://aistudio.google.com/apikey))

---

## One-time setup

### 1. Clone and configure

```bash
git clone <repo-url> test-voice
cd test-voice
```

### 2. Generate a shared JWT secret

This secret is shared between Laravel (which mints `ai_token`) and Python (which validates it). Generate one and keep it handy:

```bash
php -r "echo bin2hex(random_bytes(32));"
```

You'll paste the output into two `.env` files below.

### 3. Set up Laravel (project root)

```bash
# Install PHP deps
composer install

# Copy env file and generate app key
cp .env.example .env
php artisan key:generate

# Generate Passport encryption keys + OAuth client
php artisan passport:install

# Create the SQLite database and run migrations + seed demo user
php artisan migrate --seed
```

Then edit [.env](.env) and set:

```env
JWT_SECRET=<paste the secret you generated above>
JWT_ISSUER=laravel
JWT_AUDIENCE=python-ai
AI_TOKEN_TTL=300
```

### 4. Set up the Python AI server

```bash
cd rumble
uv sync
```

Then create [rumble/.env](rumble/.env):

```env
GEMINI_API_KEY=<your Gemini API key>

# MUST match the JWT_SECRET in the Laravel .env exactly.
JWT_SECRET=<same secret as Laravel>
JWT_ISSUER=laravel
JWT_AUDIENCE=python-ai
```

### 5. Set up the frontend

```bash
cd ../frontend
npm install
```

The default [frontend/.env](frontend/.env) already points at the right ports — no edit needed unless you change them:

```env
VITE_LARAVEL_URL=http://127.0.0.1:8001
VITE_PYTHON_WS_URL=ws://127.0.0.1:8000
```

---

## Running the app

You'll need **three terminals** open at the same time, one per service.

**Terminal 1 — Laravel** (project root)
```bash
php artisan serve --port=8001
```

**Terminal 2 — Python AI** (from `rumble/`)
```bash
cd rumble
uv run python main.py
```

**Terminal 3 — Frontend** (from `frontend/`)
```bash
cd frontend
npm run dev
```

Then open **http://localhost:5173** in a browser that supports `getUserMedia` (Chrome, Edge, Firefox).

### Demo credentials

The seeder creates one parent user. The login form is pre-filled with these:

- **Email:** `parent@test.com`
- **Password:** `password`

After signing in you'll be sent to `/voice.html`. Allow microphone access, then **press and hold** the big circular button to talk. Release to let the AI reply.

---

## How it works

```
① POST /api/login            (email + password)
② access_token (Passport)    ← long-lived, full account scope
③ POST /api/voice/ai-token   (Bearer access_token)
④ ai_token (HS256, 5 min)    ← single-purpose, "talk to AI" only
⑤ WS ws://localhost:8000/ws/audio?token=<ai_token>
   client → server: 16 kHz PCM16 mono (binary frames)
   server → client: 24 kHz PCM16 mono (binary frames) + JSON events
```

**Key properties:**

- **Python is stateless** — it never calls Laravel and never reads the database. It validates `ai_token` entirely offline using the shared HS256 secret.
- **Two-token model** — the long-lived Passport access token never leaves the Laravel ↔ frontend boundary. Only the short-lived `ai_token` is exposed to the Python service, and a leaked `ai_token` can do nothing except open one 5-minute voice session.
- **Auto-refresh** — when the WebSocket closes (e.g. the 5-minute `ai_token` expired mid-conversation), the frontend transparently mints a new one and reconnects without disturbing the user.

---

## Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| `composer require laravel/passport` fails with `ext-sodium` missing | Enable `extension=sodium` in your `php.ini` and restart. |
| Python errors `ModuleNotFoundError: No module named 'jwt'` | Run with `uv run python main.py` (not bare `python`) so the project venv is active. If still missing, run `uv sync --reinstall-package pyjwt`. |
| Frontend login works but voice page shows `WS closed code=4401` | `JWT_SECRET` mismatch between [.env](.env) and [rumble/.env](rumble/.env), or the `ai_token` already expired. Both files must contain the **same** secret. |
| `WS closed code=1008 reason=origin not allowed` | The frontend is running on a port other than 5173. Either run it on 5173 or add your origin to `ALLOWED_ORIGINS` in [rumble/main.py](rumble/main.py) and `config/cors.php`. |
| Browser refuses microphone access | Mic API requires `https://` *or* `localhost`. A LAN IP like `192.168.x.x` will not work. |
| `php artisan migrate` complains about missing DB | The default config uses SQLite at `database/database.sqlite`. The file is created automatically by `composer create-project`; if missing, `touch database/database.sqlite` and re-run `migrate`. |

---

## Project layout

```
test-voice/
├── app/
│   ├── Http/Controllers/Api/
│   │   ├── AuthController.php     ← /api/login, /api/logout, /api/me
│   │   └── AiTokenController.php  ← /api/voice/ai-token
│   └── Services/AiTokenService.php ← mints HS256 JWTs
├── config/
│   ├── auth.php                   ← passport guard
│   ├── cors.php                   ← locked to localhost:5173
│   └── services.php               ← ai_jwt block
├── database/seeders/
│   └── DatabaseSeeder.php         ← seeds parent@test.com
├── routes/api.php                 ← API routes
│
├── rumble/                        ← Python AI server (FastAPI)
│   ├── main.py                    ← /ws/audio, /health, JWT validation
│   ├── pyproject.toml
│   └── .env                       ← GEMINI_API_KEY + JWT_SECRET
│
├── frontend/                      ← Vite + vanilla JS
│   ├── index.html                 ← login page
│   ├── voice.html                 ← push-to-talk page
│   ├── src/
│   │   ├── api.js                 ← fetch wrapper, attaches Bearer token
│   │   ├── auth.js                ← localStorage token helpers
│   │   ├── audio.js               ← MicCapture + PlaybackQueue
│   │   ├── login.js
│   │   ├── voice.js
│   │   └── style.css
│   └── .env                       ← VITE_LARAVEL_URL, VITE_PYTHON_WS_URL
│
└── docs/architecture.svg          ← system diagram
```

---

## Security notes (not production-ready as-is)

- The `/api/voice/ai-token` endpoint is **auth-gated but unrate-limited**. Add `throttle:30,1` middleware before exposing this beyond local dev.
- The `ai_token` is passed in the **WebSocket query string**, which can show up in proxy/access logs. Mitigated by short TTL (5 min) and single-purpose scope, but for production consider passing it in the first WS message instead.
- **No HTTPS in dev** is fine on `localhost`. The moment you deploy to a real domain, both Laravel and the Python WebSocket must be served over TLS or the browser will refuse microphone access.
- The seeded demo password (`password`) is for local development only. Replace before deploying.
