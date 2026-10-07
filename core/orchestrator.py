"""Vyber orchestrator — plan → validate → delegate → review → apply.

The planner proposes; deterministic code disposes:

1. The planner returns a typed RoutePlan.
2. `core.routing` validates and normalizes it into a dependency graph.
3. Independent tasks run in parallel; a task receives only the upstream
   outputs it explicitly declares, plus its selected skill playbook.
4. File plans are merged deterministically. Conflicting duplicate paths
   and credential-shaped content are hard vetoes, before the model
   reviewer sees anything.
5. A model reviewer may veto a clean file plan. One bounded revision
   round is allowed; a second veto writes nothing.
6. Approved files are applied serially to the path-safe workspace.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from core.config import SETTINGS
from core.memory import Memory
from core.routing import normalize_plan
from core.schemas import FilePlan, ReviewVerdict, Step, VyberResult
from core.security import scan_file_plan
from core.skills import discover
from core.subagents import SUBAGENTS, builder_agent, planner_agent, reviewer_agent
from core.traces import TraceLog, new_trace_id
from core.workspace import apply_changes, list_files

_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
_SKILLS = {skill.name: skill for skill in discover(_SKILLS_DIR)}


class Ctx(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: str
    workspace: Path
    memory: Memory = Field(default_factory=Memory)
    trace: TraceLog = Field(default_factory=TraceLog)
    trace_id: str = Field(default_factory=new_trace_id)
    # The caller's bearer token for THIS run, set by the API layer at
    # execution time. Runtime-only: never persisted, never traced, and
    # never placed in a prompt. It exists so tool/MCP calls made by
    # subagents can forward it on-behalf-of the user to services that
    # authorize the token themselves.
    auth_token: str | None = Field(default=None, repr=False)


def _summarise(output) -> str:
    for attr in ("summary", "answer", "title", "body"):
        val = getattr(output, attr, "")
        if val:
            return str(val)[:500]
    points = getattr(output, "points", None)
    if points:
        return str(points[0])[:500]
    return f"{type(output).__name__} completed"


def _format_output(output) -> str:
    if isinstance(output, BaseModel):
        text = output.model_dump_json()
    else:
        text = str(output)
    limit = SETTINGS.max_context_chars_per_dependency
    if len(text) > limit:
        return text[:limit] + "\n[truncated for context budget]"
    return text


def _task_prompt(task, original_prompt: str, outputs: dict,
                 curated_block: str = "") -> str:
    parts = [
        f"Original user request:\n{original_prompt}",
        f"Assigned task:\n{task.task}",
    ]
    if curated_block:
        parts.append(curated_block)
    if task.done_when:
        parts.append(f"Completion criterion:\n{task.done_when}")
    for source_id in task.input_from:
        if source_id in outputs:
            parts.append(
                f"Upstream result from task {source_id}:\n"
                f"{_format_output(outputs[source_id])}")
    if task.skill and task.skill in _SKILLS:
        parts.append(f"Skill playbook ({task.skill}):\n{_SKILLS[task.skill].body()}")
    return "\n\n".join(parts)


def _merge_file_plans(file_plans: list[FilePlan]) -> tuple[FilePlan, list[str]]:
    issues: list[str] = []
    seen: dict[str, str] = {}
    files = []
    for plan in file_plans:
        for file in plan.files:
            if file.path in seen and seen[file.path] != file.content:
                issues.append(f"conflicting duplicate path: {file.path}")
            elif file.path not in seen:
                seen[file.path] = file.content
                files.append(file)
    merged = FilePlan(
        summary="; ".join(p.summary for p in file_plans if p.summary),
        files=files)
    return merged, issues


async def _run_agent(agent, prompt: str):
    return (await asyncio.wait_for(
        agent.run(prompt), timeout=SETTINGS.agent_timeout_seconds)).output


async def ask(prompt: str, ctx: Ctx, emit=None) -> VyberResult:
    """Run one user request through the planner and its specialists.

    `emit(kind, payload)` is called live for the API activity stream:
    ("step", Step) and ("subagent.started", {agent, task, task_id}).
    """
    def _emit(kind, payload):
        if emit is not None:
            emit(kind, payload)

    ctx.trace.emit(ctx.trace_id, "run.started", {"user": ctx.user_id})
    steps: list[Step] = []
    routing_defects: list[str] = []

    workspace_files = list_files(ctx.workspace)[:100]
    curated = ctx.memory.curated_block(ctx.user_id)
    planner_prompt = (
        f"User request: {prompt}\n"
        f"Approved context: {curated}\n"
        f"Current workspace files: {workspace_files}")
    try:
        raw_plan = await _run_agent(planner_agent, planner_prompt)
    except Exception as e:
        raw_plan = None
        routing_defects.append(f"planner failed ({type(e).__name__}); used fallback")
        ctx.trace.emit(ctx.trace_id, "plan.failed", {"error": type(e).__name__})

    if raw_plan is None:
        from core.schemas import RoutePlan
        raw_plan = RoutePlan(tasks=[])
    plan, defects = normalize_plan(raw_plan, prompt, known_skills=set(_SKILLS))
    routing_defects.extend(defects)
    ctx.trace.emit(ctx.trace_id, "plan.created", {
        "tasks": [task.agent for task in plan.tasks],
        "defects": routing_defects,
    })
    steps.append(Step(
        agent="planner", task=prompt,
        output=plan.rationale or f"{len(plan.tasks)} subtask(s)",
        kind="plan"))
    _emit("step", steps[-1])

    outputs: dict[str, object] = {}
    file_plans: list[FilePlan] = []
    pending = list(plan.tasks)
    completed: set[str] = set()

    while pending:
        ready = [task for task in pending
                 if all(dep in completed for dep in task.depends_on)]
        if not ready:
            for task in pending:
                msg = "Skipped because a dependency did not complete successfully."
                steps.append(Step(agent=task.agent, task=task.task, output=msg,
                                  kind="error", task_id=task.id))
                _emit("step", steps[-1])
                routing_defects.append(f"task {task.id}: {msg}")
            break

        for task in ready:
            _emit("subagent.started", {
                "agent": task.agent, "task": task.task, "task_id": task.id})
        results = await asyncio.gather(
            *(_run_agent(SUBAGENTS[task.agent],
                         _task_prompt(task, prompt, outputs, curated))
              for task in ready),
            return_exceptions=True)

        for task, result in zip(ready, results):
            if isinstance(result, Exception):
                msg = f"{type(result).__name__}: {result}"
                steps.append(Step(agent=task.agent, task=task.task, output=msg,
                                  kind="error", task_id=task.id))
                _emit("step", steps[-1])
                ctx.trace.emit(ctx.trace_id, "subagent.failed", {
                    "agent": task.agent, "task_id": task.id,
                    "error": type(result).__name__})
                routing_defects.append(f"task {task.id} failed: {type(result).__name__}")
            else:
                outputs[task.id] = result
                completed.add(task.id)
                steps.append(Step(agent=task.agent, task=task.task,
                                  output=_summarise(result), task_id=task.id))
                _emit("step", steps[-1])
                ctx.trace.emit(ctx.trace_id, "subagent.done", {
                    "agent": task.agent, "task_id": task.id})
                if isinstance(result, FilePlan):
                    file_plans.append(result)
                ctx.memory.record(ctx.user_id, "subagent.done", {
                    "agent": task.agent, "task_id": task.id,
                    "task": task.task[:120]})
            pending.remove(task)

    review: ReviewVerdict | None = None
    changed: list[str] = []
    if file_plans:
        merged, merge_issues = _merge_file_plans(file_plans)
        secret_issues = scan_file_plan(merged)
        hard_issues = merge_issues + secret_issues
        if hard_issues:
            review = ReviewVerdict(
                approved=False, issues=hard_issues,
                summary="Blocked by deterministic safety checks; nothing was written.")
            steps.append(Step(agent="reviewer", task="deterministic safety gate",
                              output=review.summary, kind="review"))
            _emit("step", steps[-1])
        elif not merged.files:
            routing_defects.append("builder returned an empty file plan; nothing to apply")
        else:
            for review_round in range(2):
                review = await _run_agent(
                    reviewer_agent,
                    f"Original request: {prompt}\n"
                    f"Proposed FilePlan: {merged.model_dump_json()}")
                steps.append(Step(
                    agent="reviewer", task="review file plan",
                    output=review.summary or
                           ("approved" if review.approved else "vetoed"),
                    kind="review"))
                _emit("step", steps[-1])
                ctx.trace.emit(ctx.trace_id, "review.done", {
                    "approved": review.approved, "round": review_round + 1})
                if review.approved or review_round == 1:
                    break
                # One bounded revision, performed by the builder and then
                # submitted to the same reviewer. A second veto is final.
                revision = await _run_agent(
                    builder_agent,
                    f"Original request: {prompt}\n"
                    f"Revise this FilePlan: {merged.model_dump_json()}\n"
                    f"Reviewer issues to fix: {review.issues}\n"
                    "Return the complete corrected FilePlan, not a diff.")
                steps.append(Step(
                    agent="builder", task="revise file plan after reviewer veto",
                    output=_summarise(revision), task_id="review-revision"))
                _emit("step", steps[-1])
                merged, merge_issues = _merge_file_plans([revision])
                secret_issues = scan_file_plan(merged)
                if merge_issues or secret_issues or not merged.files:
                    review = ReviewVerdict(
                        approved=False,
                        issues=merge_issues + secret_issues +
                               (["revision returned no files"] if not merged.files else []),
                        summary="Revision failed deterministic checks; nothing was written.")
                    break
            if review is not None and review.approved:
                changed = apply_changes(ctx.workspace, merged.files)
                steps.append(Step(agent="orchestrator", task="apply file plan",
                                  output=f"{len(changed)} file(s) written",
                                  kind="apply"))
                _emit("step", steps[-1])

    successful = [s for s in steps if s.kind == "task" and s.output]
    failures = [s for s in steps if s.kind == "error"]
    if successful:
        summary = "; ".join(f"{s.agent}: {s.output}" for s in successful)
    elif failures:
        summary = "The request failed: " + failures[0].output
    else:
        summary = "Done."
    if failures and successful:
        summary += f" ({len(failures)} task(s) failed or were skipped.)"
    if review is not None and not review.approved:
        summary = ("Reviewer vetoed the proposed files — nothing was written. "
                   + "; ".join(review.issues or [review.summary]))

    ctx.trace.emit(ctx.trace_id, "run.completed", {
        "changed": changed, "routing_defects": routing_defects})
    ctx.memory.record(ctx.user_id, "run.completed", {"prompt": prompt[:120]})
    return VyberResult(summary=summary, steps=steps, changed_files=changed,
                       review=review, routing_defects=routing_defects)
