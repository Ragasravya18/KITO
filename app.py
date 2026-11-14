from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import date, time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from kit_app.assistant import engine
from kit_app.college import college
from kit_app.knowledge import knowledge
from kit_app.settings import COOKIE_SECURE, GROQ_API_KEY, GROQ_STT_MODEL, GROQ_TTS_MODEL, GROQ_TTS_VOICE, MAX_AUDIO_BYTES, OPENAI_API_KEY, PARTICIPANT_KEY, SESSION_COOKIE
from kit_app.storage import Store
from kit_app.settings import DATABASE_PATH

store = Store(DATABASE_PATH)
engine.store = store
PUBLIC = Path(__file__).parent / "public"


@asynccontextmanager
async def lifespan(_app):
    yield


app = FastAPI(title="Kito KIT Voice Assistant", version="1.0", lifespan=lifespan)


def current_session(request: Request, require_login: bool = False):
    session = store.get_session(request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise HTTPException(401, "Your session expired. Please refresh or sign in again.")
    if require_login and session["role"] == "visitor":
        raise HTTPException(401, "Please sign in to access student services.")
    return session


def set_cookie(response, session):
    response.set_cookie(SESSION_COOKIE, session["sid"], httponly=True, secure=COOKIE_SECURE, samesite="lax", max_age=60 * 60 * 24 * 30, path="/")


@app.middleware("http")
async def visitor_cookie(request: Request, call_next):
    session, is_new = store.ensure_visitor(request.cookies.get(SESSION_COOKIE))
    request.state.kit_session = session
    response = await call_next(request)
    if is_new and (not request.url.path.startswith("/api/") or request.url.path == "/api/bootstrap"):
        set_cookie(response, session)
    return response


class LoginBody(BaseModel):
    login_id: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class ChatBody(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    conversation_id: str | None = None


class ConfirmBody(BaseModel):
    confirmed: bool = True


class EditActionBody(BaseModel):
    arguments: dict[str, Any]


class ScheduleBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    date: date
    start_time: time
    end_time: time
    notes: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def valid_times(self):
        if self.end_time <= self.start_time:
            raise ValueError("End time must be after start time.")
        return self


async def safe_public_bootstrap():
    data = {"college": {}, "courses": [], "today": {}}
    async def get(path):
        try: return await college.request("GET", path)
        except Exception: return None
    results = await asyncio.gather(get("/v1/college"), get("/v1/courses"), get("/v1/today"))
    for key, value in zip(("college", "courses", "today"), results):
        if value is not None: data[key] = value
    return data


@app.get("/api/health")
async def health():
    return {"ok": True, "kit_configured": bool(PARTICIPANT_KEY), "groq_configured": bool(GROQ_API_KEY), "llm_configured": bool(GROQ_API_KEY or OPENAI_API_KEY), "speech": "groq with browser tts fallback"}


@app.get("/api/bootstrap")
async def bootstrap(request: Request):
    session = store.get_session(request.cookies.get(SESSION_COOKIE)) or request.state.kit_session
    public = await safe_public_bootstrap()
    return {**public, "user": session.get("user"), "role": session["role"], "authenticated": session["role"] != "visitor"}


@app.post("/api/login")
async def login(body: LoginBody):
    try:
        result = await college.login(body.login_id, body.password)
    except Exception as exc:
        raise HTTPException(401, str(exc)) from exc
    token = result.get("access_token") or result.get("token")
    user = result.get("user") or {"login_id": body.login_id}
    user.setdefault("login_id", body.login_id)
    if not token: raise HTTPException(502, "The college login did not return a session token.")
    role = str(user.get("role", "student")).lower()
    if "teacher" in role or "faculty" in role: user["role"] = "teacher"
    else: user["role"] = "student"
    session = store.create_user_session(user, token, int(result.get("expires_in", 28800)))
    response = JSONResponse({"ok": True, "user": user, "role": user["role"]})
    set_cookie(response, session)
    return response


@app.post("/api/logout")
async def logout(request: Request):
    store.delete_session(request.cookies.get(SESSION_COOKIE))
    session, _ = store.ensure_visitor(None)
    response = JSONResponse({"ok": True})
    set_cookie(response, session)
    return response


@app.post("/api/assistant")
async def chat(body: ChatBody, request: Request):
    session = current_session(request)
    text = body.text.strip()
    if not text: raise HTTPException(400, "Please say or type a question.")
    if body.conversation_id and store.owns_conversation(session["owner_key"], body.conversation_id):
        conversation_id = body.conversation_id
    else:
        conversation_id = store.create_conversation(session["owner_key"], text)
    store.save_message(session["owner_key"], conversation_id, "user", text)
    history = store.get_messages(session["owner_key"], conversation_id, limit=14)
    session["_conversation"] = conversation_id
    session.pop("_pending_action", None)
    try:
        answer, trace, docs, pending = await engine.answer(text, session, history[:-1])
    except Exception:
        answer, trace, docs, pending = "I couldn’t reach the KIT services just now. Please try again in a moment.", [], [], None
    store.save_message(session["owner_key"], conversation_id, "assistant", answer, {"trace": trace, "pending": pending})
    return {"answer": answer, "conversation_id": conversation_id, "steps": trace, "sources": [{"title": d["title"]} for d in docs[:2]], "pending_action": pending}


@app.get("/api/history")
async def history(request: Request):
    session = current_session(request)
    return {"conversations": store.list_conversations(session["owner_key"])}


@app.get("/api/history/{conversation_id}")
async def conversation(conversation_id: str, request: Request):
    session = current_session(request)
    if not store.owns_conversation(session["owner_key"], conversation_id): raise HTTPException(404, "Conversation not found.")
    return {"conversation_id": conversation_id, "messages": store.get_messages(session["owner_key"], conversation_id, 100)}


@app.get("/api/glance")
async def glance(request: Request):
    session = current_session(request, True)
    if session["role"] == "teacher":
        data = {"role": "teacher", "user": session["user"]}
        for key, path in (("classes", "/v1/teacher/classes"), ("requests", "/v1/teacher/requests")):
            try: data[key] = await college.request("GET", path, session)
            except Exception: data[key] = None
        return data
    data = {"role": "student", "user": session["user"]}
    for key, path in (("attendance", "/v1/me/attendance"), ("timetable", "/v1/me/timetable"), ("calendar", "/v1/calendar")):
        try: data[key] = await college.request("GET", path, session)
        except Exception: data[key] = None
    return data


@app.get("/api/requests")
async def requests(request: Request):
    session = current_session(request, True)
    if session["role"] == "teacher":
        return await college.request("GET", "/v1/teacher/requests", session)
    return await college.request("GET", "/v1/me/requests", session)


@app.get("/api/schedule")
async def personal_schedule(request: Request, event_date: date | None = None):
    session = current_session(request, True)
    return {"items": store.list_schedule(session["owner_key"], event_date.isoformat() if event_date else None)}


@app.post("/api/schedule")
async def add_schedule_item(body: ScheduleBody, request: Request):
    session = current_session(request, True)
    record = body.model_dump()
    item = {**record, "date": record["date"].isoformat(), "start_time": record["start_time"].strftime("%H:%M"), "end_time": record["end_time"].strftime("%H:%M")}
    return {"item": store.create_schedule_item(session["owner_key"], item)}


@app.delete("/api/schedule/{item_id}")
async def remove_schedule_item(item_id: str, request: Request):
    session = current_session(request, True)
    if not store.delete_schedule_item(session["owner_key"], item_id):
        raise HTTPException(404, "Schedule entry not found.")
    return {"ok": True}


@app.get("/api/rulebook/search")
async def rulebook_search(request: Request, q: str = "attendance"):
    session = current_session(request, True)
    if not knowledge.index:
        try: await knowledge.refresh(session)
        except Exception: pass
    return {"results": knowledge.search(q, session["role"], 6)}


@app.post("/api/actions/{action_id}/confirm")
async def confirm_action(action_id: str, request: Request, body: ConfirmBody):
    if not body.confirmed:
        raise HTTPException(400, "Confirm the request before submitting it.")
    session = current_session(request)
    pending = store.get_pending(session["owner_key"], action_id)
    if not pending or pending["status"] != "pending": raise HTTPException(404, "This request is no longer waiting for confirmation.")
    if pending["operation_id"] == "local_schedule_create":
        if session["role"] not in {"student", "teacher"}:
            raise HTTPException(403, "Sign in to save a personal schedule entry.")
        args = pending["arguments"]
        try:
            schedule_date = date.fromisoformat(str(args["date"]))
            start = time.fromisoformat(str(args["start_time"]))
            end = time.fromisoformat(str(args["end_time"]))
            title = str(args["title"]).strip()
            if not title or len(title) > 120: raise ValueError("Title must be 1 to 120 characters.")
            if end <= start: raise ValueError("End time must be after start time.")
            item = store.create_schedule_item(session["owner_key"], {"title": title, "date": schedule_date.isoformat(), "start_time": start.strftime("%H:%M"), "end_time": end.strftime("%H:%M"), "notes": str(args.get("notes", ""))[:500]})
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, f"Please edit the schedule details: {exc}") from exc
        store.finish_pending(session["owner_key"], action_id, item)
        answer = "Your personal schedule entry is saved. You can view it on the My Schedule page."
        store.save_message(session["owner_key"], pending["conversation_id"], "assistant", answer)
        return {"ok": True, "result": item, "answer": answer}
    tool = college.tools.get(pending["operation_id"])
    if not tool: await college.load_tools(); tool = college.tools.get(pending["operation_id"])
    if not tool: raise HTTPException(400, "That action is no longer available.")
    op = tool["_operation"]
    if not college.role_allowed(session["role"], op["method"], op["path"]): raise HTTPException(403, "You cannot submit this action.")
    path = op["path"]
    args = dict(pending["arguments"])
    for key in __import__("re").findall(r"\{([^}]+)\}", path):
        value = args.pop(key, None)
        if value is None: raise HTTPException(400, f"Missing {key} for this action.")
        path = path.replace("{" + key + "}", str(value))
    query_keys = {p.get("name") for p in college.spec.get("paths", {}).get(op["path"], {}).get(op["method"], {}).get("parameters", []) if p.get("in") == "query"} if college.spec else set()
    params = {k: args.pop(k) for k in list(args) if k in query_keys}
    try:
        result = await college.request(op["method"].upper(), path, session, params=params, body=args or None, idempotency_key=pending["idempotency_key"])
    except Exception as exc: raise HTTPException(502, str(exc)) from exc
    store.finish_pending(session["owner_key"], action_id, result if isinstance(result, dict) else {"result": result})
    store.save_message(session["owner_key"], pending["conversation_id"], "assistant", "Your request has been submitted successfully.")
    return {"ok": True, "result": result, "answer": "Your request has been submitted successfully."}


@app.patch("/api/actions/{action_id}")
async def edit_action(action_id: str, request: Request, body: EditActionBody):
    session = current_session(request)
    pending = store.get_pending(session["owner_key"], action_id)
    if not pending or pending["status"] != "pending": raise HTTPException(404, "This request is no longer editable.")
    if pending["operation_id"] == "local_schedule_create":
        allowed = {"title", "date", "start_time", "end_time", "notes"}
        if set(body.arguments) - allowed:
            raise HTTPException(400, "The edit includes a field that is not part of this schedule entry.")
        merged = {**pending["arguments"], **body.arguments}
        store.update_pending(session["owner_key"], action_id, merged, {"fields": merged})
        return {"ok": True, "preview": {"fields": merged}}
    if not college.tools:
        await college.load_tools()
    tool = college.tools.get(pending["operation_id"])
    if not tool or not college.role_allowed(session["role"], tool["_operation"]["method"], tool["_operation"]["path"]):
        raise HTTPException(403, "You cannot edit this request.")
    allowed = set(tool["function"]["parameters"].get("properties", {}))
    if set(body.arguments) - allowed:
        raise HTTPException(400, "The edit includes a field that is not part of this request.")
    merged = {**pending["arguments"], **body.arguments}
    preview = {"fields": merged}
    store.update_pending(session["owner_key"], action_id, merged, preview)
    return {"ok": True, "preview": preview}


@app.delete("/api/actions/{action_id}")
async def cancel_action(action_id: str, request: Request):
    session = current_session(request)
    if not store.cancel_pending(session["owner_key"], action_id): raise HTTPException(404, "This request is no longer waiting.")
    return {"ok": True}


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    if not GROQ_API_KEY: raise HTTPException(503, "Add GROQ_API_KEY to the server environment to enable voice transcription.")
    content = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(content) > MAX_AUDIO_BYTES: raise HTTPException(413, "That recording is too large. Please try a shorter recording.")
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    files = {"file": (audio.filename or "recording.webm", content, audio.content_type or "audio/webm")}
    data = {"model": GROQ_STT_MODEL, "response_format": "json", "language": "en"}
    async with httpx.AsyncClient(timeout=40) as client:
        response = await client.post("https://api.groq.com/openai/v1/audio/transcriptions", headers=headers, files=files, data=data)
    if response.is_error: raise HTTPException(502, "Speech recognition is temporarily unavailable. Please type your message.")
    return {"text": response.json().get("text", "")}


class SpeakBody(BaseModel): text: str = Field(min_length=1, max_length=1200)


@app.post("/api/speak")
async def speak(body: SpeakBody):
    if not GROQ_API_KEY or len(body.text) > 200: return {"fallback": True, "text": body.text}
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": GROQ_TTS_MODEL, "voice": GROQ_TTS_VOICE, "input": body.text, "response_format": "wav"}
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post("https://api.groq.com/openai/v1/audio/speech", headers=headers, json=payload)
    if response.is_error: return {"fallback": True, "text": body.text}
    return Response(response.content, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.get("/api/openapi-tools")
async def openapi_tools(request: Request):
    session = current_session(request)
    tools = await college.load_tools()
    return {"tools": [{"name": t["function"]["name"], "description": t["function"]["description"]} for t in tools if college.role_allowed(session["role"], t["_operation"]["method"], t["_operation"]["path"])]}


app.mount("/", StaticFiles(directory=PUBLIC, html=True, check_dir=False), name="public")
