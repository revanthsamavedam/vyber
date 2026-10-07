"""Deterministic plan validation and scheduling.

The planner is probabilistic. Before Vyber spends money on specialists,
ordinary code checks the plan's shape: stable ids, known skills, valid
dependencies, no cycles, no impossible input handoffs, and bounded size.
Problems are returned as routing defects rather than silently hidden.
"""
from __future__ import annotations

from core.config import SETTINGS
from core.schemas import RoutePlan, SubTask

SKILL_AGENTS = {
    "deep-research": "researcher",
    "build-a-tool": "builder",
    "answer-from-data": "data",
    "draft-a-doc": "writer",
}


def _unique_id(candidate: str, used: set[str], index: int) -> str:
    base = candidate.strip() or f"task-{index + 1}"
    if base not in used:
        return base
    suffix = 2
    while f"{base}-{suffix}" in used:
        suffix += 1
    return f"{base}-{suffix}"


def normalize_plan(plan: RoutePlan, prompt: str,
                   known_skills: set[str] | None = None) -> tuple[RoutePlan, list[str]]:
    """Return a safe plan plus human-readable routing defects."""
    defects: list[str] = []
    known_skills = known_skills if known_skills is not None else set(SKILL_AGENTS)

    if not plan.tasks:
        defects.append("planner returned no tasks; used single researcher fallback")
        plan = RoutePlan(
            rationale=plan.rationale,
            tasks=[SubTask(id="fallback-research", agent="researcher", task=prompt,
                           done_when="Returns findings for the original request")],
        )

    if len(plan.tasks) > SETTINGS.max_tasks_per_plan:
        defects.append(
            f"planner returned {len(plan.tasks)} tasks; "
            f"truncated to {SETTINGS.max_tasks_per_plan}")
        plan.tasks = plan.tasks[:SETTINGS.max_tasks_per_plan]

    used: set[str] = set()
    for index, task in enumerate(plan.tasks):
        new_id = _unique_id(task.id, used, index)
        if new_id != task.id:
            defects.append(f"task id {task.id!r} was missing or duplicated; renamed to {new_id!r}")
            task.id = new_id
        used.add(task.id)

        if task.skill:
            expected_agent = SKILL_AGENTS.get(task.skill)
            if task.skill not in known_skills:
                defects.append(f"task {task.id}: unknown skill {task.skill!r}; skill removed")
                task.skill = None
            elif expected_agent and expected_agent != task.agent:
                defects.append(
                    f"task {task.id}: skill {task.skill!r} belongs to {expected_agent}, "
                    f"not {task.agent}; skill removed")
                task.skill = None

        if task.agent == "builder" and task.parallel_safe:
            # File plans are staged and application is serial, so generation
            # may run in parallel; the flag is nevertheless misleading for a
            # write-producing task and is not allowed to imply parallel apply.
            task.parallel_safe = False

    ids = {task.id for task in plan.tasks}
    for task in plan.tasks:
        for field_name in ("depends_on", "input_from"):
            values = getattr(task, field_name)
            cleaned = []
            for ref in values:
                if ref == task.id:
                    defects.append(f"task {task.id}: removed self-reference in {field_name}")
                elif ref not in ids:
                    defects.append(
                        f"task {task.id}: removed unknown {field_name} reference {ref!r}")
                elif ref not in cleaned:
                    cleaned.append(ref)
            setattr(task, field_name, cleaned)
        # Receiving an output necessarily creates a scheduling dependency.
        for ref in task.input_from:
            if ref not in task.depends_on:
                task.depends_on.append(ref)

    ordered, cycle_ids = topological_order(plan.tasks)
    if cycle_ids:
        defects.append(
            "dependency cycle detected among " + ", ".join(sorted(cycle_ids)) +
            "; cycle dependencies were removed and tasks kept in plan order")
        for task in plan.tasks:
            if task.id in cycle_ids:
                task.depends_on = [d for d in task.depends_on if d not in cycle_ids]
                task.input_from = [d for d in task.input_from if d not in cycle_ids]
        ordered, _ = topological_order(plan.tasks)

    plan.tasks = ordered
    return plan, defects


def topological_order(tasks: list[SubTask]) -> tuple[list[SubTask], set[str]]:
    """Stable topological order. Returns (ordered, ids_left_in_cycles)."""
    by_id = {task.id: task for task in tasks}
    remaining = list(tasks)
    ordered: list[SubTask] = []
    completed: set[str] = set()

    while remaining:
        ready = [task for task in remaining
                 if all(dep in completed for dep in task.depends_on)]
        if not ready:
            return ordered + remaining, {task.id for task in remaining}
        next_task = ready[0]
        ordered.append(next_task)
        completed.add(next_task.id)
        remaining.remove(next_task)
    return ordered, set()
