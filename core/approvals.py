"""Approval gate for consequential actions (sending, publishing, deleting).
Creating a draft never needs approval. Acting on the world does."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, PrivateAttr


class ApprovalItem(BaseModel):
    id: str
    user_id: str
    action: str
    payload: dict
    approved: bool | None = None
    decided_by: str | None = None


class ApprovalStore(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    _pending: dict[str, ApprovalItem] = PrivateAttr(default_factory=dict)
    _decided: dict[str, ApprovalItem] = PrivateAttr(default_factory=dict)
    _store: object = PrivateAttr(default=None)

    def __init__(self, _store=None, **data):
        super().__init__(**data)
        # See Memory.__init__: the store kwarg is taken explicitly.
        self._store = _store
        if _store is not None:
            pending, decided = _store.all_approvals()
            self._pending = {i["id"]: ApprovalItem.model_validate(i)
                             for i in pending}
            self._decided = {i["id"]: ApprovalItem.model_validate(i)
                             for i in decided}

    def request(self, user_id: str, action: str, payload: dict) -> str:
        item = ApprovalItem(id=uuid.uuid4().hex[:12], user_id=user_id,
                            action=action, payload=payload)
        self._pending[item.id] = item
        if self._store is not None:
            self._store.add_approval(item.model_dump())
        return item.id

    def decide(self, approval_id: str, approved: bool,
               decided_by: str) -> ApprovalItem:
        item = self._pending.pop(approval_id)
        item.approved = approved
        item.decided_by = decided_by
        self._decided[approval_id] = item
        if self._store is not None:
            self._store.decide_approval(approval_id, approved, decided_by)
        return item

    def is_approved(self, approval_id: str) -> bool:
        item = self._decided.get(approval_id)
        return bool(item and item.approved)

    def pending(self) -> list[ApprovalItem]:
        return list(self._pending.values())
