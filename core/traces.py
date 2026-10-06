"""Append-only trace: one event per planner decision, subagent step,
review, and file application. In production, mirror these to Logfire/OTel."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


@dataclass
class TraceLog:
    path: str | None = None
    _events: list[dict] = field(default_factory=list)

    def emit(self, trace_id: str, kind: str, data: dict) -> None:
        evt = {"trace_id": trace_id, "kind": kind, "ts": time.time(), **data}
        self._events.append(evt)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(evt) + "\n")

    def events(self, trace_id: str | None = None) -> list[dict]:
        return [e for e in self._events if trace_id is None or e["trace_id"] == trace_id]
