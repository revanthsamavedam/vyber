"""Vyber API — backend only. The UI lives in the separate
vyber-ui repo (React) and talks to this service over HTTP.

Run:  uvicorn api.main:app --port 8091
Auth is a demo stub (Bearer demo:<user>) where real SSO would sit.
CORS: the UI's origin must be allowed — VYBER_CORS_ORIGINS is a
comma-separated list (default covers the local Vite dev/preview ports).
Model: VYBER_MODEL env var — see core/models.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from api.runs import QueueFullError, Run, RunManager
from core.config import SETTINGS
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

logging.basicConfig(level=os.environ.get("VYBER_LOG_LEVEL", "INFO"))
logger = logging.getLogger("vyber.api")

app = FastAPI(title="vyber-api")

_origins = [o.strip() for o in _env(
    "VYBER_CORS_ORIGINS", "SUPER_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,"
    "http://localhost:4173,http://127.0.0.1:4173").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware, allow_origins=_origins, allow_methods=["*"],
    allow_headers=["*"])


_CALLER_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")


@app.middleware("http")
async def auth_mw(request: Request, call_next):
    started = time.perf_counter()
    supplied = request.headers.get("X-Request-ID", "")
    request.state.request_id = supplied if _CALLER_RE.match(supplied) else uuid.uuid4().hex
    public = request.url.path in ("/", "/healthz", "/readyz")
    if not public and request.method != "OPTIONS":
        auth = request.headers.get("Authorization", "")
        caller = auth.removeprefix("Bearer demo:").split(":")[0] \
            if auth.startswith("Bearer demo:") else ""
        if not _CALLER_RE.match(caller):
            response = JSONResponse(
                status_code=401, content={"detail": "sign-in required"})
            response.headers["X-Request-ID"] = request.state.request_id
            return response
        request.state.caller = caller
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    logger.info("%s %s -> %s %.1fms caller=%s request_id=%s",
                request.method, request.url.path, response.status_code,
                (time.perf_counter() - started) * 1000,
                getattr(request.state, "caller", "-"), request.state.request_id)
    return response


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    logger.exception("unhandled error request_id=%s",
                     getattr(request.state, "request_id", "-"))
    return JSONResponse(status_code=500, content={
        "detail": "internal server error",
        "request_id": getattr(request.state, "request_id", None)})


@app.get("/")
def root():
    return {"service": "vyber-api", "model": get_model(),
            "ui": "vyber-ui (separate repo)"}


@app.get("/healthz")
def healthz():
    return {"ok": True, "model": get_model()}


@app.get("/readyz")
def readyz():
    database = STORE.ping()
    workspaces = BASE.exists() and os.access(BASE, os.W_OK)
    ready = database and workspaces
    return JSONResponse(status_code=200 if ready else 503, content={
        "ready": ready, "database": database, "workspaces": workspaces,
        "model": get_model()})


class SessionIn(BaseModel):
    # Optional legacy field. The authenticated caller is authoritative;
    # a conflicting user value is rejected rather than trusted.
    user: str | None = Field(default=None, max_length=64)


def _owned_session(request: Request, session_id: str) -> Ctx:
    ctx = SESSIONS.get(session_id)
    if ctx is None or ctx.user_id != getattr(request.state, "caller", None):
        raise HTTPException(404, "unknown session")
    return ctx


def _owned_run(request: Request, run_id: str) -> Run:
    run = MANAGER.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")
    _owned_session(request, run.session_id)
    return run


@app.post("/api/session")
def create_session(body: SessionIn, request: Request):
    caller = request.state.caller
    if body.user is not None and body.user != caller:
        raise HTTPException(403, "session user must match authenticated caller")
    sid = uuid.uuid4().hex[:12]
    ctx = Ctx(user_id=caller, workspace=BASE / sid, memory=MEMORY, trace=TRACE)
    ctx.workspace.mkdir(parents=True, exist_ok=True)
    SESSIONS[sid] = ctx
    STORE.save_session(sid, ctx.user_id, str(ctx.workspace))
    return {"session_id": sid, "model": get_model(),
            "files": list_files(ctx.workspace)}


@app.get("/api/session/{session_id}")
def get_session(session_id: str, request: Request):
    ctx = _owned_session(request, session_id)
    return {"session_id": session_id, "model": get_model(),
            "files": list_files(ctx.workspace)}


@app.get("/api/sessions/{session_id}/runs")
def session_runs(session_id: str, request: Request):
    _owned_session(request, session_id)
    return {"runs": [_run_view(r) for r in MANAGER.runs_for_session(session_id)]}


class ChatIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=SETTINGS.max_message_chars)


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
async def chat(body: ChatIn, request: Request):
    """Non-blocking: returns a run immediately. Watch it via
    GET /api/runs/{id}/events (SSE) or poll GET /api/runs/{id}."""
    _owned_session(request, body.session_id)
    try:
        run = MANAGER.submit(body.session_id, body.message)
    except QueueFullError as e:
        raise HTTPException(429, str(e)) from e
    return {"run_id": run.id, "status": run.status}


def _run_view(run: Run) -> dict:
    return {"run_id": run.id, "session_id": run.session_id, "prompt": run.prompt,
            "status": run.status, "result": run.result, "error": run.error,
            "created_at": run.created_at, "events": run.events}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, request: Request):
    return _run_view(_owned_run(request, run_id))


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str, request: Request):
    _owned_run(request, run_id)
    run = MANAGER.cancel(run_id)
    return {"run_id": run.id, "status": run.status}


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request):
    run = _owned_run(request, run_id)

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
