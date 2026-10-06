"""SQLite persistence via SQLAlchemy — the system of record.

Everything that used to live only in process memory (sessions, runs and
their events, episodic + curated memory, approvals) is written through
to this store, so a server restart loses nothing. The engine URL comes
from SUPER_DATABASE_URL (default: sqlite file under SUPER_DATA_DIR);
because it's SQLAlchemy, moving to Postgres later is a URL change plus
a driver — the table definitions and call sites don't change.

Workspace *files* stay on disk; only their metadata lives here.
"""
from __future__ import annotations

import json
import time

from sqlalchemy import (Column, Float, Integer, MetaData, String, Table,
                        create_engine, delete, insert, select, update)

meta = MetaData()

sessions = Table(
    "sessions", meta,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("workspace", String, nullable=False),
    Column("created_at", Float, nullable=False),
)
runs = Table(
    "runs", meta,
    Column("id", String, primary_key=True),
    Column("session_id", String, nullable=False, index=True),
    Column("prompt", String, nullable=False),
    Column("status", String, nullable=False),
    Column("result_json", String),
    Column("error", String),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
)
run_events = Table(
    "run_events", meta,
    Column("run_id", String, nullable=False, index=True),
    Column("seq", Integer, nullable=False),
    Column("event_json", String, nullable=False),
    Column("ts", Float, nullable=False),
)
episodes = Table(
    "episodes", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", String, nullable=False, index=True),
    Column("kind", String, nullable=False),
    Column("payload_json", String, nullable=False),
    Column("ts", Float, nullable=False),
)
curated = Table(
    "curated", meta,
    Column("user_id", String, primary_key=True),
    Column("key", String, primary_key=True),
    Column("value", String, nullable=False),
    Column("approved_by", String, nullable=False),
)
approvals = Table(
    "approvals", meta,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("action", String, nullable=False),
    Column("payload_json", String, nullable=False),
    Column("state", String, nullable=False),  # pending | decided
    Column("approved", Integer),
    Column("decided_by", String),
)


class Store:
    def __init__(self, url: str):
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, connect_args=connect_args)
        meta.create_all(self.engine)

    # -- sessions ------------------------------------------------------
    def save_session(self, sid: str, user_id: str, workspace: str) -> None:
        with self.engine.begin() as c:
            exists = c.execute(select(sessions.c.id).where(
                sessions.c.id == sid)).first()
            if not exists:
                c.execute(insert(sessions).values(
                    id=sid, user_id=user_id, workspace=workspace,
                    created_at=time.time()))

    def all_sessions(self) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(sessions)).mappings()
            return [dict(r) for r in rows]

    # -- runs ----------------------------------------------------------
    def create_run(self, run_id: str, session_id: str, prompt: str) -> None:
        now = time.time()
        with self.engine.begin() as c:
            c.execute(insert(runs).values(
                id=run_id, session_id=session_id, prompt=prompt,
                status="queued", created_at=now, updated_at=now))

    def update_run(self, run_id: str, status: str,
                   result: dict | None = None, error: str | None = None) -> None:
        values: dict = {"status": status, "updated_at": time.time()}
        if result is not None:
            values["result_json"] = json.dumps(result)
        if error is not None:
            values["error"] = error
        with self.engine.begin() as c:
            c.execute(update(runs).where(runs.c.id == run_id).values(**values))

    def add_event(self, run_id: str, seq: int, event: dict) -> None:
        with self.engine.begin() as c:
            c.execute(insert(run_events).values(
                run_id=run_id, seq=seq, event_json=json.dumps(event),
                ts=time.time()))

    def list_runs(self) -> list[dict]:
        with self.engine.connect() as c:
            out = []
            for r in c.execute(select(runs)).mappings():
                d = dict(r)
                d["result"] = json.loads(d.pop("result_json")) if d["result_json"] else None
                out.append(d)
            return out

    def events_for(self, run_id: str) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(run_events.c.event_json).where(
                run_events.c.run_id == run_id).order_by(run_events.c.seq))
            return [json.loads(v) for (v,) in rows]

    # -- memory ----------------------------------------------------------
    def add_episode(self, user_id: str, kind: str, payload: dict, ts: float) -> None:
        with self.engine.begin() as c:
            c.execute(insert(episodes).values(
                user_id=user_id, kind=kind,
                payload_json=json.dumps(payload), ts=ts))

    def all_episodes(self) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(episodes).order_by(episodes.c.id)).mappings()
            return [{"user_id": r["user_id"], "kind": r["kind"],
                     "payload": json.loads(r["payload_json"]), "ts": r["ts"]}
                    for r in rows]

    def upsert_curated(self, user_id: str, key: str, value: str,
                       approved_by: str) -> None:
        with self.engine.begin() as c:
            exists = c.execute(select(curated.c.key).where(
                curated.c.user_id == user_id, curated.c.key == key)).first()
            if exists:
                c.execute(update(curated).where(
                    curated.c.user_id == user_id, curated.c.key == key).values(
                    value=value, approved_by=approved_by))
            else:
                c.execute(insert(curated).values(
                    user_id=user_id, key=key, value=value,
                    approved_by=approved_by))

    def all_curated(self) -> dict[str, dict[str, str]]:
        with self.engine.connect() as c:
            out: dict[str, dict[str, str]] = {}
            for r in c.execute(select(curated)).mappings():
                out.setdefault(r["user_id"], {})[r["key"]] = r["value"]
            return out

    # -- approvals -------------------------------------------------------
    def add_approval(self, item: dict) -> None:
        with self.engine.begin() as c:
            c.execute(insert(approvals).values(
                id=item["id"], user_id=item["user_id"], action=item["action"],
                payload_json=json.dumps(item["payload"]), state="pending"))

    def decide_approval(self, approval_id: str, approved: bool,
                        decided_by: str) -> None:
        with self.engine.begin() as c:
            c.execute(update(approvals).where(
                approvals.c.id == approval_id).values(
                state="decided", approved=1 if approved else 0,
                decided_by=decided_by))

    def all_approvals(self) -> tuple[list[dict], list[dict]]:
        pending, decided = [], []
        with self.engine.connect() as c:
            for r in c.execute(select(approvals)).mappings():
                item = {"id": r["id"], "user_id": r["user_id"],
                        "action": r["action"],
                        "payload": json.loads(r["payload_json"])}
                if r["state"] == "decided":
                    item.update({"approved": bool(r["approved"]),
                                 "decided_by": r["decided_by"]})
                    decided.append(item)
                else:
                    pending.append(item)
        return pending, decided

    def wipe(self) -> None:  # tests only
        with self.engine.begin() as c:
            for t in (sessions, runs, run_events, episodes, curated, approvals):
                c.execute(delete(t))
