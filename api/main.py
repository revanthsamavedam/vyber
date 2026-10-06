"""Vyber API — backend only. The UI lives in the separate
vyber-ui repo (React) and talks to this service over HTTP.

Run:  uvicorn api.main:app --port 8091
Auth is a demo stub (Bearer demo:<user>) where real SSO would sit.
CORS: the UI's origin must be allowed — VYBER_CORS_ORIGINS is a
comma-separated list (default covers the local Vite dev/preview ports).
Model: VYBER_MODEL env var — see core/models.py.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import asyncio
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from api.runs import Run, RunManager
from core.memory import Memory
from core.models import get_model
from core.orchestrator import Ctx, ask
from core.store import Store
from core.traces import TraceLog
from core.workspace import list_files

# Persistence: everything stateful goes through the store, so a restart
# loses nothing. VYBER_DATABASE_URL picks the database (SQLAlchemy —
# sqlite by default, Postgres by URL); VYBER_DATA_DIR holds the sqlite
# file, traces, and workspaces.
def _env(new: str, old: str, default=None):
    # VYBER_* is canonical; SUPER_* (pre-rename) still honored.
    return os.environ.get(new) or os.environ.get(old) or default


DATA = Path(_env("VYBER_DATA_DIR", "SUPER_DATA_DIR", Path.home() / ".vyber"))
DATA.mkdir(parents=True, exist_ok=True)
STORE = Store(_env("VYBER_DATABASE_URL", "SUPER_DATABASE_URL",
                   f"sqlite:///{DATA / 'vyber.db'}"))
BASE = Path(_env("VYBER_WORKSPACES", "SUPER_WORKSPACES", DATA / "workspaces"))
BASE.mkdir(parents=True, exist_ok=True)
MEMORY = Memory(_store=STORE)
TRACE = TraceLog(path=str(DATA / "traces.jsonl"))
SESSIONS: dict[str, Ctx] = {}
for _row in STORE.all_sessions():  # rehydrate sessions after a restart
    _ws = Path(_row["workspace"])
    _ws.mkdir(parents=True, exist_ok=True)
    SESSIONS[_row["id"]] = Ctx(user_id=_row["user_id"], workspace=_ws,
                               memory=MEMORY, trace=TRACE)

app = FastAPI(title="vyber-api")

_origins = [o.strip() for o in _env(
    "VYBER_CORS_ORIGINS", "SUPER_CORS_ORIGINS",
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
    return {"service": "vyber-api", "model": get_model(),
            "ui": "vyber-ui (separate repo)"}


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
    STORE.save_session(sid, ctx.user_id, str(ctx.workspace))
    return {"session_id": sid, "model": get_model(), "files": []}


class ChatIn(BaseModel):
    session_id: str
    message: str


async def _execute(run: Run) -> dict:
    ctx = SESSIONS[run.session_id]

    def emit(kind, payload):
        if kind == "step":
            run.publish({"type": "step", "step": payload.model_dump()})
        elif kind == "subagent.started":
            run.publish({"type": "subagent.started", **payload})

    result = await ask(run.prompt, ctx, emit=emit)
    return {**result.model_dump(),
            "files": list_files(ctx.workspace),
            "trace_events": [e["kind"] for e in TRACE.events(ctx.trace_id)]}


MANAGER = RunManager(_execute, store=STORE)


@app.post("/api/chat", status_code=202)
async def chat(body: ChatIn):
    """Non-blocking: returns a run immediately. Watch it via
    GET /api/runs/{id}/events (SSE) or poll GET /api/runs/{id}."""
    if body.session_id not in SESSIONS:
        raise HTTPException(404, "unknown session")
    run = MANAGER.submit(body.session_id, body.message)
    return {"run_id": run.id, "status": run.status}


def _run_view(run: Run) -> dict:
    return {"run_id": run.id, "session_id": run.session_id, "prompt": run.prompt,
            "status": run.status, "result": run.result, "error": run.error,
            "events": run.events}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = MANAGER.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")
    return _run_view(run)


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    run = MANAGER.cancel(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")
    return {"run_id": run.id, "status": run.status}


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str):
    run = MANAGER.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")

    async def gen():
        q = run.subscribe()
        try:
            while True:
                event = await q.get()
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("result", "error") or (
                        event.get("type") == "status"
                        and event.get("status") in ("cancelled",)):
                    break
                if run.status in ("done", "failed", "cancelled") and q.empty():
                    break
        except asyncio.CancelledError:
            pass
        finally:
            run.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")
