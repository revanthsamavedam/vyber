"""The subagents. Each is a specialist with a narrow brief and a typed
output — none of them talks to the user, all of them report to the
orchestrator. Narrow briefs are the point: a specialist that can do
everything is just the orchestrator with extra steps."""
from __future__ import annotations

from pathlib import Path

from pydantic_ai import Agent

from core.models import get_model
from core.schemas import DataAnswer, Draft, FilePlan, Findings, ReviewVerdict, RoutePlan
from core.skills import catalog, discover

MODEL = get_model()
_SKILLS = discover(Path(__file__).resolve().parent.parent / "skills")
_SKILL_CATALOG = catalog(_SKILLS)

planner_agent = Agent(
    MODEL, output_type=RoutePlan,
    instructions=(
        "You are the planner inside Vyber. Produce a work plan, never the "
        "final work. Route to exactly these specialists:\n"
        "- researcher: discovers and synthesises external or conceptual "
        "information; use when facts must be found.\n"
        "- data: answers from governed/internal data; use when source and "
        "freshness matter. Do not use researcher as a substitute for data.\n"
        "- writer: produces a finished prose deliverable from supplied or "
        "researched material.\n"
        "- builder: creates or changes files, code, tools, or pages.\n\n"
        "Rules:\n"
        "1. Use the fewest subtasks that fully cover the request. Do not "
        "route merely because a specialist exists.\n"
        "2. Give every task a stable id and make it a self-contained work "
        "order: deliverable, inputs, constraints, and done_when criterion.\n"
        "3. If a task consumes another task's output, name that task in "
        "both depends_on and input_from.\n"
        "4. Facts already supplied by the user do not need research.\n"
        "5. A document file may need writer then builder; declare the chain.\n"
        "6. Never assign work to yourself and never invent agent names.\n"
        "7. Set skill only when one playbook clearly applies.\n\n"
        "Available skills:\n" + _SKILL_CATALOG
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
