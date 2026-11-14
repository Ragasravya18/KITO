# Kito — KIT Voice Assistant

A voice-first assistant for Knotopian Institute of Technology. The Python/FastAPI server serves the vanilla HTML/CSS/JavaScript interface, keeps user sessions and conversation history in SQLite, grounds answers in the college API and PDFs, and uses Groq or the configured OpenAI-compatible fallback for model answers.

## Features

- Public admissions homepage with live course catalogue and visitor-only API access.
- Student and teacher sign-in through the provided KIT sandbox; private tools are scoped to the signed-in role.
- Chat and microphone capture. Browser speech recognition is not used: audio is recorded with MediaRecorder and silence detection, then sent to Groq Whisper.
- Spoken response from Groq Orpheus, with browser text-to-speech fallback.
- OpenAPI-derived college API tool schemas and role checks. Requests that change college data are shown for explicit confirmation and include an idempotency key.
- PDF text extraction and BM25 search for handbook, brochure, lessons, and other college documents.
- Per-account conversation history and request pages.
- Student and teacher personal schedule calendar: create entries by chatting with Kito or using the calendar form. The official college class timetable remains read-only and is displayed separately when KIT returns it.
- Teal/orange responsive interface based on the supplied KIT owl design.

## Run locally (Windows PowerShell)

1. Install Python 3.11 or later.
2. In this folder, create and activate a virtual environment:

   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

3. Edit your existing `.env.local` (or copy `.env.example` if it does not exist). Keep your private `KIT_PARTICIPANT_KEY`. This app can use `OPENAI_API_KEY` for text answers as a fallback, so your existing OpenAI key can power chat. Add `GROQ_API_KEY` from [Groq API Keys](https://console.groq.com/keys) to enable Groq chat fallback, Whisper transcription, and Orpheus speech. OpenAI keys do not authenticate to Groq. Keep `.env.local` private; it is excluded from Git and the ZIP. If neither model key is configured, typed answers use the limited local fallback.
4. Start the app:

   ```powershell
   uvicorn app:app --reload
   ```

5. Open <http://127.0.0.1:8000>. Allow microphone access for voice input. The provided KIT demo accounts use the hackathon credentials.

## Deploy to Render (recommended for saved SQLite history)

1. Push this folder to a public GitHub repository, excluding `.env.local`, `.venv`, databases, and ZIP files.
2. Create a Render Web Service from the repository. Use **Docker** (the included `Dockerfile`) or configure the native Python service with build command `pip install -r requirements.txt` and start command `uvicorn app:app --host 0.0.0.0 --port $PORT`.
3. Add environment variables `KIT_PARTICIPANT_KEY`, `GROQ_API_KEY`, optional `OPENAI_API_KEY`, `COOKIE_SECURE=true`, `DATABASE_PATH=/var/data/kit.sqlite3`.
4. Attach a persistent disk mounted at `/var/data` so conversation history survives service restarts. Then deploy and test login, chat, microphone, confirmation, and history on the HTTPS service URL.

## Deploy to Vercel

Vercel supports FastAPI deployments from the root `app.py`. Import the repository and add `KIT_PARTICIPANT_KEY`, `GROQ_API_KEY`, optional `OPENAI_API_KEY`, and `COOKIE_SECURE=true` as environment variables, then deploy. Vercel's serverless filesystem is temporary; this app defaults to `/tmp/kit.sqlite3` there, so SQLite history may not persist across invocations or instances. For durable history, use Render with a persistent disk or move storage to a managed database.

## Security and data notes

- Never put the college participant key or Groq key in browser JavaScript or commit them.
- The session cookie is HTTP-only and marked Secure on HTTPS deployments.
- Student/teacher API data and conversation records are isolated by the authenticated KIT identity.
- The assistant cannot submit a write action until a user confirms the displayed draft.
- This is a hackathon demo. Use only the supplied dummy KIT accounts and data.

## Main files

- `app.py` — FastAPI routes, auth, voice, history, and confirmation.
- `kit_app/college.py` — college API client, OpenAPI-derived tool schemas, role checks.
- `kit_app/assistant.py` — Groq tool-calling chat and safe fallback.
- `kit_app/knowledge.py` — PDF extraction and BM25 retrieval.
- `kit_app/storage.py` — SQLite sessions, conversations, messages, pending actions.
- `public/` — responsive vanilla web interface.
