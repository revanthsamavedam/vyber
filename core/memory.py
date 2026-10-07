"""3-tier memory.
Working: the current run's messages (held by Pydantic AI, not here).
Episodic: append-only record of every run/step — the audit trail.
Curated: human-approved facts only, injected into agent context.
Nothing auto-promotes into curated. Ever."""
from __future__ import annotations

import time

from pydantic import BaseModel, ConfigDict, PrivateAttr


class Memory(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    _episodes: list[dict] = PrivateAttr(default_factory=list)
    _curated: dict[str, dict[str, str]] = PrivateAttr(default_factory=dict)
    _store: object = PrivateAttr(default=None)

    def __init__(self, _store=None, **data):
        super().__init__(**data)
        # Private-attribute kwargs are not reliably honoured by Pydantic's
        # constructor, so the store is taken explicitly and loaded here.
        self._store = _store
        if _store is not None:
            self._episodes = _store.all_episodes()
            self._curated = _store.all_curated()

    def record(self, user_id: str, kind: str, payload: dict) -> None:
        ep = {"user_id": user_id, "kind": kind,
              "payload": payload, "ts": time.time()}
        self._episodes.append(ep)
        if self._store is not None:
            self._store.add_episode(user_id, kind, payload, ep["ts"])

    def episodes(self, user_id: str | None = None) -> list[dict]:
        return [e for e in self._episodes if user_id is None or e["user_id"] == user_id]

    def approve_fact(self, user_id: str, key: str, value: str, approved_by: str) -> None:
        if not approved_by:
            raise ValueError("curated facts require a human approver")
        self._curated.setdefault(user_id, {})[key] = value
        if self._store is not None:
            self._store.upsert_curated(user_id, key, value, approved_by)
        self.record(user_id, "curated.approved", {"key": key, "approved_by": approved_by})

    def curated_block(self, user_id: str) -> str:
        facts = self._curated.get(user_id, {})
        if not facts:
            return ""
        return "Approved facts:\n" + "\n".join(f"- {k}: {v}" for k, v in sorted(facts.items()))
