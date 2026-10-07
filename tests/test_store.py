"""Persistence: a fresh object graph over the same sqlite file must see
everything the old one wrote — that's the whole point of the layer."""
import asyncio

from api.runs import RunManager
from core.approvals import ApprovalStore
from core.memory import Memory
from core.store import Store


def _store(tmp_path):
    return Store(f"sqlite:///{tmp_path}/test.db")


def test_memory_survives_reopen(tmp_path):
    url = f"sqlite:///{tmp_path}/test.db"
    m1 = Memory(_store=Store(url))
    m1.approve_fact("alice", "role", "engineer", approved_by="alice")
    m1.record("alice", "run.completed", {"x": 1})

    m2 = Memory(_store=Store(url))
    assert "engineer" in m2.curated_block("alice")
    assert any(e["kind"] == "curated.approved" for e in m2.episodes("alice"))


def test_approvals_survive_reopen(tmp_path):
    url = f"sqlite:///{tmp_path}/test.db"
    a1 = ApprovalStore(_store=Store(url))
    aid = a1.request("alice", "send-email", {"to": "x"})
    a1.decide(aid, True, "alice")
    keep = a1.request("alice", "publish", {})

    a2 = ApprovalStore(_store=Store(url))
    assert a2.is_approved(aid)
    assert [p.id for p in a2.pending()] == [keep]


def test_runs_survive_reopen_with_events(tmp_path):
    url = f"sqlite:///{tmp_path}/test.db"

    async def execute(run):
        run.publish({"type": "step", "step": {"agent": "planner"}})
        return {"summary": "done"}

    async def scenario():
        mgr = RunManager(execute, store=Store(url))
        run = mgr.submit("s1", "do a thing")
        for _ in range(200):
            if run.status == "done":
                break
            await asyncio.sleep(0.02)
        assert run.status == "done"
        return run.id

    run_id = asyncio.run(scenario())

    mgr2 = RunManager(execute, store=Store(url))
    restored = mgr2.get(run_id)
    assert restored.status == "done" and restored.result == {"summary": "done"}
    kinds = [e["type"] for e in restored.events]
    assert "step" in kinds and "result" in kinds


def test_interrupted_run_is_marked_failed_not_zombie(tmp_path):
    store = _store(tmp_path)
    store.create_run("r1", "s1", "was mid-flight")
    store.update_run("r1", "running")

    async def execute(run):  # never called for rehydrated runs
        return {}

    mgr = RunManager(execute, store=store)
    run = mgr.get("r1")
    assert run.status == "failed" and "restarted" in run.error
