from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env.local", override=False)

COLLEGE_API = os.getenv("COLLEGE_API_URL", "https://ht.knowvally.com").rstrip("/")
PARTICIPANT_KEY = os.getenv("KIT_PARTICIPANT_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_CHAT_MODEL = os.getenv("GROQ_CHAT_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACK_MODELS = [
    item.strip()
    for item in os.getenv(
        "GROQ_FALLBACK_MODELS", "llama-3.3-70b-versatile,llama-3.1-8b-instant"
    ).split(",")
    if item.strip()
]
GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")
GROQ_TTS_MODEL = os.getenv("GROQ_TTS_MODEL", "canopylabs/orpheus-v1-english")
GROQ_TTS_VOICE = os.getenv("GROQ_TTS_VOICE", "hannah")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
IS_VERCEL = bool(os.getenv("VERCEL"))
DATABASE_PATH = Path(
    os.getenv("DATABASE_PATH", "/tmp/kit.sqlite3" if IS_VERCEL else str(ROOT / "data" / "kit.sqlite3"))
)
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true" if IS_VERCEL else "false").lower() == "true"
SESSION_COOKIE = "kit_session"
MAX_AUDIO_BYTES = 24 * 1024 * 1024
