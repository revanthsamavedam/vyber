"""Super Muse orchestrator — ask → plan → delegate → review → apply → report.

The orchestrator is deliberately thin code around the agents:
  1. planner_agent turns the request into a RoutePlan of subtasks.
  2. Specialist subagents execute (unknown agent names from a weak plan
     are normalised to researcher — a plan is a suggestion, not gospel).
  3. Anything that would land as files goes through reviewer_agent
     BEFORE it is applied. A veto means nothing is written, and the
     user hears the reviewer's reasons.
  4. Approved file plans apply to the session workspace (path-safe).
  5. Every step is traced and recorded in episodic memory; the result
     carries the full step list so the UI can show its work.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.memory import Memory
from core.schemas import (KNOWN_AGENTS, FilePlan, ReviewVerdict, Step,
                          SuperResult)
from core.subagents import SUBAGENTS, planner_agent, reviewer_agent
from core.traces import TraceLog, new_trace_id
from core.workspace import apply_changes


@dataclass
class Ctx:
    user_id: str
    workspace: Path
    memory: Memory = field(default_factory=Memory)
    trace: TraceLog = field(default_factory=TraceLog)
    trace_id: str = field(default_factory=new_trace_id)


def _summarise(output) -> str:
    for attr in ("summary", "answer", "title", "body"):
        val = getattr(output, attr, "")
        if val:
            return str(val)[:200]
    points = getattr(output, "points", None)
    if points:
        return str(points[0])[:200]
    return f"{type(output).__name__} completed"


async def ask(prompt: str, ctx: Ctx) -> SuperResult:
    ctx.trace.emit(ctx.trace_id, "run.started", {"user": ctx.user_id})
    steps: list[Step] = []

    plan = (await planner_agent.run(
        f"User request: {prompt}\n"
        f"Approved context: {ctx.memory.curated_block(ctx.user_id)}")).output
    if not plan.tasks:
        # An empty plan is a planner failure, not an answer. Fall back to a
        # single research task so the user always gets work, not a shrug.
        from core.schemas import SubTask
        plan.tasks = [SubTask(agent="researcher", task=prompt)]
        plan.rationale = (plan.rationale + " (fallback: single research task)").strip()
    steps.append(Step(agent="planner", task=prompt,
                      output=plan.rationale or f"{len(plan.tasks)} subtask(s)",
                      kind="plan"))
    ctx.trace.emit(ctx.trace_id, "plan.created",
                   {"tasks": [t.agent for t in plan.tasks]})

    file_plans: list[FilePlan] = []
    for sub in plan.tasks:
        name = sub.agent if sub.agent in KNOWN_AGENTS else "researcher"
        agent = SUBAGENTS[name]
        result = await agent.run(sub.task)
        out = result.output
        steps.append(Step(agent=name, task=sub.task, output=_summarise(out)))
        ctx.trace.emit(ctx.trace_id, "subagent.done", {"agent": name})
        if isinstance(out, FilePlan):
            file_plans.append(out)
        ctx.memory.record(ctx.user_id, "subagent.done",
                          {"agent": name, "task": sub.task[:120]})

    review: ReviewVerdict | None = None
    changed: list[str] = []
    if file_plans:
        merged = FilePlan(
            summary="; ".join(p.summary for p in file_plans if p.summary),
            files=[f for p in file_plans for f in p.files])
        review = (await reviewer_agent.run(
            f"Original request: {prompt}\nProposed FilePlan: {merged.model_dump_json()}"
        )).output
        steps.append(Step(agent="reviewer", task="review file plan",
                          output=review.summary or
                                 ("approved" if review.approved else "vetoed"),
                          kind="review"))
        ctx.trace.emit(ctx.trace_id, "review.done", {"approved": review.approved})
        if review.approved:
            changed = apply_changes(ctx.workspace, merged.files)
            steps.append(Step(agent="orchestrator", task="apply file plan",
                              output=f"{len(changed)} file(s) written", kind="apply"))
        # veto: write nothing; the caller surfaces review.issues

    summary_bits = [s.output for s in steps if s.kind == "task" and s.output]
    summary = summary_bits[0] if summary_bits else "Done."
    if review is not None and not review.approved:
        summary = ("Reviewer vetoed the proposed files — nothing was written. "
                   + "; ".join(review.issues) or review.summary)
    ctx.trace.emit(ctx.trace_id, "run.completed", {"changed": changed})
    ctx.memory.record(ctx.user_id, "run.completed", {"prompt": prompt[:120]})
    return SuperResult(summary=summary, steps=steps,
                       changed_files=changed, review=review)
