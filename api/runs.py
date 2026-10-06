"""Async runs — the machinery behind the live activity view.

A chat message no longer blocks on the orchestrator. submit() returns a
Run immediately; a per-session worker executes runs one at a time (two
runs must never write the same workspace simultaneously), streaming
events to subscribers as the orchestrator emits them:

    {"type": "status", "status": "queued|running|done|failed|cancelled"}
    {"type": "subagent.started", "agent": ..., "task": ...}
    {"type": "step", "step": {agent, task, output, kind}}
    {"type": "result", "result": {...}}        (terminal)
    {"type": "error", "error": "..."}          (terminal)

Cancelling a queued run means it never starts. Cancelling a running run
cancels its task at the next await point — an in-flight model call is
not interrupted mid-flight, and the run is marked cancelled either way.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

TERMINAL = ("done", "failed", "cancelled")


@dataclass
class Run:
    id: str
    session_id: str
    prompt: str
    status: str = "queued"
    events: list[dict] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None
    _subs: list[asyncio.Queue] = field(default_factory=list)
    _task: asyncio.Task | None = None

    def publish(self, event: dict) -> None:
        self.events.append(event)
        for q in list(self._subs):
            q.put_nowait(event)

    def set_status(self, status: str) -> None:
        self.status = status
        self.publish({"type": "status", "status": status})

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        for e in self.events:  # replay what already happened
            q.put_nowait(e)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subs:
            self._subs.remove(q)


class RunManager:
    def __init__(self, execute: Callable[[Run], Awaitable[dict]]):
        self._execute = execute  # async (run) -> result dict; publishes its own step events
        self.runs: dict[str, Run] = {}
        self._queues: dict[str, asyncio.Queue] = {}
        self._workers: dict[str, asyncio.Task] = {}

    def submit(self, session_id: str, prompt: str) -> Run:
        run = Run(id=uuid.uuid4().hex[:12], session_id=session_id, prompt=prompt)
        self.runs[run.id] = run
        run.publish({"type": "status", "status": "queued"})
        self._queues.setdefault(session_id, asyncio.Queue()).put_nowait(run)
        worker = self._workers.get(session_id)
        if worker is None or worker.done():
            self._workers[session_id] = asyncio.create_task(self._work(session_id))
        return run

    async def _work(self, session_id: str) -> None:
        queue = self._queues[session_id]
        while True:
            try:
                run: Run = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            if run.status == "cancelled":
                continue
            run.set_status("running")
            run._task = asyncio.create_task(self._execute(run))
            try:
                run.result = await run._task
                run.set_status("done")
                run.publish({"type": "result", "result": run.result})
            except asyncio.CancelledError:
                run.set_status("cancelled")
            except Exception as e:  # one bad run must not kill the worker
                run.error = str(e)
                run.set_status("failed")
                run.publish({"type": "error", "error": run.error})

    def cancel(self, run_id: str) -> Run | None:
        run = self.runs.get(run_id)
        if run is None or run.status in TERMINAL:
            return run
        if run.status == "queued":
            run.set_status("cancelled")
        elif run._task is not None:
            run._task.cancel()
        return run

    def get(self, run_id: str) -> Run | None:
        return self.runs.get(run_id)
