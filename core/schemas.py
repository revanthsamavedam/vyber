"""Typed contracts between agents. Agents never pass free text to each
other where a structure exists — every handoff below is validated."""
from __future__ import annotations

from pydantic import BaseModel, Field

KNOWN_AGENTS = ("researcher", "builder", "data", "writer")


class SubTask(BaseModel):
    agent: str = Field(description="one of: researcher, builder, data, writer")
    task: str


class RoutePlan(BaseModel):
    rationale: str = ""
    tasks: list[SubTask] = Field(default_factory=list)


class Findings(BaseModel):
    summary: str = ""
    points: list[str] = Field(default_factory=list)


class FileChange(BaseModel):
    path: str
    content: str


class FilePlan(BaseModel):
    summary: str = ""
    files: list[FileChange] = Field(default_factory=list)


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
    kind: str = "task"  # task | review | apply | plan


class VyberResult(BaseModel):
    summary: str
    steps: list[Step] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    review: ReviewVerdict | None = None
    pending_approval_id: str | None = None
