"""Super Muse studio — browser chat with the agent trace made visible.

Run:  uvicorn studio.main:app --port 8091  →  http://localhost:8091
Auth is a demo stub (Bearer demo:<user>) where real SSO would sit.
Model: SUPER_MODEL env var — see core/models.py.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from core.memory import Memory
from core.models import get_model
from core.orchestrator import Ctx, ask
from core.traces import TraceLog
from core.workspace import list_files

BASE = Path(os.environ.get("SUPER_WORKSPACES",
                           Path(tempfile.gettempdir()) / "super-muse-workspaces"))
BASE.mkdir(parents=True, exist_ok=True)
STATIC = Path(__file__).parent / "static"
SESSIONS: dict[str, Ctx] = {}
MEMORY = Memory()
TRACE = TraceLog()

app = FastAPI(title="super-muse")
OPEN_EXACT = ("/", "/healthz", "/favicon.ico")


@app.middleware("http")
async def auth_mw(request: Request, call_next):
    if request.url.path in OPEN_EXACT:
        return await call_next(request)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer demo:"):
        return JSONResponse(status_code=401, content={"detail": "sign-in required"})
    request.state.caller = auth.removeprefix("Bearer demo:").split(":")[0]
    return await call_next(request)


@app.get("/healthz")
def healthz():
    return {"ok": True, "model": get_model()}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


class SessionIn(BaseModel):
    user: str = "alice"


@app.post("/api/session")
def create_session(body: SessionIn, request: Request):
    sid = uuid.uuid4().hex[:12]
    ctx = Ctx(user_id=body.user or request.state.caller,
              workspace=BASE / sid, memory=MEMORY, trace=TRACE)
    SESSIONS[sid] = ctx
    return {"session_id": sid, "model": get_model(), "files": []}


class ChatIn(BaseModel):
    session_id: str
    message: str


@app.post("/api/chat")
async def chat(body: ChatIn):
    ctx = SESSIONS.get(body.session_id)
    if ctx is None:
        raise HTTPException(404, "unknown session")
    result = await ask(body.message, ctx)
    return {**result.model_dump(),
            "files": list_files(ctx.workspace),
            "trace_events": [e["kind"] for e in TRACE.events(ctx.trace_id)]}
