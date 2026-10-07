"""Runtime limits and timeouts.

Production systems need explicit bounds: an unbounded planner, file plan,
message, or queue is a cost and denial-of-service problem. Every value can
be overridden by environment variable, and the defaults are deliberately
small enough for a single-user/small-team deployment.
"""
from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        return default
    return value if value > 0 else default


def _float_env(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        return default
    return value if value > 0 else default


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_timeout_seconds: float = Field(default=120.0, gt=0)
    max_tasks_per_plan: int = Field(default=8, gt=0)
    max_file_changes: int = Field(default=50, gt=0)
    max_file_bytes: int = Field(default=256_000, gt=0)
    max_message_chars: int = Field(default=20_000, gt=0)
    max_queued_runs_per_session: int = Field(default=20, gt=0)
    max_context_chars_per_dependency: int = Field(default=12_000, gt=0)

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls.model_fields
        return cls(
            agent_timeout_seconds=_float_env(
                "VYBER_AGENT_TIMEOUT_SECONDS",
                defaults["agent_timeout_seconds"].default),
            max_tasks_per_plan=_int_env(
                "VYBER_MAX_TASKS_PER_PLAN",
                defaults["max_tasks_per_plan"].default),
            max_file_changes=_int_env(
                "VYBER_MAX_FILE_CHANGES",
                defaults["max_file_changes"].default),
            max_file_bytes=_int_env(
                "VYBER_MAX_FILE_BYTES",
                defaults["max_file_bytes"].default),
            max_message_chars=_int_env(
                "VYBER_MAX_MESSAGE_CHARS",
                defaults["max_message_chars"].default),
            max_queued_runs_per_session=_int_env(
                "VYBER_MAX_QUEUED_RUNS_PER_SESSION",
                defaults["max_queued_runs_per_session"].default),
            max_context_chars_per_dependency=_int_env(
                "VYBER_MAX_CONTEXT_CHARS_PER_DEPENDENCY",
                defaults["max_context_chars_per_dependency"].default),
        )


SETTINGS = Settings.from_env()
