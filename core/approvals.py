"""Approval gate for consequential actions (sending, publishing, deleting).
Creating a draft never needs approval. Acting on the world does."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class ApprovalStore:
    _pending: dict[str, dict] = field(default_factory=dict)
    _decided: dict[str, dict] = field(default_factory=dict)
    _store: object = field(default=None, repr=False)

    def __post_init__(self):
        if self._store is not None:
            pending, decided = self._store.all_approvals()
            self._pending = {i["id"]: i for i in pending}
            self._decided = {i["id"]: i for i in decided}

    def request(self, user_id: str, action: str, payload: dict) -> str:
        aid = uuid.uuid4().hex[:12]
        self._pending[aid] = {"id": aid, "user_id": user_id,
                              "action": action, "payload": payload}
        if self._store is not None:
            self._store.add_approval(self._pending[aid])
        return aid

    def decide(self, approval_id: str, approved: bool, decided_by: str) -> dict:
        item = self._pending.pop(approval_id)
        item.update({"approved": approved, "decided_by": decided_by})
        self._decided[approval_id] = item
        if self._store is not None:
            self._store.decide_approval(approval_id, approved, decided_by)
        return item

    def is_approved(self, approval_id: str) -> bool:
        return bool(self._decided.get(approval_id, {}).get("approved"))

    def pending(self) -> list[dict]:
        return list(self._pending.values())
