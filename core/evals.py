"""Scoring for planner/routing evaluation cases.

Routing usually has more than one valid answer, so cases list acceptable
agent sets instead of one gold set. Scores focus on production-relevant
errors: forbidden specialists, missing work, unnecessary specialists,
broken dependencies, and tasks without completion criteria.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.schemas import RoutePlan


@dataclass
class RoutingCase:
    name: str
    prompt: str
    acceptable: list[set[str]]
    forbidden: set[str] = field(default_factory=set)
    required_dependencies: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "RoutingCase":
        return cls(
            name=data["name"],
            prompt=data["prompt"],
            acceptable=[set(agents) for agents in data["acceptable"]],
            forbidden=set(data.get("forbidden", [])),
            required_dependencies=[tuple(pair) for pair in
                                   data.get("required_dependencies", [])],
        )


def _best_acceptable(case: RoutingCase, predicted: set[str]) -> set[str]:
    def overlap(candidate: set[str]):
        return (len(predicted & candidate), -len(predicted ^ candidate))
    return max(case.acceptable, key=overlap)


def score_plan(case: RoutingCase, plan: RoutePlan,
               routing_defects: list[str] | None = None) -> dict:
    predicted = {task.agent for task in plan.tasks}
    acceptable = _best_acceptable(case, predicted)
    by_agent: dict[str, set[str]] = {}
    for task in plan.tasks:
        by_agent.setdefault(task.agent, set()).add(task.id)
    id_to_agent = {task.id: task.agent for task in plan.tasks}

    dependency_results = []
    for dependent_agent, dependency_agent in case.required_dependencies:
        ok = False
        for task in plan.tasks:
            if task.agent != dependent_agent:
                continue
            dependency_agents = {id_to_agent.get(dep) for dep in task.depends_on}
            if dependency_agent in dependency_agents:
                ok = True
                break
        dependency_results.append(ok)

    return {
        "case": case.name,
        "predicted_agents": sorted(predicted),
        "route_ok": predicted in case.acceptable,
        "missing_agents": sorted(acceptable - predicted),
        "extra_agents": sorted(predicted - acceptable),
        "forbidden_used": sorted(predicted & case.forbidden),
        "dependencies_ok": all(dependency_results) if dependency_results else True,
        "done_when_coverage": (
            sum(1 for task in plan.tasks if task.done_when) / len(plan.tasks)
            if plan.tasks else 0.0),
        "task_count": len(plan.tasks),
        "routing_defects": routing_defects or [],
    }


def aggregate(results: list[dict]) -> dict:
    if not results:
        return {"cases": 0}
    n = len(results)
    return {
        "cases": n,
        "acceptable_route_rate": sum(r["route_ok"] for r in results) / n,
        "forbidden_route_rate": sum(bool(r["forbidden_used"]) for r in results) / n,
        "missing_agent_rate": sum(bool(r["missing_agents"]) for r in results) / n,
        "extra_agent_rate": sum(bool(r["extra_agents"]) for r in results) / n,
        "dependency_success_rate": sum(r["dependencies_ok"] for r in results) / n,
        "done_when_coverage": sum(r["done_when_coverage"] for r in results) / n,
        "average_tasks": sum(r["task_count"] for r in results) / n,
        "plans_with_routing_defects": sum(bool(r["routing_defects"]) for r in results),
    }
