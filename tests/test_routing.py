import asyncio
import os
import time
from types import SimpleNamespace

os.environ.setdefault("VYBER_WORKSPACES", "/tmp/vyber-test")

import core.orchestrator as orch  # noqa: E402
from core.evals import RoutingCase, aggregate, score_plan  # noqa: E402
from core.routing import normalize_plan  # noqa: E402
from core.schemas import (Draft, FileChange, FilePlan, Findings,  # noqa: E402
                          ReviewVerdict, RoutePlan, SubTask)
from core.security import scan_file_plan  # noqa: E402


class FakeAgent:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    async def run(self, prompt):
        self.prompts.append(prompt)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(output=out)


def _ctx(tmp_path):
    return orch.Ctx(user_id="alice", workspace=tmp_path / "ws")


def test_normalize_plan_repairs_ids_refs_and_cycles():
    plan = RoutePlan(tasks=[
        SubTask(id="a", agent="researcher", task="A", depends_on=["b"]),
        SubTask(id="b", agent="writer", task="B", depends_on=["a", "missing"],
                input_from=["a"]),
        SubTask(id="a", agent="data", task="C"),
    ])
    normalized, defects = normalize_plan(plan, "prompt")
    ids = [t.id for t in normalized.tasks]
    assert len(ids) == len(set(ids)) == 3
    assert any("duplicated" in d for d in defects)
    assert any("unknown" in d for d in defects)
    assert any("cycle" in d for d in defects)


def test_routing_eval_scorer_distinguishes_good_and_bad_plans():
    case = RoutingCase.from_dict({
        "name": "research-build",
        "prompt": "Research and build",
        "acceptable": [["researcher", "builder"]],
        "forbidden": ["data"],
        "required_dependencies": [["builder", "researcher"]],
    })
    good = RoutePlan(tasks=[
        SubTask(id="r", agent="researcher", task="Research", done_when="Findings"),
        SubTask(id="b", agent="builder", task="Build", depends_on=["r"],
                input_from=["r"], done_when="File exists"),
    ])
    bad = RoutePlan(tasks=[SubTask(id="d", agent="data", task="Wrong route")])
    assert score_plan(case, good)["route_ok"]
    bad_score = score_plan(case, bad)
    assert not bad_score["route_ok"] and bad_score["forbidden_used"] == ["data"]
    summary = aggregate([score_plan(case, good), bad_score])
    assert summary["cases"] == 2 and summary["acceptable_route_rate"] == 0.5


def test_orchestrator_passes_declared_upstream_output(tmp_path, monkeypatch):
    plan = RoutePlan(tasks=[
        SubTask(id="research", agent="researcher", task="Find facts"),
        SubTask(id="write", agent="writer", task="Write from facts",
                depends_on=["research"], input_from=["research"]),
    ])
    researcher = FakeAgent([Findings(summary="Evidence summary", points=["p1"])])
    writer = FakeAgent([Draft(title="Guide", body="Body")])
    monkeypatch.setattr(orch, "planner_agent", FakeAgent([plan]))
    monkeypatch.setitem(orch.SUBAGENTS, "researcher", researcher)
    monkeypatch.setitem(orch.SUBAGENTS, "writer", writer)

    result = asyncio.run(orch.ask("Research and write", _ctx(tmp_path)))
    assert "Evidence summary" in writer.prompts[0]
    assert [s.task_id for s in result.steps if s.kind == "task"] == [
        "research", "write"]
    assert "writer:" in result.summary


def test_independent_tasks_run_in_parallel(tmp_path, monkeypatch):
    started = []
    both_started = asyncio.Event()

    class ParallelAgent:
        def __init__(self, output):
            self.output = output

        async def run(self, prompt):
            started.append(prompt)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=1)
            return SimpleNamespace(output=self.output)

    plan = RoutePlan(tasks=[
        SubTask(id="r", agent="researcher", task="Research"),
        SubTask(id="d", agent="data", task="Data"),
    ])
    monkeypatch.setattr(orch, "planner_agent", FakeAgent([plan]))
    monkeypatch.setitem(orch.SUBAGENTS, "researcher",
                         ParallelAgent(Findings(summary="R")))
    from core.schemas import DataAnswer
    monkeypatch.setitem(orch.SUBAGENTS, "data",
                         ParallelAgent(DataAnswer(answer="D", source="db",
                                                  freshness="today")))
    result = asyncio.run(orch.ask("Two independent jobs", _ctx(tmp_path)))
    assert not [s for s in result.steps if s.kind == "error"]


