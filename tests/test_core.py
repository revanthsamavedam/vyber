import pytest

from core.approvals import ApprovalStore
from core.memory import Memory
from core.skills import catalog, discover
from core.workspace import apply_changes, list_files
from core.schemas import FileChange

import os
ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_skills_catalogue():
    skills = discover(os.path.join(ROOT, "skills"))
    assert {s.name for s in skills} == {
        "deep-research", "build-a-tool", "draft-a-doc", "answer-from-data"}
    assert "deep-research" in catalog(skills)


def test_curated_memory_needs_approver():
    m = Memory()
    with pytest.raises(ValueError):
        m.approve_fact("alice", "team", "X", approved_by="")
    m.approve_fact("alice", "team", "X", approved_by="alice")
    assert "X" in m.curated_block("alice")


def test_approvals_flow():
    store = ApprovalStore()
    aid = store.request("alice", "send_email", {})
    assert not store.is_approved(aid)
    store.decide(aid, True, "alice")
    assert store.is_approved(aid)


def test_workspace_blocks_escape(tmp_path):
    with pytest.raises(ValueError):
        apply_changes(tmp_path, [FileChange(path="../evil.txt", content="x")])
    changed = apply_changes(tmp_path, [FileChange(path="sub/ok.txt", content="hi")])
    assert changed == ["sub/ok.txt"] and "sub/ok.txt" in list_files(tmp_path)
