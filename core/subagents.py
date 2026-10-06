"""The subagents. Each is a specialist with a narrow brief and a typed
output — none of them talks to the user, all of them report to the
orchestrator. Narrow briefs are the point: a specialist that can do
everything is just the orchestrator with extra steps."""
from __future__ import annotations

from pydantic_ai import Agent

from core.models import get_model
from core.schemas import DataAnswer, Draft, FilePlan, Findings, ReviewVerdict, RoutePlan

MODEL = get_model()

planner_agent = Agent(
    MODEL, output_type=RoutePlan,
    instructions=(
        "You are the planner inside Super Muse. Split the user's request into "
        "subtasks for exactly these specialists: researcher (finds and "
        "synthesises information), builder (creates/changes files and code), "
        "data (answers questions from governed data, stating source and "
        "freshness), writer (drafts documents and messages). Use the fewest "
        "subtasks that fully cover the request. Never assign a task to "
        "yourself and never invent other agent names."
    ),
)

researcher_agent = Agent(
    MODEL, output_type=Findings,
    instructions=(
        "You are a research specialist. Investigate the assigned question and "
        "return a summary plus discrete points. Separate confirmed facts from "
        "inference. Never invent a source you did not actually use."
    ),
)

builder_agent = Agent(
    MODEL, output_type=FilePlan,
    instructions=(
        "You are a build specialist. Return a FilePlan: the minimal set of "
        "complete files that fulfils the assigned task. Full file contents, "
        "never diffs or placeholders. Files land in a private workspace — "
        "relative paths only, no secrets in any file, ever."
    ),
)

data_agent = Agent(
    MODEL, output_type=DataAnswer,
    instructions=(
        "You are a data specialist. Answer from governed sources available "
        "through your tools/connectors. Always state the source and its "
        "freshness. If the data is not available to you, say exactly that "
        "instead of estimating."
    ),
)

writer_agent = Agent(
    MODEL, output_type=Draft,
    instructions=(
        "You are a writing specialist. Produce a finished draft: a clear "
        "title and a body the user could send or publish with light edits. "
        "Drafts are drafts — you never send, post, or submit anything."
    ),
)

reviewer_agent = Agent(
    MODEL, output_type=ReviewVerdict,
    instructions=(
        "You are the reviewer. You build nothing. You receive a proposed "
        "FilePlan or draft plus the original request, and you judge it: "
        "does it fulfil the request, is it safe (no secrets, no destructive "
        "or irreversible action disguised as a draft, no invented facts "
        "presented as data), and is anything essential missing? Approve "
        "only if you would sign your name under it. List concrete issues, "
        "not vibes."
    ),
)

SUBAGENTS = {
    "researcher": researcher_agent,
    "builder": builder_agent,
    "data": data_agent,
    "writer": writer_agent,
}