def test_failed_dependency_skips_child(tmp_path, monkeypatch):
    plan = RoutePlan(tasks=[
        SubTask(id="research", agent="researcher", task="Find facts"),
        SubTask(id="write", agent="writer", task="Write",
                depends_on=["research"], input_from=["research"]),
    ])
    writer = FakeAgent([Draft(title="unused", body="unused")])
    monkeypatch.setattr(orch, "planner_agent", FakeAgent([plan]))
    monkeypatch.setitem(orch.SUBAGENTS, "researcher",
                         FakeAgent([RuntimeError("model unavailable")]))
    monkeypatch.setitem(orch.SUBAGENTS, "writer", writer)
    result = asyncio.run(orch.ask("Research and write", _ctx(tmp_path)))
    assert writer.prompts == []
    assert len([s for s in result.steps if s.kind == "error"]) == 2
    assert result.routing_defects


def test_secret_in_file_plan_is_hard_vetoed_before_reviewer(tmp_path, monkeypatch):
    plan = RoutePlan(tasks=[SubTask(id="build", agent="builder", task="Build")])
    # Fake key, assembled at runtime so source scanners don't flag it.
    fake_key = "AK" + "IA" + "1234567890" + "ABCDEF"
    secret_plan = FilePlan(summary="bad", files=[
        FileChange(path="config.txt", content="key = " + fake_key)])
    reviewer = FakeAgent([ReviewVerdict(approved=True)])
    monkeypatch.setattr(orch, "planner_agent", FakeAgent([plan]))
    monkeypatch.setitem(orch.SUBAGENTS, "builder", FakeAgent([secret_plan]))
    monkeypatch.setattr(orch, "reviewer_agent", reviewer)
    result = asyncio.run(orch.ask("Build config", _ctx(tmp_path)))
    assert reviewer.prompts == []
    assert result.review and not result.review.approved
    assert not (_ctx(tmp_path).workspace / "config.txt").exists()
    assert scan_file_plan(secret_plan)


def test_conflicting_duplicate_paths_are_vetoed(tmp_path, monkeypatch):
    plan = RoutePlan(tasks=[
        SubTask(id="b1", agent="builder", task="Build one"),
        SubTask(id="b2", agent="builder", task="Build two"),
    ])
    monkeypatch.setattr(orch, "planner_agent", FakeAgent([plan]))
    monkeypatch.setitem(orch.SUBAGENTS, "builder", FakeAgent([
        FilePlan(files=[FileChange(path="a.txt", content="one")]),
        FilePlan(files=[FileChange(path="a.txt", content="two")]),
    ]))
    result = asyncio.run(orch.ask("Build two versions", _ctx(tmp_path)))
    assert result.review and not result.review.approved
    assert not (_ctx(tmp_path).workspace / "a.txt").exists()


def test_reviewer_veto_gets_one_revision_then_applies(tmp_path, monkeypatch):
    plan = RoutePlan(tasks=[SubTask(id="build", agent="builder", task="Build")])
    initial = FilePlan(files=[FileChange(path="a.txt", content="draft")])
    revised = FilePlan(files=[FileChange(path="a.txt", content="corrected")])
    builder_sequence = FakeAgent([initial, revised])
    reviewer_sequence = FakeAgent([
        ReviewVerdict(approved=False, issues=["fix content"], summary="veto"),
        ReviewVerdict(approved=True, summary="approved"),
    ])
    monkeypatch.setattr(orch, "planner_agent", FakeAgent([plan]))
    monkeypatch.setitem(orch.SUBAGENTS, "builder", builder_sequence)
    monkeypatch.setattr(orch, "builder_agent", builder_sequence)
    monkeypatch.setattr(orch, "reviewer_agent", reviewer_sequence)
    ctx = _ctx(tmp_path)
    result = asyncio.run(orch.ask("Build a file", ctx))
    assert result.changed_files == ["a.txt"]
    assert (ctx.workspace / "a.txt").read_text() == "corrected"
    assert len(reviewer_sequence.prompts) == 2
