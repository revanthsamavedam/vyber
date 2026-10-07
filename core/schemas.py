"""Typed contracts between agents. Agents never pass free text to each
other where a structure exists — every handoff below is validated."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AgentName = Literal["researcher", "builder", "data", "writer"]
KNOWN_AGENTS = ("researcher", "builder", "data", "writer")


class SubTask(BaseModel):
    id: str = Field(default="", description="stable unique id, e.g. research-1")
    agent: AgentName
    task: str = Field(min_length=1)
    depends_on: list[str] = Field(
        default_factory=list,
        description="task ids that must complete before this task starts")
    input_from: list[str] = Field(
        default_factory=list,
        description="task ids whose outputs are passed into this task")
    done_when: str = Field(
        default="", description="observable completion criterion")
    skill: str | None = Field(
        default=None, description="optional SKILL.md playbook name")
    parallel_safe: bool = Field(
        default=False,
        description="true only when this task has no ordering side effects")


class RoutePlan(BaseModel):
    rationale: str = ""
    tasks: list[SubTask] = Field(default_factory=list, max_length=8)


class Findings(BaseModel):
    summary: str = ""
    points: list[str] = Field(default_factory=list)


class FileChange(BaseModel):
    path: str = Field(min_length=1)
    content: str = Field(max_length=1_000_000)


class FilePlan(BaseModel):
    summary: str = ""
    files: list[FileChange] = Field(default_factory=list, max_length=50)


class DataAnswer(BaseModel):
    answer: str = ""
    source: str = ""
    freshness: str = ""


class Draft(BaseModel):
    title: str = ""
    body: str = ""


class ReviewVerdict(BaseModel):
    approved: bool = True
    issues: list[str] = Field(default_factory=list)
    summary: str = ""


class Step(BaseModel):
    agent: str
    task: str
    output: str
    kind: str = "task"  # task | review | apply | plan | error
    task_id: str = ""


class VyberResult(BaseModel):
    summary: str
    steps: list[Step] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    review: ReviewVerdict | None = None
    pending_approval_id: str | None = None
    routing_defects: list[str] = Field(default_factory=list)
