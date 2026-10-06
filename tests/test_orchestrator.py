import asyncio
import os

os.environ.setdefault("SUPER_WORKSPACES", "/tmp/super-muse-test")

from core.orchestrator import Ctx, ask  # noqa: E402
from core.schemas import KNOWN_AGENTS  # noqa: E402
from core.subagents import SUBAGENTS  # noqa: E402


def test_subagent_roster():
    assert set(SUBAGENTS) == set(KNOWN_AGENTS) == {
        "researcher", "builder", "data", "writer"}


def test_orchestrator_runs_end_to_end(tmp_path):
    ctx = Ctx(user_id="alice", workspace=tmp_path / "ws")
    result = asyncio.run(ask("Research deep work and build me a short guide", ctx))
    kinds = [s.kind for s in result.steps]
    assert kinds[0] == "plan"                      # planner went first
    assert any(s.agent in KNOWN_AGENTS for s in result.steps)  # a specialist ran
    assert result.summary
    assert ctx.trace.events(ctx.trace_id)          # trace recorded
    assert ctx.memory.episodes("alice")            # episodic memory recorded
