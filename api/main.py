"""Super Muse API — backend only. The UI lives in the separate
super-muse-ui repo (React) and talks to this service over HTTP.

Run:  uvicorn api.main:app --port 8091
Auth is a demo stub (Bearer demo:<user>) where real SSO would sit.
CORS: the UI's origin must be allowed — SUPER_CORS_ORIGINS is a
comma-separated list (default covers the local Vite dev/preview ports).
Model: SUPER_MODEL env var — see core/models.py.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.memory import Memory
from core.models import get_model
from core.orchestrator import Ctx, ask
from core.traces import TraceLog
from core.workspace import list_files

BASE = Path(os.environ.get("SUPER_WORKSPACES",
                           Path(tempfile.gettempdir()) / "super-muse-workspaces"))
BASE.mkdir(parents=True, exist_ok=True)
SESSIONS: dict[str, Ctx] = {}
MEMORY = Memory()
TRACE = TraceLog()

app = FastAPI(title="super-muse-api")

_origins = [o.strip() for o in os.environ.get(
    "SUPER_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,"
    "http://localhost:4173,http://127.0.0.1:4173").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware, allow_origins=_origins, allow_methods=["*"],
    allow_headers=["*"])


@app.middleware("http")
async def auth_mw(request: Request, call_next):
    if request.url.path in ("/", "/healthz") or request.method == "OPTIONS":
        return await call_next(request)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer demo:"):
        return JSONResponse(status_code=401, content={"detail": "sign-in required"})
    request.state.caller = auth.removeprefix("Bearer demo:").split(":")[0]
    return await call_next(request)


@app.get("/")
def root():
    return {"service": "super-muse-api", "model": get_model(),
            "ui": "super-muse-ui (separate repo)"}


@app.get("/healthz")
def healthz():
    return {"ok": True, "model": get_model()}


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
