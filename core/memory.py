"""3-tier memory.
Working: the current run's messages (held by Pydantic AI, not here).
Episodic: append-only record of every run/step — the audit trail.
Curated: human-approved facts only, injected into agent context.
Nothing auto-promotes into curated. Ever."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Memory:
    _episodes: list[dict] = field(default_factory=list)
    _curated: dict[str, dict[str, str]] = field(default_factory=dict)
    _store: object = field(default=None, repr=False)

    def __post_init__(self):
        if self._store is not None:
            self._episodes = self._store.all_episodes()
            self._curated = self._store.all_curated()

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
