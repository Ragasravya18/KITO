# Kito — KIT Voice Assistant

**A real-time voice and chat assistant for the Knotopian Institute of Technology (KIT) hackathon.** Kito answers public admissions questions and provides role-scoped services for signed-in students and teachers, using the supplied KIT API and documents as its sources.

| | |
|---|---|
| **Live app** | [kito-theta.vercel.app](https://kito-theta.vercel.app) |
| **Source** | [github.com/Ragasravya18/KITO](https://github.com/Ragasravya18/KITO) |
| **Runtime** | Python 3.12 · FastAPI · Vercel Functions |

## What evaluators can try

### Visitor mode — no account required

- Explore the KIT homepage, course catalogue, admissions guidance, campus information, and contact details.
- Ask Kito about courses, eligibility, fees, seats, dates, and application documents.
- Start an admission application. Kito gathers required details, shows a draft, and waits for confirmation before submitting it.
- Visitor requests cannot access student or teacher records.

### Student mode

- Sign in and ask about your own attendance, timetable, holidays, exam dates, college rules, requests, placements, and lesson notes where data is available.
- Prepare leave and on-duty requests. Kito checks the relevant KIT information, presents the request for review, and submits only after confirmation.
- View conversation history and manage a private personal schedule. Calendar entries are personal reminders and do not change KIT's official timetable.

### Teacher mode

- Sign in for teacher-scoped class and request information.
- Review eligible student requests through the KIT teacher services.
- Use conversation history and a private personal schedule calendar.

## Requirements coverage

| Requirement | Implementation |
|---|---|
| Voice conversation | Microphone capture with `MediaRecorder` and Web Audio silence detection; Groq Whisper transcription. Browser speech recognition is not used. |
| Spoken replies | Groq Orpheus text-to-speech with browser speech synthesis fallback. Speech can be stopped when a new message starts or the user logs out. |
| Correct, useful answers | Groq OpenAI-compatible chat models with configured model/provider fallback; live KIT data and retrieved document excerpts are supplied as evidence. Kito is instructed to answer directly and not invent missing facts. |
| Student and teacher services | KIT OpenAPI operations are loaded as tools, filtered by role, and called with the signed-in user's token. |
| Leave and on-duty requests | Write actions are drafted for user review and require explicit confirmation before submission. Idempotency keys help prevent duplicate requests. |
| Saved history | SQLite stores sessions, conversations, messages, pending actions, and personal schedule items, scoped to the account owner. See the hosting note below. |
| Public admissions | Visitor-only public catalogue and admission flows; public mode is kept separate from student records. |
| Rulebook and lesson knowledge | PDFs are extracted with PyPDF and searched using BM25 retrieval. |
| Student/teacher scheduling | Personal entries can be created, listed, and removed in the calendar or through Kito. Official KIT timetable data stays read-only. |
| Responsive interface | Vanilla HTML, CSS, and JavaScript, with light and dark themes and desktop/mobile layouts. |

## How it works

1. The browser sends text or recorded audio to the FastAPI app. Audio is transcribed with Groq Whisper; no Web Speech API recognition is used.
2. The assistant retrieves relevant KIT document passages and/or reads current data from the KIT API.
3. Role checks restrict tools before a request is made. Visitors can only use public operations; student and teacher operations require their own login token.
4. For actions that change KIT data, Kito saves a draft and waits for the user to confirm it.
5. Answers are displayed in the chat and spoken using Groq Orpheus when available, with browser speech synthesis as fallback.

## Technology

- **Frontend:** HTML, responsive CSS, vanilla JavaScript
- **Voice capture:** MediaRecorder, Web Audio API silence detection
- **Backend:** Python, FastAPI, Uvicorn, Pydantic, HTTPX
- **Speech-to-text / speech:** Groq Whisper / Groq Orpheus, browser TTS fallback
- **AI and tools:** Groq OpenAI-compatible chat API, optional OpenAI fallback, OpenAPI-derived KIT API tools
- **Document retrieval:** PyPDF and BM25
- **Storage:** SQLite for sessions, private conversation history, confirmation drafts, and personal schedule entries
- **College integration:** Supplied KIT REST API; this project consumes it and does not implement the college system
- **Hosting:** Vercel (configured) or Docker/Render

## Demo sign-ins

Use these supplied hackathon sandbox accounts. The demo password is the same for each account.

| Role | Login IDs | Password |
|---|---|---|
| Student | `arjun`, `priya`, `kavya`, `rahul`, `karthik`, `meena`, `divya`, `sneha` | `Kit@2026` |
| Teacher | `lakshmi`, `senthil` | `Kit@2026` |

These are dummy hackathon accounts. Do not use real personal data.

## Run locally on Windows

Requirements: Python 3.12+ and PowerShell.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env.local
```

Open `.env.local` and set:

- `KIT_PARTICIPANT_KEY` — your private key for the KIT sandbox.
- `GROQ_API_KEY` — required for Groq chat, Whisper transcription, and Orpheus speech.
- `OPENAI_API_KEY` — optional chat provider fallback.

Keep `.env.local` private. It is ignored by Git. Never put API keys in browser code, this README, or a public commit.

Start the server:

```powershell
uvicorn app:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) and allow microphone access to try voice input. Without a configured model key, the app has a limited local response fallback; AI voice features require a Groq key.

## Deploy

### Vercel

The GitHub repository is connected to Vercel and deploys from `master`. Configure these environment variables in the Vercel project for **Production**:

- `KIT_PARTICIPANT_KEY` — required for KIT data and services.
- `GROQ_API_KEY` — required for model chat and Groq speech services.
- `OPENAI_API_KEY` — optional model fallback.

Set `COOKIE_SECURE=true` when configuring a non-Vercel HTTPS host. Vercel sets its runtime environment automatically; the app enables secure cookies there by default. The production URL is [kito-theta.vercel.app](https://kito-theta.vercel.app).

**Storage note:** Vercel's function filesystem is temporary, and the app's default database is `/tmp/kit.sqlite3`. SQLite history and personal schedules may not survive function restarts or be shared between instances. For durable saved history, deploy with Render and attach the included persistent disk, or connect a managed database.

### Render with persistent history

Use the included `render.yaml` or Dockerfile. Configure `KIT_PARTICIPANT_KEY` and `GROQ_API_KEY` (plus optional `OPENAI_API_KEY`), and mount a persistent disk at `/var/data`. The Render blueprint sets `DATABASE_PATH=/var/data/kit.sqlite3` and `COOKIE_SECURE=true`.

## Security and reliability

- Secrets stay on the server; `.env.local`, databases, build output, and ZIP archives are excluded from Git.
- Session cookies are HTTP-only and secure on HTTPS hosting.
- Personal API operations are role-filtered and use the authenticated KIT token.
- Conversation history and schedule entries are scoped to their owner.
- Write operations require confirmation and use idempotency keys where supported.
- The model is instructed to ground answers in KIT API results and source documents and to state when information is unavailable.

## Repository map

| Path | Purpose |
|---|---|
| `app.py` | FastAPI routes for bootstrap, login/logout, chat, voice, history, schedule, requests, and action confirmation |
| `kit_app/assistant.py` | Prompting, model fallback, retrieval context, and tool-calling flow |
| `kit_app/college.py` | KIT API client, OpenAPI tool generation, authentication, and role checks |
| `kit_app/knowledge.py` | PDF downloads, text extraction, and BM25 search |
| `kit_app/storage.py` | SQLite sessions, conversations, pending requests, and personal schedules |
| `kit_app/settings.py` | Server-side environment configuration |
| `public/` | Responsive vanilla frontend and campus illustration |
| `vercel.json` | Vercel FastAPI runtime configuration |
| `render.yaml`, `Dockerfile` | Render and Docker deployment configuration |
